import asyncio
import base64
import pwd

import aiohttp
import os
import re
import shlex
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from urllib.parse import quote

from textual import log, events
from textual._path import CSSPathType
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.driver import Driver
from textual.widgets import Button, Collapsible, Footer, Header, Input, Label, Markdown, Select
import textual.app

from textual.design import ColorSystem

if not hasattr(textual.app, "DEFAULT_COLORS"):
    textual.app.DEFAULT_COLORS = {
        "dark": ColorSystem(primary="#004578", background="#121212", surface="#1e1e1e", dark=True),
        "light": ColorSystem(primary="#004578", background="#efefef", surface="#f5f5f5"),
    }

from rich.style import Style
from textual_terminal._terminal import TerminalDisplay



from textual_terminal import Terminal

from labtools.check import groups_pass_silently, step_groups
from labtools.command import fill_captured
from labtools.hint import available_indices
from labtools.lint import validate_lab
from labtools.score import compute_score
from labtools.state import (
    LAB_HOME as _LAB_HOME, STEP_FILE, is_started, read_checks, read_help, read_hints, read_step, read_step_seconds,
    read_student, set_help, set_student, start,
)
from labtools.task import (
    LAB_DIR, content_text, get_hints, get_lab, get_lab_user, lab_path, open_lab_file, run_step_setup, setup_lab,
)

HINTS_TITLE = "💡 Hints"
SHELL = os.environ.get("SHELL", "bash")
SCRIPT = "task.py"
# Editors offered on the start screen, as (label, value)
EDITORS = [("Terminal only", "terminal"), ("VS Code", "vscode")]
CODE_SNAP = "/snap/bin/code"
# Seconds to wait for the snap install before giving up
INSTALL_TIMEOUT = 600

class BlinkingTerminal(Terminal):
    cursor_on = True

    def on_mount(self) -> None:
        self.set_interval(0.5, self._blink)

    def _blink(self) -> None:
        self.cursor_on = not self.cursor_on
        self.refresh()

    def render(self):
        if self._display is None:
            return self._display
        lines = []
        for line in self._display.lines:
            copy = line.copy()
            # Drop the cursor span added by the base class, it loses to later styles
            copy.spans = [s for s in copy.spans if s.style != "reverse"]
            lines.append(copy)
        cursor = self._screen.cursor
        if self.has_focus and self.cursor_on and not cursor.hidden and 0 <= cursor.y < len(lines):
            # Added last so no earlier style can switch reverse off again
            lines[cursor.y].stylize(Style(reverse=True), cursor.x, cursor.x + 1)
        return TerminalDisplay(lines)

    def on_focus(self) -> None:
        self.cursor_on = True
        self.refresh()

    def on_blur(self) -> None:
        self.refresh()

class LabTerminal(BlinkingTerminal):
    """Terminal that always forwards control keys to the shell."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        extra = {
            "escape": "\x1b",
            "tab": "\t",
            "enter": "\r",
            "backspace": "\x7f",
            "up": "\x1b[A",
            "down": "\x1b[B",
            "right": "\x1b[C",
            "left": "\x1b[D",
            "home": "\x1b[1~",
            "end": "\x1b[4~",
        }
        # ctrl+a is 0x01 ... ctrl+z is 0x1a, ctrl+q stays with the app as quit
        for i, letter in enumerate("abcdefghijklmnopqrstuvwxyz", start=1):
            if letter != "q":
                extra[f"ctrl+{letter}"] = chr(i)
        self.ctrl_keys.update(extra)

    def char_rich_style(self, char):
        style = super().char_rich_style(char)
        if style is None:
            return style
        return style + Style(
            reverse=char.reverse,
            italic=char.italics,
            underline=char.underscore,
            strike=char.strikethrough,
            blink=char.blink,
        )

    async def on_paste(self, event: events.Paste) -> None:
        if self.emulator is not None:
            event.stop()
            await self.send_queue.put(["stdin", event.text])

class Lab(App):
    CSS = """
    Screen > Horizontal { height: 1fr; }
    #instructions-box { width: 1fr; border: round $accent; }
    #terminal { width: 1fr; border: round $secondary; }
    #welcome, #setup { height: auto; padding: 1 2; }
    #welcome .centered, #setup .centered { height: auto; width: 100%; align-horizontal: center; }
    #welcome Label, #setup Label { margin-top: 1; }
    #setup Input, #setup Select { width: 40; margin-top: 1; }
    /* The toggle only appears once the student is off the start page */
    #lab-instructions CollapsibleTitle { display: none; }
    #instructions-box.started #lab-instructions CollapsibleTitle { display: block; }
    #hints { margin: 1 0; }
    /* Vertical defaults to 1fr, which stretched the list to fill the pane */
    #hint-list { height: auto; }
    .hint { height: auto; border-left: thick $success; padding: 0 1; margin-bottom: 1; }
    /* A hint that has just unlocked stands out until its timer clears the class */
    .hint.new { border-left: thick $warning; background: $warning 15%; }
    """

    # Priority so quit still works while the terminal has focus
    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit", priority=True, ),
        Binding("ctrl+shift+c", "copy_terminal", "Copy terminal", priority=True),
        Binding("f2", "request_help", "Get help", priority=True),
    ]
    SCRUB = {"VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT", "PYTHONHOME", "PYTHONPATH", "PYTHONUSERBASE"}
    LAB_DIR = Path(os.environ.get("LAB_DIR", Path.home() / "Projects" / "lab-scorer")).resolve()
    LAB_HOME = _LAB_HOME
    SCRIPT = (LAB_DIR / "run.py").resolve()
    SHELL = os.environ.get("SHELL", "/bin/bash")
    current_step = 0
    started = False
    # Seconds between silent runs of the current step's checks
    WATCH_INTERVAL = 3.0
    ready_step = None
    watching = False
    # Seconds a freshly unlocked hint keeps its highlight
    HINT_HIGHLIGHT = 20.0
    # Seconds a new hint takes to fade in
    HINT_FADE = 1.5
    # (step, hint number) pairs already on screen, so only new ones are announced
    shown_hints: set[tuple[int, int]] = set()
    # Where progress reports go, the viewer is optional so failures are ignored
    VIEWER_URL = os.environ.get("LAB_VIEWER_URL", base64.b64decode(b'aHR0cHM6Ly9sYWJzLmtpZXJhbmhvZ2cuY29t').decode())
    STUDENT_NAME = os.environ.get("LAB_STUDENT_NAME", "")
    report_session = None

    def __init__(
        self,
        driver_class: type[Driver] | None = None,
        css_path: CSSPathType | None = None,
        watch_css: bool = False,
        ansi_color: bool | None = None,
    ):
        super().__init__(driver_class, css_path, watch_css, ansi_color)
        log("Getting lab...")
        self.lab = open_lab_file()
        if problems := validate_lab(self.lab):
            sys.exit("Lab file problems:\n" + "\n".join(problems))
        self.steps = get_lab()
        self.instance_id = uuid.uuid4().hex

    def get_lab_instructions(self):
        return f"{self.lab.get("lab_instructions")}\n" if self.lab.get("lab_instructions") else ""


    def get_progress(self, step: int) -> str:
        return f"Progress: {step + 1}/{len(self.steps)}"

    def get_step_heading(self, step):
        title = self.steps[step].get("title")
        markdown = "# Tasks\n"
        markdown += f"## Step {step + 1}"
        markdown += f": {title}\n" if title is not None else "\n"
        return markdown

    def get_step_instructions(self, step):
        instructions = self.steps[step].get("instructions")
        links = self.steps[step].get("links", [])
        markdown = ""
        # Captured values only exist once earlier checks pass, so fill them in each time a step opens
        markdown += self.linkify_commands(fill_captured(content_text(instructions))) if instructions is not None else ""
        if links:
            markdown += "\n\n---\n\n"
            for link in links:
                markdown += link
        return markdown

    def clean_env(self):
        env = {k: v for k, v in os.environ.items() if k not in self.SCRUB}
        tool_bin = str(Path(sys.executable).parent)
        env["PATH"] = os.pathsep.join(
            p for p in env.get("PATH", "").split(os.pathsep) if p != tool_bin
        )
        return env

    def terminal_command(self, shell, cwd, script: str) -> str:
        # textual-terminal starts the child with only TERM, LC_ALL and HOME, so the
        # whole environment is passed on the command line, including the LAB_* settings
        # that the check, next, back and hint commands read.
        env = self.clean_env()
        env.update(
            TERM="linux",
            LC_ALL="C.UTF-8",
            LAB_HOME=str(self.LAB_HOME),
            LAB_DIR=str(LAB_DIR),
            LAB_FILE=str(lab_path()),
            LAB_STEP_FILE=str(STEP_FILE),
            PROMPT_COMMAND='pwd > "$LAB_HOME/.student_cwd"',
        )
        lab_user = get_lab_user()
        if lab_user:
            env["HOME"] = pwd.getpwnam(lab_user).pw_dir
        assignments = " ".join(
            f"{name}={shlex.quote(value)}"
            for name, value in env.items()
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name)
        )
        parts = [f"cd {shlex.quote(str(cwd))}"]
        if script is not None:
            parts.append(f"python3 -u {shlex.quote(str(script))}")

        inner = "; ".join(parts) + f"; exec {shlex.quote(shell)} -l "
        command = f"env -i {assignments} {shlex.quote(shell)} -c {shlex.quote(inner)}"
        if lab_user:
            command = f"/usr/sbin/runuser -u {shlex.quote(lab_user)} -- {command}"
        return command

    def linkify_commands(self, text: str) -> str:
        return re.sub(
            r"\{\%(.+?)\%\}",
            lambda m: f"[`⌨️ {m.group(1)}`](cmd:{quote(m.group(1))})",
            text,
        )

    def compose(self) -> ComposeResult:
        yield Header()
        yield Label(content="Not started", id="progress")
        with Horizontal():
            with VerticalScroll(id="instructions-box"):
                with Vertical(id="setup"):
                    with Horizontal(classes="centered"):
                        yield Label("Tell us a little about you before you begin")
                    with Horizontal(classes="centered"):
                        yield Input(placeholder="Your name", max_length=40, id="student-name")
                    with Horizontal(classes="centered"):
                        yield Label("Which editor would you like to use?")
                    with Horizontal(classes="centered"):
                        yield Select(EDITORS, value="terminal", allow_blank=False, id="editor")
                    with Horizontal(classes="centered"):
                        yield Button("Continue", id="continue", variant="primary")
                with Collapsible(id="lab-instructions", title="Lab Instructions", collapsed=False):
                    yield Markdown(self.get_lab_instructions(), open_links=False)
                with Vertical(id="welcome"):
                    with Horizontal(classes="centered"):
                        yield Button("Start lab", id="start", variant="success")
                    with Horizontal(classes="centered"):
                        yield Label("or type 'start' in the terminal to begin")
                heading = Markdown(self.get_step_heading(0), id="step-heading", open_links=False)
                heading.display = False
                yield heading
                # Hints sit between the step title and its instructions
                hints = Collapsible(Vertical(id="hint-list"), id="hints", title=HINTS_TITLE, collapsed=True)
                hints.display = False
                yield hints
                tasks = Markdown(self.get_step_instructions(0), id="instructions", open_links=False)
                tasks.display = False
                yield tasks
            with VerticalScroll(id="terminal-window"):
                yield LabTerminal(
                    # Run the script, then drop into a normal shell so the pane stays open
                    command=self.terminal_command(self.SHELL, self.LAB_HOME, None),
                    default_colors="system",
                    id="terminal",
                )
        # yield Button("Default")
        yield Footer()

    def on_mount(self) -> None:
        setup_lab()
        self.query_one("#instructions-box").border_title = self.lab.get("title", "Lab")

        # Clear any marker left over from a previous run
        STEP_FILE.unlink(missing_ok=True)

        # The terminal runs as the lab user, so it needs to own the lab directory
        if lab_user := get_lab_user():
            shutil.chown(self.LAB_HOME, lab_user, lab_user)
            for child in self.LAB_HOME.rglob("*"):
                shutil.chown(child, lab_user, lab_user)

        terminal = self.query_one("#terminal", LabTerminal)
        terminal.start()

        # The lab instructions and Start button only appear once the setup screen is done
        self.query_one("#lab-instructions").display = False
        self.query_one("#welcome").display = False
        self.query_one("#student-name", Input).focus()
        self.set_interval(1.0, self.check_progress)
        self.set_interval(1.0, self.update_hints)
        self.set_interval(self.WATCH_INTERVAL, self.send_progress)
        self.set_interval(self.WATCH_INTERVAL, self.watch_checks)

    def on_markdown_link_clicked(self, event: Markdown.LinkClicked) -> None:
        if not event.href.startswith("cmd:"):
            self.open_url(event.href)  # keep ordinary links working
            return
        command = event.href.removeprefix("cmd:")  # LinkClicked already URL-decodes href
        terminal = self.query_one("#terminal", LabTerminal)
        terminal.send_queue.put_nowait(["stdin", command])
        terminal.focus()

    async def check_progress(self) -> None:
        step = read_step()
        if not is_started() or (self.started and step == self.current_step):
            return
        if not 0 <= step <= len(self.steps):
            return
        if not self.started:
            self.started = True
            self.query_one("#welcome").display = False
            self.query_one("#step-heading").display = True
            self.query_one("#instructions").display = True
            self.query_one("#instructions-box").add_class("started")
        self.current_step = step
        if step == len(self.steps):
            self.ready_step = None
            await self.show_complete()
            return
        await self.query_one("#step-heading", Markdown).update(self.get_step_heading(step))
        await self.query_one("#instructions", Markdown).update(self.get_step_instructions(step))
        self.query_one("#lab-instructions", Collapsible).collapsed = True
        # Reset with the label so a watcher result that landed during the awaits above is not lost
        self.ready_step = None
        self.query_one("#progress", Label).update(self.get_progress(step))
        await self.reset_hints(step)
        self.query_one("#instructions-box", VerticalScroll).scroll_home(animate=False)

    async def send_progress(self) -> None:
        """Report this instance to the viewer without ever letting a failure reach the student."""
        if not self.VIEWER_URL:
            return
        if self.report_session is None:
            self.report_session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=2))
        total = len(self.steps)
        payload = {
            "instance_id": self.instance_id,
            "name": read_student().get("name") or self.STUDENT_NAME or self.instance_id[:6],
            "module": self.lab.get("module"),
            "unit": self.lab.get("unit"),
            "step": min(self.current_step + 1, total) if self.started else 0,
            "total_steps": total,
            "started": self.started,
            "finished": self.started and self.current_step >= total,
            "help": read_help(),
            "screen": self.get_terminal_output(),
        }
        try:
            async with self.report_session.post(f"{self.VIEWER_URL}/api/report", json=payload) as resp:
                reply = await resp.json()
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
            return
        if reply.get("ack_help") and read_help():
            set_help(False)

    async def on_unmount(self) -> None:
        if self.report_session is not None:
            await self.report_session.close()

    async def watch_checks(self) -> None:
        """Tell the student once the current step's checks all pass, before they run check.

        The checks run silently in a thread, so they never touch the step file or the
        check counter. Watching stops for a step after the message, and starts again when the step changes.
        """
        step = read_step()
        if self.watching or self.ready_step == step or not is_started() or step >= len(self.steps):
            return
        groups = step_groups(step)
        if not groups:
            return
        self.watching = True
        try:
            passed = await asyncio.to_thread(groups_pass_silently, groups)
        finally:
            self.watching = False
        if passed and read_step() == step:
            self.ready_step = step
            self.query_one("#progress", Label).update(f"{self.get_progress(step)} · All checks pass, run `check`")
            self.notify("All checks pass. Run `check` to complete this step.", timeout=10)

    def hint_markdown(self, number: int, text: str, new: bool) -> str:
        badge = "  ✨ **NEW**" if new else ""
        return f"**Hint {number}**{badge}\n\n{self.linkify_commands(fill_captured(text))}"

    def available_hint_numbers(self, step: int) -> list[int]:
        """Hints the student can see now, as positions in the step's hint list."""
        return available_indices(get_hints(step), read_checks(), read_step_seconds(), read_hints() > 0)

    async def reset_hints(self, step: int) -> None:
        """Show the hints that are already unlocked when a step opens, without announcing them."""
        hints = get_hints(step)
        container = self.query_one("#hint-list", Vertical)
        await container.remove_children()
        numbers = self.available_hint_numbers(step)
        self.shown_hints = {(step, number) for number in numbers}
        await container.mount_all(
            Markdown(self.hint_markdown(number + 1, hints[number]["text"], new=False), classes="hint", open_links=False)
            for number in numbers
        )
        collapsible = self.query_one("#hints", Collapsible)
        collapsible.collapsed = True
        collapsible.title = f"{HINTS_TITLE} ({len(numbers)})"
        collapsible.display = bool(numbers)

    async def update_hints(self) -> None:
        """Reveal hints that unlock while the student works, with a fade in, a NEW badge and a toast."""
        step = self.current_step
        if not self.started or step >= len(self.steps):
            return
        hints = get_hints(step)
        numbers = self.available_hint_numbers(step)
        fresh = [number for number in numbers if (step, number) not in self.shown_hints]
        if not fresh:
            return
        container = self.query_one("#hint-list", Vertical)
        collapsible = self.query_one("#hints", Collapsible)
        for number in fresh:
            self.shown_hints.add((step, number))
            text = hints[number]["text"]
            widget = Markdown(self.hint_markdown(number + 1, text, new=True), classes="hint new", open_links=False)
            widget.styles.opacity = 0.0
            await container.mount(widget)
            widget.styles.animate("opacity", value=1.0, duration=self.HINT_FADE, easing="out_cubic")
            self.set_timer(self.HINT_HIGHLIGHT, self.clear_new_hint(widget, number + 1, text))
        collapsible.title = f"{HINTS_TITLE} ({len(numbers)})"
        collapsible.display = True
        # Open the toggle so the student sees it appear, they can close it again
        collapsible.collapsed = False
        self.notify(
            "A new hint has unlocked" if len(fresh) == 1 else f"{len(fresh)} new hints have unlocked",
            title="💡 Hint",
            timeout=8,
        )

    def clear_new_hint(self, widget: Markdown, number: int, text: str):
        """Return the timer callback that drops a hint's NEW highlight."""
        async def clear() -> None:
            if widget.is_mounted:
                widget.remove_class("new")
                await widget.update(self.hint_markdown(number, text, new=False))
        return clear

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "continue":
            self.finish_setup()
        elif event.button.id == "start":
            start()
            await asyncio.to_thread(run_step_setup, 0)
            await self.check_progress()
            self.query_one("#terminal", LabTerminal).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "student-name":
            self.finish_setup()

    def finish_setup(self) -> None:
        """Save the student's details and move from the setup screen to the lab instructions."""
        name = self.query_one("#student-name", Input).value.strip()
        if not name:
            self.notify("Enter your name to continue", severity="warning")
            self.query_one("#student-name", Input).focus()
            return
        editor = self.query_one("#editor", Select).value
        set_student(name, editor)
        self.query_one("#setup").display = False
        self.query_one("#lab-instructions").display = True
        self.query_one("#welcome").display = True
        self.query_one("#start", Button).focus()
        if editor == "vscode":
            self.run_worker(self.open_vscode(), exclusive=False)

    async def open_vscode(self) -> None:
        """Install VS Code with snap if needed, then open the lab folder in it."""
        failed = "VS Code could not be installed here, open your own editor on the lab folder instead"
        executable = shutil.which("code") or (CODE_SNAP if Path(CODE_SNAP).exists() else None)
        if executable is None:
            if not shutil.which("snap"):
                self.notify(failed, severity="warning")
                return
            self.notify("Installing VS Code, this can take a few minutes", timeout=10)
            try:
                proc = await asyncio.create_subprocess_exec(
                    "sudo", "-n", "snap", "install", "code", "--classic",
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                try:
                    await asyncio.wait_for(proc.wait(), timeout=INSTALL_TIMEOUT)
                except asyncio.TimeoutError:
                    proc.kill()
                    self.notify(failed, severity="warning")
                    return
            except OSError:
                self.notify(failed, severity="warning")
                return
            if proc.returncode != 0:
                self.notify(failed, severity="warning")
                return
            executable = shutil.which("code") or CODE_SNAP
        try:
            self.notify("Opening VS Code, hang on!", timeout=10)
            subprocess.Popen(
                [executable, str(self.LAB_HOME)],
                env=self.clean_env(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            self.notify("Could not open VS Code", severity="warning")

    def action_request_help(self) -> None:
        if not read_help():
            set_help(True)
        self.notify("Your instructor has been flagged and will be with you shortly.")

    async def show_complete(self) -> None:
        """Show the finish screen once the last step has been passed."""
        earned, total = compute_score(self.steps)
        text = f"# Lab complete\nAll steps are done. Run `back` to revisit a step.\n\n**Score: {earned}/{total}**"
        await self.query_one("#instructions", Markdown).update(text)
        self.query_one("#step-heading").display = False
        self.query_one("#hints").display = False
        self.query_one("#progress", Label).update("Progress: complete")
        self.query_one("#lab-instructions", Collapsible).collapsed = True
        self.query_one("#instructions-box", VerticalScroll).scroll_home(animate=False)

    def get_terminal_output(self):
        screen = self.query_one("#terminal", LabTerminal)._screen
        return "\n".join(line.rstrip() for line in screen.display).rstrip()

    def action_copy_terminal(self) -> None:
        screen = self.query_one("#terminal", LabTerminal)._screen
        text = "\n".join(line.rstrip() for line in screen.display).rstrip()
        self.copy_to_clipboard(self.get_terminal_output())
        self.notify("Terminal contents copied")

if __name__ == "__main__":
    Lab().run()