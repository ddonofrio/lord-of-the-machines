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
from lord_of_the_machines.mission.prompting import (
    RolePromptProfile,
    compose_system_prompt,
    default_role_profile,
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


DEFAULT_MEETING_RESULT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "status": {
            "type": "string",
            "enum": ["completed", "needs_follow_up", "blocked", "failed"],
        },
        "meeting_summary": {"type": "string"},
        "decisions": {"type": "array", "items": {"type": "string"}},
        "required_changes": {"type": "array", "items": {"type": "string"}},
        "unresolved_questions": {"type": "array", "items": {"type": "string"}},
        "follow_ups": {"type": "array", "items": {"type": "string"}},
        "final_recommendation": {"type": "string"},
        "metadata": {"type": "object"},
    },
    "required": ["status"],
}


@dataclass(slots=True)
class MeetingToolAgentConfig:
    role_name: str = "meeting_organizer"
    include_golden_rules: bool = True
    extra_dna_rulesets: tuple[str, ...] = ()
    role_profile_override: RolePromptProfile | None = None
    tool_name: str = "meeting"
    method_name: str = "run_meeting"
    description: str = (
        "Run a structured cross-role meeting. The tool is backed by a specialized meeting organizer agent."
    )
    method_description: str = (
        "Coordinate a meeting round and return a structured summary with decisions, doubts and follow-ups."
    )
    arguments_schema: dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_RUN_MEETING_SCHEMA))
    result_tool_name: str = "_meeting_result"
    result_method_name: str = "submit"


class MeetingToolAgent:
    def __init__(
        self,
        organizer_agent: BaseAgent,
        *,
        config: MeetingToolAgentConfig | None = None,
    ) -> None:
        self.organizer_agent = organizer_agent
        self.config = config or MeetingToolAgentConfig()
        self.organizer_agent.set_system_prompt(self._build_system_prompt())
        self.organizer_agent.add_tool(self._result_definition(), handlers=self._result_handlers())

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
        raw_result, reply = self.organizer_agent.query_structured_tool_result(
            prompt,
            tool_name=self.config.result_tool_name,
            method_name=self.config.result_method_name,
        )
        if raw_result is not None:
            try:
                return MeetingResult.from_mapping(raw_result)
            except ValueError as exc:
                return MeetingResult(
                    status="needs_follow_up",
                    meeting_summary=f"Invalid structured meeting result: {exc}",
                    metadata={"raw_tool_result": raw_result},
                )
        return MeetingResult(
            status="needs_follow_up",
            meeting_summary=(
                "Meeting organizer did not submit a structured meeting result via "
                f"{self.config.result_tool_name}.{self.config.result_method_name}."
            ),
            follow_ups=[
                "Call the required structured meeting result tool with status and summary.",
            ],
            metadata={
                "raw_message": reply.message,
                "tool_calls": [call.raw for call in reply.tool_calls],
            },
        )

    def _run_meeting(self, arguments: dict[str, Any]) -> dict[str, Any]:
        request = MeetingRequest.from_mapping(arguments)
        result = self.execute_meeting(request)
        return result.to_mapping()

    def _build_system_prompt(self) -> str:
        profile = self.config.role_profile_override or default_role_profile(self.config.role_name)
        return compose_system_prompt(
            profile,
            include_golden_rules=self.config.include_golden_rules,
            extra_rulesets=self.config.extra_dna_rulesets,
        )

    def _result_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.config.result_tool_name,
            description="Submit the structured result for the current meeting.",
            internal=True,
            single_round=True,
            methods=[
                ToolMethodDefinition(
                    name=self.config.result_method_name,
                    description="Return the final structured meeting result payload.",
                    arguments_schema=dict(DEFAULT_MEETING_RESULT_SCHEMA),
                )
            ],
        )

    def _result_handlers(self) -> dict[str, ToolHandler]:
        return {self.config.result_method_name: self._capture_result}

    def _capture_result(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return dict(arguments)

    def _build_prompt(self, request: MeetingRequest) -> str:
        payload = request.to_mapping()
        return (
            "Run the meeting process and then call this tool with your structured result:\n"
            f"- tool: {self.config.result_tool_name}\n"
            f"- method: {self.config.result_method_name}\n"
            "Use this schema for arguments:\n"
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
            "After calling that tool, optionally call reply.send_message with a short human summary.\n"
            f"Meeting payload:\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
        )


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
