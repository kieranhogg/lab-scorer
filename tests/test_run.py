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
            assert "Step 1: One" in app.query_one("#step-heading", Markdown).source
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


HINT_LAB = """
title: Test lab
steps:
  - id: one
    title: One
    instructions: first
    hints:
      - {id: free, text: "always there"}
      - {id: timed, text: "after a wait", reveal_after: 2s}
      - {id: tries, text: "after a try", after_failed_attempts: 1}
      - {id: asked, text: "when asked", reveal: on_request}
  - {id: two, title: Two, instructions: second}
"""


def hint_texts(app):
    return [widget.source for widget in app.query(".hint")]


def test_hints_sit_between_the_title_and_the_instructions(lab_file):
    lab_file(HINT_LAB)
    import run

    async def scenario():
        app = run.Lab()
        async with app.run_test() as pilot:
            start()
            await pilot.pause(1.5)
            order = [child.id for child in app.query_one("#instructions-box").children if child.id]
            assert order.index("step-heading") < order.index("hints") < order.index("instructions")
            hints = app.query_one("#hints", Collapsible)
            assert hints.display
            assert hints.collapsed
            assert "(1)" in hints.title
            assert len(hint_texts(app)) == 1
            assert "always there" in hint_texts(app)[0]
            assert "NEW" not in hint_texts(app)[0]

    asyncio.run(scenario())


def test_hints_are_not_announced_while_a_step_is_loading(lab_file):
    lab_file(HINT_LAB)
    import run

    async def scenario():
        app = run.Lab()
        async with app.run_test() as pilot:
            start()
            await pilot.pause(1.5)
            # A step change clears hints_step until reset_hints has loaded the new step
            app.hints_step = None
            app.shown_hints = set()
            await app.update_hints()
            assert app.shown_hints == set()
            assert not list(app.query(".hint.new"))

    asyncio.run(scenario())


def test_timed_hint_appears_with_a_highlight_and_a_toast(lab_file):
    lab_file(HINT_LAB)
    import run

    async def scenario():
        app = run.Lab()
        async with app.run_test() as pilot:
            start()
            await pilot.pause(1.5)
            assert len(hint_texts(app)) == 1
            await pilot.pause(2.5)
            hints = app.query_one("#hints", Collapsible)
            assert len(hint_texts(app)) == 2
            assert "(2)" in hints.title
            assert not hints.collapsed
            new = list(app.query(".hint.new"))
            assert len(new) == 1
            assert "NEW" in new[0].source
            assert "after a wait" in new[0].source
            assert any("new hint" in notification.message for notification in app._notifications)

    asyncio.run(scenario())


def test_new_highlight_fades_after_a_while(lab_file, monkeypatch):
    lab_file(HINT_LAB)
    import run

    monkeypatch.setattr(run.Lab, "HINT_HIGHLIGHT", 0.4)

    async def scenario():
        app = run.Lab()
        async with app.run_test() as pilot:
            start()
            await pilot.pause(3.6)
            assert len(hint_texts(app)) == 2
            assert not list(app.query(".hint.new"))
            assert all("NEW" not in text for text in hint_texts(app))

    asyncio.run(scenario())


def test_attempt_and_requested_hints_unlock_when_earned(lab_file):
    from labtools.state import record_check, record_hint

    lab_file(HINT_LAB)
    import run

    async def scenario():
        app = run.Lab()
        async with app.run_test() as pilot:
            start()
            await pilot.pause(1.5)
            assert len(hint_texts(app)) == 1
            record_check()
            await pilot.pause(1.5)
            assert any("after a try" in text for text in hint_texts(app))
            assert not any("when asked" in text for text in hint_texts(app))
            record_hint()
            await pilot.pause(1.5)
            assert any("when asked" in text for text in hint_texts(app))

    asyncio.run(scenario())


def test_step_without_hints_has_no_toggle(lab_file):
    lab_file(LAB)
    import run

    async def scenario():
        app = run.Lab()
        async with app.run_test() as pilot:
            start()
            await pilot.pause(1.5)
            assert not app.query_one("#hints").display

    asyncio.run(scenario())


def test_hints_reset_when_the_step_changes(lab_file):
    lab_file(HINT_LAB)
    import run

    async def scenario():
        app = run.Lab()
        async with app.run_test() as pilot:
            start()
            await pilot.pause(1.5)
            assert app.query_one("#hints").display
            write_step(1)
            await pilot.pause(1.5)
            assert not app.query_one("#hints").display
            assert not hint_texts(app)

    asyncio.run(scenario())


CODE_HINT_LAB = """
title: Test lab
steps:
  - id: one
    title: One
    instructions: first
    hints:
      - id: code
        text: |
          Try this:

          ```python
          def test_sky():
              assert 1 == 1
          ```
"""


def test_expanded_hints_take_only_the_space_they_need(lab_file):
    lab_file(CODE_HINT_LAB)
    import run

    async def scenario():
        app = run.Lab()
        async with app.run_test(size=(120, 50)) as pilot:
            start()
            await pilot.pause(1.5)
            app.query_one("#hints", Collapsible).collapsed = False
            await pilot.pause(0.5)
            hint = app.query_one(".hint")
            assert app.query_one("#hint-list").size.height <= hint.size.height + 1
            assert hint.size.height < 15

    asyncio.run(scenario())
