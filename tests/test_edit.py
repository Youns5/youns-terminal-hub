import tempfile
import unittest
from pathlib import Path

from tests import helpers  # noqa: F401
from tests.test_app import make, text
from yhelp_tui.store import Store


def type_text(app, s):
    for ch in s:
        app.handle_key(ch)


def go_to_navigation(app):
    app.handle_key("left")
    app.handle_key("down")
    app.handle_key("down")
    app.handle_key("right")
    assert app.current_section().kind == "shortcuts"


class StoreEditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.store = Store(self.tmp)

    def test_shortcut_crud_persists(self):
        sc = self.store.add_shortcut("", "~/Projets/site")
        self.assertEqual(sc.name, "site")
        self.store.update_shortcut(sc, "Mon site", "~/Web")
        self.assertEqual(Store(self.tmp).shortcuts[-1].path, "~/Web")
        self.store.delete_shortcut(sc)
        self.assertNotIn("Mon site", [s.name for s in Store(self.tmp).shortcuts])

    def test_unique_ids_and_move(self):
        a = self.store.add_shortcut("Home", "~")
        self.assertNotEqual(a.id, "home")
        self.assertTrue(self.store.move_shortcut(a, -1))
        self.assertFalse(self.store.move_shortcut(self.store.shortcuts[0], -1))
        self.assertEqual(Store(self.tmp).shortcuts[-2].id, a.id)

    def test_command_crud(self):
        c = self.store.add_command("", "docker ps -a", category="outils", dangerous=True)
        self.assertEqual(c.name, "docker")
        self.store.update_command(c, "Docker PS", "docker ps", params="-q")
        c2 = Store(self.tmp).command_by_id(c.id)
        self.assertEqual((c2.name, c2.command, c2.params, c2.dangerous), ("Docker PS", "docker ps", "-q", False))
        self.store.delete_command(c)
        self.assertIsNone(Store(self.tmp).command_by_id(c.id))


class AppEditTests(unittest.TestCase):
    def test_add_shortcut_from_ui(self):
        app = make()
        go_to_navigation(app)
        before = len(app.store.shortcuts)
        app.handle_key("a")
        self.assertIn("NOUVEAU RACCOURCI", text(app))
        app.handle_key("ctrl-u")
        type_text(app, "Mes docs")
        app.handle_key("tab")
        app.handle_key("ctrl-u")
        type_text(app, "/tmp")
        app.handle_key("enter")
        self.assertIsNone(app.modal)
        self.assertEqual(len(app.store.shortcuts), before + 1)
        self.assertEqual(app.current_item().obj.name, "Mes docs")
        self.assertEqual(Store(app.store.root).shortcuts[-1].path, "/tmp")

    def test_shortcut_path_required(self):
        app = make()
        go_to_navigation(app)
        app.handle_key("a")
        app.handle_key("tab")
        app.handle_key("ctrl-u")
        app.handle_key("enter")
        self.assertIsNotNone(app.modal)
        self.assertIn("obligatoire", text(app))
        app.handle_key("esc")
        self.assertIsNone(app.modal)

    def test_edit_and_delete_shortcut(self):
        app = make()
        go_to_navigation(app)
        app.handle_key("e")
        self.assertIn("MODIFIER LE RACCOURCI", text(app))
        app.handle_key("ctrl-u")
        type_text(app, "Maison")
        app.handle_key("enter")
        self.assertEqual(app.store.shortcuts[0].name, "Maison")
        n = len(app.store.shortcuts)
        app.handle_key("d")
        self.assertIn("SUPPRESSION", text(app))
        app.handle_key("n")
        self.assertEqual(len(app.store.shortcuts), n)
        app.handle_key("d")
        app.handle_key("y")
        self.assertEqual(len(app.store.shortcuts), n - 1)

    def test_reorder_shortcut(self):
        app = make()
        go_to_navigation(app)
        first, second = app.store.shortcuts[0], app.store.shortcuts[1]
        app.handle_key("J")
        self.assertEqual(app.store.shortcuts[:2], [second, first])
        self.assertIs(app.current_item().obj, first)
        app.handle_key("K")
        self.assertEqual(app.store.shortcuts[:2], [first, second])

    def test_delete_all_then_add_again(self):
        app = make()
        go_to_navigation(app)
        for _ in range(len(app.store.shortcuts)):
            app.handle_key("d")
            app.handle_key("y")
        self.assertEqual(app.store.shortcuts, [])
        self.assertEqual(app.current_section().kind, "shortcuts")  # la section reste accessible
        app.handle_key("a")
        type_text(app, "x")
        app.handle_key("enter")
        self.assertEqual(len(app.store.shortcuts), 1)

    def test_command_form_add_edit_delete(self):
        app = make()
        n = len(app.store.commands)
        app.handle_key("a")
        self.assertIn("NOUVELLE COMMANDE", text(app))
        app.handle_key("tab")
        type_text(app, "docker ps -a")
        app.handle_key("tab")
        app.handle_key("tab")
        app.handle_key("right")  # change de catégorie
        app.handle_key("tab")
        app.handle_key("tab")
        app.handle_key(" ")  # dangereuse
        app.handle_key("enter")
        self.assertEqual(len(app.store.commands), n + 1)
        cmd = app.store.commands[-1]
        self.assertEqual((cmd.name, cmd.command, cmd.dangerous), ("docker", "docker ps -a", True))
        app.handle_key("e")
        app.handle_key("tab")
        app.handle_key("ctrl-u")
        type_text(app, "docker ps")
        app.handle_key("enter")
        self.assertEqual(cmd.command, "docker ps")
        app.handle_key("d")
        app.handle_key("y")
        self.assertEqual(len(app.store.commands), n)

    def test_command_requires_command(self):
        app = make()
        app.handle_key("a")
        app.handle_key("enter")
        self.assertIsNotNone(app.modal)
        self.assertIn("obligatoire", text(app))

    def test_form_fits_small_terminal(self):
        app = make()
        app.handle_key("a")
        lines = app.draw(60, 16).text_lines()
        self.assertEqual(len(lines), 16)
        self.assertIn("NOUVELLE COMMANDE", "\n".join(lines))

    def test_history_is_read_only_for_edit(self):
        app = make()
        app.store.record_run(None, "echo hi", 0)
        app.handle_key("left")
        for _ in range(7):
            app.handle_key("down")
        app.handle_key("right")
        app.handle_key("e")
        app.handle_key("d")
        self.assertIsNone(app.modal)
        self.assertEqual(len(app.store.history), 1)


if __name__ == "__main__":
    unittest.main()
