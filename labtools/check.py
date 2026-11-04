#!/usr/bin/env python3
import operator
import os
import subprocess

from rich.console import Console
from rich.markup import escape
from rich.padding import Padding
from rich.panel import Panel
from rich.text import Text

from labtools.start import NOT_STARTED
from labtools.state import LAB_HOME, is_started, read_step, record_check, record_pass, write_step, read_cwd
from labtools.task import get_checks

BOLD = '\033[1m'
END = '\033[0m'

COMPARISONS = {
    "equals": operator.eq,
    "gt": operator.gt,
    "gte": operator.ge,
    "lt": operator.lt,
    "lte": operator.le,
}
STDOUT_RULES = {*COMPARISONS, "contains"}
MAX_LINES = 10
DEFAULT_TIMEOUT = 30

console = Console()

def _compare(op, text: str, wanted) -> bool:
    """Compare numerically when the lab file gives a number, otherwise as text."""
    if isinstance(wanted, (int, float)) and not isinstance(wanted, bool):
        try:
            return op(float(text), wanted)
        except ValueError:
            return False
    return op(text, str(wanted))


def stdout_matches(stdout: str, rules: dict) -> bool:
    """Return True if stdout (whitespace trimmed) satisfies every rule."""
    text = stdout.strip()
    for name, wanted in rules.items():
        if name == "contains":
            ok = str(wanted) in text
        elif name in COMPARISONS:
            ok = _compare(COMPARISONS[name], text, wanted)
        else:
            raise ValueError(f"Unknown stdout rule: {name}")
        if not ok:
            return False
    return True


def failure_panel(check, result) -> Panel:
    body = Text(check.get("feedback_on_fail") or "Check failed", style="bold")
    if check.get("show_output"):
        output = (result.stderr.strip() or result.stdout.strip()).splitlines()[-MAX_LINES:]
        if output:
            body.append("\n\n")
            body.append("\n".join(output), style="dim")
    return Panel(
        body,
        title=f"[bold]✗ FAIL[/bold] {escape(str(check.get('description')))}",
        title_align="left",
        border_style="red",
    )

def execute(check) -> subprocess.CompletedProcess:
    """Run one check command in LAB_HOME and return the finished process.

    Raises FileNotFoundError if LAB_HOME is missing and TimeoutExpired after check['timeout'] seconds.
    """
    return subprocess.run(
        check["run"],
        shell=True,
        capture_output=True,
        text=True,
        errors="replace",
        stdin=subprocess.DEVNULL,
        cwd=LAB_HOME,
        env={**os.environ, "STUDENT_CWD": read_cwd()},
        timeout=check.get("timeout", DEFAULT_TIMEOUT),
    )


def meets_expectations(check, result) -> bool:
    """Return True if the process result satisfies the check's expect block."""
    expect = check["expect"]
    if "exit_code" in expect and result.returncode != int(expect["exit_code"]):
        return False
    return "stdout" not in expect or stdout_matches(result.stdout, expect["stdout"])


def run_check(check) -> bool:
    """Run one check command and report whether its output met the expectations.

    expect.exit_code is compared when present. expect.stdout holds the rules
    from STDOUT_RULES. Commands run in LAB_HOME, never read from the student's terminal, and
    stop after check['timeout'] seconds (default 30).
    """
    description = escape(str(check.get("description")))
    timeout = check.get("timeout", DEFAULT_TIMEOUT)
    with console.status(f"{description}..."):
        try:
            result = execute(check)
        except FileNotFoundError:
            console.print(Panel(
                f"The lab folder {LAB_HOME} does not exist. Set LAB_HOME to the lab folder.",
                title=f"[bold]✗ FAIL[/bold] {description}",
                title_align="left",
                border_style="red",
            ))
            return False
        except subprocess.TimeoutExpired:
            console.print(Panel(
                f"Timed out after {timeout} seconds. Check for an infinite loop.",
                title=f"[bold]✗ FAIL[/bold] {description}",
                title_align="left",
                border_style="red",
            ))
            return False
    if meets_expectations(check, result):
        console.print(f"[green bold]✓ PASS[/green bold] {description}")
        return True
    console.print(failure_panel(check, result))
    return False


def is_required(check) -> bool:
    return check.get("required", True)


def run_checks(checks) -> tuple[bool, bool]:
    """Run checks in order and return (required_passed, all_passed).

    A failing required check stops the run, since later checks would only
    add noise. A failing optional check is reported and the run continues,
    so the required checks after it still count.
    """
    all_passed = True
    for check in checks:
        if not check.get("run") or run_check(check):
            continue
        all_passed = False
        if is_required(check):
            return False, False
    return True, all_passed


def checks_pass_silently(checks) -> bool:
    """Return True if every check passes, without printing or recording anything.

    The lab app calls this on a timer to tell the student the step is ready for `check`.
    Optional checks count too, because `check` only completes a step when all of them pass.
    """
    for check in checks:
        if not check.get("run"):
            continue
        try:
            result = execute(check)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False
        if not meets_expectations(check, result):
            return False
    return True


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

    this_check = checks[step]
    if this_check is not None:
        record_check()
        required_passed, all_passed = run_checks(this_check)
    else:
        required_passed = all_passed = True

    if all_passed:
        record_pass(step)
        write_step(step + 1)
        console.print("[bold green]Step complete![/bold green]")
    elif required_passed:
        console.print("Only optional checks failed. Fix them and run `check` again, or run `next` to move on.")


if __name__ == "__main__":
    main()
