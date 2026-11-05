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
    assert "one/c: timeout must be a number of seconds or a duration such as 30s, 5m or 1h" in problems


def test_duplicate_ids_and_missing_text():
    bad = lab("steps: [{id: a}, {id: a, title: t, instructions: i}]")
    problems = validate_lab(bad)
    assert "a: duplicate step id" in problems
    assert "a: missing title" in problems


def test_missing_setup_script(tmp_path):
    bad = lab(GOOD.replace("setup: []", "setup: [{script: nope.sh}]"))
    assert "setup: script nope.sh not found" in validate_lab(bad, tmp_path)


def test_setup_entry_needs_exactly_one_of_run_or_script():
    for entry in ("{}", "{run: a, script: b.sh}"):
        bad = lab(GOOD.replace("setup: []", f"setup: [{entry}]"))
        assert "setup: entry needs exactly one of run or script" in validate_lab(bad)


def test_setup_run_is_not_looked_up_as_a_file(tmp_path):
    good = lab(GOOD.replace("setup: []", "setup: [{run: apt-get install -y python3-pip}]"))
    assert validate_lab(good, tmp_path) == []


def test_negative_points_are_reported():
    lab = {"steps": [{"id": "s", "title": "t", "instructions": "i", "points": -5}]}
    assert any("points" in problem for problem in validate_lab(lab))


def test_schema_expectations_are_accepted():
    good = GOOD.replace(
        "expect: {exit_code: 0}",
        "expect: {exit_code: {not: 1}, stderr: {is_empty: true}, stdout: {matches: '^a', line_count: {gte: 2}},"
        " json: [{path: $.a, exists: true}], files: [{path: f, mode: '0644'}]}",
    )
    assert validate_lab(lab(good)) == []


def test_bad_expectations_are_reported():
    bad = GOOD.replace(
        "expect: {exit_code: 0}",
        "expect: {exit_code: 300, stdout: {matches: '('}, json: [{path: a}], files: [{path: f, mode: rw}]}",
    )
    problems = validate_lab(lab(bad))
    assert "one/c: exit_code must be 0 to 255, or {not: 0 to 255}" in problems
    assert "one/c: stdout.matches is not a valid regular expression" in problems
    assert "one/c: json[1] needs a path starting with $" in problems
    assert any("mode must be an octal string" in problem for problem in problems)


def test_depends_on_and_requires_must_name_known_ids():
    bad = GOOD.replace("expect:", "depends_on: [ghost], expect:").replace("    checks:", "    requires: [nope]\n    checks:")
    problems = validate_lab(lab(bad))
    assert "one/c: depends_on ghost is not another check in the same list" in problems
    assert "one: requires unknown step nope" in problems


def test_hint_reveal_rules_are_exclusive():
    bad = lab(GOOD)
    bad["steps"][0]["hints"] = [{"id": "h", "text": "t", "reveal_after": "2m", "reveal": "on_request"}]
    assert "one/h: use only one of reveal_after, after_failed_attempts and reveal" in validate_lab(bad)


def test_secret_capture_cannot_appear_in_instructions():
    bad = lab(GOOD.replace("instructions: do it", "instructions: 'token ${captured.key}'").replace(
        "expect: {exit_code: 0}", "expect: {exit_code: 0}, capture: {key: {from: stdout, secret: true}}"))
    assert "one/instructions: shows secret capture key to the learner" in validate_lab(bad)


def test_capture_rules():
    bad = lab(GOOD.replace("expect: {exit_code: 0}",
                           "expect: {exit_code: 0}, capture: {Bad: {from: stdout}, n: {from: exit_code, regex: x}}"))
    problems = validate_lab(bad)
    assert any("capture name Bad" in problem for problem in problems)
    assert "one/c/n: json and regex cannot be used with exit_code" in problems
