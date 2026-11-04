#!/usr/bin/env python3
import sys

from rich.console import Console

from labtools.check import is_required, run_checks
from labtools.start import NOT_STARTED
from labtools.state import is_started, read_step, record_pass, write_step
from labtools.task import get_checks

console = Console()

def main() -> None:
    if not is_started():
        console.print(NOT_STARTED)
        return
    step = read_step()
    checks = get_checks()
    if step >= len(checks):
        console.print("Nothing to skip, you're at the end!")
        return

    this_check = checks[step]
    if len(sys.argv) > 1 and sys.argv[1] == "--dev":
        # Dev skips earn no points, so authors can walk a lab without faking a score
        write_step(step + 1)
        return
    if this_check is None:
        record_pass(step)
        write_step(step + 1)
        return

    # Optional checks never block next, so only the required ones are run
    required_passed, _ = run_checks([c for c in this_check if is_required(c)])
    if required_passed:
        record_pass(step)
        write_step(step + 1)
    else:
        console.print("You must pass this step first. Run hint if you are stuck.")


if __name__ == "__main__":
    main()
