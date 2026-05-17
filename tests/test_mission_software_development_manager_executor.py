from __future__ import annotations

import unittest

from lord_of_the_machines.llm import BaseAgent
from lord_of_the_machines.mission import (
    RoleTaskRequest,
    SoftwareDevelopmentManagerRoleExecutor,
)
from tests.helpers.fake_openai import FakeClient
from tests.helpers.outputs import tool_output


class SoftwareDevelopmentManagerRoleExecutorTests(unittest.TestCase):
    def _make_request(self) -> RoleTaskRequest:
        return RoleTaskRequest(
            objective="Prepare implementation plan.",
            mission_id="m_sdm",
            phase="development_plan",
        )

    def test_extracts_implementation_tasks_from_artifact_content_when_metadata_is_missing(self) -> None:
        artifact_content = """
# Development Plan

Implementation Task Metadata
```json
[
  {
    "key": "TASK-1",
    "title": "Refactor runtime phase scheduling",
    "description": "Split scheduling logic and add queue guards.",
    "priority": "P0",
    "task_type": "implementation",
    "depends_on": []
  }
]
```
"""
        client = FakeClient(
            [
                tool_output(
                    {
                        "tool": "_role_task_result",
                        "method": "submit",
                        "arguments": {
                            "status": "completed",
                            "summary": "Plan ready.",
                            "artifact_type": "development_plan",
                            "artifact_title": "Development Plan",
                            "artifact_content": artifact_content,
                        },
                    },
                )
            ]
        )
        agent = BaseAgent.new(client=client, rate_limiter=None)
        executor = SoftwareDevelopmentManagerRoleExecutor(agent)

        result = executor.execute_task(self._make_request())

        self.assertEqual(result.status, "completed")
        self.assertIn("implementation_tasks", result.metadata)
        tasks = list(result.metadata["implementation_tasks"])
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["title"], "Refactor runtime phase scheduling")

    def test_requires_structured_implementation_tasks(self) -> None:
        client = FakeClient(
            [
                tool_output(
                    {
                        "tool": "_role_task_result",
                        "method": "submit",
                        "arguments": {
                            "status": "completed",
                            "summary": "Plan ready but not structured.",
                            "artifact_type": "development_plan",
                            "artifact_title": "Development Plan",
                            "artifact_content": "# Development Plan\\nNo structured task metadata here.",
                        },
                    },
                )
            ]
        )
        agent = BaseAgent.new(client=client, rate_limiter=None)
        executor = SoftwareDevelopmentManagerRoleExecutor(agent)

        result = executor.execute_task(self._make_request())

        self.assertEqual(result.status, "needs_follow_up")
        self.assertIn("structured implementation task metadata", result.summary.lower())
        self.assertTrue(result.required_changes)


if __name__ == "__main__":
    unittest.main()
