from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from lord_of_the_machines.agent_tools import MissionRegistryTool, MissionRegistryToolConfig
from lord_of_the_machines.llm import BaseAgent
from tests.helpers.fake_openai import FakeClient
from tests.helpers.outputs import tool_output


class MissionRegistryToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self._tmpdir.name)
        self.tool = MissionRegistryTool(
            self.root / "missions",
            config=MissionRegistryToolConfig(root_path=self.root / "missions"),
        )

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_create_update_and_assign_roles(self) -> None:
        created = self.tool.handlers()["create_mission"](
            {
                "mission_id": "mission_alpha",
                "title": "Alpha Mission",
                "description": "Build event driven runtime",
            }
        )
        self.assertEqual(created["mission"]["status"], "new")

        updated_status = self.tool.handlers()["update_mission_status"](
            {
                "mission_id": "mission_alpha",
                "status": "in_progress",
                "reason": "kickoff started",
            }
        )
        self.assertEqual(updated_status["mission"]["status"], "in_progress")

        updated_phase = self.tool.handlers()["update_mission_phase"](
            {
                "mission_id": "mission_alpha",
                "phase": "product_direction",
                "status": "completed",
                "notes": "HLR published",
            }
        )
        self.assertEqual(updated_phase["mission"]["phase_status"]["product_direction"], "completed")

        assigned = self.tool.handlers()["assign_mission_role"](
            {
                "mission_id": "mission_alpha",
                "role": "product_manager",
                "agent_id": "pm_01",
            }
        )
        self.assertIn("pm_01", assigned["mission"]["role_assignments"]["product_manager"])

        unassigned = self.tool.handlers()["unassign_mission_role"](
            {
                "mission_id": "mission_alpha",
                "role": "product_manager",
                "agent_id": "pm_01",
            }
        )
        self.assertEqual(unassigned["mission"]["role_assignments"]["product_manager"], [])

    def test_list_missions_filters_by_status(self) -> None:
        self.tool.handlers()["create_mission"](
            {
                "mission_id": "m_new",
                "title": "New mission",
                "description": "pending",
            }
        )
        self.tool.handlers()["create_mission"](
            {
                "mission_id": "m_done",
                "title": "Done mission",
                "description": "complete",
                "initial_status": "completed",
            }
        )
        pending = self.tool.handlers()["list_missions"]({"statuses": ["new"]})
        self.assertEqual(len(pending["missions"]), 1)
        self.assertEqual(pending["missions"][0]["mission_id"], "m_new")

    def test_tool_installs_on_base_agent(self) -> None:
        self.tool.handlers()["create_mission"](
            {
                "mission_id": "mission_beta",
                "title": "Mission Beta",
                "description": "beta flow",
            }
        )
        client = FakeClient(
            [
                tool_output(
                    {
                        "tool": "mission_registry",
                        "method": "get_mission",
                        "arguments": {"mission_id": "mission_beta"},
                    },
                    {
                        "tool": "reply",
                        "method": "send_message",
                        "arguments": {"message": "mission loaded"},
                    },
                )
            ]
        )
        agent = BaseAgent.new(client=client, rate_limiter=None)
        self.tool.install(agent)

        reply = agent.query("load mission beta")

        self.assertEqual(reply.message, "mission loaded")
        envelope = json.loads(client.responses.calls[0]["input"])
        available_tools = envelope["runtime_context"]["available_tools"]
        self.assertTrue(any(tool["name"] == "mission_registry" for tool in available_tools))


if __name__ == "__main__":
    unittest.main()

