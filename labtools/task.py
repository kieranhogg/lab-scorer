import logging
import os
import subprocess
from pathlib import Path

import yaml

from labtools.state import LAB_HOME

logger = logging.getLogger(__name__)

DEFAULT_LAB_FILE = "/opt/lab/lab.yml"
# Setup scripts missing next to the lab file are looked up here, which is the repo root.
LAB_DIR = Path(os.environ.get("LAB_DIR", Path(__file__).parent.parent))
SETUP_MARKER = LAB_HOME / ".setup-done"


def lab_path() -> Path:
    """Return the lab definition path, LAB_FILE if set."""
    return Path(os.environ.get("LAB_FILE", DEFAULT_LAB_FILE))


def find_script(script: str, base: Path | None = None) -> Path:
    """Find a setup script next to the lab file, falling back to LAB_DIR."""
    base = base or lab_path().parent
    beside_lab = base / script
    return beside_lab if beside_lab.exists() else LAB_DIR / script


def open_lab_file():
    """Load the lab definition, from LAB_FILE if set (used by tests and local runs).

    Raises FileNotFoundError with a hint when the file is missing, so a misconfigured VM
    fails loudly instead of showing the student an empty lab.
    """
    path = lab_path()
    try:
        with open(path) as lab_file:
            return yaml.safe_load(lab_file)
    except FileNotFoundError:
        raise FileNotFoundError(f"Lab file {path} not found. Set LAB_FILE to the lab definition.") from None


def setup_lab():
    """Run each setup script once, skipping if a previous run completed.

    Scripts must be safe to run twice, since the Docker build and the app start both run them.
    A failing script raises CalledProcessError so the lab never starts half set up.
    """
    if SETUP_MARKER.exists():
        return
    logger.info("Setting up lab...")
    LAB_HOME.mkdir(parents=True, exist_ok=True)
    for entry in open_lab_file().get("setup") or []:
        if script := entry.get("run"):
            logger.info(f"Running {script}")
            subprocess.run(
                ["bash", str(find_script(script))],
                cwd=entry.get("cwd", LAB_HOME),
                env={**os.environ, "LAB_HOME": str(LAB_HOME)},
                check=True,
            )
    SETUP_MARKER.touch()


def get_lab():
    return open_lab_file().get("steps", [])

def get_lab_user() -> str | None:
    """Return the account the terminal should run as, or None to stay as the current user."""
    return open_lab_file().get("user")

def get_checks():
    """Return the list of checks for each step, None where a step has none."""
    return [step.get("checks") for step in get_lab()]


def get_hints(step: int) -> list[dict]:
    """Return the hints for one step index, or an empty list if it has none."""
    steps = get_lab()
    if not 0 <= step < len(steps):
        return []
    return steps[step].get("hints") or []