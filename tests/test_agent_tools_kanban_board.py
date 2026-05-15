from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from lord_of_the_machines.agent_tools import KanbanBoardTool, KanbanBoardToolConfig
from lord_of_the_machines.llm import BaseAgent
from tests.helpers.fake_openai import FakeClient
from tests.helpers.outputs import tool_output


class KanbanBoardToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self._tmpdir.name)
        self.tool = KanbanBoardTool(
            self.root / "board",
            config=KanbanBoardToolConfig(
                root_path=self.root / "board",
                columns=("01-inbox", "02-dev", "90-done"),
            ),
        )

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_create_claim_move_and_append_note(self) -> None:
        created = self.tool.handlers()["create_task"](
            {
                "column": "01-inbox",
                "title": "Document architecture",
                "description": "# Task\n\nCreate architecture notes.",
                "status": "ready",
            }
        )
        self.assertTrue(created["created"])
        task_id = created["task"]["task_id"]
        self.assertEqual(created["task"]["column"], "01-inbox")

        claimed = self.tool.handlers()["claim_next_task"](
            {
                "column": "01-inbox",
                "agent_id": "software_developer",
            }
        )
        self.assertTrue(claimed["claimed"])
        self.assertEqual(claimed["task"]["task_id"], task_id)
        self.assertEqual(claimed["task"]["owner"], "software_developer")
        self.assertEqual(claimed["task"]["status"], "in_progress")

        moved = self.tool.handlers()["move_task"](
            {
                "task_id": task_id,
                "to_column": "02-dev",
                "actor": "software_developer",
                "note": "Task moved to development.",
            }
        )
        self.assertTrue(moved["moved"])
        self.assertEqual(moved["task"]["column"], "02-dev")
        self.assertIn("## Activity Log", moved["task"]["body"])

        updated = self.tool.handlers()["append_task_note"](
            {
                "task_id": task_id,
                "column": "02-dev",
                "actor": "software_developer",
                "note": "Work in progress.",
            }
        )
        self.assertTrue(updated["updated"])
        self.assertIn("Work in progress.", updated["task"]["body"])
        self.assertGreaterEqual(len(updated["task"]["history"]), 4)

        loaded = self.tool.handlers()["get_task"](
            {
                "task_id": task_id,
                "include_body": True,
            }
        )
        self.assertEqual(loaded["task"]["column"], "02-dev")
        self.assertIn("Work in progress.", loaded["task"]["body"])

    def test_list_columns_and_list_tasks(self) -> None:
        self.tool.handlers()["create_task"](
            {
                "column": "01-inbox",
                "task_id": "K-000010",
                "title": "Inbox task",
                "description": "A",
            }
        )
        self.tool.handlers()["create_task"](
            {
                "column": "02-dev",
                "task_id": "K-000011",
                "title": "Dev task",
                "description": "B",
            }
        )

        columns = self.tool.handlers()["list_columns"]({})
        by_name = {item["column"]: item["task_count"] for item in columns["columns"]}
        self.assertEqual(by_name["01-inbox"], 1)
        self.assertEqual(by_name["02-dev"], 1)
        self.assertEqual(by_name["90-done"], 0)

        listed = self.tool.handlers()["list_tasks"]({"include_body": False})
        self.assertEqual(len(listed["columns"]), 3)
        inbox_tasks = next(item["tasks"] for item in listed["columns"] if item["column"] == "01-inbox")
        self.assertEqual(inbox_tasks[0]["task_id"], "K-000010")
        self.assertNotIn("body", inbox_tasks[0])

    def test_tool_installs_on_base_agent(self) -> None:
        created = self.tool.handlers()["create_task"](
            {
                "column": "01-inbox",
                "task_id": "K-000120",
                "title": "Load me",
                "description": "Body",
            }
        )
        task_id = created["task"]["task_id"]
        client = FakeClient(
            [
                tool_output(
                    {
                        "tool": "kanban_board",
                        "method": "get_task",
                        "arguments": {"task_id": task_id, "include_body": False},
                    },
                    {
                        "tool": "reply",
                        "method": "send_message",
                        "arguments": {"message": "task loaded"},
                    },
                )
            ]
        )
        agent = BaseAgent.new(client=client, rate_limiter=None)
        self.tool.install(agent)

        reply = agent.query("load kanban task")

        self.assertEqual(reply.message, "task loaded")
        envelope = json.loads(client.responses.calls[0]["input"])
        available_tools = envelope["runtime_context"]["available_tools"]
        self.assertTrue(any(tool["name"] == "kanban_board" for tool in available_tools))

    def test_claim_respects_dependencies_and_priority(self) -> None:
        first = self.tool.handlers()["create_task"](
            {
                "column": "01-inbox",
                "task_id": "K-000200",
                "title": "Foundational task",
                "description": "Must run first",
                "priority": "P1",
            }
        )["task"]
        second = self.tool.handlers()["create_task"](
            {
                "column": "01-inbox",
                "task_id": "K-000201",
                "title": "Higher priority blocked task",
                "description": "Blocked by dependency",
                "priority": "P0",
                "depends_on": ["K-000200"],
            }
        )["task"]
        self.assertEqual(second["priority"], "P0")

        claimed_one = self.tool.handlers()["claim_next_task"](
            {
                "column": "01-inbox",
                "agent_id": "software_developer",
                "agent_role": "software_developer",
                "statuses": ["ready"],
                "done_statuses": ["done"],
            }
        )
        self.assertTrue(claimed_one["claimed"])
        self.assertEqual(claimed_one["task"]["task_id"], first["task_id"])

        self.tool.handlers()["move_task"](
            {
                "task_id": first["task_id"],
                "to_column": "90-done",
                "status": "done",
                "actor": "software_developer",
            }
        )

        claimed_two = self.tool.handlers()["claim_next_task"](
            {
                "column": "01-inbox",
                "agent_id": "software_developer",
                "agent_role": "software_developer",
                "statuses": ["ready"],
                "done_statuses": ["done"],
            }
        )
        self.assertTrue(claimed_two["claimed"])
        self.assertEqual(claimed_two["task"]["task_id"], second["task_id"])

    def test_update_task_applies_priority_owner_and_metadata(self) -> None:
        created = self.tool.handlers()["create_task"](
            {
                "column": "01-inbox",
                "task_id": "K-000250",
                "title": "Update me",
                "description": "Initial",
            }
        )["task"]

        updated = self.tool.handlers()["update_task"](
            {
                "task_id": created["task_id"],
                "priority": "P0",
                "owner": "agent-a",
                "task_type": "research",
                "assignee_role": "software_architect",
                "metadata_merge": {"mission_id": "m-1"},
                "actor": "software_development_manager",
                "note": "Escalated",
            }
        )["task"]
        self.assertEqual(updated["priority"], "P0")
        self.assertEqual(updated["owner"], "agent-a")
        self.assertEqual(updated["task_type"], "research")
        self.assertEqual(updated["assignee_role"], "software_architect")
        self.assertEqual(updated["metadata"]["mission_id"], "m-1")
        self.assertIn("Escalated", updated["body"])


if __name__ == "__main__":
    unittest.main()
