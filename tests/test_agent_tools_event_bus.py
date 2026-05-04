from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from lord_of_the_machines.agent_tools import EventBusTool, EventBusToolConfig
from lord_of_the_machines.llm import BaseAgent
from tests.helpers.fake_openai import FakeClient
from tests.helpers.outputs import tool_output


class EventBusToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self._tmpdir.name)
        self.tool = EventBusTool(
            self.root / "event_bus",
            config=EventBusToolConfig(root_path=self.root / "event_bus"),
        )

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_publish_consume_and_ack(self) -> None:
        published_1 = self.tool.handlers()["publish_event"](
            {
                "topic": "mission.created",
                "mission_id": "mission_alpha",
                "payload": {"title": "Alpha"},
            }
        )
        published_2 = self.tool.handlers()["publish_event"](
            {
                "topic": "artifact.published",
                "mission_id": "mission_alpha",
                "payload": {"artifact_id": "A-1"},
            }
        )
        self.assertEqual(published_1["event"]["sequence"], 1)
        self.assertEqual(published_2["event"]["sequence"], 2)

        consumed = self.tool.handlers()["consume_events"](
            {
                "consumer_id": "product_director",
            }
        )
        self.assertEqual(len(consumed["events"]), 2)
        first_event = consumed["events"][0]

        acked = self.tool.handlers()["ack_event"](
            {
                "consumer_id": "product_director",
                "event_id": first_event["event_id"],
            }
        )
        self.assertEqual(acked["consumer_state"]["last_acked_sequence"], 1)

        next_batch = self.tool.handlers()["consume_events"](
            {
                "consumer_id": "product_director",
            }
        )
        self.assertEqual(len(next_batch["events"]), 1)
        self.assertEqual(next_batch["events"][0]["sequence"], 2)

    def test_list_events_filters(self) -> None:
        self.tool.handlers()["publish_event"](
            {
                "topic": "mission.created",
                "mission_id": "m1",
                "payload": {},
            }
        )
        self.tool.handlers()["publish_event"](
            {
                "topic": "mission.completed",
                "mission_id": "m1",
                "payload": {},
            }
        )
        self.tool.handlers()["publish_event"](
            {
                "topic": "mission.created",
                "mission_id": "m2",
                "payload": {},
            }
        )

        filtered = self.tool.handlers()["list_events"](
            {
                "topics": ["mission.created"],
                "mission_id": "m1",
            }
        )
        self.assertEqual(len(filtered["events"]), 1)
        self.assertEqual(filtered["events"][0]["topic"], "mission.created")
        self.assertEqual(filtered["events"][0]["mission_id"], "m1")

    def test_tool_installs_on_base_agent(self) -> None:
        client = FakeClient(
            [
                tool_output(
                    {
                        "tool": "event_bus",
                        "method": "get_consumer_state",
                        "arguments": {"consumer_id": "planner"},
                    },
                    {
                        "tool": "reply",
                        "method": "send_message",
                        "arguments": {"message": "state loaded"},
                    },
                )
            ]
        )
        agent = BaseAgent.new(client=client, rate_limiter=None)
        self.tool.install(agent)

        reply = agent.query("load consumer state")

        self.assertEqual(reply.message, "state loaded")
        envelope = json.loads(client.responses.calls[0]["input"])
        available_tools = envelope["runtime_context"]["available_tools"]
        self.assertTrue(any(tool["name"] == "event_bus" for tool in available_tools))


if __name__ == "__main__":
    unittest.main()
