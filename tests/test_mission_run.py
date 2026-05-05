from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from lord_of_the_machines.mission.run import main


class MissionRunModuleTests(unittest.TestCase):
    def test_bootstrap_only_mode_loads_missions_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_dir = root / "config"
            config_dir.mkdir(parents=True, exist_ok=True)
            (config_dir / "missions.json").write_text(
                json.dumps(
                    {
                        "missions": [
                            {
                                "mission_id": "m_bootstrap_1",
                                "title": "Bootstrap Mission",
                                "description": "Seed only",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main(
                    [
                        "--repo-root",
                        str(root),
                        "--missions-file",
                        str(config_dir / "missions.json"),
                        "--bootstrap-only",
                        "--json",
                    ]
                )

            self.assertEqual(code, 0)
            output = json.loads(stdout.getvalue())
            self.assertEqual(output["loaded"], 1)
            self.assertEqual(len(output["created"]), 1)
            self.assertIn("log_path", output)
            self.assertIn("human_log_path", output)
            self.assertTrue(Path(output["log_path"]).exists())
            self.assertTrue(Path(output["human_log_path"]).exists())

    def test_require_all_completed_returns_non_zero_when_missions_are_pending(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_dir = root / "config"
            config_dir.mkdir(parents=True, exist_ok=True)
            (config_dir / "missions.json").write_text(
                json.dumps(
                    {
                        "missions": [
                            {
                                "mission_id": "m_pending_1",
                                "title": "Pending Mission",
                                "description": "Will remain pending",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            previous_api_key = os.environ.get("OPENAI_API_KEY")
            os.environ["OPENAI_API_KEY"] = "sk-test-invalid"
            try:
                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    code = main(
                        [
                            "--repo-root",
                            str(root),
                            "--missions-file",
                            str(config_dir / "missions.json"),
                            "--max-cycles",
                            "0",
                            "--require-all-completed",
                            "--json",
                        ]
                    )
            finally:
                if previous_api_key is None:
                    os.environ.pop("OPENAI_API_KEY", None)
                else:
                    os.environ["OPENAI_API_KEY"] = previous_api_key

            self.assertEqual(code, 3)
            output = json.loads(stdout.getvalue())
            self.assertIn("incomplete_missions", output)
            self.assertEqual(output["incomplete_missions"][0]["mission_id"], "m_pending_1")


if __name__ == "__main__":
    unittest.main()
