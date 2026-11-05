"""Terminal widgets for the lab app.

This wraps up the textual-related code needed in run.py, interacting with the terminal
via send_text and screen_text.
"""
import textual.app
from rich.style import Style
from textual import events
from textual.design import ColorSystem

# Compatibility shim, keep it before the textual_terminal imports below
# This fixes a bug in textual-terminal not keeping up with textual code changes.
if not hasattr(textual.app, "DEFAULT_COLORS"):
    fallback_colors = {
        "dark": ColorSystem(primary="#004578", background="#121212", surface="#1e1e1e", dark=True),
        "light": ColorSystem(primary="#004578", background="#efefef", surface="#f5f5f5"),
    }
    setattr(textual.app, "DEFAULT_COLORS", fallback_colors)  # noqa: B010 textual.app does not declare it, so plain assignment fails type checks

from textual_terminal import Terminal
from textual_terminal._terminal import TerminalDisplay


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

    def send_text(self, text: str) -> None:
        """Type text into the shell as if the student had."""
        self.send_queue.put_nowait(["stdin", text])

    def screen_text(self) -> str:
        """Return the visible terminal contents with trailing whitespace trimmed."""
        return "\n".join(line.rstrip() for line in self._screen.display).rstrip()
