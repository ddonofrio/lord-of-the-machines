from __future__ import annotations

import unittest

from lord_of_the_machines.llm import BaseAgent
from lord_of_the_machines.mission import (
    MeetingToolAgent,
    RoleAgentFactory,
    compose_system_prompt,
    default_role_profile,
)
from tests.helpers.fake_openai import FakeClient


class MissionPromptingTests(unittest.TestCase):
    def test_default_role_profile_composes_golden_and_role_rules(self) -> None:
        prompt = compose_system_prompt(default_role_profile("product_manager"))
        self.assertIn("# Golden Rules", prompt)
        self.assertIn("# Product Manager role", prompt)
        self.assertIn("# Product Manager rules", prompt)

    def test_role_agent_factory_creates_agent_with_composed_prompt(self) -> None:
        factory = RoleAgentFactory()
        agent = factory.create("software_developer", client=FakeClient(), rate_limiter=None)
        system_prompt = agent.get_system_prompt() or ""
        self.assertIn("# Golden Rules", system_prompt)
        self.assertIn("# Software Developer role", system_prompt)
        self.assertIn("# Developer Standards", system_prompt)
        self.assertIn("# Secondary objectives", system_prompt)

    def test_meeting_tool_sets_meeting_organizer_system_prompt(self) -> None:
        organizer = BaseAgent.new(client=FakeClient(), rate_limiter=None)
        MeetingToolAgent(organizer)
        system_prompt = organizer.get_system_prompt() or ""
        self.assertIn("# Golden Rules", system_prompt)
        self.assertIn("# Meeting Organizer Role", system_prompt)


if __name__ == "__main__":
    unittest.main()
