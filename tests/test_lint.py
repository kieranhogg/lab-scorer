import yaml

from labtools.lint import validate_lab

GOOD = """
setup: []
steps:
  - id: one
    title: One
    instructions: do it
    checks:
      - {id: c, run: "true", expect: {exit_code: 0}, feedback_on_fail: nope}
"""


def lab(text):
    return yaml.safe_load(text)


def test_valid_lab_has_no_problems():
    assert validate_lab(lab(GOOD)) == []


def test_missing_steps():
    assert validate_lab(lab("title: x")) == ["steps: missing or empty"]


def test_reports_each_check_problem():
    bad = GOOD.replace('feedback_on_fail: nope', 'required: maybe, timeout: soon')
    problems = validate_lab(lab(bad))
    assert "one/c: missing feedback_on_fail" in problems
    assert "one/c: required must be true or false" in problems
    assert "one/c: timeout must be a number of seconds" in problems


def test_duplicate_ids_and_missing_text():
    bad = lab("steps: [{id: a}, {id: a, title: t, instructions: i}]")
    problems = validate_lab(bad)
    assert "a: duplicate step id" in problems
    assert "a: missing title" in problems


def test_missing_setup_script(tmp_path):
    bad = lab(GOOD.replace("setup: []", "setup: [{run: nope.sh}]"))
    assert "setup: script nope.sh not found" in validate_lab(bad, tmp_path)


def test_negative_points_are_reported():
    lab = {"steps": [{"id": "s", "title": "t", "instructions": "i", "points": -5}]}
    assert any("points" in problem for problem in validate_lab(lab))
