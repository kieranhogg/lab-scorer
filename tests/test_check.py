from pathlib import Path

import pytest

from labtools import check
from labtools.state import read_checks, read_step, write_step

LAB = """
steps:
  - id: step-1
    checks:
      - id: passes
        description: "true passes"
        run: "true"
        expect: {exit_code: 0}
        feedback_on_fail: "true should pass"
      - id: expects-failure
        description: "false is expected to fail"
        run: "false"
        expect: {exit_code: 1}
        feedback_on_fail: "false should exit 1"
  - id: step-2
    checks:
      - id: fails
        description: "false fails"
        run: "false"
        expect: {exit_code: 0}
        feedback_on_fail: "nope"
      - id: never-reached
        description: "must not run"
        run: "echo reached"
        expect: {exit_code: 0}
        feedback_on_fail: "nope"
  - id: step-3
    title: "no checks"
"""


@pytest.fixture(autouse=True)
def lab(lab_file):
    lab_file(LAB)


def test_run_check_matches_expected_non_zero_exit():
    check_def = {"run": "false", "expect": {"exit_code": 1}}
    assert check.run_check(check_def)


def test_run_check_reports_feedback_on_mismatch(capsys):
    check_def = {"run": "true", "expect": {"exit_code": 1}, "feedback_on_fail": "bad"}
    assert not check.run_check(check_def)
    assert "bad" in capsys.readouterr().out


def test_run_checks_stops_at_first_failure(capsys):
    checks = [
        {"run": "false", "expect": {"exit_code": 0}, "feedback_on_fail": "first"},
        {"run": "true", "expect": {"exit_code": 0}, "description": "second"},
    ]
    assert check.run_checks(checks) == (False, False)
    assert "second" not in capsys.readouterr().out


def test_main_advances_when_all_checks_pass():
    check.main()
    assert read_step() == 1


def test_main_stays_put_when_a_check_fails():
    write_step(1)
    check.main()
    assert read_step() == 1


def test_main_advances_past_step_without_checks():
    write_step(2)
    check.main()
    assert read_step() == 3


def test_main_at_end_does_nothing(capsys):
    write_step(3)
    check.main()
    assert read_step() == 3
    assert "final step" in capsys.readouterr().out


@pytest.mark.parametrize(
    "stdout, rules, expected",
    [
        ("2\n", {"equals": 2}, True),
        ("3\n", {"equals": 2}, False),
        ("5\n", {"gte": 5}, True),
        ("4\n", {"gte": 5}, False),
        ("6\n", {"gt": 5, "lt": 10}, True),
        ("", {"gte": 5}, False),
        ("not a number", {"equals": 2}, False),
        ("hello world\n", {"contains": "world"}, True),
        ("hello\n", {"equals": "hello"}, True),
    ],
)
def test_stdout_matches(stdout, rules, expected):
    assert check.text_matches(stdout, rules) is expected


def test_stdout_unknown_rule_is_an_error():
    with pytest.raises(ValueError):
        check.text_matches("x", {"startswith": "x"})


def test_run_check_with_stdout_only_ignores_exit_code():
    check_def = {"run": "echo 3; exit 1", "expect": {"stdout": {"equals": 3}}}
    assert check.run_check(check_def)


def test_run_check_requires_both_exit_code_and_stdout():
    check_def = {
        "run": "echo 3",
        "expect": {"exit_code": 1, "stdout": {"equals": 3}},
    }
    assert not check.run_check(check_def)


def test_run_check_does_not_read_the_terminal():
    check_def = {"run": "sed -n '$='", "expect": {"stdout": {"equals": 2}}}
    assert not check.run_check(check_def)


def test_failure_shows_stderr_when_opted_in(capsys):
    check_def = {"run": "echo oops >&2; exit 1", "expect": {"exit_code": 0}, "show_output": True}
    assert not check.run_check(check_def)
    assert "oops" in capsys.readouterr().out


def test_failure_falls_back_to_stdout(capsys):
    check_def = {"run": "echo report; exit 1", "expect": {"exit_code": 0}, "show_output": True}
    assert not check.run_check(check_def)
    assert "report" in capsys.readouterr().out


def test_failure_output_hidden_by_default(capsys):
    check_def = {"run": "echo secret; exit 1", "expect": {"exit_code": 0}}
    assert not check.run_check(check_def)
    assert "secret" not in capsys.readouterr().out


def test_failure_output_is_limited_to_the_last_lines(capsys):
    check_def = {"run": "seq 1 50; exit 1", "expect": {"exit_code": 0}, "show_output": True}
    check.run_check(check_def)
    out = capsys.readouterr().out
    assert "50" in out
    assert "\n   1\n" not in out


OPTIONAL_FAILS = [
    {"run": "true", "expect": {"exit_code": 0}},
    {"run": "false", "expect": {"exit_code": 0}, "required": False},
]


def test_failing_optional_check_does_not_fail_required():
    assert check.run_checks(OPTIONAL_FAILS) == (True, False)


def test_required_check_after_failing_optional_still_runs():
    checks = [OPTIONAL_FAILS[1], {"run": "false", "expect": {"exit_code": 0}}]
    assert check.run_checks(checks) == (False, False)


def test_failing_optional_check_is_styled_apart_from_a_required_failure(capsys):
    check.run_checks(OPTIONAL_FAILS)
    out = capsys.readouterr().out
    assert "OPTIONAL" in out
    assert "FAIL" not in out
    check.run_checks([{"run": "false", "expect": {"exit_code": 0}}])
    assert "FAIL" in capsys.readouterr().out


def test_all_passing_reports_both_true():
    assert check.run_checks(OPTIONAL_FAILS[:1]) == (True, True)


def test_main_does_not_advance_when_only_optional_checks_fail(lab_file, capsys):
    lab_file("""
steps:
  - id: step-1
    checks:
      - {id: req, run: "true", expect: {exit_code: 0}}
      - {id: opt, run: "false", expect: {exit_code: 0}, required: false}
  - id: step-2
""")
    check.main()
    assert read_step() == 0
    assert "`next`" in capsys.readouterr().out


def test_run_check_runs_in_lab_home(lab_home):
    (lab_home / "marker").touch()
    assert check.run_check({"run": "test -f marker", "expect": {"exit_code": 0}})


def test_run_check_times_out(capsys):
    check_def = {"run": "sleep 5", "expect": {"exit_code": 0}, "timeout": 0.1}
    assert not check.run_check(check_def)
    assert "Timed out" in capsys.readouterr().out


def test_description_with_markup_characters_does_not_crash():
    check_def = {"description": "Check [/x] file", "run": "true", "expect": {"exit_code": 0}}
    assert check.run_check(check_def)


def test_missing_lab_folder_gives_a_clear_message(monkeypatch, capsys):
    monkeypatch.setattr(check, "LAB_HOME", Path("/nope"))
    assert not check.run_check({"run": "true", "expect": {"exit_code": 0}})
    assert "does not exist" in capsys.readouterr().out


def test_checks_pass_silently_when_all_pass(capsys):
    checks = [
        {"run": "true", "expect": {"exit_code": 0}},
        {"run": "false", "expect": {"exit_code": 1}},
    ]
    assert check.checks_pass_silently(checks)
    assert capsys.readouterr().out == ""


def test_checks_pass_silently_fails_without_output(capsys):
    checks = [{"run": "false", "expect": {"exit_code": 0}, "feedback_on_fail": "nope"}]
    assert not check.checks_pass_silently(checks)
    assert capsys.readouterr().out == ""


def test_checks_pass_silently_counts_optional_checks():
    checks = [{"run": "false", "expect": {"exit_code": 0}, "required": False}]
    assert not check.checks_pass_silently(checks)


def test_checks_pass_silently_treats_a_timeout_as_failing():
    checks = [{"run": "sleep 5", "expect": {"exit_code": 0}, "timeout": 0.1}]
    assert not check.checks_pass_silently(checks)


def test_checks_pass_silently_leaves_the_state_alone():
    check.checks_pass_silently([{"run": "true", "expect": {"exit_code": 0}}])
    assert read_step() == 0
    assert read_checks() == 0
