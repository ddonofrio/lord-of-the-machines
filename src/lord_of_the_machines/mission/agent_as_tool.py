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


@dataclass(slots=True)
class AgentAsToolConfig:
    role_name: str
    tool_name: str
    method_name: str = "run_task"
    description: str = "Execute a structured role task through a specialized role agent."
    method_description: str = "Run one task and return a structured completion payload."
    arguments_schema: dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_RUN_TASK_SCHEMA))
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
        reply = self.agent.query(prompt, continue_previous=request.continue_previous)
        return self._parse_role_result(reply.message)

    def _run_task(self, arguments: dict[str, Any]) -> dict[str, Any]:
        request = RoleTaskRequest.from_mapping(arguments)
        result = self.execute_task(request)
        return result.to_mapping()

    def _build_prompt(self, request: RoleTaskRequest) -> str:
        payload = request.to_mapping()
        return (
            f"Role: {self.config.role_name}\n"
            "Execute the task and return ONLY a JSON object with this schema:\n"
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
            "Do not include markdown fences.\n"
            f"Task payload:\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
        )

    def _parse_role_result(self, message: str) -> RoleTaskResult:
        stripped = message.strip()
        if not stripped:
            return RoleTaskResult(
                status="needs_follow_up",
                summary="Role agent returned an empty response.",
            )
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            return RoleTaskResult(
                status="needs_follow_up",
                summary=stripped,
            )
        return RoleTaskResult.from_mapping(parsed if isinstance(parsed, dict) else {})
