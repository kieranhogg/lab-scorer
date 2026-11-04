#!/usr/bin/env python3
"""Validate a lab file so authoring mistakes show up before students see them.

Run `lablint path/to/lab.yml`. The app runs the same checks on startup.
"""
import sys
from pathlib import Path

import yaml

from labtools.check import STDOUT_RULES
from labtools.task import DEFAULT_LAB_FILE, find_script


def _check_problems(where: str, check: dict) -> list[str]:
    problems = []
    if not check.get("run") and not check.get("command_run"):
        problems.append(f"{where}: missing run or command_run")
    if check.get("run"):
        expect = check.get("expect")
        if not isinstance(expect, dict) or not expect:
            problems.append(f"{where}: expect must list exit_code and/or stdout")
            return problems
        if not expect.keys() <= {"exit_code", "stdout"}:
            problems.append(f"{where}: unknown expect keys {sorted(expect.keys() - {'exit_code', 'stdout'})}")
        if "exit_code" in expect and not isinstance(expect["exit_code"], int):
            problems.append(f"{where}: exit_code must be an integer")
        rules = expect.get("stdout") or {}
        if not isinstance(rules, dict) or not rules.keys() <= STDOUT_RULES:
            problems.append(f"{where}: stdout rules must be among {sorted(STDOUT_RULES)}")
    if not check.get("feedback_on_fail"):
        problems.append(f"{where}: missing feedback_on_fail")
    if not isinstance(check.get("required", True), bool):
        problems.append(f"{where}: required must be true or false")
    if not isinstance(check.get("timeout", 1), (int, float)):
        problems.append(f"{where}: timeout must be a number of seconds")
    return problems


def validate_lab(lab, base_dir: Path | None = None) -> list[str]:
    """Return a list of problems found in a loaded lab definition, empty when it is valid."""
    if not isinstance(lab, dict) or not lab.get("steps"):
        return ["steps: missing or empty"]
    problems = []
    seen = set()
    for number, step in enumerate(lab["steps"], start=1):
        where = str(step.get("id") or f"step {number}")
        if where in seen:
            problems.append(f"{where}: duplicate step id")
        seen.add(where)
        for key in ("title", "instructions"):
            if not step.get(key):
                problems.append(f"{where}: missing {key}")
        points = step.get("points", 0)
        if isinstance(points, bool) or not isinstance(points, (int, float)) or points < 0:
            problems.append(f"{where}: points must be a number of 0 or more")
        for check in step.get("checks") or []:
            problems += _check_problems(f"{where}/{check.get('id')}", check)
        for hint in step.get("hints") or []:
            if not hint.get("text"):
                problems.append(f"{where}/{hint.get('id')}: hint has no text")
    for entry in lab.get("setup") or []:
        script = entry.get("run")
        if not script:
            problems.append("setup: entry has no run")
        elif not find_script(script, base_dir).exists():
            problems.append(f"setup: script {script} not found")
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
