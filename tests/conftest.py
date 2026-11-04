import pytest

from labtools import check, state


@pytest.fixture(autouse=True)
def step_file(tmp_path, monkeypatch):
    """Point every test at its own step file so nothing touches /tmp/lab_step."""
    path = tmp_path / "lab_step"
    monkeypatch.setattr(state, "STEP_FILE", path)
    return path


@pytest.fixture(autouse=True)
def started(step_file):
    """Most tests run a lab that the student has already started."""
    state.start()


@pytest.fixture(autouse=True)
def lab_home(tmp_path, monkeypatch):
    """Run checks in a throwaway lab folder."""
    home = tmp_path / "lab"
    home.mkdir()
    monkeypatch.setattr(check, "LAB_HOME", home)
    return home


@pytest.fixture
def lab_file(tmp_path, monkeypatch):
    """Write a lab definition to disk and make labtools load it."""

    def write(text: str):
        path = tmp_path / "lab.yml"
        path.write_text(text)
        monkeypatch.setenv("LAB_FILE", str(path))
        return path

    return write
