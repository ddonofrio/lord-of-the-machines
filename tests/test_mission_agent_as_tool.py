from __future__ import annotations

import json
import unittest

from lord_of_the_machines.llm import BaseAgent
from lord_of_the_machines.mission import AgentAsToolBridge, AgentAsToolConfig
from tests.helpers.fake_openai import FakeClient
from tests.helpers.outputs import reply_output, tool_output


class AgentAsToolBridgeTests(unittest.TestCase):
    def test_bridge_executes_role_agent_and_returns_structured_payload(self) -> None:
        role_client = FakeClient(
            [
                reply_output(
                    json.dumps(
                        {
                            "status": "completed",
                            "summary": "Product direction drafted.",
                            "artifact_type": "hlr",
                            "artifact_title": "HLR",
                            "artifact_content": "# High Level Requirement",
                        }
                    )
                )
            ]
        )
        role_agent = BaseAgent.new(client=role_client, rate_limiter=None)
        bridge = AgentAsToolBridge(
            role_agent,
            config=AgentAsToolConfig(
                role_name="product_director",
                tool_name="product_director_agent",
            ),
        )

        result = bridge.handlers()["run_task"](
            {
                "objective": "Define the high-level product direction.",
                "mission_id": "mission_alpha",
                "phase": "product_direction",
            }
        )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["artifact_type"], "hlr")
        self.assertIn("Product direction drafted", result["summary"])

    def test_bridge_can_be_installed_on_host_agent_as_a_tool(self) -> None:
        role_client = FakeClient(
            [
                reply_output(
                    json.dumps(
                        {
                            "status": "completed",
                            "summary": "Role task done.",
                        }
                    )
                )
            ]
        )
        host_client = FakeClient(
            [
                tool_output(
                    {
                        "tool": "product_director_agent",
                        "method": "run_task",
                        "arguments": {"objective": "Run role task"},
                    },
                    {
                        "tool": "reply",
                        "method": "send_message",
                        "arguments": {"message": "host done"},
                    },
                )
            ]
        )

        role_agent = BaseAgent.new(client=role_client, rate_limiter=None)
        host_agent = BaseAgent.new(client=host_client, rate_limiter=None)
        bridge = AgentAsToolBridge(
            role_agent,
            config=AgentAsToolConfig(role_name="product_director", tool_name="product_director_agent"),
        )
        bridge.install(host_agent)

        reply = host_agent.query("execute role")

        self.assertEqual(reply.message, "host done")
        envelope = json.loads(host_client.responses.calls[0]["input"])
        tool_names = [tool["name"] for tool in envelope["runtime_context"]["available_tools"]]
        self.assertIn("product_director_agent", tool_names)


if __name__ == "__main__":
    unittest.main()
