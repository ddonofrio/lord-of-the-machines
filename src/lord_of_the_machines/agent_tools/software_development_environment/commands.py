from __future__ import annotations

import subprocess
import logging
from datetime import datetime
from lord_of_the_machines.agent_tools.software_development_environment.contracts import (
    DiagnosticProfileResult,
    GitStatusRequest,
    GitStatusResult,
    RunCommandRequest,
    RunCommandResult,
    RunDiagnosticsRequest,
    RunDiagnosticsResult,
)
from lord_of_the_machines.agent_tools.software_development_environment.policy import SoftwareDevelopmentEnvironmentPolicyError


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

    def _run_system_command(self, arguments: dict[str, object]) -> dict[str, object]:
        # -- OS-level system command execution --
        if not self.config.permission_policy.allow_system_command_execution:
            self._audit_system_command(arguments, allowed=False)
            raise SoftwareDevelopmentEnvironmentPolicyError(
                "System command execution denied by policy."
            )
        argv = arguments.get("argv")
        if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
            raise ValueError("Argument 'argv' must be a non-empty list of strings.")

        # OS-level: no workdir, runs in configured environment
        timeout_seconds = arguments.get("timeout_seconds", 60)
        expected_exit_codes = arguments.get("expected_exit_codes") or [0]
        try:
            completed = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_seconds,
                shell=False,
            )
            result = {
                "argv": argv,
                "exit_code": completed.returncode,
                "ok": completed.returncode in expected_exit_codes,
                "stdout": self._clip_text(completed.stdout),
                "stderr": self._clip_text(completed.stderr),
            }
        except Exception as exc:
            result = {
                "argv": argv,
                "exit_code": None,
                "ok": False,
                "stdout": "",
                "stderr": str(exc),
            }
        self._audit_system_command(arguments, allowed=True, result=result)
        return result

    def _audit_system_command(self, arguments, allowed: bool, result=None):
        user = getattr(self, "_current_user", None) or "unknown"
        role = getattr(self, "_current_role", None) or "unknown"
        timestamp = datetime.utcnow().isoformat()
        argv = arguments.get("argv")
        log_entry = {
            "type": "system_command_attempt",
            "user": user,
            "role": role,
            "timestamp": timestamp,
            "allowed": allowed,
            "argv": argv,
            "result": result if allowed and result else None,
        }
        logger = logging.getLogger("SoftwareDevelopmentEnvironment.SystemCommand")
        # Optionally redact secrets or large data in argv here
        logger.info(f"AUDIT: {log_entry}")
