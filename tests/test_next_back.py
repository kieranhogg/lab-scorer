import pytest

from labtools import back
from labtools import next as next_cmd
from labtools.state import read_step, write_step

LAB = """
steps:
  - id: step-1
    checks:
      - {id: c, run: "false", expect: {exit_code: 0}}
  - id: step-2
"""


@pytest.fixture(autouse=True)
def lab(lab_file):
    lab_file(LAB)


def test_next_refuses_a_step_with_checks(capsys):
    next_cmd.main()
    assert read_step() == 0
    assert "must pass" in capsys.readouterr().out


def test_next_skips_a_step_without_checks():
    write_step(1)
    next_cmd.main()
    assert read_step() == 2


def test_next_at_end_does_nothing(capsys):
    write_step(2)
    next_cmd.main()
    assert read_step() == 2
    assert "end" in capsys.readouterr().out


def test_back_goes_to_previous_step():
    write_step(1)
    back.main()
    assert read_step() == 0


def test_back_stops_at_first_step(capsys):
    back.main()
    assert read_step() == 0
    assert "start" in capsys.readouterr().out


OPTIONAL_LAB = """
steps:
  - id: step-1
    checks:
      - {id: req, run: "true", expect: {exit_code: 0}}
      - {id: opt, run: "false", expect: {exit_code: 0}, required: false}
  - id: step-2
    checks:
      - {id: req, run: "false", expect: {exit_code: 0}}
      - {id: opt, run: "true", expect: {exit_code: 0}, required: false}
  - id: step-3
"""


def test_next_allows_step_when_only_optional_checks_fail(lab_file):
    lab_file(OPTIONAL_LAB)
    next_cmd.main()
    assert read_step() == 1


def test_next_still_blocks_when_a_required_check_fails(lab_file, capsys):
    lab_file(OPTIONAL_LAB)
    write_step(1)
    next_cmd.main()
    assert read_step() == 1
    assert "must pass" in capsys.readouterr().out
