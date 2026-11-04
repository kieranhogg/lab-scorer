import pytest

from labtools import check, hint
from labtools import next as next_cmd
from labtools import start as start_cmd
from labtools.state import STEP_FILE, is_started, read_step, set_student

LAB = """
steps:
  - id: step-1
    checks:
      - {id: c, run: "true", expect: {exit_code: 0}}
    hints:
      - {id: h, text: "a hint"}
  - id: step-2
"""


@pytest.fixture(autouse=True)
def lab(lab_file):
    lab_file(LAB)


@pytest.fixture
def not_started(step_file):
    step_file.unlink(missing_ok=True)


@pytest.fixture
def named(not_started):
    set_student("Kim", "terminal")


def test_start_marks_the_lab_started(named):
    start_cmd.main()
    assert is_started()


def test_start_twice_is_harmless(capsys):
    start_cmd.main()
    assert "already started" in capsys.readouterr().out


@pytest.mark.parametrize("command", [check, next_cmd, hint])
def test_commands_ask_for_start_first(command, not_started, capsys):
    command.main()
    assert "`start`" in capsys.readouterr().out
    assert read_step() == 0
    assert not STEP_FILE.exists()


def test_start_needs_a_name_first(not_started, capsys):
    start_cmd.main()
    assert "name" in capsys.readouterr().out
    assert not is_started()
