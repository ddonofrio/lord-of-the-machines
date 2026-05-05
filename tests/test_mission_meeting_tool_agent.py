from __future__ import annotations

import json
import unittest

from lord_of_the_machines.llm import BaseAgent
from lord_of_the_machines.mission import MeetingRequest, MeetingRoleExecutor, MeetingToolAgent, RoleTaskRequest
from tests.helpers.fake_openai import FakeClient
from tests.helpers.outputs import reply_output, tool_output


class MeetingToolAgentTests(unittest.TestCase):
    def test_execute_meeting_returns_structured_result(self) -> None:
        organizer_client = FakeClient(
            [
                tool_output(
                    {
                        "tool": "_meeting_result",
                        "method": "submit",
                        "arguments": {
                            "status": "completed",
                            "meeting_summary": "Consensus reached after two rounds.",
                            "decisions": ["Split scope in two milestones"],
                            "required_changes": ["Clarify analytics acceptance criteria"],
                            "unresolved_questions": ["Retention baseline source"],
                            "follow_ups": ["PM to update PRD"],
                            "final_recommendation": "Proceed with milestone 1 first.",
                        },
                    }
                )
            ]
        )
        organizer_agent = BaseAgent.new(client=organizer_client, rate_limiter=None)
        meeting_tool = MeetingToolAgent(organizer_agent)

        result = meeting_tool.handlers()["run_meeting"](
            {
                "objective": "Align scope for phase 1",
                "presenter": "product_director",
                "participants": ["product_manager", "software_architect"],
                "structured_input": "Mission draft",
            }
        )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["decisions"][0], "Split scope in two milestones")
        self.assertIn("Proceed with milestone 1", result["final_recommendation"])

    def test_meeting_tool_can_be_installed_on_host_agent(self) -> None:
        organizer_client = FakeClient(
            [
                tool_output(
                    {
                        "tool": "_meeting_result",
                        "method": "submit",
                        "arguments": {
                            "status": "completed",
                            "meeting_summary": "Done",
                        },
                    }
                )
            ]
        )
        host_client = FakeClient(
            [
                tool_output(
                    {
                        "tool": "meeting",
                        "method": "run_meeting",
                        "arguments": {
                            "objective": "Kickoff",
                            "presenter": "product_director",
                        },
                    },
                    {
                        "tool": "reply",
                        "method": "send_message",
                        "arguments": {"message": "meeting done"},
                    },
                )
            ]
        )
        organizer_agent = BaseAgent.new(client=organizer_client, rate_limiter=None)
        host_agent = BaseAgent.new(client=host_client, rate_limiter=None)
        meeting_tool = MeetingToolAgent(organizer_agent)
        meeting_tool.install(host_agent)

        reply = host_agent.query("run kickoff meeting")

        self.assertEqual(reply.message, "meeting done")
        envelope = json.loads(host_client.responses.calls[0]["input"])
        tool_names = [tool["name"] for tool in envelope["runtime_context"]["available_tools"]]
        self.assertIn("meeting", tool_names)
        meeting_tool = next(tool for tool in envelope["runtime_context"]["available_tools"] if tool["name"] == "meeting")
        run_meeting = next(method for method in meeting_tool["methods"] if method["name"] == "run_meeting")
        self.assertIn(
            "product_director",
            run_meeting["arguments_schema"]["properties"]["presenter"]["enum"],
        )
        self.assertIn(
            "product_manager",
            run_meeting["arguments_schema"]["properties"]["participants"]["items"]["enum"],
        )

    def test_meeting_tool_lists_available_roles(self) -> None:
        meeting_tool = MeetingToolAgent(BaseAgent.new(client=FakeClient(), rate_limiter=None))

        result = meeting_tool.handlers()["list_available_roles"]({})

        role_names = [role["role"] for role in result["roles"]]
        self.assertIn("product_manager", role_names)
        self.assertIn("software_architect", role_names)

    def test_meeting_organizer_can_call_participant_agent_tool(self) -> None:
        product_manager_client = FakeClient(
            [
                tool_output(
                    {
                        "tool": "_role_task_result",
                        "method": "submit",
                        "arguments": {
                            "status": "completed",
                            "summary": "Acceptance criteria should be explicit.",
                        },
                    }
                )
            ]
        )
        organizer_client = FakeClient(
            [
                tool_output(
                    {
                        "tool": "product_manager_agent",
                        "method": "run_task",
                        "arguments": {
                            "objective": "Review meeting input from product perspective.",
                        },
                    }
                ),
                tool_output(
                    {
                        "tool": "_meeting_result",
                        "method": "submit",
                        "arguments": {
                            "status": "completed",
                            "meeting_summary": "Product review completed.",
                            "decisions": ["Clarify acceptance criteria"],
                        },
                    }
                ),
            ]
        )
        meeting_tool = MeetingToolAgent(
            BaseAgent.new(client=organizer_client, rate_limiter=None),
            participant_agents={
                "product_manager": BaseAgent.new(client=product_manager_client, rate_limiter=None),
            },
        )

        result = meeting_tool.execute_meeting(
            MeetingRequest(
                objective="Review direction",
                presenter="product_director",
                participants=["product_manager"],
            )
        )

        self.assertEqual(result.status, "completed")
        self.assertEqual(len(product_manager_client.responses.calls), 1)
        self.assertIn("Clarify acceptance criteria", result.decisions)

    def test_meeting_role_executor_adapts_to_role_task_shape(self) -> None:
        organizer_client = FakeClient(
            [
                tool_output(
                    {
                        "tool": "_meeting_result",
                        "method": "submit",
                        "arguments": {
                            "status": "completed",
                            "meeting_summary": "All aligned",
                            "decisions": ["Start implementation"],
                        },
                    }
                )
            ]
        )
        meeting_tool = MeetingToolAgent(BaseAgent.new(client=organizer_client, rate_limiter=None))
        executor = MeetingRoleExecutor(
            meeting_tool=meeting_tool,
            presenter="product_director",
            participants=["product_manager", "software_development_manager"],
        )

        role_result = executor.execute_task(
            request=RoleTaskRequest(
                objective="Plan implementation",
                mission_id="m1",
                phase="product_direction",
                context={"document": "HLR"},
                max_rounds=2,
            )
        )

        self.assertEqual(role_result.status, "completed")
        self.assertEqual(role_result.artifact_type, "meeting_summary")
        self.assertIn("Meeting Summary", role_result.artifact_content or "")

    def test_meeting_returns_follow_up_when_structured_result_is_missing(self) -> None:
        organizer_client = FakeClient([reply_output("Meeting done.")])
        meeting_tool = MeetingToolAgent(BaseAgent.new(client=organizer_client, rate_limiter=None))

        result = meeting_tool.execute_meeting(
            request=MeetingRequest(
                objective="Validate proposal",
                presenter="product_director",
            )
        )

        self.assertEqual(result.status, "needs_follow_up")
        self.assertIn("did not submit a structured meeting result", result.meeting_summary)


if __name__ == "__main__":
    unittest.main()
