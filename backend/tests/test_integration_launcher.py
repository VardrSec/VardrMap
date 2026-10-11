"""Unix virtualenv launch paths must retain interpreter identity."""
import importlib.util
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.mark.skipif(os.name == "nt", reason="Unix venv interpreter symlinks")
def test_launcher_preserves_venv_interpreter_symlink(tmp_path, monkeypatch):
    source = Path(__file__).resolve().parents[2] / "scripts/integration/run.py"
    spec = importlib.util.spec_from_file_location("integration_launcher", source)
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    interpreter = tmp_path / "venv/bin/python"
    interpreter.parent.mkdir(parents=True)
    interpreter.symlink_to(sys.executable)
    calls = []
    monkeypatch.setattr(launcher, "snapshot", lambda *args: {})

    def capture(*args, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(launcher.subprocess, "run", capture)
    monkeypatch.setattr(sys, "argv", ["run.py", "--runner", str(tmp_path),
        "--gate", str(tmp_path), "--runner-python", str(interpreter),
        "--output", str(tmp_path)])
    assert launcher.main() == 0
    selected = calls[-1]["env"]["RUNNER_PYTHON"]
    assert selected == str(interpreter.absolute())
    assert selected != str(interpreter.resolve())
