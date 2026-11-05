import logging
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

import yaml

from labtools.command import extract_values, run_command, shell_refs
from labtools.state import LAB_HOME, read_passed, save_captured, write_step

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


VAR_REF = re.compile(r"\$\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def apply_vars(node, variables: dict):
    """Replace ${name} with the lab's vars everywhere. Other ${...} text is left for later."""
    if isinstance(node, str):
        def value(match):
            if match[1] not in variables:
                return match[0]
            item = variables[match[1]]
            return str(item).lower() if isinstance(item, bool) else str(item)
        return VAR_REF.sub(value, node)
    if isinstance(node, list):
        return [apply_vars(item, variables) for item in node]
    if isinstance(node, dict):
        return {key: apply_vars(item, variables) for key, item in node.items()}
    return node


def open_lab_file():
    """Load the lab definition, from LAB_FILE if set (used by tests and local runs).

    Raises FileNotFoundError with a hint when the file is missing, so a misconfigured VM
    fails loudly instead of showing the student an empty lab.
    """
    path = lab_path()
    try:
        with open(path) as lab_file:
            lab = yaml.safe_load(lab_file)
    except FileNotFoundError:
        raise FileNotFoundError(f"Lab file {path} not found. Set LAB_FILE to the lab definition.") from None
    if isinstance(lab, dict) and isinstance(lab.get("vars"), dict):
        lab = {key: value if key == "vars" else apply_vars(value, lab["vars"]) for key, value in lab.items()}
    return lab


def content_text(value) -> str:
    """Return inline text, or the Markdown file named by {file: path} next to the lab file."""
    if isinstance(value, dict):
        return (lab_path().parent / value["file"]).read_text()
    return value or ""


def setup_command(entry: dict) -> str | None:
    """Return the shell command for a setup entry: bash on its script, or its run text. None when it has neither."""
    if script := entry.get("script"):
        return f"bash {shlex.quote(str(find_script(script)))}"
    if run := entry.get("run"):
        return shell_refs(run)
    return None


def setup_lab():
    """Run each setup script once, skipping if a previous run completed.

    Scripts must be safe to run twice, since the Docker build and the app start both run them.
    Every entry runs even if an earlier one fails. The first failure is raised afterwards with no marker
    written, so the lab never starts half set up and the next start tries again.
    """
    if SETUP_MARKER.exists():
        return
    logger.info("Setting up lab...")
    LAB_HOME.mkdir(parents=True, exist_ok=True)
    failures = []
    for entry in open_lab_file().get("setup") or []:
        if command := setup_command(entry):
            logger.info(f"Running {entry.get('script') or entry['run']}")
            try:
                result = run_command(entry, command, LAB_HOME, default_timeout=None)
                sys.stdout.write(result.stdout)
                sys.stderr.write(result.stderr)
                if result.returncode != 0:
                    raise subprocess.CalledProcessError(result.returncode, command, result.stdout, result.stderr)
                if entry.get("capture"):
                    save_captured(extract_values(entry["capture"], result, LAB_HOME), setup=True)
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
                logger.error(f"Setup entry failed: {error}")
                failures.append(error)
    if failures:
        raise failures[0]
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

def get_progression() -> str:
    """Return linear (a step unlocks when the one before is passed) or free."""
    return open_lab_file().get("progression", "linear")


def unmet_requirements(step: int) -> list[str]:
    """Return the ids of steps the student must pass before entering this step."""
    steps = get_lab()
    if not 0 <= step < len(steps):
        return []
    ids = [other.get("id") for other in steps]
    passed = read_passed()
    return [wanted for wanted in steps[step].get("requires") or [] if wanted in ids and ids.index(wanted) not in passed]


def run_step_setup(step: int) -> None:
    """Run the setup commands of a step. A failing command is reported and the step carries on."""
    steps = get_lab()
    if not 0 <= step < len(steps):
        return
    for entry in steps[step].get("setup") or []:
        try:
            result = run_command(entry, setup_command(entry), LAB_HOME)
            if result.returncode != 0:
                raise OSError(result.stderr.strip() or f"exit code {result.returncode}")
            if entry.get("capture"):
                save_captured(extract_values(entry["capture"], result, LAB_HOME))
        except (OSError, ValueError, subprocess.TimeoutExpired) as error:
            print(f"Setup for this step failed: {error}", file=sys.stderr)


def enter_step(step: int) -> None:
    """Move to a step and run its setup commands."""
    write_step(step)
    run_step_setup(step)
