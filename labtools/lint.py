#!/usr/bin/env python3
"""Validate a lab file so authoring mistakes show up before students see them.

Run `lablint path/to/lab.yml`. The app runs the same checks on startup.
"""
import re
import sys
from pathlib import Path

import yaml

from labtools.check import TEXT_RULES
from labtools.task import DEFAULT_LAB_FILE, find_script

ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
DURATION_PATTERN = re.compile(r"^[0-9]+[smh]$")
CAPTURE_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
VAR_NAME_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
CAPTURE_REF_PATTERN = re.compile(r"\$\{captured\.([a-z][a-z0-9_]*)\}")
MODE_PATTERN = re.compile(r"^[0-7]{3,4}$")

EXPECT_KEYS = {"exit_code", "stdout", "stderr", "json", "files"}
NORMALISE_RULES = {"trim", "ignore_case", "collapse_whitespace", "sort_lines"}
COMPARISON_KEYS = ("eq", "gt", "gte", "lt", "lte")
JSON_RULES = {"exists", "equals", "not_equals", "contains", "matches", "gt", "gte", "lt", "lte", "length", "type"}
JSON_TYPES = {"string", "number", "boolean", "array", "object", "null"}
FILE_KEYS = {"path", "exists", "contains", "not_contains", "matches", "mode", "owner"}
CAPTURE_SOURCES = {"stdout", "stderr", "exit_code", "file"}
CAPTURE_TYPES = {"string", "int", "number", "bool"}


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _regex_problem(where: str, name: str, pattern) -> list[str]:
    try:
        re.compile(pattern)
    except (re.error, TypeError):
        return [f"{where}: {name} is not a valid regular expression"]
    return []


def _timeout_problem(where: str, timeout) -> list[str]:
    if _is_number(timeout) or (isinstance(timeout, str) and DURATION_PATTERN.match(timeout)):
        return []
    return [f"{where}: timeout must be a number of seconds or a duration such as 30s, 5m or 1h"]


def _number_or_ref(where: str, name: str, value, known: set[str]) -> list[str]:
    """A number, or ${captured.name} naming a capture defined somewhere in the lab."""
    if _is_number(value):
        return []
    match = CAPTURE_REF_PATTERN.fullmatch(value) if isinstance(value, str) else None
    if not match:
        return [f"{where}: {name} must be a number or a ${{captured.name}} reference"]
    if match[1] not in known:
        return [f"{where}: {name} refers to unknown capture {match[1]}"]
    return []


def _comparison_problems(where: str, name: str, value, known: set[str]) -> list[str]:
    """An exact integer, or a dict of eq, gt, gte, lt and lte."""
    if _is_int(value):
        return []
    if not isinstance(value, dict) or not value or not value.keys() <= set(COMPARISON_KEYS):
        return [f"{where}: {name} must be an integer or use {', '.join(COMPARISON_KEYS)}"]
    return [p for key, wanted in value.items() for p in _number_or_ref(where, f"{name}.{key}", wanted, known)]


def _text_problems(where: str, stream: str, rules, known: set[str]) -> list[str]:
    if not isinstance(rules, dict) or not rules or not rules.keys() <= TEXT_RULES:
        return [f"{where}: {stream} rules must be among {sorted(TEXT_RULES)}"]
    problems = []
    for name in ("matches", "not_matches"):
        if name in rules:
            problems += _regex_problem(where, f"{stream}.{name}", rules[name])
    if "is_empty" in rules and not isinstance(rules["is_empty"], bool):
        problems.append(f"{where}: {stream}.is_empty must be true or false")
    if "line_count" in rules:
        problems += _comparison_problems(where, f"{stream}.line_count", rules["line_count"], known)
    normalise = rules.get("normalise", {})
    if not isinstance(normalise, dict) or not normalise.keys() <= NORMALISE_RULES or not all(isinstance(v, bool) for v in normalise.values()):
        problems.append(f"{where}: {stream}.normalise must set {sorted(NORMALISE_RULES)} to true or false")
    return problems


def _json_problems(where: str, assertions, known: set[str]) -> list[str]:
    if not isinstance(assertions, list) or not assertions:
        return [f"{where}: json must be a list of assertions"]
    problems = []
    for number, assertion in enumerate(assertions, start=1):
        label = f"{where}: json[{number}]"
        if not isinstance(assertion, dict) or not str(assertion.get("path", "")).startswith("$"):
            problems.append(f"{label} needs a path starting with $")
            continue
        rules = assertion.keys() - {"path"}
        if not rules or not rules <= JSON_RULES:
            problems.append(f"{label} must use at least one of {sorted(JSON_RULES)}")
            continue
        if "exists" in rules and not isinstance(assertion["exists"], bool):
            problems.append(f"{label} exists must be true or false")
        if "matches" in rules:
            problems += _regex_problem(label, "matches", assertion["matches"])
        if "type" in rules and assertion["type"] not in JSON_TYPES:
            problems.append(f"{label} type must be one of {sorted(JSON_TYPES)}")
        if "length" in rules:
            problems += _comparison_problems(label, "length", assertion["length"], known)
        for key in ("gt", "gte", "lt", "lte"):
            if key in rules:
                problems += _number_or_ref(label, key, assertion[key], known)
    return problems


def _files_problems(where: str, assertions) -> list[str]:
    if not isinstance(assertions, list) or not assertions:
        return [f"{where}: files must be a list of assertions"]
    problems = []
    for number, assertion in enumerate(assertions, start=1):
        label = f"{where}: files[{number}]"
        if not isinstance(assertion, dict) or not assertion.get("path") or not assertion.keys() <= FILE_KEYS:
            problems.append(f"{label} needs a path and may only use {sorted(FILE_KEYS)}")
            continue
        if "exists" in assertion and not isinstance(assertion["exists"], bool):
            problems.append(f"{label} exists must be true or false")
        if "mode" in assertion and not MODE_PATTERN.match(str(assertion["mode"])):
            problems.append(f"{label} mode must be an octal string such as \"0644\"")
        if "matches" in assertion:
            problems += _regex_problem(label, "matches", assertion["matches"])
    return problems


def _expect_problems(where: str, expect, known: set[str]) -> list[str]:
    if not isinstance(expect, dict) or not expect:
        return [f"{where}: expect must list at least one of {sorted(EXPECT_KEYS)}"]
    problems = []
    if not expect.keys() <= EXPECT_KEYS:
        problems.append(f"{where}: unknown expect keys {sorted(expect.keys() - EXPECT_KEYS)}")
    if "exit_code" in expect:
        code = expect["exit_code"]
        if isinstance(code, dict):
            code = code.get("not") if code.keys() == {"not"} else None
        if not _is_int(code) or not 0 <= code <= 255:
            problems.append(f"{where}: exit_code must be 0 to 255, or {{not: 0 to 255}}")
    for stream in ("stdout", "stderr"):
        if stream in expect:
            problems += _text_problems(where, stream, expect[stream], known)
    if "json" in expect:
        problems += _json_problems(where, expect["json"], known)
    if "files" in expect:
        problems += _files_problems(where, expect["files"])
    return problems


def _execution_problems(where: str, entry: dict) -> list[str]:
    problems = []
    for key in ("cwd", "target", "as_user"):
        if key in entry and not (isinstance(entry[key], str) and entry[key]):
            problems.append(f"{where}: {key} must be a non-empty string")
    env = entry.get("env", {})
    if not isinstance(env, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in env.items()):
        problems.append(f"{where}: env must map names to string values")
    if "timeout" in entry:
        problems += _timeout_problem(where, entry["timeout"])
    return problems


def _capture_problems(where: str, name: str, capture) -> list[str]:
    if not CAPTURE_NAME_PATTERN.match(str(name)):
        return [f"{where}: capture name {name} must be lowercase letters, digits and underscores"]
    where = f"{where}/{name}"
    if not isinstance(capture, dict) or capture.get("from") not in CAPTURE_SOURCES:
        return [f"{where}: capture needs from: one of {sorted(CAPTURE_SOURCES)}"]
    source = capture["from"]
    problems = []
    if source == "file" and not capture.get("file"):
        problems.append(f"{where}: capture from file needs a file path")
    if source != "file" and "file" in capture:
        problems.append(f"{where}: file is only allowed when from is file")
    if "json" in capture and not str(capture["json"]).startswith("$"):
        problems.append(f"{where}: json must be a JSONPath starting with $")
    if "json" in capture and "regex" in capture:
        problems.append(f"{where}: use json or regex, not both")
    if source == "exit_code" and ("json" in capture or "regex" in capture):
        problems.append(f"{where}: json and regex cannot be used with exit_code")
    if "regex" in capture:
        problems += _regex_problem(where, "regex", capture["regex"])
    if capture.get("type", "string") not in CAPTURE_TYPES:
        problems.append(f"{where}: type must be one of {sorted(CAPTURE_TYPES)}")
    for key in ("trim", "secret"):
        if key in capture and not isinstance(capture[key], bool):
            problems.append(f"{where}: {key} must be true or false")
    return problems


def _captures_problems(where: str, captures) -> list[str]:
    if not isinstance(captures, dict) or not captures:
        return [f"{where}: capture must map names to definitions"]
    return [p for name, capture in captures.items() for p in _capture_problems(where, name, capture)]


def _collect_captures(lab: dict) -> tuple[dict[str, bool], list[str]]:
    """Map every capture name in the lab to its secret flag, and report names used twice."""
    entries = list(lab.get("setup") or []) + list(lab.get("final_checks") or [])
    for step in lab.get("steps") or []:
        entries += list(step.get("setup") or []) + list(step.get("checks") or [])
    names: dict[str, bool] = {}
    problems = []
    for entry in entries:
        captures = entry.get("capture") if isinstance(entry, dict) else None
        for name, capture in (captures.items() if isinstance(captures, dict) else []):
            if name in names:
                problems.append(f"capture {name} is defined more than once")
            names[name] = bool(isinstance(capture, dict) and capture.get("secret"))
    return names, problems


def _secret_problems(where: str, text, secrets: set[str]) -> list[str]:
    """Learner facing text must not mention a secret capture."""
    if not isinstance(text, str):
        return []
    return [f"{where}: shows secret capture {name} to the learner" for name in CAPTURE_REF_PATTERN.findall(text) if name in secrets]


def _check_problems(where: str, check: dict, known: set[str], secrets: set[str], siblings: set[str]) -> list[str]:
    problems = []
    if not check.get("id"):
        problems.append(f"{where}: missing id")
    elif not ID_PATTERN.match(str(check["id"])):
        problems.append(f"{where}: id must be lowercase letters, digits, - and _")
    if not check.get("run") and not check.get("command_run"):
        problems.append(f"{where}: missing run or command_run")
    if check.get("run"):
        problems += _expect_problems(where, check.get("expect"), known)
    if not check.get("feedback_on_fail"):
        problems.append(f"{where}: missing feedback_on_fail")
    problems += _secret_problems(where, check.get("feedback_on_fail"), secrets)
    for number, rule in enumerate(check.get("feedback_rules") or [], start=1):
        label = f"{where}: feedback_rules[{number}]"
        if not isinstance(rule, dict) or not rule.get("message"):
            problems.append(f"{label} needs a when and a message")
            continue
        problems += _expect_problems(label, rule.get("when"), known)
        problems += _secret_problems(label, rule["message"], secrets)
    for key in ("required", "regression"):
        if not isinstance(check.get(key, True), bool):
            problems.append(f"{where}: {key} must be true or false")
    depends = check.get("depends_on", [])
    if not isinstance(depends, list) or len(set(map(str, depends))) != len(depends):
        problems.append(f"{where}: depends_on must be a list of unique check ids")
    else:
        for other in depends:
            if other == check.get("id") or other not in siblings:
                problems.append(f"{where}: depends_on {other} is not another check in the same list")
    problems += _execution_problems(where, check)
    if "capture" in check:
        problems += _captures_problems(where, check["capture"])
    return problems


def _checks_problems(where: str, checks, known: set[str], secrets: set[str]) -> list[str]:
    problems = []
    ids = [check.get("id") for check in checks]
    for duplicate in sorted({i for i in ids if i and ids.count(i) > 1}):
        problems.append(f"{where}: duplicate check id {duplicate}")
    siblings = {i for i in ids if i}
    for check in checks:
        problems += _check_problems(f"{where}/{check.get('id')}", check, known, secrets, siblings)
    return problems


def _hint_problems(where: str, hint: dict, secrets: set[str]) -> list[str]:
    problems = []
    if not hint.get("text"):
        problems.append(f"{where}: hint has no text")
    problems += _secret_problems(where, hint.get("text"), secrets)
    rules = [key for key in ("reveal_after", "after_failed_attempts", "reveal") if key in hint]
    if len(rules) > 1:
        problems.append(f"{where}: use only one of reveal_after, after_failed_attempts and reveal")
    if "reveal_after" in hint and not (isinstance(hint["reveal_after"], str) and DURATION_PATTERN.match(hint["reveal_after"])):
        problems.append(f"{where}: reveal_after must be a duration such as 30s, 5m or 1h")
    if "after_failed_attempts" in hint and not (_is_int(hint["after_failed_attempts"]) and hint["after_failed_attempts"] >= 1):
        problems.append(f"{where}: after_failed_attempts must be an integer of 1 or more")
    if "reveal" in hint and hint["reveal"] != "on_request":
        problems.append(f"{where}: reveal must be on_request")
    return problems


def _content_problems(where: str, value, base_dir: Path | None) -> list[str]:
    """Inline text, or {file: path} relative to the lab file."""
    if isinstance(value, str):
        return []
    if not isinstance(value, dict) or value.keys() != {"file"} or not isinstance(value["file"], str) or not value["file"]:
        return [f"{where}: must be text or {{file: path}}"]
    if base_dir is not None and not (base_dir / value["file"]).is_file():
        return [f"{where}: file {value['file']} not found"]
    return []


def _setup_problems(where: str, entries, base_dir: Path | None, look_for_scripts: bool) -> list[str]:
    problems = []
    for entry in entries or []:
        script = entry.get("script")
        if bool(script) == bool(entry.get("run")):
            problems.append(f"{where}: entry needs exactly one of run or script")
        elif script and look_for_scripts and not find_script(script, base_dir).exists():
            problems.append(f"{where}: script {script} not found")
        problems += _execution_problems(where, entry)
        if "capture" in entry:
            problems += _captures_problems(where, entry["capture"])
    return problems


def validate_lab(lab, base_dir: Path | None = None) -> list[str]:
    """Return a list of problems found in a loaded lab definition, empty when it is valid."""
    if not isinstance(lab, dict) or not lab.get("steps"):
        return ["steps: missing or empty"]
    captures, problems = _collect_captures(lab)
    known = set(captures)
    secrets = {name for name, secret in captures.items() if secret}
    if lab.get("progression", "linear") not in ("linear", "free"):
        problems.append("progression: must be linear or free")
    variables = lab.get("vars", {})
    if not isinstance(variables, dict):
        problems.append("vars: must map names to values")
    else:
        for name, value in variables.items():
            if not VAR_NAME_PATTERN.match(str(name)) or not isinstance(value, (str, int, float, bool)):
                problems.append(f"vars: {name} needs a simple name and a string, number or boolean value")
    if "description" in lab:
        problems += _content_problems("description", lab["description"], base_dir)
    step_ids = [step.get("id") for step in lab["steps"]]
    seen = set()
    for number, step in enumerate(lab["steps"], start=1):
        where = str(step.get("id") or f"step {number}")
        if where in seen:
            problems.append(f"{where}: duplicate step id")
        seen.add(where)
        for key in ("title", "instructions"):
            if not step.get(key):
                problems.append(f"{where}: missing {key}")
        if step.get("instructions"):
            problems += _content_problems(f"{where}/instructions", step["instructions"], base_dir)
            problems += _secret_problems(f"{where}/instructions", step["instructions"], secrets)
        points = step.get("points", 0)
        if isinstance(points, bool) or not isinstance(points, (int, float)) or points < 0:
            problems.append(f"{where}: points must be a number of 0 or more")
        requires = step.get("requires", [])
        if not isinstance(requires, list) or len(set(map(str, requires))) != len(requires):
            problems.append(f"{where}: requires must be a list of unique step ids")
        else:
            problems += [f"{where}: requires unknown step {other}" for other in requires if other not in step_ids or other == step.get("id")]
        problems += _setup_problems(f"{where}/setup", step.get("setup"), base_dir, look_for_scripts=False)
        problems += _checks_problems(where, step.get("checks") or [], known, secrets)
        for hint in step.get("hints") or []:
            problems += _hint_problems(f"{where}/{hint.get('id')}", hint, secrets)
    problems += _checks_problems("final_checks", lab.get("final_checks") or [], known, secrets)
    problems += _setup_problems("setup", lab.get("setup"), base_dir, look_for_scripts=True)
    return problems


def main() -> None:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_LAB_FILE)
    try:
        lab = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError) as error:
        sys.exit(f"{path}: {error}")
    problems = validate_lab(lab, path.parent)
    for problem in problems:
        print(problem)
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
