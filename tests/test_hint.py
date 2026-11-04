import pytest

from labtools import hint
from labtools.state import read_hints, record_check, write_step

LAB = """
steps:
  - id: step-1
    hints:
      - {id: always, text: "free hint"}
      - {id: gated, text: "gated hint", after_failed_attempts: 2}
  - id: step-2
"""


@pytest.fixture(autouse=True)
def lab(lab_file):
    lab_file(LAB)


def test_ungated_hint_shows_immediately(capsys):
    hint.main()
    out = capsys.readouterr().out
    assert "free hint" in out
    assert "gated hint" not in out


def test_gated_hint_unlocks_after_enough_checks(capsys):
    record_check()
    record_check()
    hint.main()
    assert "gated hint" in capsys.readouterr().out


def test_each_request_is_counted_once():
    hint.main()
    hint.main()
    assert read_hints() == 2


def test_step_without_hints(capsys):
    write_step(1)
    hint.main()
    assert "No hints" in capsys.readouterr().out
    assert read_hints() == 0
