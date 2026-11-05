#!/usr/bin/env python3
from rich.console import Console

from labtools.state import read_step
from labtools.task import enter_step

console = Console()

def main() -> None:
    step = read_step()
    if step <= 0:
        console.print("Nothing to go back to, you're at the start!")
        return
    enter_step(step - 1)


if __name__ == "__main__":
    main()
