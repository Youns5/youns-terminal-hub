import json
import tempfile
import unittest
from pathlib import Path

from tests import helpers  # noqa: F401
from yhelp_tui import __version__
from yhelp_tui.ansi import Canvas, Style, detect_color_mode, rgb_to_256, str_width, truncate, wrap
from yhelp_tui.keys import parse_keys
from yhelp_tui.store import Store


class AnsiTests(unittest.TestCase):
    def test_width_and_truncate(self):
        self.assertEqual(str_width("abc"), 3)
        self.assertEqual(str_width("🐍a"), 3)
        self.assertEqual(truncate("abcdef", 4), "abc…")
        self.assertEqual(truncate("abc", 5), "abc")

    def test_wrap(self):
        self.assertEqual(wrap("un deux trois", 7), ["un deux", "trois"])
        self.assertTrue(all(str_width(x) <= 4 for x in wrap("abcdefghij", 4)))

    def test_color_modes(self):
        self.assertEqual(detect_color_mode({"COLORTERM": "truecolor"}), "truecolor")
        self.assertEqual(detect_color_mode({"NO_COLOR": "1"}), "none")
        self.assertEqual(detect_color_mode({"TERM": "xterm-256color"}), "256")
        self.assertEqual(rgb_to_256((0, 0, 0)), 16)

    def test_canvas(self):
        cv = Canvas(10, 2, Style())
        cv.put(0, 0, "hello")
        self.assertEqual(cv.text_lines()[0], "hello     ")
        self.assertIn("hello", cv.render("none"))


class KeyTests(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(parse_keys(b"\x1b[A\x1b[B\r")[0], ["up", "down", "enter"])
        self.assertEqual(parse_keys(b"\x1bOA")[0], ["up"])
        self.assertEqual(parse_keys(b"\x1b[5~")[0], ["pgup"])
        self.assertEqual(parse_keys(b"\x1b"), ([], b"\x1b"))
        self.assertEqual(parse_keys("é".encode())[0], ["é"])
        self.assertEqual(parse_keys(b"\x1b[1;5C")[0], ["right"])


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_seed_and_persist(self):
        s = Store(self.tmp)
        self.assertEqual(len(s.commands), 6)
        s.toggle_favorite(s.commands[0])
        s.record_run(s.commands[0], "fastfetch", 0)
        s2 = Store(self.tmp)
        self.assertTrue(s2.commands[0].favorite)
        self.assertEqual(s2.commands[0].use_count, 1)
        self.assertEqual(len(s2.history), 1)

    def test_corrupt_file_is_backed_up(self):
        Store(self.tmp)
        (self.tmp / "commands.json").write_text("{ pas du json")
        s = Store(self.tmp)
        self.assertEqual(len(s.commands), 6)
        self.assertTrue((self.tmp / "commands.json.bak").exists())
        self.assertTrue(s.warnings)

    def test_history_limit_and_tolerance(self):
        s = Store(self.tmp)
        s.config["history_limit"] = 3
        for i in range(5):
            s.record_run(None, f"echo {i}", 0)
        self.assertEqual(len(s.history), 3)
        (self.tmp / "commands.json").write_text(json.dumps([{"name": "x"}, {"command": "ls"}, {"command": "ls"}]))
        s = Store(self.tmp)
        self.assertEqual([c.id for c in s.commands], ["ls", "ls-2"])

    def test_version_matches(self):
        self.assertRegex(__version__, r"^\d+\.\d+\.\d+$")


if __name__ == "__main__":
    unittest.main()
