"""Run lab commands and turn their output into captured values.

Captured values are available to later commands as ${captured.name}. In a shell command
the reference becomes a shell variable, so a value is never parsed as extra commands.
Wrap it in double quotes like any shell variable, otherwise a value with spaces is split into words.
"""
import json
import os
import re
import subprocess
from pathlib import Path

from labtools import jsonpath
from labtools.state import read_captured, read_cwd

DEFAULT_TIMEOUT = 30
DURATION_SECONDS = {"s": 1, "m": 60, "h": 3600}
CAPTURE_NAME = r"[a-z][a-z0-9_]*"
CAPTURE_REF = re.compile(rf"\$\{{captured\.({CAPTURE_NAME})\}}")
RUNUSER = "/usr/sbin/runuser"
TRUE_WORDS = {"true", "1", "yes", "y"}
FALSE_WORDS = {"false", "0", "no", "n", ""}


def timeout_seconds(value, default: float | None = DEFAULT_TIMEOUT) -> float | None:
    """Turn 30, "30s", "5m" or "1h" into seconds. A missing value gives the default."""
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return value
    return int(value[:-1]) * DURATION_SECONDS[value[-1]]


def fill_captured(text: str) -> str:
    """Replace ${captured.name} with its value. Names that were never captured stay as written."""
    values = read_captured()
    return CAPTURE_REF.sub(lambda match: str(values.get(match[1], match[0])), text)


def shell_refs(command: str) -> str:
    """Point ${captured.name} at the LAB_CAPTURED_NAME variable that run_command exports."""
    return CAPTURE_REF.sub(lambda match: f"$LAB_CAPTURED_{match[1].upper()}", command)


def run_command(entry: dict, command: str, home: Path, default_timeout: float | None = DEFAULT_TIMEOUT) -> subprocess.CompletedProcess:
    """Run a command with the cwd, env, timeout and as_user of a check or setup entry.

    The target field names a machine for runners that have several. This runner has one, so it is ignored.
    Raises FileNotFoundError if the working directory is missing and TimeoutExpired on timeout.
    """
    env = {
        **os.environ,
        "LAB_HOME": str(home),
        "STUDENT_CWD": read_cwd(),
        **{f"LAB_CAPTURED_{name.upper()}": str(value) for name, value in read_captured().items()},
        **{name: fill_captured(value) for name, value in (entry.get("env") or {}).items()},
    }
    argv = ["bash", "-c", command]
    if entry.get("as_user"):
        argv = [RUNUSER, "-p", "-u", entry["as_user"], "--", *argv]
    return subprocess.run(
        argv,
        capture_output=True,
        text=True,
        errors="replace",
        stdin=subprocess.DEVNULL,
        cwd=home / entry.get("cwd", "."),
        env=env,
        timeout=timeout_seconds(entry.get("timeout"), default_timeout),
        check=False,
    )


def _convert(raw, kind: str):
    if kind == "string":
        return raw if isinstance(raw, str) else str(raw)
    if kind == "bool":
        if isinstance(raw, bool):
            return raw
        word = str(raw).strip().lower()
        if word not in TRUE_WORDS | FALSE_WORDS:
            raise ValueError(f"{raw!r} is not true or false")
        return word in TRUE_WORDS
    if isinstance(raw, bool):
        raise ValueError(f"{raw!r} is not a number")
    return int(raw) if kind == "int" else float(raw)


def extract_value(capture: dict, result: subprocess.CompletedProcess, home: Path):
    """Read one captured value from a finished command. Raises ValueError when it cannot be found."""
    source = capture["from"]
    if source == "exit_code":
        raw = str(result.returncode)
    elif source == "file":
        try:
            raw = (home / capture["file"]).read_text(errors="replace")
        except OSError as error:
            raise ValueError(f"cannot read {capture['file']}") from error
    else:
        raw = result.stdout if source == "stdout" else result.stderr
    if capture.get("trim", True):
        raw = raw.strip()
    if "json" in capture:
        found, raw = jsonpath.lookup(json.loads(raw), capture["json"])
        if not found:
            raise ValueError(f"{capture['json']} not found in the JSON")
    elif "regex" in capture:
        match = re.search(capture["regex"], raw)
        if not match:
            raise ValueError(f"{capture['regex']} did not match")
        raw = match[1] if match.re.groups else match[0]
    return _convert(raw, capture.get("type", "string"))


def extract_values(captures: dict, result: subprocess.CompletedProcess, home: Path) -> dict:
    """Read every capture of an entry, or raise ValueError naming the one that failed."""
    values = {}
    for name, capture in captures.items():
        try:
            values[name] = extract_value(capture, result, home)
        except ValueError as error:
            raise ValueError(f"Could not capture {name}: {error}") from error
    return values
