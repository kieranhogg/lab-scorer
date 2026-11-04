#!/usr/bin/env python3
from labtools.start import NOT_STARTED
from labtools.state import is_started, read_checks, read_step, record_hint
from labtools.task import get_hints

from rich.console import Console

console = Console()

def main() -> None:
    if not is_started():
        console.print(NOT_STARTED)
        return
    hints = get_hints(read_step())
    if not hints:
        console.print("No hints")
        return

    attempts = read_checks()
    available = [h for h in hints if attempts >= h.get("after_failed_attempts", 0)]
    if not available:
        console.print("Not yet!")
        return

    for hint in available:
        console.print(hint["text"])
    if len(available) < len(hints):
        console.print("More hints unlock after more check attempts.")
    record_hint()


if __name__ == "__main__":
    main()
