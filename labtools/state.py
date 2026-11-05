"""Tracks lab progress in a JSON file shared by the scorer UI and the lab commands.

The file looks like {"started": true, "step": 1, "checks": {"0": 3}, "hints": {"0": 1}, "passed": {"0": true},
"entered": {"0": 1730000000.0}, "captured": {"orders": 3}}.
Counters, pass marks and the time a step was first entered are keyed by the step they happened on.
Values captured by setup commands live in a second file, because the step file is wiped each time the app starts
and setup only runs once.
"""
import fcntl
import json
import os
import time
from contextlib import contextmanager
from pathlib import Path

LAB_HOME = Path(os.environ.get("LAB_HOME", Path.home() / "lab")).resolve()
STEP_FILE = Path(os.environ.get("LAB_STEP_FILE", LAB_HOME / ".lab_step"))
CWD_FILE = LAB_HOME / ".student_cwd"
NOT_STARTED = "Type `start` to begin the lab."


@contextmanager
def _locked():
    """Hold an exclusive lock for one read, change and save of the state files.

    The app and the lab commands write the same files from different processes, so without
    this one can overwrite the other's update. The lock is taken on the folder itself, which
    anyone who can read it can lock, so it works whichever account created the step file.
    """
    fd = os.open(STEP_FILE.parent, os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


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


def require_started(console) -> bool:
    """Print the not started message and return False when the student has not started the lab."""
    if is_started():
        return True
    console.print(NOT_STARTED)
    return False


def start() -> None:
    with _locked():
        data = read_state()
        data["started"] = True
        data.setdefault("entered", {}).setdefault("0", time.time())
        _save(data)


def write_step(step: int) -> None:
    with _locked():
        data = read_state()
        data["step"] = step
        # Only the first visit counts, so going back never relocks a hint that timed out
        data.setdefault("entered", {}).setdefault(str(step), time.time())
        _save(data)


def read_step_seconds() -> float:
    """Return the seconds since the student first entered the current step, 0 if unknown."""
    data = read_state()
    entered = data.get("entered", {}).get(str(data.get("step", 0)))
    return max(0.0, time.time() - entered) if entered else 0.0


def record_pass(step: int) -> None:
    """Mark a step as passed. Going back and passing again changes nothing."""
    with _locked():
        data = read_state()
        data.setdefault("passed", {})[str(step)] = True
        _save(data)


def _bump(counter: str) -> int:
    with _locked():
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
    with _locked():
        data = read_state()
        data["help"] = requested
        _save(data)


def read_student() -> dict:
    """Return the name and editor the student gave on the start screen, empty if not given."""
    student = read_state().get("student")
    return student if isinstance(student, dict) else {}


def set_student(name: str, editor: str) -> None:
    with _locked():
        data = read_state()
        data["student"] = {"name": name, "editor": editor}
        _save(data)


def _setup_captures_file() -> Path:
    return STEP_FILE.with_name(".lab_setup_captures")


def read_captured() -> dict:
    """Return every captured value. Values captured on a step override those from setup."""
    from_steps = read_state().get("captured", {})
    return {**read_captured_setup(), **(from_steps if isinstance(from_steps, dict) else {})}


def save_captured(values: dict, setup: bool = False) -> None:
    """Remember captured values for later commands, instructions and assertions."""
    if setup:
        path = _setup_captures_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        with _locked():
            path.write_text(json.dumps({**read_captured_setup(), **values}))
        return
    with _locked():
        data = read_state()
        data.setdefault("captured", {}).update(values)
        _save(data)


def read_captured_setup() -> dict:
    try:
        data = json.loads(_setup_captures_file().read_text())
    except (FileNotFoundError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}
