from __future__ import annotations

import io
import json
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
            self.assertTrue(Path(output["log_path"]).exists())


if __name__ == "__main__":
    unittest.main()
