import sys

from rich.console import Console

from labtools.check import run_groups, step_groups
from labtools.state import read_step, record_pass, require_started
from labtools.task import enter_step, get_lab, get_progression, unmet_requirements

console = Console()

def main() -> None:
    if not require_started(console):
        return
    step = read_step()
    if step >= len(get_lab()):
        console.print("Nothing to skip, you're at the end!")
        return

    if blocked := unmet_requirements(step + 1):
        console.print(f"You must pass {', '.join(blocked)} first.")
        return
    groups = step_groups(step)
    if (len(sys.argv) > 1 and sys.argv[1] == "--dev") or get_progression() == "free":
        # Dev skips earn no points, so authors can walk a lab without faking a score.
        # A free lab lets students move on without passing, and they earn nothing for the step.
        enter_step(step + 1)
        return
    if groups is None:
        record_pass(step)
        enter_step(step + 1)
        return

    # Optional checks never block next, so only the required ones are run
    required_passed, _ = run_groups(groups, required_only=True)
    if required_passed:
        record_pass(step)
        enter_step(step + 1)
    else:
        console.print("You must pass this step first. Run hint if you are stuck.")


if __name__ == "__main__":
    main()
