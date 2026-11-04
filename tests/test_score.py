import pytest

from labtools import check, hint, score
from labtools import next as next_cmd
from labtools.state import read_passed, record_hint, record_pass, write_step

STEPS = [{"points": 25}, {"points": 25}, {"points": 50}]


def test_nothing_passed_scores_zero():
    assert score.compute_score(STEPS) == (0, 100)


def test_passed_steps_earn_their_points():
    record_pass(0)
    record_pass(2)
    assert score.compute_score(STEPS) == (75, 100)


def test_each_hint_costs_ten_percent():
    record_pass(2)
    for _ in range(2):
        write_step(2)
        record_hint()
    assert score.compute_score(STEPS) == (40, 100)


def test_hint_penalty_is_capped_at_half():
    record_pass(0)
    for _ in range(9):
        record_hint()
    assert score.compute_score(STEPS) == (12, 100)


def test_hints_on_an_unpassed_step_cost_nothing_else():
    record_hint()
    assert score.compute_score(STEPS) == (0, 100)


def test_step_without_points_counts_as_zero():
    record_pass(0)
    assert score.compute_score([{}]) == (0, 0)


LAB = """
steps:
  - id: step-1
    checks:
      - {id: c, run: "true", expect: {exit_code: 0}}
  - id: step-2
    checks:
      - {id: c, run: "false", expect: {exit_code: 0}}
  - id: step-3
"""


@pytest.fixture
def lab(lab_file):
    lab_file(LAB)


def test_check_marks_the_step_passed(lab):
    check.main()
    assert read_passed() == {0}


def test_failed_check_marks_nothing(lab):
    write_step(1)
    check.main()
    assert read_passed() == set()


def test_next_marks_a_step_without_checks_passed(lab):
    write_step(2)
    next_cmd.main()
    assert read_passed() == {2}


def test_dev_skip_earns_nothing(lab, monkeypatch):
    monkeypatch.setattr("sys.argv", ["next", "--dev"])
    next_cmd.main()
    assert read_passed() == set()


def test_hint_command_feeds_the_penalty(lab_file):
    lab_file("steps:\n  - id: s\n    hints:\n      - {text: hi}\n")
    hint.main()
    record_pass(0)
    assert score.compute_score([{"points": 10}]) == (9, 10)
