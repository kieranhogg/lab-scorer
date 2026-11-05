import subprocess

import pytest

from labtools import task


@pytest.fixture
def home(tmp_path, monkeypatch):
    home = tmp_path / "lab"
    monkeypatch.setattr(task, "LAB_HOME", home)
    monkeypatch.setattr(task, "SETUP_MARKER", home / ".setup-done")
    monkeypatch.setattr(task, "LAB_DIR", tmp_path)
    return home


def test_setup_runs_script_in_lab_home(home, tmp_path, lab_file):
    (tmp_path / "setup.sh").write_text("touch ran-$(basename $LAB_HOME)\n")
    lab_file("setup:\n  - script: setup.sh\nsteps: []\n")
    task.setup_lab()
    assert (home / "ran-lab").exists()


def test_setup_failure_raises(home, tmp_path, lab_file):
    (tmp_path / "setup.sh").write_text("exit 3\n")
    lab_file("setup:\n  - script: setup.sh\nsteps: []\n")
    with pytest.raises(subprocess.CalledProcessError):
        task.setup_lab()


def test_setup_run_executes_a_shell_command(home, lab_file):
    lab_file("setup:\n  - run: touch ran-inline\nsteps: []\n")
    task.setup_lab()
    assert (home / "ran-inline").exists()


def test_lab_without_setup_is_fine(home, lab_file):
    lab_file("steps: []\n")
    task.setup_lab()
