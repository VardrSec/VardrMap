import os, sys
from pathlib import Path
from rich.console import Console

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root / "runner"))
from vardrrunner import api, config, resources
from vardrrunner.commands.jobs import execute_pending_jobs
from vardrrunner.journal import Journal

state = root / "worker-state"
state.mkdir(exist_ok=True)
config.CONFIG_DIR = state
config.CONFIG_FILE = state / "config.json"
config.RUNS_DIR = state / "runs"
config.TOOLS_DIR = state / "tools"
config.DATA_DIR = state / "data"
config.JOURNAL_FILE = state / "journal.sqlite3"
os.environ.pop("VARDRRUNNER_DENY_TARGETS", None)
client = api.VardrMapClient(
    os.environ["LAB_BACKEND"], os.environ["LAB_RUNNER_KEY"], retries=0
)
execute_pending_jobs(
    client,
    Console(),
    yes=True,
    journal_store=Journal(config.JOURNAL_FILE),
    backend_url=os.environ["LAB_BACKEND"],
    limits=resources.RunnerLimits(min_free_disk_bytes=0),
)
