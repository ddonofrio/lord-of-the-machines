from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from lord_of_the_machines.llm import BaseAgent, ToolDefinition, ToolMethodDefinition
from lord_of_the_machines.llm.tools import ToolHandler
from lord_of_the_machines.mission.contracts import RoleTaskRequest, RoleTaskResult


DEFAULT_RUN_TASK_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "objective": {"type": "string"},
        "mission_id": {"type": "string"},
        "phase": {"type": "string"},
        "task_id": {"type": "string"},
        "context": {"type": "object"},
        "constraints": {"type": "array", "items": {"type": "string"}},
        "max_rounds": {"type": "integer"},
        "continue_previous": {"type": "boolean"},
        "metadata": {"type": "object"},
    },
    "required": ["objective"],
}


DEFAULT_ROLE_RESULT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "status": {
            "type": "string",
            "enum": ["completed", "needs_follow_up", "blocked", "failed"],
        },
        "summary": {"type": "string"},
        "artifact_type": {"type": ["string", "null"]},
        "artifact_title": {"type": ["string", "null"]},
        "artifact_content": {"type": ["string", "null"]},
        "artifact_format": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "required_changes": {"type": "array", "items": {"type": "string"}},
        "unresolved_questions": {"type": "array", "items": {"type": "string"}},
        "follow_ups": {"type": "array", "items": {"type": "string"}},
        "metadata": {"type": "object"},
    },
    "required": ["status"],
}


@dataclass(slots=True)
class AgentAsToolConfig:
    role_name: str
    tool_name: str
    method_name: str = "run_task"
    description: str = "Execute a structured role task through a specialized role agent."
    method_description: str = "Run one task and return a structured completion payload."
    arguments_schema: dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_RUN_TASK_SCHEMA))
    result_tool_name: str = "_role_task_result"
    result_method_name: str = "submit"
    internal: bool = False
    require_structured_result: bool = True
    structured_result_retries: int = 2
    disable_reply_tool_for_structured_result: bool = True
    structured_result_max_tool_rounds: int | None = None
    structured_result_max_output_tokens: int | None = 1536
    structured_result_parallel_tool_calls: bool = False
    force_structured_submit_on_failure: bool = True
    forced_submit_max_tool_rounds: int = 1


class AgentAsToolBridge:
    def __init__(
        self,
        agent: BaseAgent,
        *,
        config: AgentAsToolConfig,
    ) -> None:
        self.agent = agent
        self.config = config
        self.agent.add_tool(self._result_definition(), handlers=self._result_handlers())

    def install(self, host_agent: BaseAgent) -> None:
        host_agent.add_tool(self.definition(), handlers=self.handlers())

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.config.tool_name,
            description=self.config.description,
            internal=self.config.internal,
            methods=[
                ToolMethodDefinition(
                    name=self.config.method_name,
                    description=self.config.method_description,
                    arguments_schema=dict(self.config.arguments_schema),
                )
            ],
        )

    def handlers(self) -> dict[str, ToolHandler]:
        return {self.config.method_name: self._run_task}

    def execute_task(self, request: RoleTaskRequest) -> RoleTaskResult:
        prompt = self._build_prompt(request)
        disabled_tools = set()
        if self.config.disable_reply_tool_for_structured_result:
            disabled_tools.add(self.agent.config.reply.tool)
        query_overrides = self._query_overrides()
        try:
            raw_result, reply = self.agent.query_structured_tool_result(
                prompt,
                tool_name=self.config.result_tool_name,
                method_name=self.config.result_method_name,
                continue_previous=request.continue_previous,
                disabled_tools=disabled_tools,
                max_tool_rounds=self.config.structured_result_max_tool_rounds,
                **query_overrides,
            )
        except Exception as exc:
            forced = self._force_structured_submission(
                reason=f"Initial structured query failed: {exc}",
                disabled_tools=disabled_tools,
                query_overrides=query_overrides,
            )
            if forced is not None:
                return forced
            return self._missing_structured_result(
                query_stage="initial",
                query_error=str(exc),
            )
        parsed_result, error_message = self._parse_role_result(raw_result)
        if parsed_result is not None:
            return self._normalize_recoverable_failure(parsed_result)

        retries = max(0, int(self.config.structured_result_retries))
        for attempt in range(1, retries + 1):
            repair_prompt = self._build_repair_prompt(
                attempt=attempt,
                total=retries,
                reason=error_message or "No structured result was submitted.",
            )
            try:
                raw_result, reply = self.agent.query_structured_tool_result(
                    repair_prompt,
                    tool_name=self.config.result_tool_name,
                    method_name=self.config.result_method_name,
                    continue_previous=False,
                    disabled_tools=disabled_tools,
                    max_tool_rounds=self.config.structured_result_max_tool_rounds,
                    **query_overrides,
                )
            except Exception as exc:
                forced = self._force_structured_submission(
                    reason=f"Structured repair query failed (attempt {attempt}/{retries}): {exc}",
                    disabled_tools=disabled_tools,
                    query_overrides=query_overrides,
                )
                if forced is not None:
                    return forced
                return self._missing_structured_result(
                    query_stage="repair",
                    query_error=str(exc),
                    repair_attempt=attempt,
                )
            parsed_result, error_message = self._parse_role_result(raw_result)
            if parsed_result is not None:
                return self._normalize_recoverable_failure(parsed_result)

        if error_message or raw_result is None:
            forced = self._force_structured_submission(
                reason=error_message or "No structured result was submitted.",
                disabled_tools=disabled_tools,
                query_overrides=query_overrides,
            )
            if forced is not None:
                return forced

        if error_message and raw_result is not None:
            return RoleTaskResult(
                status="needs_follow_up",
                summary=error_message,
                metadata={"raw_tool_result": raw_result},
            )

        if not self.config.require_structured_result:
            fallback_summary = str(reply.message or "").strip() or (
                "Role agent finished without structured result."
            )
            return RoleTaskResult(
                status="needs_follow_up",
                summary=fallback_summary,
                metadata={
                    "raw_message": reply.message,
                    "tool_calls": [call.raw for call in reply.tool_calls],
                },
            )
        return self._missing_structured_result(
            raw_message=reply.message,
            tool_calls=[call.raw for call in reply.tool_calls],
        )

    def _parse_role_result(
        self,
        raw_result: dict[str, Any] | None,
    ) -> tuple[RoleTaskResult | None, str | None]:
        if raw_result is None:
            return None, None
        try:
            return RoleTaskResult.from_mapping(raw_result), None
        except ValueError as exc:
            return None, f"Invalid structured role result: {exc}"

    def _build_repair_prompt(self, *, attempt: int, total: int, reason: str) -> str:
        return (
            "Structured result repair step.\n"
            f"Reason: {reason}\n"
            f"Attempt: {attempt}/{total}\n"
            "Do not call reply.send_message.\n"
            "Now call only this tool and method with valid arguments.\n"
            "If native function calling is enabled, call the available function whose name "
            "ends with '__submit' for the role task result tool.\n"
            "Tool and method:\n"
            f"- tool: {self.config.result_tool_name}\n"
            f"- method: {self.config.result_method_name}\n"
            "Required fields:\n"
            "{"
            '"status":"completed|needs_follow_up|blocked|failed",'
            '"summary":"string"'
            "}\n"
            "Optional fields:\n"
            "{"
            '"artifact_type":"string|null",'
            '"artifact_title":"string|null",'
            '"artifact_content":"string|null",'
            '"artifact_format":"string",'
            '"tags":["string"],'
            '"required_changes":["string"],'
            '"unresolved_questions":["string"],'
            '"follow_ups":["string"],'
            '"metadata":{}'
            "}"
        )

    def _run_task(self, arguments: dict[str, Any]) -> dict[str, Any]:
        request = RoleTaskRequest.from_mapping(arguments)
        result = self.execute_task(request)
        return result.to_mapping()

    def _result_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.config.result_tool_name,
            description="Submit the structured result for the current role task.",
            internal=True,
            single_round=True,
            methods=[
                ToolMethodDefinition(
                    name=self.config.result_method_name,
                    description="Return the final structured role result payload.",
                    arguments_schema=dict(DEFAULT_ROLE_RESULT_SCHEMA),
                )
            ],
        )

    def _result_handlers(self) -> dict[str, ToolHandler]:
        return {self.config.result_method_name: self._capture_result}

    def _capture_result(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return dict(arguments)

    def _build_prompt(self, request: RoleTaskRequest) -> str:
        payload = request.to_mapping()
        focused_guidance = ""
        if self.config.role_name == "software_architect" and (request.phase or "") == "technical_design":
            focused_guidance = (
                "Technical-design execution rules for this run:\n"
                "- Do not call meeting.run_meeting in this task.\n"
                "- Keep exploration tight: at most 6 tool calls total.\n"
                "- Prefer one read_files call on the most relevant modules, then synthesize.\n"
                "- If the referenced files exist, submit status='completed' with concrete module-level design.\n"
                "- Use status='needs_follow_up' only when a truly missing external dependency blocks design.\n"
            )
        if self.config.role_name == "software_development_manager" and (request.phase or "") == "development_plan":
            focused_guidance = (
                "Development-plan execution rules for this run:\n"
                "- Do not call meeting.run_meeting in this task.\n"
                "- Keep exploration tight: at most 6 tool calls total.\n"
                "- Prefer one read_files call on the most relevant modules, then synthesize.\n"
                "- Submit status='completed' with a concrete file-by-file implementation plan.\n"
                "- Use status='needs_follow_up' only when a truly missing external dependency blocks planning.\n"
            )
        if self.config.role_name == "software_developer" and (request.phase or "") == "implementation":
            focused_guidance = (
                "Implementation execution rules for this run:\n"
                "- Do not call meeting.run_meeting in this task.\n"
                "- Keep exploration tight: at most 10 tool calls total before first write.\n"
                "- Read only target files needed for the current edits, then implement immediately.\n"
                "- Apply concrete file edits, run required diagnostics, and submit status='completed' with evidence.\n"
                "- Use status='needs_follow_up' only when a truly missing external dependency blocks implementation.\n"
            )
        return (
            f"Role: {self.config.role_name}\n"
            "Execute the task and then call this tool with your structured result:\n"
            f"- tool: {self.config.result_tool_name}\n"
            f"- method: {self.config.result_method_name}\n"
            "If native function calling is enabled, call the available function whose name "
            "ends with '__submit' for the role task result tool.\n"
            "Use this schema for arguments:\n"
            "{"
            '"status":"completed|needs_follow_up|blocked|failed",'
            '"summary":"string",'
            '"artifact_type":"string|null",'
            '"artifact_title":"string|null",'
            '"artifact_content":"string|null",'
            '"artifact_format":"string",'
            '"tags":["string"],'
            '"required_changes":["string"],'
            '"unresolved_questions":["string"],'
            '"follow_ups":["string"],'
            '"metadata":{}'
            "}\n"
            "Prioritize finishing the task within limited tool rounds. Avoid exhaustive browsing.\n"
            "Use only the minimum file reads/searches needed to produce a concrete result.\n"
            "If uncertainty remains, submit status='needs_follow_up' with specific required_changes.\n"
            "If any string field is too long, first call pagination.append_page "
            "for a stable target until status='stop', then use the matching "
            "pagination://<target> reference. Never submit a pagination:// "
            "reference unless that target was populated in the current task. "
            "When the content is already in a project file, either submit the "
            "literal final content or a concise implementation report; do not "
            "invent unresolved pagination references.\n"
            f"{focused_guidance}"
            "After calling that tool, optionally call reply.send_message with a short human summary.\n"
            f"Task payload:\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
        )

    def _query_overrides(self) -> dict[str, Any]:
        overrides: dict[str, Any] = {}
        if self.config.structured_result_max_output_tokens is not None:
            overrides["max_output_tokens"] = int(self.config.structured_result_max_output_tokens)
        overrides["parallel_tool_calls"] = bool(self.config.structured_result_parallel_tool_calls)
        return overrides

    def _missing_structured_result(
        self,
        *,
        query_stage: str | None = None,
        query_error: str | None = None,
        repair_attempt: int | None = None,
        raw_message: str | None = None,
        tool_calls: list[dict[str, Any]] | None = None,
    ) -> RoleTaskResult:
        metadata: dict[str, Any] = {}
        if query_stage is not None:
            metadata["query_stage"] = query_stage
        if query_error is not None:
            metadata["query_error"] = query_error
        if repair_attempt is not None:
            metadata["repair_attempt"] = repair_attempt
        if raw_message is not None:
            metadata["raw_message"] = raw_message
        if tool_calls is not None:
            metadata["tool_calls"] = list(tool_calls)
        return RoleTaskResult(
            status="needs_follow_up",
            summary=(
                "Role agent did not submit a structured task result via "
                f"{self.config.result_tool_name}.{self.config.result_method_name}."
            ),
            follow_ups=[
                f"Call {self.config.result_tool_name}.{self.config.result_method_name} with status and summary."
            ],
            metadata=metadata,
        )

    def _force_structured_submission(
        self,
        *,
        reason: str,
        disabled_tools: set[str],
        query_overrides: dict[str, Any],
    ) -> RoleTaskResult | None:
        if not self.config.force_structured_submit_on_failure:
            return None
        forced_disabled_tools = {
            tool.name
            for tool in self.agent.list_tools()
            if tool.name != self.config.result_tool_name
        }
        forced_disabled_tools.update(disabled_tools)
        forced_prompt = (
            "Forced structured close-out.\n"
            f"Reason: {reason}\n"
            "You must submit a final structured result now.\n"
            "No additional exploration is allowed.\n"
            "Set status to:\n"
            "- completed: if the task is done.\n"
            "- needs_follow_up: if specific actions are still needed.\n"
            "- blocked: only if an external blocker exists.\n"
            "- failed: only for irrecoverable errors.\n"
            "Call only the structured result submit tool/function."
        )
        try:
            raw_result, _reply = self.agent.query_structured_tool_result(
                forced_prompt,
                tool_name=self.config.result_tool_name,
                method_name=self.config.result_method_name,
                continue_previous=False,
                disabled_tools=forced_disabled_tools,
                max_tool_rounds=max(1, int(self.config.forced_submit_max_tool_rounds)),
                **query_overrides,
            )
        except Exception:
            return None
        parsed_result, _error_message = self._parse_role_result(raw_result)
        if parsed_result is None:
            return None
        parsed_result = self._normalize_recoverable_failure(parsed_result)
        parsed_result.metadata = dict(parsed_result.metadata)
        parsed_result.metadata["forced_structured_submit"] = True
        parsed_result.metadata["forced_structured_submit_reason"] = reason
        return parsed_result

    def _normalize_recoverable_failure(self, result: RoleTaskResult) -> RoleTaskResult:
        if result.status != "failed":
            return result
        summary = (result.summary or "").strip()
        summary_lower = summary.lower()
        recoverable_signals = (
            "maximum tool rounds",
            "tool rounds",
            "without producing a reply",
            "before providing a reply",
            "request too large",
            "rate limit",
            "context window",
            "initial structured query failed",
            "no additional exploration",
        )
        if not any(signal in summary_lower for signal in recoverable_signals):
            return result
        result.status = "needs_follow_up"
        if not summary:
            result.summary = "Recoverable execution limit reached. Follow-up is required."
        result.required_changes = list(result.required_changes) + [
            "Continue from current workspace state and complete the phase with scoped edits."
        ]
        result.follow_ups = list(result.follow_ups) + [
            "Prioritize required deliverables and submit _role_task_result.submit when complete."
        ]
        result.metadata = dict(result.metadata)
        result.metadata["normalized_from_failed"] = True
        return result
