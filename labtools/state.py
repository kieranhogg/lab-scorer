"""Tracks lab progress in a JSON file shared by the scorer UI and the lab commands.

The file looks like {"started": true, "step": 1, "checks": {"0": 3}, "hints": {"0": 1}, "passed": {"0": true}}.
Counters and pass marks are keyed by the step they happened on.
"""
import json
import os
from pathlib import Path

LAB_HOME = Path(os.environ.get("LAB_HOME", Path.home() / "lab")).resolve()
STEP_FILE = Path(os.environ.get("LAB_STEP_FILE", LAB_HOME / ".lab_step"))
CWD_FILE = LAB_HOME / ".student_cwd"

def read_cwd() -> str:
    """Return the student's last prompt directory, or LAB_HOME before the first prompt."""
    try:
        return CWD_FILE.read_text().strip() or str(LAB_HOME)
    except FileNotFoundError:
        return str(LAB_HOME)

def read_state() -> dict:
    try:
        data = json.loads(STEP_FILE.read_text())
    except (FileNotFoundError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(data: dict) -> None:
    # Write then rename, so the scorer polling every second never reads half a file
    tmp = STEP_FILE.with_name(STEP_FILE.name + ".tmp")
    tmp.write_text(json.dumps(data))
    tmp.replace(STEP_FILE)


def read_step() -> int:
    return int(read_state().get("step", 0))

def _count(counter: str) -> int:
    data = read_state()
    return int(data.get(counter, {}).get(str(data.get("step", 0)), 0))


def read_checks() -> int:
    """Return how many times check ran on the current step."""
    return _count("checks")


def read_hints() -> int:
    """Return how many times hint ran on the current step."""
    return _count("hints")


def read_passed() -> set[int]:
    """Return the steps the student passed, by check or by next."""
    return {int(step) for step, passed in read_state().get("passed", {}).items() if passed}


def read_hint_counts() -> dict[int, int]:
    """Return how many times hint ran on each step."""
    return {int(step): int(count) for step, count in read_state().get("hints", {}).items()}


def is_started() -> bool:
    """Return whether the student has started the lab."""
    return bool(read_state().get("started"))


def start() -> None:
    data = read_state()
    data["started"] = True
    _save(data)


def write_step(step: int) -> None:
    data = read_state()
    data["step"] = step
    _save(data)


def record_pass(step: int) -> None:
    """Mark a step as passed. Going back and passing again changes nothing."""
    data = read_state()
    data.setdefault("passed", {})[str(step)] = True
    _save(data)


def _bump(counter: str) -> int:
    data = read_state()
    counts = data.setdefault(counter, {})
    key = str(data.get("step", 0))
    counts[key] = counts.get(key, 0) + 1
    _save(data)
    return counts[key]


def record_check() -> int:
    """Count one check attempt on the current step and return that step's total."""
    return _bump("checks")


def record_hint() -> int:
    """Count one hint request on the current step and return that step's total."""
    return _bump("hints")

def read_help() -> bool:
    """Return whether the student has asked for help and nobody has answered yet."""
    return bool(read_state().get("help"))


def set_help(requested: bool) -> None:
    """Raise or clear the help flag the viewer shows to the instructor."""
    data = read_state()
    data["help"] = requested
    _save(data)


def read_student() -> dict:
    """Return the name and editor the student gave on the start screen, empty if not given."""
    student = read_state().get("student")
    return student if isinstance(student, dict) else {}


def set_student(name: str, editor: str) -> None:
    data = read_state()
    data["student"] = {"name": name, "editor": editor}
    _save(data)
