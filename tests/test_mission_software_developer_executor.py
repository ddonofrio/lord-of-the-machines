from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from lord_of_the_machines.agent_tools import SoftwareDevelopmentEnvironmentPolicyError
from lord_of_the_machines.llm import BaseAgent
from lord_of_the_machines.mission import (
    RoleTaskRequest,
    SoftwareDeveloperRoleExecutor,
    SoftwareDeveloperRoleExecutorConfig,
    install_read_only_software_workspace_tool,
    task_start_details,
)
from tests.helpers.fake_openai import FakeClient
from tests.helpers.outputs import tool_output


class SoftwareDeveloperRoleExecutorTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self._tmpdir.name)
        (self.root / "docs").mkdir(parents=True)
        (self.root / "config").mkdir(parents=True)
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

    def _voice_acceptance_checks(self) -> dict[str, object]:
        return {
            "documentation_file": "docs/voice-of-the-agents.md",
            "required_role_mentions": [
                "product_director",
                "product_manager",
                "software_architect",
                "software_development_manager",
                "software_developer",
            ],
            "follow_up_mission_file": "config/missions.json",
            "minimum_missions_in_follow_up_file": 2,
            "require_distinct_follow_up_mission": True,
        }

    def test_task_start_details_include_previous_artifact_handoff(self) -> None:
        request = RoleTaskRequest(
            objective="Implement the plan.",
            mission_id="m_handoff",
            phase="implementation",
            context={
                "previous_phase": "development_plan",
                "previous_phase_summary": "Plan ready.",
                "previous_artifact": {
                    "artifact_id": "a1",
                    "artifact_type": "development_plan",
                    "title": "Development Plan",
                    "producer_role": "software_development_manager",
                    "content": "Do the work.",
                },
            },
            constraints=["Keep changes scoped."],
        )

        details = task_start_details(request)

        self.assertEqual(details["previous_phase"], "development_plan")
        self.assertEqual(details["previous_artifact"]["title"], "Development Plan")
        self.assertEqual(details["previous_artifact"]["content_chars"], len("Do the work."))
        self.assertEqual(details["constraints_count"], 1)

    def test_read_only_workspace_tool_allows_architect_inspection_but_blocks_writes(self) -> None:
        (self.root / "README.md").write_text("# Project\n", encoding="utf-8")
        agent = BaseAgent.new(client=FakeClient(), rate_limiter=None)

        tool = install_read_only_software_workspace_tool(agent, workspace_root=self.root)
        handlers = tool.handlers()

        tool_names = [definition.name for definition in agent.list_tools()]
        self.assertIn("software_development_environment", tool_names)
        self.assertIn("README.md", str(handlers["list_tree"]({"path": ".", "max_depth": 1})))
        with self.assertRaises(SoftwareDevelopmentEnvironmentPolicyError):
            handlers["write_file"]({"path": "README.md", "content": "rewrite"})

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
                    },
                    {
                        "tool": "_role_task_result",
                        "method": "submit",
                        "arguments": {"status": "completed", "summary": "Code updated."},
                    },
                ),
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

    def test_completed_execution_can_be_idempotent_when_no_changes_are_needed(self) -> None:
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
                        "tool": "_role_task_result",
                        "method": "submit",
                        "arguments": {
                            "status": "completed",
                            "summary": "Verified that the requested deliverable already exists.",
                            "metadata": {"no_changes_required": True},
                        },
                    },
                ),
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
        self.assertIn("- None", result.artifact_content or "")

    def test_allows_no_change_completion_when_summary_clearly_states_no_dead_code_found(self) -> None:
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
                        "tool": "_role_task_result",
                        "method": "submit",
                        "arguments": {
                            "status": "completed",
                            "summary": (
                                "Completed dead-code audit; no dead code instances were found, "
                                "so no removal was performed."
                            ),
                        },
                    },
                ),
            ]
        )
        agent = BaseAgent.new(client=client, rate_limiter=None)
        executor = SoftwareDeveloperRoleExecutor(
            agent,
            config=SoftwareDeveloperRoleExecutorConfig(
                workspace_root=self.root,
                diagnostics_profiles=("unittest",),
                diagnostics_timeout_seconds=60,
                require_changed_files=True,
            ),
        )
        request = RoleTaskRequest(
            objective="Audit dead code and remove only if proven dead.",
            mission_id="m_sd",
            phase="implementation",
            context={"board_task": {"task_type": "implementation"}},
        )

        result = executor.execute_task(request)

        self.assertEqual(result.status, "completed")

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
                    },
                    {
                        "tool": "_role_task_result",
                        "method": "submit",
                        "arguments": {"status": "completed", "summary": "Code updated."},
                    },
                ),
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
                    },
                    {
                        "tool": "_role_task_result",
                        "method": "submit",
                        "arguments": {"status": "completed", "summary": "Code updated."},
                    },
                ),
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

    def test_returns_follow_up_when_acceptance_checks_fail(self) -> None:
        (self.root / "tests" / "test_ok.py").write_text(
            "import unittest\n\n"
            "class Smoke(unittest.TestCase):\n"
            "    def test_ok(self):\n"
            "        self.assertTrue(True)\n",
            encoding="utf-8",
        )
        (self.root / "config" / "missions.json").write_text(
            '{"missions":[{"mission_id":"mvp_agent_voice_prioritization","title":"Current","description":"Current"}]}',
            encoding="utf-8",
        )
        client = FakeClient(
            [
                tool_output(
                    {
                        "tool": "software_development_environment",
                        "method": "write_file",
                        "arguments": {
                            "path": "docs/voice-of-the-agents.md",
                            "content": (
                                "# Voice of the Agents\n\n"
                                "Contributors: product_director, product_manager, software_architect.\n"
                            ),
                        },
                    },
                    {
                        "tool": "_role_task_result",
                        "method": "submit",
                        "arguments": {"status": "completed", "summary": "Draft done."},
                    },
                ),
            ]
        )
        agent = BaseAgent.new(client=client, rate_limiter=None)
        executor = SoftwareDeveloperRoleExecutor(
            agent,
            config=SoftwareDeveloperRoleExecutorConfig(
                workspace_root=self.root,
                diagnostics_profiles=("unittest",),
                diagnostics_timeout_seconds=60,
                allowed_write_prefixes=("docs/", "config/", "src/", "tests/"),
            ),
        )
        request = RoleTaskRequest(
            objective="Collect role input and produce the final document.",
            mission_id="mvp_agent_voice_prioritization",
            phase="implementation",
            context={"metadata": {"acceptance_checks": self._voice_acceptance_checks()}},
        )

        result = executor.execute_task(request)

        self.assertEqual(result.status, "needs_follow_up")
        self.assertIn("acceptance checks", result.summary.lower())
        self.assertTrue(result.required_changes)

    def test_acceptance_checks_pass_when_document_and_follow_up_mission_exist(self) -> None:
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
                            "path": "docs/voice-of-the-agents.md",
                            "content": (
                                "# Voice of the Agents\n\n"
                                "Participants: product_director, product_manager, software_architect, "
                                "software_development_manager, software_developer.\n"
                            ),
                        },
                    },
                    {
                        "tool": "software_development_environment",
                        "method": "write_file",
                        "arguments": {
                            "path": "config/missions.json",
                            "content": (
                                '{"missions":['
                                '{"mission_id":"mvp_agent_voice_prioritization","title":"Current","description":"Current"},'
                                '{"mission_id":"mvp_qa_lane","title":"Add QA role","description":"Add QA role and workflow"}'
                                ']}'
                            ),
                        },
                    },
                    {
                        "tool": "_role_task_result",
                        "method": "submit",
                        "arguments": {"status": "completed", "summary": "Finalized vote and added follow-up mission."},
                    },
                ),
            ]
        )
        agent = BaseAgent.new(client=client, rate_limiter=None)
        executor = SoftwareDeveloperRoleExecutor(
            agent,
            config=SoftwareDeveloperRoleExecutorConfig(
                workspace_root=self.root,
                diagnostics_profiles=("unittest",),
                diagnostics_timeout_seconds=60,
                allowed_write_prefixes=("docs/", "config/", "src/", "tests/"),
            ),
        )
        request = RoleTaskRequest(
            objective="Collect role input and produce the final document.",
            mission_id="mvp_agent_voice_prioritization",
            phase="implementation",
            context={"metadata": {"acceptance_checks": self._voice_acceptance_checks()}},
        )

        result = executor.execute_task(request)

        self.assertEqual(result.status, "completed")


if __name__ == "__main__":
    unittest.main()
