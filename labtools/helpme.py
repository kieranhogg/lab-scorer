#!/usr/bin/env python3
from rich.console import Console

from labtools.state import read_help, set_help

console = Console()


def main() -> None:
    if read_help():
        console.print("Your instructor has already been flagged, they will be with you shortly.")
        return
    set_help(True)
    console.print("Your instructor has been flagged and will be with you shortly.")


if __name__ == "__main__":
    main()
