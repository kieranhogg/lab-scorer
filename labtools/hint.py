#!/usr/bin/env python3
"""Hints and when they unlock.

A hint with no rule is always available. reveal_after unlocks it after that long on the step,
after_failed_attempts after that many `check` runs on the step, and reveal: on_request once
the student has asked with the `hint` command.
"""
from rich.console import Console

from labtools.command import timeout_seconds
from labtools.state import (
    read_checks,
    read_step,
    read_step_seconds,
    record_hint,
    require_started,
)
from labtools.task import get_hints

console = Console()


def is_available(hint: dict, attempts: int, seconds: float, requested: bool) -> bool:
    """Return whether a hint can be shown, given the check runs and time spent on the step."""
    if "after_failed_attempts" in hint:
        return attempts >= hint["after_failed_attempts"]
    if "reveal_after" in hint:
        return seconds >= timeout_seconds(hint["reveal_after"])
    if hint.get("reveal") == "on_request":
        return requested
    return True


def available_indices(hints: list[dict], attempts: int, seconds: float, requested: bool) -> list[int]:
    """Return the positions of the hints that can be shown, in lab file order."""
    return [number for number, hint in enumerate(hints) if is_available(hint, attempts, seconds, requested)]


def main() -> None:
    if not require_started(console):
        return
    hints = get_hints(read_step())
    if not hints:
        console.print("No hints")
        return

    # Running this command is the request, so on_request hints count as asked for
    shown = available_indices(hints, read_checks(), read_step_seconds(), requested=True)
    if not shown:
        console.print("Not yet!")
        return

    for number in shown:
        console.print(hints[number]["text"])
    if len(shown) < len(hints):
        console.print("More hints unlock after more check attempts or more time on this step.")
    record_hint()


if __name__ == "__main__":
    main()
