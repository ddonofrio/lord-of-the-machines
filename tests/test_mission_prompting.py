from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from lord_of_the_machines.llm import BaseAgent
from lord_of_the_machines.mission import (
    MeetingToolAgent,
    RoleAgentFactory,
    RoleAgentFactoryConfig,
    compose_system_prompt,
    default_role_profile,
    load_agent_global_rules,
)
from tests.helpers.fake_openai import FakeClient


class MissionPromptingTests(unittest.TestCase):
    def test_default_role_profile_composes_golden_and_role_rules(self) -> None:
        prompt = compose_system_prompt(default_role_profile("product_manager"))
        self.assertIn("# Golden Rules", prompt)
        self.assertIn("# Company Software Development Process", prompt)
        self.assertIn("product_direction -> product_requirements", prompt)
        self.assertIn("# Product Manager role", prompt)
        self.assertIn("# Product Manager rules", prompt)

    def test_role_agent_factory_creates_agent_with_composed_prompt(self) -> None:
        factory = RoleAgentFactory()
        agent = factory.create("software_developer", client=FakeClient(), rate_limiter=None)
        system_prompt = agent.get_system_prompt() or ""
        self.assertIn("# Golden Rules", system_prompt)
        self.assertIn("# Company Software Development Process", system_prompt)
        self.assertIn("# Software Developer role", system_prompt)
        self.assertIn("# Developer Standards", system_prompt)
        self.assertIn("# Secondary objectives", system_prompt)

    def test_meeting_tool_sets_meeting_organizer_system_prompt(self) -> None:
        organizer = BaseAgent.new(client=FakeClient(), rate_limiter=None)
        MeetingToolAgent(organizer)
        system_prompt = organizer.get_system_prompt() or ""
        self.assertIn("# Golden Rules", system_prompt)
        self.assertIn("# Company Software Development Process", system_prompt)
        self.assertIn("# Meeting Organizer Role", system_prompt)
        self.assertNotIn("# Product Manager rules", system_prompt)
        self.assertNotIn("# Secondary objectives", system_prompt)

    def test_agent_global_rules_can_be_disabled_for_specialized_agents(self) -> None:
        factory = RoleAgentFactory(
            config=RoleAgentFactoryConfig(include_global_rules=False)
        )

        prompt = factory.create("product_director", client=FakeClient(), rate_limiter=None).get_system_prompt() or ""

        self.assertIn("# Golden Rules", prompt)
        self.assertIn("# Product Director role", prompt)
        self.assertNotIn("# Company Software Development Process", prompt)

    def test_agent_global_rules_are_loaded_from_directory(self) -> None:
        factory = RoleAgentFactory()

        prompt = factory.create("product_manager", client=FakeClient(), rate_limiter=None).get_system_prompt() or ""

        self.assertIn("# Company Software Development Process", prompt)
        self.assertIn("Use these exact role names", prompt)

    def test_agent_global_rules_autoloads_all_markdown_files_in_filename_order(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            rules_dir = Path(tempdir)
            (rules_dir / "020-second.md").write_text("# Second rule\n", encoding="utf-8")
            (rules_dir / "010-first.md").write_text("# First rule\n", encoding="utf-8")
            (rules_dir / "ignored.txt").write_text("# Ignored\n", encoding="utf-8")

            rules = load_agent_global_rules(rules_dir)

        self.assertEqual(rules, ["# First rule", "# Second rule"])

    def test_role_dna_assignment_matches_expected_policy(self) -> None:
        factory = RoleAgentFactory()

        sdm_prompt = (factory.create("software_development_manager", client=FakeClient(), rate_limiter=None).get_system_prompt() or "")
        self.assertIn("# Golden Rules", sdm_prompt)
        self.assertIn("# Software Development Manager role", sdm_prompt)
        self.assertIn("# Secondary objectives", sdm_prompt)
        self.assertIn("If software_development_environment is available", sdm_prompt)
        self.assertIn("project_context", sdm_prompt)
        self.assertIn("list_tree", sdm_prompt)
        self.assertIn("read_file/read_files", sdm_prompt)
        self.assertIn("Do not plan from mission text alone", sdm_prompt)
        self.assertNotIn("# Developer Standards", sdm_prompt)

        dev_prompt = (factory.create("software_developer", client=FakeClient(), rate_limiter=None).get_system_prompt() or "")
        self.assertIn("# Golden Rules", dev_prompt)
        self.assertIn("# Software Developer role", dev_prompt)
        self.assertIn("# Secondary objectives", dev_prompt)
        self.assertIn("# Developer Standards", dev_prompt)

        pd_prompt = (factory.create("product_director", client=FakeClient(), rate_limiter=None).get_system_prompt() or "")
        self.assertIn("# Golden Rules", pd_prompt)
        self.assertIn("# Product Director role", pd_prompt)
        self.assertIn("# Product Manager rules", pd_prompt)
        self.assertNotIn("# Secondary objectives", pd_prompt)

        pm_prompt = (factory.create("product_manager", client=FakeClient(), rate_limiter=None).get_system_prompt() or "")
        self.assertIn("# Golden Rules", pm_prompt)
        self.assertIn("# Product Manager role", pm_prompt)
        self.assertIn("# Product Manager rules", pm_prompt)
        self.assertNotIn("# Secondary objectives", pm_prompt)

        architect_prompt = (factory.create("software_architect", client=FakeClient(), rate_limiter=None).get_system_prompt() or "")
        self.assertIn("# Golden Rules", architect_prompt)
        self.assertIn("# Software Architect role", architect_prompt)
        self.assertIn("# Software architect", architect_prompt)
        self.assertIn("owner of technical architecture documentation", architect_prompt)
        self.assertIn("Do not invent paths", architect_prompt)
        self.assertIn("module names", architect_prompt)
        self.assertNotIn("# Product Manager rules", architect_prompt)
        self.assertNotIn("# Secondary objectives", architect_prompt)


if __name__ == "__main__":
    unittest.main()
