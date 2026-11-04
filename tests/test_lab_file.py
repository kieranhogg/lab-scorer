"""Sanity checks on the shipped lab.yml, so authoring mistakes fail early."""
from pathlib import Path

import pytest

from labtools.lint import validate_lab
from labtools.task import open_lab_file

SHIPPED_LAB = Path(__file__).parent.parent / "lab.yml"


def test_shipped_lab_is_valid(monkeypatch):
    # The Docker image copies lab.yml to /opt/lab, so read it from the repo here
    monkeypatch.setenv("LAB_FILE", str(SHIPPED_LAB))
    assert validate_lab(open_lab_file(), SHIPPED_LAB.parent) == []


def test_missing_lab_file_names_the_path(monkeypatch, tmp_path):
    missing = tmp_path / "nope.yml"
    monkeypatch.setenv("LAB_FILE", str(missing))
    with pytest.raises(FileNotFoundError, match="nope.yml"):
        open_lab_file()
