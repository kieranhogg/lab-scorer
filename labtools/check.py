#!/usr/bin/env python3
import json
import operator
import os
import pwd
import re
import stat
import subprocess
from pathlib import Path

from rich.console import Console
from rich.markup import escape
from rich.padding import Padding
from rich.panel import Panel
from rich.text import Text

from labtools import jsonpath
from labtools.command import (
    DEFAULT_TIMEOUT,
    extract_values,
    fill_captured,
    run_command,
    shell_refs,
    timeout_seconds,
)
from labtools.start import NOT_STARTED
from labtools.state import (
    LAB_HOME,
    is_started,
    read_captured,
    read_step,
    record_check,
    record_pass,
    save_captured,
)
from labtools.task import (
    enter_step,
    get_checks,
    get_lab,
    open_lab_file,
    unmet_requirements,
)

BOLD = '\033[1m'
END = '\033[0m'

COMPARISONS = {
    "equals": operator.eq,
    "gt": operator.gt,
    "gte": operator.ge,
    "lt": operator.lt,
    "lte": operator.le,
}
NUMBER_COMPARISONS = {"eq": operator.eq, **{name: COMPARISONS[name] for name in ("gt", "gte", "lt", "lte")}}
TEXT_RULES = {
    *COMPARISONS, "contains", "not_contains", "starts_with", "matches", "not_matches", "is_empty", "line_count", "normalise",
}
STDOUT_RULES = TEXT_RULES
CAPTURE_REF = re.compile(r"^\$\{captured\.([a-z][a-z0-9_]*)\}$")
MAX_LINES = 10

console = Console()


def _limit(wanted):
    """Resolve a number, or a ${captured.name} reference to a numeric capture. None if it is not a number."""
    if isinstance(wanted, str) and (ref := CAPTURE_REF.match(wanted)):
        wanted = read_captured().get(ref[1])
    return wanted if isinstance(wanted, (int, float)) and not isinstance(wanted, bool) else None


def number_matches(actual: float, wanted) -> bool:
    """Compare against an exact integer, or a dict of eq, gt, gte, lt and lte."""
    if isinstance(wanted, int):
        return actual == wanted
    for name, wanted_limit in wanted.items():
        limit = _limit(wanted_limit)
        if limit is None or not NUMBER_COMPARISONS[name](actual, limit):
            return False
    return True


def _normalise(text: str, options: dict) -> str:
    if options.get("trim", True):
        text = text.strip()
    if options.get("collapse_whitespace"):
        text = " ".join(text.split())
    if options.get("ignore_case"):
        text = text.casefold()
    if options.get("sort_lines"):
        text = "\n".join(sorted(text.splitlines()))
    return text


def _compare(op, text: str, wanted, options: dict) -> bool:
    """Compare numerically when the lab file gives a number, otherwise as text."""
    if isinstance(wanted, (int, float)) and not isinstance(wanted, bool):
        try:
            return op(float(text), wanted)
        except ValueError:
            return False
    return op(text, _normalise(str(wanted), options))


def text_matches(output: str, rules: dict) -> bool:
    """Return True if the output satisfies every rule in TEXT_RULES, after the normalise options."""
    options = rules.get("normalise", {})
    text = _normalise(output, options)
    flags = re.IGNORECASE if options.get("ignore_case") else 0
    for name, wanted in rules.items():
        if name == "normalise":
            continue
        if name in COMPARISONS:
            ok = _compare(COMPARISONS[name], text, wanted, options)
        elif name == "contains":
            ok = _normalise(str(wanted), options) in text
        elif name == "not_contains":
            ok = _normalise(str(wanted), options) not in text
        elif name == "starts_with":
            ok = text.startswith(_normalise(str(wanted), options))
        elif name == "matches":
            ok = re.search(wanted, text, flags) is not None
        elif name == "not_matches":
            ok = re.search(wanted, text, flags) is None
        elif name == "is_empty":
            ok = (text == "") is wanted
        elif name == "line_count":
            ok = number_matches(len(text.splitlines()), wanted)
        else:
            raise ValueError(f"Unknown text rule: {name}")
        if not ok:
            return False
    return True


stdout_matches = text_matches


def _json_type(value) -> str:
    for kind, name in ((bool, "boolean"), ((int, float), "number"), (str, "string"), (list, "array"), (dict, "object")):
        if isinstance(value, kind):
            return name
    return "null"


def _json_assertion_holds(data, assertion: dict) -> bool:
    try:
        found, value = jsonpath.lookup(data, assertion["path"])
    except ValueError:
        return False
    if "exists" in assertion and found != assertion["exists"]:
        return False
    rules = assertion.keys() - {"path", "exists"}
    if not rules:
        return True
    if not found:
        return False
    for name in rules:
        wanted = assertion[name]
        if name == "equals":
            ok = value == wanted
        elif name == "not_equals":
            ok = value != wanted
        elif name == "contains":
            ok = (wanted in value) if isinstance(value, (str, list, dict)) else False
        elif name == "matches":
            ok = isinstance(value, str) and re.search(wanted, value) is not None
        elif name == "type":
            ok = _json_type(value) == wanted
        elif name == "length":
            ok = isinstance(value, (str, list, dict)) and number_matches(len(value), wanted)
        else:
            limit = _limit(wanted)
            number = isinstance(value, (int, float)) and not isinstance(value, bool)
            ok = number and limit is not None and NUMBER_COMPARISONS[name](value, limit)
        if not ok:
            return False
    return True


def json_matches(stdout: str, assertions: list) -> bool:
    """Parse stdout as JSON and check every assertion. Output that is not JSON fails."""
    try:
        data = json.loads(stdout)
    except ValueError:
        return False
    return all(_json_assertion_holds(data, assertion) for assertion in assertions)


def _file_holds(assertion: dict, base: Path) -> bool:
    path = base / os.path.expanduser(assertion["path"])
    wants_to_exist = assertion.get("exists", True)
    if path.exists() != wants_to_exist:
        return False
    if not wants_to_exist:
        return True
    try:
        if {"contains", "not_contains", "matches"} & assertion.keys():
            text = path.read_text(errors="replace")
            if "contains" in assertion and assertion["contains"] not in text:
                return False
            if "not_contains" in assertion and assertion["not_contains"] in text:
                return False
            if "matches" in assertion and not re.search(assertion["matches"], text):
                return False
        info = path.stat()
    except OSError:
        return False
    if "mode" in assertion and stat.S_IMODE(info.st_mode) != int(assertion["mode"], 8):
        return False
    if "owner" in assertion:
        try:
            owner = pwd.getpwuid(info.st_uid).pw_name
        except KeyError:
            owner = str(info.st_uid)
        return owner == assertion["owner"]
    return True


def files_match(assertions: list, base: Path) -> bool:
    """Check every file assertion. Relative paths start from the check's working directory."""
    return all(_file_holds(assertion, base) for assertion in assertions)


def check_directory(check) -> Path:
    return LAB_HOME / check.get("cwd", ".")


def failure_message(check, result) -> str:
    """Return the first feedback rule whose conditions match the result, else feedback_on_fail."""
    for rule in check.get("feedback_rules") or []:
        if expectations_met(rule["when"], result, check_directory(check)):
            return fill_captured(rule["message"])
    return fill_captured(check.get("feedback_on_fail") or "Check failed")


def fail_style(check) -> tuple[str, str]:
    """Return the title label and border colour for a failed check. Optional checks are softer than required ones."""
    return ("⚠ OPTIONAL", "yellow") if not is_required(check) else ("✗ FAIL", "red")


def failure_panel(check, result, note: str = "") -> Panel:
    body = Text(failure_message(check, result), style="bold")
    if note:
        body.append(f"\n{note}", style="dim")
    if check.get("show_output"):
        output = (result.stderr.strip() or result.stdout.strip()).splitlines()[-MAX_LINES:]
        if output:
            body.append("\n\n")
            body.append("\n".join(output), style="dim")
    label, colour = fail_style(check)
    return Panel(
        body,
        title=f"[bold]{label}[/bold] {escape(str(check.get('description')))}",
        title_align="left",
        border_style=colour,
    )

def execute(check) -> subprocess.CompletedProcess:
    """Run one check command in LAB_HOME and return the finished process.

    The check's cwd, env, timeout and as_user apply. Raises FileNotFoundError if LAB_HOME is missing
    and TimeoutExpired after the timeout (default 30 seconds).
    """
    return run_command(check, shell_refs(check["run"]), LAB_HOME)


def expectations_met(expect: dict, result, base: Path) -> bool:
    """Return True if a finished command satisfies every assertion in an expect block."""
    if "exit_code" in expect:
        wanted = expect["exit_code"]
        if isinstance(wanted, dict):
            if result.returncode == int(wanted["not"]):
                return False
        elif result.returncode != int(wanted):
            return False
    if "stdout" in expect and not text_matches(result.stdout, expect["stdout"]):
        return False
    if "stderr" in expect and not text_matches(result.stderr, expect["stderr"]):
        return False
    if "json" in expect and not json_matches(result.stdout, expect["json"]):
        return False
    return "files" not in expect or files_match(expect["files"], base)


def meets_expectations(check, result) -> bool:
    """Return True if the process result satisfies the check's expect block."""
    return expectations_met(check["expect"], result, check_directory(check))


def panel(message: str, description: str, check) -> Panel:
    label, colour = fail_style(check)
    return Panel(message, title=f"[bold]{label}[/bold] {description}", title_align="left", border_style=colour)


def run_check(check, prefix: str = "", commit: bool = True, note: str = "") -> bool:
    """Run one check command and report whether its output met the expectations.

    expect.exit_code, stdout, stderr, json and files are compared when present. Commands run in the
    check's cwd (LAB_HOME by default), never read from the student's terminal, and stop after
    check['timeout'] (default 30 seconds). When the check passes and commit is true, its captures are saved.
    """
    description = prefix + escape(str(check.get("description")))
    timeout = check.get("timeout", DEFAULT_TIMEOUT)
    with console.status(f"{description}..."):
        try:
            result = execute(check)
        except FileNotFoundError:
            console.print(panel(f"The lab folder {LAB_HOME} does not exist. Set LAB_HOME to the lab folder.", description, check))
            return False
        except subprocess.TimeoutExpired:
            console.print(panel(f"Timed out after {timeout_seconds(timeout)} seconds. Check for an infinite loop.", description, check))
            return False
    if not meets_expectations(check, result):
        console.print(failure_panel(check, result, note))
        return False
    if commit and check.get("capture"):
        try:
            save_captured(extract_values(check["capture"], result, check_directory(check)))
        except ValueError as error:
            console.print(panel(escape(str(error)), description, check))
            return False
    console.print(f"[green bold]✓ PASS[/green bold] {description}")
    return True


def is_required(check) -> bool:
    return check.get("required", True)


def unmet_dependencies(check, passed: set[str]) -> list[str]:
    return [other for other in check.get("depends_on") or [] if other not in passed]


def run_checks(checks, prefix: str = "", commit: bool = True, note: str = "") -> tuple[bool, bool]:
    """Run checks in order and return (required_passed, all_passed).

    A failing required check stops the run, since later checks would only
    add noise. A failing optional check is reported and the run continues,
    so the required checks after it still count. A check whose depends_on ids have not all passed
    is skipped and counts as not passed.
    """
    all_passed = True
    passed: set[str] = set()
    for check in checks:
        if not check.get("run"):
            passed.add(check.get("id"))
            continue
        if missing := unmet_dependencies(check, passed):
            console.print(f"[yellow bold]↷ SKIP[/yellow bold] {prefix}{escape(str(check.get('description')))} (needs {', '.join(missing)})")
        elif run_check(check, prefix, commit, note):
            passed.add(check.get("id"))
            continue
        all_passed = False
        if is_required(check):
            return False, False
    return True, all_passed


def regression_group(checks) -> list[dict]:
    """Return the checks marked regression, plus the checks they depend on, in their original order."""
    by_id = {check.get("id"): check for check in checks}
    keep: set = set()

    def add(check_id):
        if check_id in by_id and check_id not in keep:
            keep.add(check_id)
            for other in by_id[check_id].get("depends_on") or []:
                add(other)

    for check in checks:
        if check.get("regression"):
            add(check.get("id"))
    return [check for check in checks if check.get("id") in keep]


def step_groups(step: int) -> list[tuple[list, str, bool]] | None:
    """Return what `check` runs on a step as (checks, prefix, commit) groups, None when there is nothing to run.

    The step's own checks come first, then the regression checks of earlier steps, then on the last step
    the lab's final_checks. Each group has its own depends_on scope. Regression runs never overwrite captures.
    """
    steps = get_lab()
    groups = [(steps[step].get("checks") or [], "", True)]
    for number, earlier in enumerate(steps[:step], start=1):
        groups.append((regression_group(earlier.get("checks") or []), f"(step {number}) ", False))
    if step == len(steps) - 1:
        groups.append((open_lab_file().get("final_checks") or [], "(final) ", True))
    groups = [group for group in groups if group[0]]
    return groups or None


def run_groups(groups, required_only: bool = False) -> tuple[bool, bool]:
    """Run groups in order and return (required_passed, all_passed). A required failure stops the run."""
    all_passed = True
    for checks, prefix, commit in groups:
        if required_only:
            checks = [check for check in checks if is_required(check)]
        note = "This passed on an earlier step. Something you changed since has broken it." if prefix.startswith("(step") else ""
        required_passed, passed = run_checks(checks, prefix, commit, note)
        if not required_passed:
            return False, False
        all_passed = all_passed and passed
    return True, all_passed


def checks_pass_silently(checks) -> bool:
    """Return True if every check passes, without printing or recording anything.

    The lab app calls this on a timer to tell the student the step is ready for `check`.
    Optional checks count too, because `check` only completes a step when all of them pass.
    Captures are not saved, so a check that needs a capture from an earlier check only passes after `check` runs.
    """
    passed: set[str] = set()
    for check in checks:
        if not check.get("run"):
            passed.add(check.get("id"))
            continue
        if unmet_dependencies(check, passed):
            return False
        try:
            result = execute(check)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False
        if not meets_expectations(check, result):
            return False
        passed.add(check.get("id"))
    return True


def groups_pass_silently(groups) -> bool:
    return all(checks_pass_silently(checks) for checks, _, _ in groups)


def main() -> None:
    console.rule(style="dim")
    if not is_started():
        console.print(NOT_STARTED)
        return
    step = read_step()
    checks = get_checks()
    if step >= len(checks):
        console.print("Nothing left to check, you're on the final step.")
        return

    groups = step_groups(step)
    if groups is not None:
        record_check()
        required_passed, all_passed = run_groups(groups)
    else:
        required_passed = all_passed = True

    if all_passed:
        record_pass(step)
        if blocked := unmet_requirements(step + 1):
            console.print(f"Step passed, but the next step needs {', '.join(blocked)} first.")
            return
        enter_step(step + 1)
        console.print("[bold green]Step complete![/bold green]")
    elif required_passed:
        console.print("Only optional checks failed. Fix them and run `check` again, or run `next` to move on.")


if __name__ == "__main__":
    main()
