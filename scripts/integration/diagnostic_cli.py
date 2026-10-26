"""Run the real diagnostics CLI with all writable Runner state in this fixture."""

import sys
from pathlib import Path

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root / "runner"))
from vardrrunner import config  # noqa: E402
from vardrrunner.cli import app  # noqa: E402

state = root / "doctor-state"
state.mkdir(exist_ok=True)
config.CONFIG_DIR = state
config.CONFIG_FILE = state / "config.json"
config.RUNS_DIR = state / "runs"
config.TOOLS_DIR = state / "tools"
config.DATA_DIR = state / "data"
config.JOURNAL_FILE = state / "journal.sqlite3"
app()
