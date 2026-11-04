import asyncio

from textual.widgets import Button, Collapsible, Label, Markdown

from labtools.state import is_started, read_step, start, write_step

LAB = """
title: Test lab
steps:
  - {id: one, title: One, instructions: first}
  - {id: two, title: Two, instructions: second}
"""


def test_finishing_the_last_step_shows_completion(lab_file):
    lab_file(LAB)
    import run

    async def scenario():
        app = run.Lab()
        async with app.run_test() as pilot:
            start()
            write_step(2)
            await pilot.pause(1.5)
            assert "complete" in str(app.query_one("#progress", Label).render())
            assert "Lab complete" in app.query_one("#instructions", Markdown).source

    asyncio.run(scenario())


def test_shell_receives_lab_settings(lab_file, tmp_path):
    import shlex
    import subprocess

    lab_file(LAB)
    import run

    command = run.Lab().terminal_command("sh", tmp_path, None)
    result = subprocess.run(
        shlex.split(command),
        input="echo home=$LAB_HOME step=$LAB_STEP_FILE\n",
        capture_output=True,
        text=True,
    )
    assert f"home={run.Lab.LAB_HOME}" in result.stdout
    assert f"step={run.STEP_FILE}" in result.stdout


def test_lab_opens_on_the_welcome_screen(lab_file, step_file):
    lab_file(LAB)
    step_file.unlink(missing_ok=True)  # run.py binds STEP_FILE at import, so clear it here
    import run

    async def scenario():
        app = run.Lab()
        async with app.run_test() as pilot:
            await pilot.pause(1.2)
            assert app.query_one("#welcome").display
            assert not app.query_one("#instructions").display
            assert not app.query_one("#lab-instructions", Collapsible).collapsed
            assert not app.query_one("#lab-instructions CollapsibleTitle").display
            assert "Not started" in str(app.query_one("#progress", Label).render())

    asyncio.run(scenario())


def test_start_button_loads_the_first_task(lab_file):
    lab_file(LAB)
    import run

    async def scenario():
        app = run.Lab()
        async with app.run_test() as pilot:
            await pilot.pause(0.5)
            app.query_one("#start", Button).press()
            await pilot.pause(0.5)
            assert is_started()
            assert not app.query_one("#welcome").display
            assert app.query_one("#instructions").display
            assert "Step 1: One" in app.query_one("#instructions", Markdown).source
            assert app.query_one("#lab-instructions", Collapsible).collapsed
            assert app.query_one("#lab-instructions CollapsibleTitle").display

    asyncio.run(scenario())


def test_start_typed_in_the_terminal_loads_the_first_task(lab_file):
    lab_file(LAB)
    import run

    async def scenario():
        app = run.Lab()
        async with app.run_test() as pilot:
            await pilot.pause(0.5)
            start()
            await pilot.pause(1.5)
            assert app.query_one("#instructions").display
            assert "Progress: 1/2" in str(app.query_one("#progress", Label).render())

    asyncio.run(scenario())


CHECKED_LAB = """
title: Test lab
steps:
  - id: one
    title: One
    instructions: first
    checks:
      - id: ready
        description: "Ready"
        run: "{command}"
        expect: {{exit_code: 0}}
        feedback_on_fail: "Not ready"
  - {{id: two, title: Two, instructions: second}}
"""


def watch(lab_file, monkeypatch, command):
    """Start a lab whose first step runs command as its check, then return the progress label text."""
    lab_file(CHECKED_LAB.format(command=command))
    import run

    monkeypatch.setattr(run.Lab, "WATCH_INTERVAL", 0.2)
    result = {}

    async def scenario():
        app = run.Lab()
        async with app.run_test() as pilot:
            start()
            await pilot.pause(1.8)
            result["label"] = str(app.query_one("#progress", Label).render())
            result["step"] = read_step()

    asyncio.run(scenario())
    return result


def test_message_appears_when_all_checks_pass_before_check_runs(lab_file, monkeypatch):
    result = watch(lab_file, monkeypatch, "true")
    assert "All checks pass" in result["label"]
    assert result["step"] == 0


def test_no_message_while_a_check_fails(lab_file, monkeypatch):
    result = watch(lab_file, monkeypatch, "false")
    assert "All checks pass" not in result["label"]
