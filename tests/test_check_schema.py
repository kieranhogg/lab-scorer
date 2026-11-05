"""The check vocabulary from lab.schema: matchers, captures, depends_on, regression, final checks, step setup."""
import json
import subprocess

import pytest

from labtools import check, command, hint, task
from labtools import next as next_cmd
from labtools.state import read_captured, read_step, record_check, record_pass, write_step


def make(run, expect, **extra):
    return {"id": "c", "description": "d", "run": run, "expect": expect, **extra}


@pytest.mark.parametrize(
    "output, rules, expected",
    [
        ("hello world", {"not_contains": "bye"}, True),
        ("hello world", {"not_contains": "world"}, False),
        ("hello", {"starts_with": "he"}, True),
        ("hello", {"starts_with": "lo"}, False),
        ("abc123", {"matches": r"\d+$"}, True),
        ("abc", {"not_matches": r"\d"}, True),
        ("", {"is_empty": True}, True),
        ("x", {"is_empty": True}, False),
        ("a\nb\nc\n", {"line_count": 3}, True),
        ("a\nb\n", {"line_count": {"gte": 3}}, False),
        ("Hello", {"equals": "hello", "normalise": {"ignore_case": True}}, True),
        ("a   b", {"equals": "a b", "normalise": {"collapse_whitespace": True}}, True),
        ("b\na", {"equals": "a\nb", "normalise": {"sort_lines": True}}, True),
        ("  x ", {"equals": "  x ", "normalise": {"trim": False}}, True),
        ("ABC", {"matches": "^abc$", "normalise": {"ignore_case": True}}, True),
    ],
)
def test_text_rules(output, rules, expected):
    assert check.text_matches(output, rules) is expected


def test_exit_code_not():
    assert check.run_check(make("exit 2", {"exit_code": {"not": 0}}))
    assert not check.run_check(make("exit 0", {"exit_code": {"not": 0}}))


def test_stderr_rules():
    assert check.run_check(make("echo warn >&2", {"stderr": {"contains": "warn"}}))
    assert not check.run_check(make("echo warn >&2", {"stderr": {"is_empty": True}}))


JSON = json.dumps({"status": "ok", "tags": ["a", "b"], "count": 3, "nested": {"items": [{"n": 1}, {"n": 2}]}, "flag": True})


@pytest.mark.parametrize(
    "assertion, expected",
    [
        ({"path": "$.status", "equals": "ok"}, True),
        ({"path": "$.status", "not_equals": "bad"}, True),
        ({"path": "$.missing", "exists": False}, True),
        ({"path": "$.status", "exists": False}, False),
        ({"path": "$.tags", "contains": "a"}, True),
        ({"path": "$.tags", "length": 2}, True),
        ({"path": "$.tags", "length": {"gte": 3}}, False),
        ({"path": "$.count", "gt": 2, "lte": 3}, True),
        ({"path": "$.status", "matches": "^o"}, True),
        ({"path": "$.status", "type": "string"}, True),
        ({"path": "$.flag", "type": "boolean"}, True),
        ({"path": "$.flag", "gt": 0}, False),
        ({"path": "$.nested.items[1].n", "equals": 2}, True),
        ({"path": "$.nested.items[*].n", "equals": [1, 2]}, True),
        ({"path": "$['status']", "equals": "ok"}, True),
        ({"path": "$.nested.items[-1].n", "equals": 2}, True),
        ({"path": "$.status", "equals": "ok", "gt": 1}, False),
    ],
)
def test_json_assertions(assertion, expected):
    assert check.json_matches(JSON, [assertion]) is expected


def test_json_that_is_not_json_fails():
    assert not check.json_matches("not json", [{"path": "$", "exists": True}])


def test_files_assertions(lab_home):
    (lab_home / "a.txt").write_text("hello world")
    (lab_home / "a.txt").chmod(0o640)
    good = [{"path": "a.txt", "contains": "hello", "not_contains": "bye", "matches": "w.rld", "mode": "0640"}]
    assert check.files_match(good, lab_home)
    assert not check.files_match([{"path": "a.txt", "mode": "0600"}], lab_home)
    assert not check.files_match([{"path": "nope.txt"}], lab_home)
    assert check.files_match([{"path": "nope.txt", "exists": False}], lab_home)
    assert not check.files_match([{"path": "a.txt", "owner": "nobody-here"}], lab_home)


def test_run_check_uses_files_expectation(lab_home):
    assert check.run_check(make("echo hi > out.txt", {"files": [{"path": "out.txt", "contains": "hi"}]}))


def test_cwd_env_and_duration_timeout(lab_home):
    (lab_home / "sub").mkdir()
    assert check.run_check(make('test "$(basename "$PWD")" = sub && test "$FOO" = bar', {"exit_code": 0}, cwd="sub", env={"FOO": "bar"}))
    assert command.timeout_seconds("5m") == 300
    assert command.timeout_seconds("2h") == 7200
    assert command.timeout_seconds("30s") == 30
    assert command.timeout_seconds(None) == command.DEFAULT_TIMEOUT


def test_captures_feed_later_checks(lab_home):
    first = make("echo 'orders=7'", {"exit_code": 0}, capture={"orders": {"from": "stdout", "regex": r"orders=(\d+)", "type": "int"}})
    assert check.run_check(first)
    assert read_captured()["orders"] == 7
    # numberOrRef in an assertion, and the shell form that cannot inject commands
    assert check.run_check(make('test "${captured.orders}" = 7', {"exit_code": 0}))
    assert check.run_check(make("echo 9", {"stdout": {"line_count": {"lte": "${captured.orders}"}}}))
    assert not check.run_check(make("seq 1 9", {"stdout": {"line_count": {"lte": "${captured.orders}"}}}))


def test_capture_values_are_not_run_as_commands(lab_home):
    check.run_check(make("echo '$(touch pwned)'", {"exit_code": 0}, capture={"v": {"from": "stdout"}}))
    assert check.run_check(make('test "${captured.v}" = \'$(touch pwned)\'', {"exit_code": 0}))
    assert not (lab_home / "pwned").exists()


@pytest.mark.parametrize(
    "capture, run, value",
    [
        ({"from": "stdout", "json": "$.a", "type": "int"}, "echo '{\"a\": 4}'", 4),
        ({"from": "stderr"}, "echo oops >&2", "oops"),
        ({"from": "exit_code", "type": "int"}, "exit 3", 3),
        ({"from": "file", "file": "f.txt", "type": "number"}, "echo 2.5 > f.txt", 2.5),
        ({"from": "stdout", "type": "bool"}, "echo true", True),
        ({"from": "stdout", "trim": False}, "echo hi", "hi\n"),
    ],
)
def test_capture_sources(lab_home, capture, run, value):
    # exit_code captures need a failing command to be interesting, so the expectation follows the capture
    expect = {"exit_code": 3} if capture["from"] == "exit_code" else {"exit_code": 0}
    assert check.run_check(make(run, expect, capture={"x": capture}))
    assert read_captured()["x"] == value


def test_failed_capture_fails_the_check(capsys):
    bad = make("echo nothing", {"exit_code": 0}, capture={"x": {"from": "stdout", "regex": r"(\d+)", "type": "int"}})
    assert not check.run_check(bad)
    assert "Could not capture x" in capsys.readouterr().out
    assert "x" not in read_captured()


def test_regression_runs_do_not_overwrite_captures():
    check.run_check(make("echo 1", {"exit_code": 0}, capture={"n": {"from": "stdout", "type": "int"}}))
    check.run_check(make("echo 2", {"exit_code": 0}, capture={"n": {"from": "stdout", "type": "int"}}), commit=False)
    assert read_captured()["n"] == 1


def test_feedback_rules_pick_the_first_match(capsys):
    rules = [
        {"when": {"stderr": {"contains": "denied"}}, "message": "Permission problem"},
        {"when": {"exit_code": 1}, "message": "Plain failure"},
    ]
    bad = make("echo denied >&2; exit 1", {"exit_code": 0}, feedback_on_fail="default", feedback_rules=rules)
    assert not check.run_check(bad)
    out = capsys.readouterr().out
    assert "Permission problem" in out
    assert "Plain failure" not in out
    other = make("exit 1", {"exit_code": 0}, feedback_on_fail="default", feedback_rules=rules)
    check.run_check(other)
    assert "Plain failure" in capsys.readouterr().out
    unmatched = make("exit 2", {"exit_code": 0}, feedback_on_fail="default", feedback_rules=rules)
    check.run_check(unmatched)
    assert "default" in capsys.readouterr().out


def test_depends_on_skips_when_a_dependency_fails(capsys):
    checks = [
        {"id": "a", "description": "A", "run": "false", "expect": {"exit_code": 0}, "required": False},
        {"id": "b", "description": "B", "run": "echo ran", "expect": {"exit_code": 0}, "depends_on": ["a"], "required": False},
    ]
    assert check.run_checks(checks) == (True, False)
    out = capsys.readouterr().out
    assert "SKIP" in out
    assert "needs a" in out


def test_required_check_with_failed_dependency_blocks():
    checks = [
        {"id": "a", "run": "false", "expect": {"exit_code": 0}, "required": False},
        {"id": "b", "run": "true", "expect": {"exit_code": 0}, "depends_on": ["a"]},
    ]
    assert check.run_checks(checks) == (False, False)


def test_depends_on_runs_when_dependency_passes():
    checks = [
        {"id": "a", "run": "true", "expect": {"exit_code": 0}},
        {"id": "b", "run": "true", "expect": {"exit_code": 0}, "depends_on": ["a"]},
    ]
    assert check.run_checks(checks) == (True, True)
    assert check.checks_pass_silently(checks)
    assert not check.checks_pass_silently(list(reversed(checks)))


LAB = """
vars: {word: hello}
progression: linear
steps:
  - id: one
    checks:
      - {id: base, run: "test -f marker", expect: {exit_code: 0}, regression: true, feedback_on_fail: "marker gone"}
      - {id: extra, run: "true", expect: {exit_code: 0}, depends_on: [base]}
  - id: two
    requires: [one]
    checks:
      - {id: new, run: "true", expect: {exit_code: 0}}
  - id: three
final_checks:
  - {id: end, run: "test -f final", expect: {exit_code: 0}, feedback_on_fail: "final missing"}
"""


@pytest.fixture
def staged(lab_file, lab_home):
    lab_file(LAB)
    (lab_home / "marker").touch()
    (lab_home / "final").touch()
    return lab_home


def test_step_groups_add_regression_and_final_checks(staged):
    groups = check.step_groups(1)
    assert [prefix for _, prefix, _ in groups] == ["", "(step 1) "]
    assert [c["id"] for c in groups[1][0]] == ["base"]
    last = check.step_groups(2)
    assert [prefix for _, prefix, _ in last] == ["(step 1) ", "(final) "]
    assert check.step_groups(0)[0][0][0]["id"] == "base"


def test_regression_check_blocks_a_later_step(staged, capsys):
    write_step(1)
    (staged / "marker").unlink()
    check.main()
    out = capsys.readouterr().out
    assert read_step() == 1
    assert "marker gone" in out
    assert "passed on an earlier step" in out


def test_final_checks_block_the_last_step(staged, capsys):
    write_step(2)
    (staged / "final").unlink()
    check.main()
    assert read_step() == 2
    assert "final missing" in capsys.readouterr().out
    (staged / "final").touch()
    check.main()
    assert read_step() == 3


def test_next_runs_final_checks_too(staged):
    write_step(2)
    (staged / "final").unlink()
    next_cmd.main()
    assert read_step() == 2


def test_vars_are_filled_in_at_load_time(lab_file):
    lab_file("vars: {word: hello, flag: true}\nsteps:\n  - {id: a, instructions: 'say ${word} ${flag} ${captured.x} ${OTHER}'}\n")
    assert task.open_lab_file()["steps"][0]["instructions"] == "say hello true ${captured.x} ${OTHER}"


def test_content_can_come_from_a_file(lab_file, tmp_path):
    lab_file("steps: []\n")
    (tmp_path / "notes.md").write_text("from a file")
    assert task.content_text({"file": "notes.md"}) == "from a file"
    assert task.content_text("inline") == "inline"


STEP_LAB = """
steps:
  - id: one
  - id: two
    setup:
      - {run: "echo ready > made-by-setup && echo 'n=5'", capture: {n: {from: stdout, regex: "n=(\\\\d+)", type: int}}}
  - id: three
    requires: [one, two]
"""


def test_step_setup_runs_on_entry_and_captures(lab_file, tmp_path, monkeypatch):
    home = tmp_path / "labhome"
    home.mkdir()
    monkeypatch.setattr(task, "LAB_HOME", home)
    lab_file(STEP_LAB)
    task.enter_step(1)
    assert (home / "made-by-setup").read_text() == "ready\n"
    assert read_captured()["n"] == 5
    assert read_step() == 1


def test_failing_step_setup_is_reported_not_fatal(lab_file, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(task, "LAB_HOME", tmp_path)
    lab_file("steps:\n  - {id: a, setup: [{run: 'exit 4'}]}\n")
    task.enter_step(0)
    assert "Setup for this step failed" in capsys.readouterr().err


def test_requires_blocks_entering_a_step(lab_file):
    lab_file(STEP_LAB)
    assert task.unmet_requirements(2) == ["one", "two"]
    record_pass(0)
    assert task.unmet_requirements(2) == ["two"]
    record_pass(1)
    assert task.unmet_requirements(2) == []
    assert task.unmet_requirements(0) == []


def test_next_refuses_a_step_with_unmet_requirements(lab_file, capsys):
    lab_file(STEP_LAB)
    write_step(1)
    next_cmd.main()
    assert read_step() == 1
    assert "must pass" in capsys.readouterr().out


def test_free_progression_lets_next_skip(lab_file):
    lab_file("progression: free\nsteps:\n  - {id: a, checks: [{id: c, run: 'false', expect: {exit_code: 0}}]}\n  - {id: b}\n")
    next_cmd.main()
    assert read_step() == 1


def test_setup_captures_survive_the_step_file_being_cleared(step_file, tmp_path, lab_file, monkeypatch):
    home = tmp_path / "h"
    monkeypatch.setattr(task, "LAB_HOME", home)
    monkeypatch.setattr(task, "SETUP_MARKER", home / ".setup-done")
    (tmp_path / "setup.sh").write_text("echo seed=3\n")
    monkeypatch.setattr(task, "LAB_DIR", tmp_path)
    lab_file("setup:\n  - script: setup.sh\n    capture: {seed: {from: stdout, regex: 'seed=(\\d+)', type: int}}\nsteps: []\n")
    task.setup_lab()
    step_file.unlink(missing_ok=True)
    assert read_captured()["seed"] == 3


def test_setup_runs_with_env_and_no_default_timeout(tmp_path, lab_file, monkeypatch):
    home = tmp_path / "h"
    monkeypatch.setattr(task, "LAB_HOME", home)
    monkeypatch.setattr(task, "SETUP_MARKER", home / ".setup-done")
    (tmp_path / "setup.sh").write_text('echo "$GREETING" > greeting\n')
    monkeypatch.setattr(task, "LAB_DIR", tmp_path)
    lab_file("vars: {g: hi}\nsetup:\n  - script: setup.sh\n    env: {GREETING: '${g}'}\nsteps: []\n")
    task.setup_lab()
    assert (home / "greeting").read_text() == "hi\n"


HINTS = [
    {"text": "free"},
    {"text": "timed", "reveal_after": "2m"},
    {"text": "attempts", "after_failed_attempts": 2},
    {"text": "asked", "reveal": "on_request"},
]


@pytest.mark.parametrize(
    "attempts, seconds, requested, shown",
    [
        (0, 0, False, [0]),
        (0, 119, False, [0]),
        (0, 120, False, [0, 1]),
        (1, 0, False, [0]),
        (2, 0, False, [0, 2]),
        (0, 0, True, [0, 3]),
        (5, 500, True, [0, 1, 2, 3]),
    ],
)
def test_hint_rules(attempts, seconds, requested, shown):
    assert hint.available_indices(HINTS, attempts, seconds, requested) == shown


def test_timed_hint_unlocks_in_the_cli(lab_file, capsys, monkeypatch):
    lab_file("steps:\n  - id: a\n    hints:\n      - {text: now}\n      - {text: later, reveal_after: 1m}\n      - {text: asked, reveal: on_request}\n")
    hint.main()
    out = capsys.readouterr().out
    assert "now" in out
    assert "asked" in out
    assert "later" not in out
    monkeypatch.setattr(hint, "read_step_seconds", lambda: 61)
    hint.main()
    assert "later" in capsys.readouterr().out


def test_entry_time_is_kept_when_going_back(lab_file):
    from labtools import state

    lab_file("steps: [{id: a}, {id: b}]\n")
    write_step(1)
    first = state.read_state()["entered"]["1"]
    write_step(0)
    write_step(1)
    assert state.read_state()["entered"]["1"] == first
    assert state.read_step_seconds() >= 0


def test_duration_string_timeout_is_accepted():
    assert check.run_check(make("true", {"exit_code": 0}, timeout="1s"))
