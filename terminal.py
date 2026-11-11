"""Terminal widgets for the lab app.

This wraps up the textual-related code needed in run.py, interacting with the terminal
via send_text and screen_text.
"""
import re
from collections import deque

import pyte
import textual.app
from pyte.screens import Margins
from rich.style import Style
from rich.text import Text
from textual import events
from textual.design import ColorSystem
from textual.geometry import Size

# Compatibility shim, keep it before the textual_terminal imports below
# This fixes a bug in textual-terminal not keeping up with textual code changes.
if not hasattr(textual.app, "DEFAULT_COLORS"):
    fallback_colors = {
        "dark": ColorSystem(primary="#004578", background="#121212", surface="#1e1e1e", dark=True),
        "light": ColorSystem(primary="#004578", background="#efefef", surface="#f5f5f5"),
    }
    setattr(textual.app, "DEFAULT_COLORS", fallback_colors)  # noqa: B010 textual.app does not declare it, so plain assignment fails type checks

from textual_terminal import Terminal
from textual_terminal._terminal import TerminalDisplay, TerminalPyteScreen

# Lines of output kept for scrolling back
SCROLLBACK_LINES = 2000

# Trailing punctuation is left off, it usually ends the sentence rather than the URL
URL_PATTERN = re.compile(r"https?://[^\s<>\"'`]*[^\s<>\"'`.,;:!?)\]}]")


class ScrollbackScreen(TerminalPyteScreen):
    """A pyte screen that keeps the lines scrolled off the top."""

    def __init__(self, *args, **kwargs):
        # Set first, the base class calls reset() while it initialises
        self.history: deque = deque(maxlen=SCROLLBACK_LINES)
        super().__init__(*args, **kwargs)

    def index(self) -> None:
        top, bottom = self.margins or Margins(0, self.lines - 1)
        # Only the whole screen scrolling counts, not a margin region inside it
        if self.cursor.y == bottom and top == 0:
            self.history.append(self.buffer[0])
        super().index()


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

    # The gutter keeps the width, and so the shell's column count, fixed
    DEFAULT_CSS = """
    LabTerminal {
        overflow-y: scroll;
        scrollbar-gutter: stable;
    }
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._screen = ScrollbackScreen(self.ncol, self.nrow)
        self.stream = pyte.Stream(self._screen)
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

    @property
    def is_scrollable(self) -> bool:
        # Textual treats a widget with no children as not scrollable, even with a scrollbar
        return True

    @property
    def allow_vertical_scroll(self) -> bool:
        # While the shell tracks the mouse the wheel belongs to it, not to the scrollback
        return super().allow_vertical_scroll and not self.mouse_tracking

    def _size_updated(self, size, virtual_size, container_size, layout=True):
        # Layout sizes a widget with no children to its own size, so add the history back on
        virtual_size = Size(virtual_size.width, virtual_size.height + len(self._screen.history))
        return super()._size_updated(size, virtual_size, container_size, layout)

    def refresh(self, *args, **kwargs):
        # The base class refreshes after every batch of output, so this keeps up with it
        self._sync_scrollback()
        return super().refresh(*args, **kwargs)

    def _sync_scrollback(self) -> None:
        """Grow the scrollable area with the history, following new output if at the end."""
        following = self.scroll_y >= self.max_scroll_y
        self.virtual_size = Size(self.size.width, len(self._screen.history) + self.size.height)
        if following:
            self.scroll_to(y=self.max_scroll_y, animate=False, immediate=True)

    def _history_text(self, row) -> Text:
        text = Text()
        for x in range(self._screen.columns):
            text.append(row[x].data, self.char_rich_style(row[x]))
        return text

    def render(self):
        display = super().render()
        history = self._screen.history
        # The history is followed by the live screen, and scroll_y is the first line shown
        first = round(self.scroll_y)
        if display is None:
            return display
        lines = [self._history_text(history[i]) for i in range(first, min(first + self.size.height, len(history)))]
        lines.extend(display.lines[: self.size.height - len(lines)])
        self._linkify(lines)
        return TerminalDisplay(lines)

    @staticmethod
    def _linkify(lines: list[Text]) -> None:
        """Make URLs clickable. Textual runs the @click action and underlines them on hover."""
        # pyte does not record soft wraps, so a line filled to the last column is taken to carry
        # on into the next one. Lines are padded to the full width, so that means no trailing space.
        joined = ""
        starts = []
        for line in lines:
            if joined and not joined[-1].isspace():
                starts.append(len(joined))
            else:
                joined += "\n"
                starts.append(len(joined))
            joined += line.plain
        for match in URL_PATTERN.finditer(joined):
            style = Style.from_meta({"@click": f"open_url({match.group()!r})"})
            # Style every line the URL passes through with the whole URL
            for line, start in zip(lines, starts):
                begin, end = max(match.start(), start), min(match.end(), start + len(line.plain))
                if begin < end:
                    line.stylize(style, begin - start, end - start)

    def action_open_url(self, url: str) -> None:
        # A program tracking the mouse, such as vim, gets the click instead
        if not self.mouse_tracking:
            self.app.open_url(url)

    async def on_key(self, event: events.Key) -> None:
        # Typing returns to the live screen, as it does in other terminals
        self.scroll_to(y=self.max_scroll_y, animate=False, immediate=True)

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
