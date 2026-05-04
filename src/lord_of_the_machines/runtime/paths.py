from __future__ import annotations

from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PACKAGE_ROOT.parent
REPO_ROOT = SRC_ROOT.parent

CONFIG_DIR = REPO_ROOT / "config"
DEFAULT_BASE_AGENT_CONFIG = CONFIG_DIR / "base_agent.json"
LOG_DIR = REPO_ROOT / "logs"
