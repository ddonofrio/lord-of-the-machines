from __future__ import annotations

import subprocess

from lord_of_the_machines.agent_tools.software_development_environment.contracts import (
    DiagnosticProfileResult,
    GitStatusRequest,
    GitStatusResult,
    RunCommandRequest,
    RunCommandResult,
    RunDiagnosticsRequest,
    RunDiagnosticsResult,
)


class CommandOperationsMixin:
    def _run_command(self, arguments: dict[str, object]) -> dict[str, object]:
        request = RunCommandRequest.from_mapping(arguments)
        argv = request.argv
        self._assert_command_allowed("run_command", timeout_seconds=request.timeout_seconds)
        self._ensure_allowed_command(argv[0])

        workdir = self._resolve_path(request.workdir, allow_missing=False)
        if not workdir.is_dir():
            raise NotADirectoryError(f"Working directory is not a directory: {self._relative_path(workdir)}")

        timeout_seconds = self._int_argument(
            request.timeout_seconds,
            self.config.default_command_timeout_seconds,
            minimum=1,
        )
        expected_exit_codes = request.expected_exit_codes or [0]
        completed = subprocess.run(
            argv,
            cwd=str(workdir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            shell=False,
        )
        result = RunCommandResult(
            argv=argv,
            workdir=self._relative_path(workdir),
            exit_code=completed.returncode,
            ok=completed.returncode in expected_exit_codes,
            stdout=self._clip_text(completed.stdout),
            stderr=self._clip_text(completed.stderr),
        )
        self._executed_commands.append(result)
        self._record_activity(
            "run_command_result",
            {"argv": argv, "exit_code": completed.returncode},
            status="ok" if result.ok else "failed",
            category="command",
        )
        return result.to_mapping()

    def _run_diagnostics(self, arguments: dict[str, object]) -> dict[str, object]:
        request = RunDiagnosticsRequest.from_mapping(arguments)
        self._assert_diagnostics_allowed()
        workdir = self._resolve_path(request.workdir, allow_missing=False)
        if not workdir.is_dir():
            raise NotADirectoryError(f"Working directory is not a directory: {self._relative_path(workdir)}")

        timeout_seconds = self._int_argument(
            request.timeout_seconds,
            self.config.default_command_timeout_seconds,
            minimum=1,
        )
        profiles = request.profiles
        commands = self._diagnostic_commands(profiles)

        results: list[DiagnosticProfileResult] = []
        for profile_name, command in commands:
            if command is None:
                results.append(
                    DiagnosticProfileResult(
                        profile=profile_name,
                        ok=None,
                        skipped=True,
                        reason="not available",
                    )
                )
                continue
            result_mapping = self._run_command(
                {
                    "argv": command,
                    "workdir": self._relative_path(workdir),
                    "timeout_seconds": timeout_seconds,
                    "expected_exit_codes": [0],
                }
            )
            results.append(
                DiagnosticProfileResult(
                    profile=profile_name,
                    ok=bool(result_mapping["ok"]),
                    argv=list(result_mapping["argv"]),
                    workdir=str(result_mapping["workdir"]),
                    exit_code=int(result_mapping["exit_code"]),
                    stdout=str(result_mapping["stdout"]),
                    stderr=str(result_mapping["stderr"]),
                )
            )

        self._record_activity(
            "run_diagnostics_result",
            {"profiles": profiles, "count": len(results)},
            status="ok",
            category="command",
        )
        return RunDiagnosticsResult(results=results).to_mapping()

    def _git_status(self, arguments: dict[str, object]) -> dict[str, object]:
        request = GitStatusRequest.from_mapping(arguments)
        self._assert_git_allowed()
        if not (self.config.root_path / ".git").exists():
            return GitStatusResult(available=False, reason="workspace is not a git repository").to_mapping()

        include_diff = request.include_diff
        recent_commit_count = self._int_argument(request.recent_commit_count, 5, minimum=1)
        max_diff_chars = self._int_argument(request.max_diff_chars, 4000, minimum=200)

        branch = self._run_git(["rev-parse", "--abbrev-ref", "HEAD"])
        status = self._run_git(["status", "--short", "--branch"])
        recent_commits = self._run_git(["log", "--oneline", f"-n{recent_commit_count}"])
        working_tree = self._run_git(["diff", "--name-only"])
        staged = self._run_git(["diff", "--cached", "--name-only"])

        result = GitStatusResult(
            available=True,
            branch=branch.stdout.strip(),
            status_lines=[line for line in status.stdout.splitlines() if line.strip()],
            working_tree_files=[line for line in working_tree.stdout.splitlines() if line.strip()],
            staged_files=[line for line in staged.stdout.splitlines() if line.strip()],
            recent_commits=[line for line in recent_commits.stdout.splitlines() if line.strip()],
        )
        if include_diff:
            diff = self._run_git(["diff", "--no-ext-diff", "--unified=3"])
            result.diff = self._clip_text(diff.stdout, limit=max_diff_chars)

        self._record_activity(
            "git_status_snapshot",
            {"include_diff": include_diff, "branch": result.branch},
            status="ok",
            category="command",
        )
        return result.to_mapping()
