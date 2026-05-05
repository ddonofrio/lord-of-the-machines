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
        raw_result, reply = self.agent.query_structured_tool_result(
            prompt,
            tool_name=self.config.result_tool_name,
            method_name=self.config.result_method_name,
            continue_previous=request.continue_previous,
        )
        if raw_result is not None:
            try:
                return RoleTaskResult.from_mapping(raw_result)
            except ValueError as exc:
                return RoleTaskResult(
                    status="needs_follow_up",
                    summary=f"Invalid structured role result: {exc}",
                    metadata={"raw_tool_result": raw_result},
                )
        return RoleTaskResult(
            status="needs_follow_up",
            summary=(
                "Role agent did not submit a structured task result via "
                f"{self.config.result_tool_name}.{self.config.result_method_name}."
            ),
            follow_ups=[
                "Call the required structured result tool with status and summary.",
            ],
            metadata={
                "raw_message": reply.message,
                "tool_calls": [call.raw for call in reply.tool_calls],
            },
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
        return (
            f"Role: {self.config.role_name}\n"
            "Execute the task and then call this tool with your structured result:\n"
            f"- tool: {self.config.result_tool_name}\n"
            f"- method: {self.config.result_method_name}\n"
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
            "If any string field is too long, first call pagination.append_page "
            "for a stable target until status='stop', then use the matching "
            "pagination://<target> reference. Never submit a pagination:// "
            "reference unless that target was populated in the current task. "
            "When the content is already in a project file, either submit the "
            "literal final content or a concise implementation report; do not "
            "invent unresolved pagination references.\n"
            "After calling that tool, optionally call reply.send_message with a short human summary.\n"
            f"Task payload:\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
        )
