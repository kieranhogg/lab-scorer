#!/usr/bin/env python3
from rich.console import Console

from labtools.state import is_started, read_student, start
from labtools.task import run_step_setup

console = Console()

NOT_STARTED = "Type `start` to begin the lab."


def main() -> None:
    if is_started():
        console.print("The lab has already started.")
        return
    if not read_student().get("name"):
        console.print("Enter your name in the instructions pane first.")
        return
    start()
    run_step_setup(0)
    console.print("Lab started. The first task is in the instructions pane.")


if __name__ == "__main__":
    main()
