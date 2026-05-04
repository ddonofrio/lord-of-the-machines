from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from lord_of_the_machines.agent_tools import ArtifactRegistryTool, ArtifactRegistryToolConfig
from lord_of_the_machines.llm import BaseAgent
from tests.helpers.fake_openai import FakeClient
from tests.helpers.outputs import tool_output


class ArtifactRegistryToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self._tmpdir.name)
        self.tool = ArtifactRegistryTool(
            self.root / "artifacts",
            config=ArtifactRegistryToolConfig(root_path=self.root / "artifacts"),
        )

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_publish_list_get_and_update_artifact(self) -> None:
        published = self.tool.handlers()["publish_artifact"](
            {
                "mission_id": "mission_alpha",
                "phase": "product_direction",
                "artifact_type": "hlr",
                "title": "High Level Requirement",
                "content": "# HLR",
                "tags": ["product", "phase1"],
            }
        )
        artifact = published["artifact"]
        artifact_id = artifact["artifact_id"]
        self.assertEqual(artifact["version"], 1)
        self.assertEqual(artifact["status"], "published")

        listed = self.tool.handlers()["list_artifacts"](
            {
                "mission_id": "mission_alpha",
                "phase": "product_direction",
                "artifact_type": "hlr",
            }
        )
        self.assertEqual(len(listed["artifacts"]), 1)
        self.assertEqual(listed["artifacts"][0]["artifact_id"], artifact_id)

        loaded = self.tool.handlers()["get_artifact"]({"artifact_id": artifact_id})
        self.assertEqual(loaded["artifact"]["title"], "High Level Requirement")

        updated = self.tool.handlers()["update_artifact"](
            {
                "artifact_id": artifact_id,
                "content": "# HLR Updated",
                "status": "approved",
                "tags": [],
            }
        )
        self.assertEqual(updated["artifact"]["version"], 2)
        self.assertEqual(updated["artifact"]["status"], "approved")
        self.assertEqual(updated["artifact"]["tags"], [])

    def test_tool_installs_on_base_agent(self) -> None:
        published = self.tool.handlers()["publish_artifact"](
            {
                "mission_id": "mission_beta",
                "phase": "planning",
                "artifact_type": "brief",
                "title": "Brief",
                "content": "initial",
            }
        )
        artifact_id = published["artifact"]["artifact_id"]

        client = FakeClient(
            [
                tool_output(
                    {
                        "tool": "artifact_registry",
                        "method": "get_artifact",
                        "arguments": {"artifact_id": artifact_id},
                    },
                    {
                        "tool": "reply",
                        "method": "send_message",
                        "arguments": {"message": "artifact loaded"},
                    },
                )
            ]
        )
        agent = BaseAgent.new(client=client, rate_limiter=None)
        self.tool.install(agent)

        reply = agent.query("load artifact")

        self.assertEqual(reply.message, "artifact loaded")
        envelope = json.loads(client.responses.calls[0]["input"])
        available_tools = envelope["runtime_context"]["available_tools"]
        self.assertTrue(any(tool["name"] == "artifact_registry" for tool in available_tools))


if __name__ == "__main__":
    unittest.main()
