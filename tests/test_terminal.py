import asyncio

from textual.app import App

from terminal import LabTerminal


class TerminalApp(App):
    def compose(self):
        yield LabTerminal(command="sh", default_colors="system", id="terminal")

    def on_mount(self) -> None:
        self.query_one(LabTerminal).start()


def test_output_past_the_screen_can_be_scrolled_back_to():
    async def scenario():
        app = TerminalApp()
        async with app.run_test(size=(80, 20)) as pilot:
            terminal = app.query_one(LabTerminal)
            await pilot.pause(0.5)
            terminal.send_text("seq 1 100\r")
            await pilot.pause(0.8)
            assert terminal.show_vertical_scrollbar
            assert terminal.scroll_y == terminal.max_scroll_y
            terminal.scroll_to(y=0, animate=False, immediate=True)
            await pilot.pause(0.2)
            assert "seq 1 100" in str(terminal.render().lines[0])
            # Typing returns to the live screen
            await pilot.press("x")
            await pilot.pause(0.2)
            assert terminal.scroll_y == terminal.max_scroll_y

    asyncio.run(scenario())
