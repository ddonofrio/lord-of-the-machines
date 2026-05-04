from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from lord_of_the_machines.llm import BaseAgent, ToolDefinition, ToolMethodDefinition
from lord_of_the_machines.llm.tools import ToolHandler
from lord_of_the_machines.mission.contracts import (
    MeetingRequest,
    MeetingResult,
    RoleTaskRequest,
    RoleTaskResult,
)


DEFAULT_RUN_MEETING_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "objective": {"type": "string"},
        "presenter": {"type": "string"},
        "participants": {"type": "array", "items": {"type": "string"}},
        "structured_input": {"type": "string"},
        "constraints": {"type": "array", "items": {"type": "string"}},
        "max_rounds": {"type": "integer"},
        "mission_id": {"type": "string"},
        "phase": {"type": "string"},
        "metadata": {"type": "object"},
    },
    "required": ["objective", "presenter"],
}


@dataclass(slots=True)
class MeetingToolAgentConfig:
    tool_name: str = "meeting"
    method_name: str = "run_meeting"
    description: str = (
        "Run a structured cross-role meeting. The tool is backed by a specialized meeting organizer agent."
    )
    method_description: str = (
        "Coordinate a meeting round and return a structured summary with decisions, doubts and follow-ups."
    )
    arguments_schema: dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_RUN_MEETING_SCHEMA))


class MeetingToolAgent:
    def __init__(
        self,
        organizer_agent: BaseAgent,
        *,
        config: MeetingToolAgentConfig | None = None,
    ) -> None:
        self.organizer_agent = organizer_agent
        self.config = config or MeetingToolAgentConfig()

    def install(self, host_agent: BaseAgent) -> None:
        host_agent.add_tool(self.definition(), handlers=self.handlers())

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.config.tool_name,
            description=self.config.description,
            methods=[
                ToolMethodDefinition(
                    name=self.config.method_name,
                    description=self.config.method_description,
                    arguments_schema=dict(self.config.arguments_schema),
                )
            ],
        )

    def handlers(self) -> dict[str, ToolHandler]:
        return {self.config.method_name: self._run_meeting}

    def execute_meeting(self, request: MeetingRequest) -> MeetingResult:
        prompt = self._build_prompt(request)
        reply = self.organizer_agent.query(prompt)
        return self._parse_meeting_result(reply.message)

    def _run_meeting(self, arguments: dict[str, Any]) -> dict[str, Any]:
        request = MeetingRequest.from_mapping(arguments)
        result = self.execute_meeting(request)
        return result.to_mapping()

    def _build_prompt(self, request: MeetingRequest) -> str:
        payload = request.to_mapping()
        return (
            "Run the meeting process and return ONLY a JSON object with this schema:\n"
            "{"
            '"status":"completed|needs_follow_up|blocked|failed",'
            '"meeting_summary":"string",'
            '"decisions":["string"],'
            '"required_changes":["string"],'
            '"unresolved_questions":["string"],'
            '"follow_ups":["string"],'
            '"final_recommendation":"string",'
            '"metadata":{}'
            "}\n"
            "Do not include markdown fences.\n"
            f"Meeting payload:\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
        )

    def _parse_meeting_result(self, message: str) -> MeetingResult:
        stripped = message.strip()
        if not stripped:
            return MeetingResult(
                status="needs_follow_up",
                meeting_summary="Meeting organizer returned an empty response.",
            )
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            return MeetingResult(
                status="needs_follow_up",
                meeting_summary=stripped,
            )
        return MeetingResult.from_mapping(parsed if isinstance(parsed, dict) else {})


@dataclass(slots=True)
class MeetingRoleExecutor:
    meeting_tool: MeetingToolAgent
    presenter: str
    participants: list[str] = field(default_factory=list)

    def execute_task(self, request: RoleTaskRequest) -> RoleTaskResult:
        meeting_request = MeetingRequest(
            objective=request.objective,
            presenter=self.presenter,
            participants=list(self.participants),
            structured_input=json.dumps(request.context, ensure_ascii=False, indent=2) if request.context else None,
            constraints=list(request.constraints),
            max_rounds=request.max_rounds,
            mission_id=request.mission_id,
            phase=request.phase,
            metadata=dict(request.metadata),
        )
        meeting_result = self.meeting_tool.execute_meeting(meeting_request)
        return RoleTaskResult(
            status=meeting_result.status,
            summary=meeting_result.meeting_summary,
            artifact_type="meeting_summary",
            artifact_title=f"Meeting summary: {request.phase or 'phase'}",
            artifact_content=self._meeting_artifact_content(meeting_result),
            artifact_format="markdown",
            required_changes=list(meeting_result.required_changes),
            unresolved_questions=list(meeting_result.unresolved_questions),
            follow_ups=list(meeting_result.follow_ups),
            metadata=dict(meeting_result.metadata),
        )

    def _meeting_artifact_content(self, result: MeetingResult) -> str:
        lines = [
            "# Meeting Summary",
            "",
            result.meeting_summary.strip() or "No summary provided.",
            "",
            "## Decisions",
        ]
        if result.decisions:
            lines.extend([f"- {item}" for item in result.decisions])
        else:
            lines.append("- None")
        lines.extend(["", "## Required Changes"])
        if result.required_changes:
            lines.extend([f"- {item}" for item in result.required_changes])
        else:
            lines.append("- None")
        lines.extend(["", "## Unresolved Questions"])
        if result.unresolved_questions:
            lines.extend([f"- {item}" for item in result.unresolved_questions])
        else:
            lines.append("- None")
        lines.extend(["", "## Follow Ups"])
        if result.follow_ups:
            lines.extend([f"- {item}" for item in result.follow_ups])
        else:
            lines.append("- None")
        lines.extend(["", "## Recommendation", result.final_recommendation.strip() or "No recommendation provided."])
        return "\n".join(lines)
