from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from lord_of_the_machines.agent_tools import TodoListTool, TodoListToolConfig
from lord_of_the_machines.llm import BaseAgent
from tests.helpers.fake_openai import FakeClient
from tests.helpers.outputs import tool_output


class TodoListToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self._tmpdir.name)
        self.tool = TodoListTool(
            self.root / "todos",
            config=TodoListToolConfig(root_path=self.root / "todos"),
        )

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_create_add_update_unmark_and_remove_items(self) -> None:
        created = self.tool.handlers()["create_todo_list"](
            {
                "agent_id": "planner",
                "list_name": "sprint_alpha",
                "tasks": ["Design API", "Write tests"],
            }
        )
        self.assertTrue(created["created"])
        self.assertEqual(created["todo_list"]["total_tasks"], 2)

        added = self.tool.handlers()["add_todo_items"](
            {
                "agent_id": "planner",
                "list_name": "sprint_alpha",
                "tasks": ["Implement feature"],
            }
        )
        self.assertEqual(len(added["added_items"]), 1)
        item_id = added["added_items"][0]["item_id"]

        completed = self.tool.handlers()["update_todo_item"](
            {
                "agent_id": "planner",
                "list_name": "sprint_alpha",
                "item_id": item_id,
                "completed": True,
            }
        )
        self.assertTrue(completed["updated_item"]["completed"])
        self.assertIsNotNone(completed["updated_item"]["completed_at"])

        reopened = self.tool.handlers()["update_todo_item"](
            {
                "agent_id": "planner",
                "list_name": "sprint_alpha",
                "item_id": item_id,
                "completed": False,
            }
        )
        self.assertFalse(reopened["updated_item"]["completed"])
        self.assertIsNone(reopened["updated_item"]["completed_at"])

        removed = self.tool.handlers()["remove_todo_item"](
            {
                "agent_id": "planner",
                "list_name": "sprint_alpha",
                "item_id": item_id,
            }
        )
        self.assertEqual(removed["removed_item"]["item_id"], item_id)
        self.assertEqual(removed["todo_list"]["total_tasks"], 2)

    def test_list_agents_and_lists_show_progress(self) -> None:
        self.tool.handlers()["create_todo_list"](
            {
                "agent_id": "coder",
                "list_name": "backlog",
                "tasks": ["Task 1", "Task 2"],
            }
        )
        self.tool.handlers()["update_todo_item"](
            {
                "agent_id": "coder",
                "list_name": "backlog",
                "item_id": "T-0001",
                "completed": True,
            }
        )

        agents = self.tool.handlers()["list_agents"]({})
        self.assertEqual(len(agents["agents"]), 1)
        self.assertEqual(agents["agents"][0]["agent_id"], "coder")
        self.assertEqual(agents["agents"][0]["open_tasks"], 1)
        self.assertEqual(agents["agents"][0]["completed_tasks"], 1)

        lists = self.tool.handlers()["list_todo_lists"]({"agent_id": "coder"})
        self.assertEqual(len(lists["lists"]), 1)
        self.assertEqual(lists["lists"][0]["list_name"], "backlog")
        self.assertEqual(lists["lists"][0]["completed_tasks"], 1)

    def test_tool_installs_on_base_agent(self) -> None:
        self.tool.handlers()["create_todo_list"](
            {
                "agent_id": "ops",
                "list_name": "launch",
                "tasks": ["Prepare release notes"],
            }
        )
        client = FakeClient(
            [
                tool_output(
                    {
                        "tool": "todo_list",
                        "method": "get_todo_list",
                        "arguments": {"agent_id": "ops", "list_name": "launch"},
                    },
                    {
                        "tool": "reply",
                        "method": "send_message",
                        "arguments": {"message": "todo loaded"},
                    },
                )
            ]
        )
        agent = BaseAgent.new(client=client, rate_limiter=None)
        self.tool.install(agent)

        reply = agent.query("load launch todos")

        self.assertEqual(reply.message, "todo loaded")
        envelope = json.loads(client.responses.calls[0]["input"])
        available_tools = envelope["runtime_context"]["available_tools"]
        self.assertTrue(any(tool["name"] == "todo_list" for tool in available_tools))


if __name__ == "__main__":
    unittest.main()

