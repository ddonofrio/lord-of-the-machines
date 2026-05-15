from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from lord_of_the_machines.agent_tools import (
    SoftwareDevelopmentEnvironmentPermissionPolicy,
    SoftwareDevelopmentEnvironmentPolicyError,
    SoftwareDevelopmentEnvironmentTool,
    SoftwareDevelopmentEnvironmentToolConfig,
)
from lord_of_the_machines.llm import BaseAgent
from tests.helpers.fake_openai import FakeClient
from tests.helpers.outputs import tool_output


class SoftwareDevelopmentEnvironmentToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self._tmpdir.name)
        (self.root / "src").mkdir()
        (self.root / "src" / "app.py").write_text("print('hello')\n", encoding="utf-8")
        (self.root / "README.md").write_text("# Demo\n", encoding="utf-8")
        (self.root / "node_modules").mkdir()
        (self.root / "node_modules" / "ignore.js").write_text("console.log('x')\n", encoding="utf-8")
        (self.root / ".git").mkdir()
        (self.root / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
        self.tool = SoftwareDevelopmentEnvironmentTool(
            self.root,
            config=SoftwareDevelopmentEnvironmentToolConfig(
                root_path=self.root,
                journal_log_dir=self.root / "logs",
            ),
        )

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_definition_uses_new_tool_name(self) -> None:
        self.assertEqual(self.tool.definition().name, "software_development_environment")

    def test_line_range_schemas_are_one_based(self) -> None:
        methods = {method.name: method for method in self.tool.definition().methods}

        read_schema = methods["read_file"].arguments_schema["properties"]
        replace_schema = methods["replace_lines"].arguments_schema["properties"]

        self.assertEqual(read_schema["start_line"]["minimum"], 1)
        self.assertEqual(read_schema["end_line"]["minimum"], 1)
        self.assertEqual(replace_schema["start_line"]["minimum"], 1)
        self.assertEqual(replace_schema["end_line"]["minimum"], 1)

    def test_list_tree_ignores_generated_directories(self) -> None:
        result = self.tool.handlers()["list_tree"]({})
        paths = {entry["path"] for entry in result["entries"]}

        self.assertIn("src", paths)
        self.assertIn("src/app.py", paths)
        self.assertNotIn("node_modules", paths)
        self.assertNotIn(".git", paths)

    def test_search_text_accepts_file_path(self) -> None:
        result = self.tool.handlers()["search_text"](
            {
                "path": "src/app.py",
                "query": "print",
            }
        )
        self.assertEqual(len(result["matches"]), 1)
        self.assertEqual(result["matches"][0]["path"], "src/app.py")

    def test_write_read_and_sha_guard(self) -> None:
        write_result = self.tool.handlers()["write_file"]({"path": "notes.txt", "content": "alpha"})
        read_result = self.tool.handlers()["read_file"]({"path": "notes.txt"})

        self.assertTrue(write_result["changed"])
        self.assertEqual(read_result["text"], "alpha")

        append_result = self.tool.handlers()["append_file"](
            {
                "path": "notes.txt",
                "content": "\nbeta",
                "expected_sha256": read_result["sha256"],
            }
        )
        self.assertTrue(append_result["changed"])

        with self.assertRaises(ValueError):
            self.tool.handlers()["append_file"](
                {
                    "path": "notes.txt",
                    "content": "\ngamma",
                    "expected_sha256": "wrong-sha",
                }
            )

    def test_truncation_guard_blocks_large_overwrite(self) -> None:
        large_text = "A" * 10_000
        (self.root / "README.md").write_text(large_text, encoding="utf-8")

        with self.assertRaises(SoftwareDevelopmentEnvironmentPolicyError):
            self.tool.handlers()["write_file"](
                {
                    "path": "README.md",
                    "content": "short\n",
                }
            )

    def test_truncation_guard_can_be_overridden_for_intentional_rewrite(self) -> None:
        large_text = "A" * 10_000
        (self.root / "README.md").write_text(large_text, encoding="utf-8")

        result = self.tool.handlers()["write_file"](
            {
                "path": "README.md",
                "content": "short\n",
                "allow_large_rewrite": True,
            }
        )
        self.assertTrue(result["changed"])
        read_back = self.tool.handlers()["read_file"]({"path": "README.md"})
        self.assertEqual(read_back["text"], "short")

    def test_delete_path_requires_explicit_confirmation(self) -> None:
        dry_run = self.tool.handlers()["delete_path"]({"path": "README.md"})
        self.assertTrue(dry_run["dry_run"])
        self.assertFalse(dry_run.get("ok", False))

        with self.assertRaises(ValueError):
            self.tool.handlers()["delete_path"]({"path": "README.md", "dry_run": False})

    def test_activity_log_persists_journal(self) -> None:
        result = self.tool.handlers()["run_command"](
            {
                "argv": ["python", "-c", "print('ok')"],
                "workdir": ".",
            }
        )
        activity = self.tool.handlers()["activity_log"]({"limit": 10})
        journal_path = Path(activity["journal"]["journal_path"])

        self.assertTrue(result["ok"])
        self.assertTrue(journal_path.exists())
        self.assertGreaterEqual(activity["total_entries"], 2)

        persisted_lines = journal_path.read_text(encoding="utf-8").splitlines()
        persisted_events = [json.loads(line) for line in persisted_lines]
        self.assertTrue(any(entry["action"] == "run_command" for entry in persisted_events))

    def test_read_only_permission_policy_blocks_writes_and_commands(self) -> None:
        tool = SoftwareDevelopmentEnvironmentTool(
            self.root,
            config=SoftwareDevelopmentEnvironmentToolConfig(
                root_path=self.root,
                permission_policy=SoftwareDevelopmentEnvironmentPermissionPolicy.read_only(),
            ),
        )

        read_result = tool.handlers()["read_file"]({"path": "README.md"})
        self.assertEqual(read_result["path"], "README.md")

        with self.assertRaises(SoftwareDevelopmentEnvironmentPolicyError):
            tool.handlers()["write_file"]({"path": "notes.txt", "content": "alpha"})

        with self.assertRaises(SoftwareDevelopmentEnvironmentPolicyError):
            tool.handlers()["run_command"]({"argv": ["python", "-c", "print('blocked')"]})

    def test_read_only_definition_hides_write_and_command_methods(self) -> None:
        tool = SoftwareDevelopmentEnvironmentTool(
            self.root,
            config=SoftwareDevelopmentEnvironmentToolConfig(
                root_path=self.root,
                permission_policy=SoftwareDevelopmentEnvironmentPermissionPolicy.read_only(),
            ),
        )
        method_names = {method.name for method in tool.definition().methods}

        self.assertIn("read_file", method_names)
        self.assertIn("git_status", method_names)
        self.assertNotIn("write_file", method_names)
        self.assertNotIn("append_file", method_names)
        self.assertNotIn("replace_text", method_names)
        self.assertNotIn("replace_lines", method_names)
        self.assertNotIn("insert_text", method_names)
        self.assertNotIn("run_command", method_names)
        self.assertNotIn("run_diagnostics", method_names)

    def test_tool_installs_on_base_agent(self) -> None:
        client = FakeClient(
            [
                tool_output(
                    {
                        "tool": "software_development_environment",
                        "method": "read_file",
                        "arguments": {"path": "README.md"},
                    },
                    {
                        "tool": "reply",
                        "method": "send_message",
                        "arguments": {"message": "workspace loaded"},
                    },
                )
            ]
        )
        agent = BaseAgent.new(client=client, rate_limiter=None)
        self.tool.install(agent)

        reply = agent.query("inspect the workspace")

        self.assertEqual(reply.message, "workspace loaded")
        envelope = json.loads(client.responses.calls[0]["input"])
        available_tools = envelope["runtime_context"]["available_tools"]
        self.assertTrue(any(tool["name"] == "software_development_environment" for tool in available_tools))
