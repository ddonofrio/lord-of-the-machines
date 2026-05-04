from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from lord_of_the_machines.llm import BaseAgent
from lord_of_the_machines.mission import (
    RoleTaskRequest,
    SoftwareDeveloperRoleExecutor,
    SoftwareDeveloperRoleExecutorConfig,
)
from tests.helpers.fake_openai import FakeClient
from tests.helpers.outputs import reply_output, tool_output


class SoftwareDeveloperRoleExecutorTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self._tmpdir.name)
        (self.root / "src" / "lord_of_the_machines" / "mission").mkdir(parents=True)
        (self.root / "tests").mkdir(parents=True)
        (self.root / "tests" / "__init__.py").write_text("", encoding="utf-8")

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def _make_request(self) -> RoleTaskRequest:
        return RoleTaskRequest(
            objective="Apply a scoped code improvement.",
            mission_id="m_sd",
            phase="implementation",
            context={"target": "mission module"},
        )

    def test_completed_execution_with_allowed_changes_and_passing_diagnostics(self) -> None:
        (self.root / "tests" / "test_ok.py").write_text(
            "import unittest\n\n"
            "class Smoke(unittest.TestCase):\n"
            "    def test_ok(self):\n"
            "        self.assertTrue(True)\n",
            encoding="utf-8",
        )
        client = FakeClient(
            [
                tool_output(
                    {
                        "tool": "software_development_environment",
                        "method": "write_file",
                        "arguments": {
                            "path": "src/lord_of_the_machines/mission/new_helper.py",
                            "content": "VALUE = 1\n",
                        },
                    }
                ),
                reply_output(json.dumps({"status": "completed", "summary": "Code updated."})),
            ]
        )
        agent = BaseAgent.new(client=client, rate_limiter=None)
        executor = SoftwareDeveloperRoleExecutor(
            agent,
            config=SoftwareDeveloperRoleExecutorConfig(
                workspace_root=self.root,
                diagnostics_profiles=("unittest",),
                diagnostics_timeout_seconds=60,
            ),
        )

        result = executor.execute_task(self._make_request())

        self.assertEqual(result.status, "completed")
        self.assertTrue(result.artifact_content)
        self.assertIn("Implementation Report", result.artifact_content or "")

    def test_blocks_when_changes_outside_allowed_prefixes(self) -> None:
        (self.root / "tests" / "test_ok.py").write_text(
            "import unittest\n\n"
            "class Smoke(unittest.TestCase):\n"
            "    def test_ok(self):\n"
            "        self.assertTrue(True)\n",
            encoding="utf-8",
        )
        client = FakeClient(
            [
                tool_output(
                    {
                        "tool": "software_development_environment",
                        "method": "write_file",
                        "arguments": {
                            "path": "README.md",
                            "content": "# unexpected\n",
                        },
                    }
                ),
                reply_output(json.dumps({"status": "completed", "summary": "Code updated."})),
            ]
        )
        agent = BaseAgent.new(client=client, rate_limiter=None)
        executor = SoftwareDeveloperRoleExecutor(
            agent,
            config=SoftwareDeveloperRoleExecutorConfig(
                workspace_root=self.root,
                diagnostics_profiles=("unittest",),
                diagnostics_timeout_seconds=60,
            ),
        )

        result = executor.execute_task(self._make_request())

        self.assertEqual(result.status, "blocked")
        self.assertIn("outside allowed prefixes", result.summary)

    def test_returns_follow_up_when_diagnostics_fail(self) -> None:
        (self.root / "tests" / "test_fail.py").write_text(
            "import unittest\n\n"
            "class Failing(unittest.TestCase):\n"
            "    def test_fail(self):\n"
            "        self.assertTrue(False)\n",
            encoding="utf-8",
        )
        client = FakeClient(
            [
                tool_output(
                    {
                        "tool": "software_development_environment",
                        "method": "write_file",
                        "arguments": {
                            "path": "src/lord_of_the_machines/mission/new_helper.py",
                            "content": "VALUE = 2\n",
                        },
                    }
                ),
                reply_output(json.dumps({"status": "completed", "summary": "Code updated."})),
            ]
        )
        agent = BaseAgent.new(client=client, rate_limiter=None)
        executor = SoftwareDeveloperRoleExecutor(
            agent,
            config=SoftwareDeveloperRoleExecutorConfig(
                workspace_root=self.root,
                diagnostics_profiles=("unittest",),
                diagnostics_timeout_seconds=60,
            ),
        )

        result = executor.execute_task(self._make_request())

        self.assertEqual(result.status, "needs_follow_up")
        self.assertIn("diagnostics failed", result.summary.lower())


if __name__ == "__main__":
    unittest.main()
