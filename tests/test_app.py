import os
import tempfile
import unittest
from pathlib import Path

from tests import helpers  # noqa: F401
from yhelp_tui.app import App
from yhelp_tui.store import Store


class FakeTerm:
    fd = 0

    def __init__(self):
        self.out = []

    def write(self, s):
        self.out.append(s)

    def suspend(self):
        pass

    resume = suspend


def make(tmp=None):
    tmp = tmp or Path(tempfile.mkdtemp())
    app = App(Store(tmp), FakeTerm(), color_mode="truecolor")
    return app


def text(app, w=100, h=30):
    return "\n".join(app.draw(w, h).text_lines())


class AppTests(unittest.TestCase):
    def test_draw_all_sizes(self):
        app = make()
        for w, h in [(40, 10), (60, 16), (80, 24), (100, 30), (160, 50), (300, 80)]:
            lines = app.draw(w, h).text_lines()
            self.assertEqual(len(lines), h)
            self.assertTrue(all(len(x) == w for x in lines))
        self.assertIn("System Info", text(app))
        self.assertIn("T E R M I N A L", text(app, 110, 34))
        self.assertIn("Agrandissez", text(app, 40, 10))

    def test_navigation_search_favorite(self):
        app = make()
        app.handle_key("down")
        app.handle_key("f")
        self.assertTrue(app.store.commands[1].favorite)
        app.handle_key("/")
        for ch in "git":
            app.handle_key(ch)
        self.assertEqual(len(app.list_items()), 2)
        app.handle_key("esc")
        self.assertEqual(app.query, "")
        app.handle_key("?")
        self.assertIn("AIDE", text(app))
        app.handle_key("x")
        self.assertIsNone(app.modal)

    def test_sections_and_empty(self):
        app = make()
        app.handle_key("left")
        for _ in range(7):
            app.handle_key("down")
        self.assertEqual(app.current_section().id, "history")
        self.assertIn("Historique vide", text(app))

    def test_run_records_history(self):
        app = make()
        app.runner = lambda cmd: 0
        app.waiter = lambda: None
        app.handle_key("enter")
        self.assertEqual(len(app.store.history), 1)
        self.assertEqual(app.store.commands[0].use_count, 1)

    def test_dangerous_needs_confirmation(self):
        app = make()
        app.store.commands[1].dangerous = True
        calls = []
        app.runner = lambda cmd: calls.append(cmd) or 0
        app.waiter = lambda: None
        app.handle_key("down")
        app.handle_key("enter")
        self.assertEqual(calls, [])
        self.assertIn("CONFIRMATION", text(app))
        app.handle_key("n")
        self.assertEqual(calls, [])
        app.handle_key("enter")
        app.handle_key("y")
        self.assertEqual(calls, ["df -h"])

    def test_shortcut_sets_cd_target(self):
        app = make()
        os.environ["HOME"] = tempfile.mkdtemp()
        app.handle_key("left")
        app.handle_key("down")
        app.handle_key("down")
        self.assertEqual(app.current_section().kind, "shortcuts")
        app.handle_key("right")
        app.handle_key("enter")
        self.assertEqual(app.cd_target, os.environ["HOME"])
        self.assertTrue(app.quit)

    def test_themes_and_256(self):
        app = make()
        app.store.config.update(accent_color="violet", theme="midnight", background="transparent")
        app2 = App(app.store, FakeTerm(), color_mode="256")
        self.assertIn("\x1b[0;", app2.draw(100, 30).render("256"))


if __name__ == "__main__":
    unittest.main()
