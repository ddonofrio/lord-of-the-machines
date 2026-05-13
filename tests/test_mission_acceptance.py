from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from lord_of_the_machines.mission.acceptance import (
    MissionAcceptanceChecks,
    evaluate_mission_acceptance_checks,
)


class MissionAcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self._tmpdir.name)
        (self.root / "docs").mkdir(parents=True)
        (self.root / "config").mkdir(parents=True)

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_reports_missing_role_mentions_and_follow_up(self) -> None:
        (self.root / "docs" / "voice-of-the-agents.md").write_text(
            "Participants: product_director, product_manager\n",
            encoding="utf-8",
        )
        (self.root / "config" / "missions.json").write_text(
            '{"missions":[{"mission_id":"mvp_agent_voice_prioritization","title":"Current","description":"Current"}]}',
            encoding="utf-8",
        )
        checks = MissionAcceptanceChecks(
            documentation_file="docs/voice-of-the-agents.md",
            required_role_mentions=(
                "product_director",
                "product_manager",
                "software_architect",
            ),
            follow_up_mission_file="config/missions.json",
            minimum_missions_in_follow_up_file=2,
            require_distinct_follow_up_mission=True,
        )

        errors = evaluate_mission_acceptance_checks(
            checks=checks,
            workspace_root=self.root,
            mission_id="mvp_agent_voice_prioritization",
        )

        self.assertGreaterEqual(len(errors), 2)

    def test_passes_when_checks_are_satisfied(self) -> None:
        (self.root / "docs" / "voice-of-the-agents.md").write_text(
            "Participants: product_director, product_manager, software_architect\n",
            encoding="utf-8",
        )
        (self.root / "config" / "missions.json").write_text(
            '{"missions":[{"mission_id":"mvp_agent_voice_prioritization","title":"Current","description":"Current"},'
            '{"mission_id":"mvp_follow_up","title":"Follow up","description":"Follow up"}]}',
            encoding="utf-8",
        )
        checks = MissionAcceptanceChecks(
            documentation_file="docs/voice-of-the-agents.md",
            required_role_mentions=(
                "product_director",
                "product_manager",
                "software_architect",
            ),
            follow_up_mission_file="config/missions.json",
            minimum_missions_in_follow_up_file=2,
            require_distinct_follow_up_mission=True,
        )

        errors = evaluate_mission_acceptance_checks(
            checks=checks,
            workspace_root=self.root,
            mission_id="mvp_agent_voice_prioritization",
        )

        self.assertEqual(errors, [])

    def test_required_file_checks_report_missing_files(self) -> None:
        checks = MissionAcceptanceChecks(
            required_files=("docs/qa-agent-integration.md",),
        )
        errors = evaluate_mission_acceptance_checks(
            checks=checks,
            workspace_root=self.root,
            mission_id="mvp_qa",
        )
        self.assertIn("required file does not exist: docs/qa-agent-integration.md", errors)

    def test_required_file_contains_checks(self) -> None:
        target = self.root / "config" / "example.py"
        target.write_text("ROLE_PROMPTS = {'qa_agent': 'ok'}\n", encoding="utf-8")
        checks = MissionAcceptanceChecks(
            required_file_contains={
                "config/example.py": ("qa_agent", "ROLE_PROMPTS"),
            }
        )
        errors = evaluate_mission_acceptance_checks(
            checks=checks,
            workspace_root=self.root,
            mission_id="mvp_qa",
        )
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
