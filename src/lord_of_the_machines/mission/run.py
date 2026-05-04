from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from lord_of_the_machines import MissingApiKeyError
from lord_of_the_machines.agent_tools import (
    ArtifactRegistryTool,
    EventBusTool,
    MissionRegistryTool,
)
from lord_of_the_machines.mission import (
    BaseAgentRoleExecutor,
    BaseAgentRoleExecutorConfig,
    MissionRunner,
    MissionRunnerConfig,
    MissionRuntime,
    MissionRuntimeConfig,
    RoleAgentFactory,
    SoftwareDeveloperRoleExecutor,
    SoftwareDeveloperRoleExecutorConfig,
)
from lord_of_the_machines.runtime import close_run_logging, configure_run_logging, current_log_path


def create_storage_tools(state_dir: Path) -> tuple[MissionRegistryTool, EventBusTool, ArtifactRegistryTool]:
    state_dir = state_dir.resolve()
    state_dir.mkdir(parents=True, exist_ok=True)
    mission_registry = MissionRegistryTool(state_dir / "missions")
    event_bus = EventBusTool(state_dir / "events")
    artifact_registry = ArtifactRegistryTool(state_dir / "artifacts")
    return mission_registry, event_bus, artifact_registry


def build_bootstrap_runner(
    *,
    repo_root: Path,
    state_dir: Path,
    missions_file: Path,
) -> MissionRunner:
    mission_registry, event_bus, artifact_registry = create_storage_tools(state_dir)
    runtime = MissionRuntime(
        mission_registry=mission_registry,
        event_bus=event_bus,
        artifact_registry=artifact_registry,
        role_executors={},
        config=MissionRuntimeConfig(phase_transitions={}),
    )
    return MissionRunner(
        mission_registry=mission_registry,
        runtime=runtime,
        config=MissionRunnerConfig(
            max_cycles=1,
            max_events_per_cycle=1,
            idle_cycles_to_stop=1,
            seed_each_cycle=False,
            bootstrap_missions_from_file=False,
            missions_file_path=missions_file,
        ),
    )


def build_default_runner(
    *,
    repo_root: Path,
    state_dir: Path,
    missions_file: Path,
    max_cycles: int,
    max_events_per_cycle: int,
    idle_cycles_to_stop: int,
    max_follow_up_rounds: int,
    diagnostics_profiles: tuple[str, ...],
    diagnostics_timeout_seconds: int,
    allowed_write_prefixes: tuple[str, ...],
) -> MissionRunner:
    mission_registry, event_bus, artifact_registry = create_storage_tools(state_dir)
    factory = RoleAgentFactory()

    product_director_agent = factory.create("product_director", max_tool_rounds=8)
    software_developer_agent = factory.create("software_developer", max_tool_rounds=12)

    product_director_executor = BaseAgentRoleExecutor(
        product_director_agent,
        config=BaseAgentRoleExecutorConfig(role_name="product_director"),
    )
    software_developer_executor = SoftwareDeveloperRoleExecutor(
        software_developer_agent,
        config=SoftwareDeveloperRoleExecutorConfig(
            workspace_root=repo_root,
            diagnostics_profiles=diagnostics_profiles,
            diagnostics_timeout_seconds=diagnostics_timeout_seconds,
            allowed_write_prefixes=allowed_write_prefixes,
        ),
    )

    runtime = MissionRuntime(
        mission_registry=mission_registry,
        event_bus=event_bus,
        artifact_registry=artifact_registry,
        role_executors={
            "product_director": product_director_executor,
            "software_developer": software_developer_executor,
        },
        config=MissionRuntimeConfig(
            max_events_per_run=max_events_per_cycle,
            max_follow_up_rounds=max_follow_up_rounds,
        ),
    )
    return MissionRunner(
        mission_registry=mission_registry,
        runtime=runtime,
        config=MissionRunnerConfig(
            max_cycles=max_cycles,
            max_events_per_cycle=max_events_per_cycle,
            idle_cycles_to_stop=idle_cycles_to_stop,
            seed_each_cycle=True,
            bootstrap_missions_from_file=True,
            missions_file_path=missions_file,
            skip_existing_missions_on_bootstrap=True,
        ),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Lord of the Machines mission runner.")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--state-dir", type=Path, default=None)
    parser.add_argument("--missions-file", type=Path, default=None)
    parser.add_argument("--max-cycles", type=int, default=20)
    parser.add_argument("--max-events-per-cycle", type=int, default=10)
    parser.add_argument("--idle-cycles-to-stop", type=int, default=2)
    parser.add_argument("--max-follow-up-rounds", type=int, default=3)
    parser.add_argument("--diagnostics-timeout", type=int, default=300)
    parser.add_argument("--diagnostics-profile", action="append", default=["unittest"])
    parser.add_argument(
        "--allow-write-prefix",
        action="append",
        default=[
            "docs/",
            "README.md",
            "src/lord_of_the_machines/mission/",
            "tests/",
        ],
    )
    parser.add_argument("--bootstrap-only", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-log", action="store_true")
    parser.add_argument("--log-dir", type=Path, default=None)
    parser.add_argument("--run-name", type=str, default="mission-run")
    args = parser.parse_args(list(argv) if argv is not None else None)

    repo_root = args.repo_root.resolve()
    state_dir = (args.state_dir or (repo_root / ".state")).resolve()
    missions_file = (args.missions_file or (repo_root / "config" / "missions.json")).resolve()
    log_path: str | None = None
    try:
        if not args.no_log:
            resolved_log_dir = (args.log_dir or (repo_root / "logs")).resolve()
            configure_run_logging(run_name=args.run_name, log_dir=resolved_log_dir)
            current = current_log_path()
            log_path = str(current) if current is not None else None

        try:
            if args.bootstrap_only:
                runner = build_bootstrap_runner(
                    repo_root=repo_root,
                    state_dir=state_dir,
                    missions_file=missions_file,
                )
                result = runner.create_missions_from_file(missions_file, skip_existing=True)
            else:
                runner = build_default_runner(
                    repo_root=repo_root,
                    state_dir=state_dir,
                    missions_file=missions_file,
                    max_cycles=args.max_cycles,
                    max_events_per_cycle=args.max_events_per_cycle,
                    idle_cycles_to_stop=args.idle_cycles_to_stop,
                    max_follow_up_rounds=args.max_follow_up_rounds,
                    diagnostics_profiles=tuple(str(item) for item in args.diagnostics_profile),
                    diagnostics_timeout_seconds=args.diagnostics_timeout,
                    allowed_write_prefixes=tuple(str(item) for item in args.allow_write_prefix),
                )
                result = runner.run()
        except MissingApiKeyError as exc:
            print(f"Missing API key: {exc}", file=sys.stderr)
            return 2
        except Exception as exc:
            print(f"Mission run failed: {exc}", file=sys.stderr)
            if log_path:
                print(f"See logs: {log_path}", file=sys.stderr)
            return 1

        if log_path and isinstance(result, dict):
            result = dict(result)
            result["log_path"] = log_path

        if args.json:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            if args.bootstrap_only:
                print(
                    f"Bootstrap complete. Loaded={result['loaded']} "
                    f"Created={len(result['created'])} Skipped={len(result['skipped'])}"
                )
            else:
                print(f"Mission run complete. Cycles={len(result['cycles'])}")
                for mission in result.get("final_missions", []):
                    print(
                        f"- {mission.get('mission_id')} | "
                        f"status={mission.get('status')} | "
                        f"phases={mission.get('phase_status')}"
                    )
            if log_path:
                print(f"Logs: {log_path}")
        return 0
    finally:
        if not args.no_log:
            close_run_logging()


if __name__ == "__main__":
    raise SystemExit(main())
