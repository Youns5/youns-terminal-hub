"""Application TUI : état, entrées clavier et rendu."""

from __future__ import annotations

import getpass
import os
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import __version__
from .ansi import (
    Canvas,
    Style,
    detect_color_mode,
    gradient_text,
    mix,
    paint,
    str_width,
    truncate,
    wrap,
)
from .keys import KeyReader
from .store import Category, Command, HistoryEntry, Shortcut, Store
from .theme import Theme, build_theme

MIN_W, MIN_H = 60, 16
TOAST_SECONDS = 2.8

GLYPHS = {
    "all": "◈",
    "favorites": "★",
    "history": "↺",
    "navigation": "▸",
    "outils": "✦",
    "systeme": "◉",
    "git": "±",
    "python": "❖",
}
DEFAULT_GLYPH = "◆"

Seg = Tuple[str, Style]


@dataclass
class Section:
    id: str
    kind: str  # all | favorites | category | shortcuts | history
    label: str
    glyph: str
    count: int = 0


@dataclass
class Item:
    kind: str  # command | shortcut | history
    obj: Any


@dataclass
class Field:
    """Un champ de formulaire : texte, case à cocher (bool) ou choix dans une liste."""

    key: str
    label: str
    value: Any = ""
    kind: str = "text"  # text | bool | choice
    options: List[Tuple[str, str]] = field(default_factory=list)  # (valeur, libellé) pour `choice`
    placeholder: str = ""


@dataclass
class Modal:
    kind: str  # help | confirm | form
    title: str
    lines: List[List[Seg]]
    on_yes: Optional[Callable[[], None]] = None
    danger: bool = False
    fields: List[Field] = field(default_factory=list)
    idx: int = 0
    error: str = ""
    on_submit: Optional[Callable[[Dict[str, Any]], Optional[str]]] = None


FORM_LABEL_W, FORM_VALUE_W = 13, 34


def _window(offset: int, cursor: int, visible: int, total: int) -> int:
    """Décalage de défilement qui garde le curseur visible."""
    if visible <= 0 or total <= visible:
        return 0
    if cursor < offset:
        offset = cursor
    elif cursor >= offset + visible:
        offset = cursor - visible + 1
    return max(0, min(offset, total - visible))


def _run_shell(command: str) -> int:
    try:
        return subprocess.call(command, shell=True)
    except KeyboardInterrupt:
        return 130


def _wait_enter() -> None:
    try:
        sys.stdin.readline()
    except (EOFError, KeyboardInterrupt):
        pass


def _short_path(path: str) -> str:
    home = os.path.expanduser("~")
    if home and (path == home or path.startswith(home + os.sep)):
        return "~" + path[len(home):]
    return path


class App:
    def __init__(self, store: Store, term=None, color_mode: Optional[str] = None):
        self.store = store
        self.term = term
        self.mode = color_mode or detect_color_mode()
        self.theme: Theme = build_theme(store.config)
        self._build_styles()

        self.section_idx = 0
        self.cursor = 0
        self.list_off = 0
        self.side_off = 0
        self.page_size = 10
        self.focus = "list"  # list | side
        self.query = ""
        self.searching = False
        self.modal: Optional[Modal] = None
        self.toast: Optional[Tuple[str, str, float]] = None
        self.quit = False
        self.dirty = True
        self.cd_target: Optional[str] = None
        self.runner: Callable[[str], int] = _run_shell
        self.waiter: Callable[[], None] = _wait_enter
        self.user = self._whoami()
        if store.warnings:
            self.notify(store.warnings[0], "warn")

    # ------------------------------------------------------------------ #
    # Styles et utilitaires
    # ------------------------------------------------------------------ #
    def _build_styles(self) -> None:
        t = self.theme
        self.s_base = Style(fg=t.text, bg=t.bg)
        self.s_panel = Style(fg=t.text, bg=t.panel)
        self.s_text = Style(fg=t.text)
        self.s_bold = Style(fg=t.text, bold=True)
        self.s_muted = Style(fg=t.muted)
        self.s_faint = Style(fg=t.faint)
        self.s_acc = Style(fg=t.accent)
        self.s_acc_b = Style(fg=t.accent, bold=True)
        self.s_acc2 = Style(fg=t.accent2)
        self.s_acc2_b = Style(fg=t.accent2, bold=True)
        self.s_ok = Style(fg=t.success)
        self.s_warn = Style(fg=t.warning)
        self.s_err = Style(fg=t.danger)
        self.s_err_b = Style(fg=t.danger, bold=True)

    @staticmethod
    def _whoami() -> str:
        try:
            user = getpass.getuser()
        except Exception:  # noqa: BLE001 - environnements sans utilisateur
            user = "user"
        try:
            host = socket.gethostname().split(".")[0]
        except OSError:
            host = "host"
        return f"{user}@{host}"

    def notify(self, text: str, kind: str = "info") -> None:
        self.toast = (text, kind, time.monotonic() + TOAST_SECONDS)
        self.dirty = True

    # ------------------------------------------------------------------ #
    # Modèle : sections et éléments
    # ------------------------------------------------------------------ #
    def sections(self) -> List[Section]:
        st = self.store
        emoji = str(st.config.get("icons", "glyph")).lower() == "emoji"
        cmds = st.commands
        out = [
            Section("all", "all", "Toutes", GLYPHS["all"], len(cmds)),
            Section("favorites", "favorites", "Favoris", GLYPHS["favorites"], sum(c.favorite for c in cmds)),
        ]
        cats: List[Category] = list(st.categories)
        known = {c.id for c in cats}
        for c in cmds:  # catégories utilisées mais non déclarées
            if c.category and c.category not in known:
                cats.append(Category(c.category, c.category.capitalize()))
                known.add(c.category)
        if "navigation" not in known:
            cats.insert(0, Category("navigation", "Navigation", "📁"))
        for cat in cats:
            glyph = cat.icon if emoji else GLYPHS.get(cat.id, DEFAULT_GLYPH)
            if cat.id == "navigation":
                count = len(st.shortcuts) + sum(c.category == cat.id for c in cmds)
                out.append(Section(cat.id, "shortcuts", cat.name, glyph, count))
            else:
                out.append(Section(cat.id, "category", cat.name, glyph, sum(c.category == cat.id for c in cmds)))
        out.append(Section("history", "history", "Historique", GLYPHS["history"], len(st.history)))
        return out

    def current_section(self) -> Section:
        secs = self.sections()
        self.section_idx = max(0, min(self.section_idx, len(secs) - 1))
        return secs[self.section_idx]

    def _section_items(self, sec: Section) -> List[Item]:
        st = self.store
        if sec.kind == "all":
            return [Item("command", c) for c in st.commands]
        if sec.kind == "favorites":
            favs = sorted((c for c in st.commands if c.favorite), key=lambda c: -c.use_count)
            return [Item("command", c) for c in favs]
        if sec.kind == "category":
            return [Item("command", c) for c in st.commands if c.category == sec.id]
        if sec.kind == "shortcuts":
            items = [Item("shortcut", s) for s in st.shortcuts]
            items += [Item("command", c) for c in st.commands if c.category == sec.id]
            return items
        return [Item("history", h) for h in st.history]

    def _search(self, query: str) -> List[Item]:
        tokens = query.lower().split()
        found: List[Item] = []
        for c in self.store.commands:
            hay = f"{c.name} {c.command} {c.description} {self.store.category_name(c.category)}".lower()
            if all(tok in hay for tok in tokens):
                found.append(Item("command", c))
        found.sort(key=lambda i: not i.obj.favorite)
        for s in self.store.shortcuts:
            if all(tok in f"{s.name} {s.path}".lower() for tok in tokens):
                found.append(Item("shortcut", s))
        return found

    def list_items(self) -> List[Item]:
        if self.query.strip():
            return self._search(self.query.strip())
        return self._section_items(self.current_section())

    def current_item(self) -> Optional[Item]:
        items = self.list_items()
        if not items:
            return None
        self.cursor = max(0, min(self.cursor, len(items) - 1))
        return items[self.cursor]

    def _command_of(self, item: Optional[Item]) -> Optional[Command]:
        if item is None:
            return None
        if item.kind == "command":
            return item.obj
        if item.kind == "history" and item.obj.id:
            return self.store.command_by_id(item.obj.id)
        return None

    # ------------------------------------------------------------------ #
    # Clavier
    # ------------------------------------------------------------------ #
    def handle_key(self, key: str) -> None:
        self.dirty = True
        if self.modal:
            self._modal_key(key)
        elif self.searching:
            self._search_key(key)
        else:
            self._nav_key(key)

    def _modal_key(self, key: str) -> None:
        m = self.modal
        assert m is not None
        if m.kind == "help":
            self.modal = None
            return
        if m.kind == "form":
            self._form_key(m, key)
            return
        if key in ("y", "Y", "o", "O", "enter"):
            self.modal = None
            if m.on_yes:
                m.on_yes()
        elif key in ("n", "N", "esc", "q", "ctrl-c"):
            self.modal = None

    def _search_key(self, key: str) -> None:
        if key == "esc":
            self.query, self.searching, self.cursor = "", False, 0
        elif key == "enter":
            self.searching = False
        elif key == "backspace":
            self.query = self.query[:-1]
            self.cursor = 0
        elif key == "ctrl-u":
            self.query, self.cursor = "", 0
        elif key == "up":
            self.move(-1)
        elif key == "down":
            self.move(1)
        elif key == "ctrl-c":
            self.quit = True
        elif len(key) == 1 and key.isprintable():
            self.query += key
            self.cursor = 0

    def _nav_key(self, key: str) -> None:
        if key in ("q", "ctrl-c", "ctrl-d"):
            self.quit = True
        elif key == "esc":
            if self.query:
                self.query, self.cursor = "", 0
            elif self.focus == "list":
                self.focus = "side"
            else:
                self.quit = True
        elif key == "?":
            self.modal = self._help_modal()
        elif key == "/":
            self.searching, self.focus = True, "list"
        elif key in ("up", "k"):
            self.move(-1)
        elif key in ("down", "j"):
            self.move(1)
        elif key == "pgup":
            self.move(-self.page_size)
        elif key == "pgdn":
            self.move(self.page_size)
        elif key in ("home", "g"):
            self.move_to(0)
        elif key in ("end", "G"):
            self.move_to(10**9)
        elif key in ("tab", "shift-tab"):
            self.focus = "side" if self.focus == "list" else "list"
        elif key in ("right", "l"):
            self.focus = "list"
        elif key in ("left", "h"):
            self.focus = "side"
        elif key == "enter":
            if self.focus == "side":
                self.focus = "list"
            else:
                self.activate()
        elif key == "f":
            self.toggle_favorite()
        elif key == "a":
            self.add_entry()
        elif key == "A":
            self.add_entry(force_command=True)
        elif key == "e":
            self.edit_entry()
        elif key in ("d", "delete"):
            self.delete_entry()
        elif key in ("K", "J"):
            self.reorder_shortcut(-1 if key == "K" else 1)
        elif key == "r":
            self.store.reload()
            self.cursor = 0
            self.notify("Données rechargées", "ok")
        elif key == "x" and self.current_section().kind == "history" and not self.query:
            if self.store.history:
                self.modal = Modal(
                    "confirm",
                    "VIDER L'HISTORIQUE",
                    [[(f"Supprimer {len(self.store.history)} entrée(s) ?", self.s_text)],
                     [],
                     [("y", self.s_acc_b), (" confirmer    ", self.s_muted), ("n", self.s_acc_b), (" annuler", self.s_muted)]],
                    on_yes=self._clear_history,
                )

    def _clear_history(self) -> None:
        self.store.clear_history()
        self.cursor = 0
        self.notify("Historique vidé", "ok")

    def move(self, delta: int) -> None:
        if self.focus == "side" and not self.searching:
            n = len(self.sections())
            new = max(0, min(self.section_idx + delta, n - 1))
            if new != self.section_idx:
                self.section_idx, self.cursor, self.list_off = new, 0, 0
                self.query = ""
        else:
            n = len(self.list_items())
            self.cursor = max(0, min(self.cursor + delta, max(0, n - 1)))

    def move_to(self, index: int) -> None:
        if self.focus == "side" and not self.searching:
            self.section_idx = max(0, min(index, len(self.sections()) - 1))
            self.cursor, self.list_off, self.query = 0, 0, ""
        else:
            self.cursor = max(0, min(index, max(0, len(self.list_items()) - 1)))

    # ------------------------------------------------------------------ #
    # Actions
    # ------------------------------------------------------------------ #
    def toggle_favorite(self) -> None:
        cmd = self._command_of(self.current_item())
        if cmd is None:
            return
        on = self.store.toggle_favorite(cmd)
        self.notify(f"{'★ Ajouté aux favoris' if on else '☆ Retiré des favoris'} — {cmd.name}", "ok" if on else "info")
        self.cursor = max(0, min(self.cursor, len(self.list_items()) - 1))

    def activate(self) -> None:
        item = self.current_item()
        if item is None:
            return
        if item.kind == "shortcut":
            sc: Shortcut = item.obj
            if sc.exists():
                self.cd_target = sc.resolved()
                self.quit = True
            else:
                self.notify(f"Dossier introuvable : {sc.path}", "error")
        elif item.kind == "command":
            self.request_run(item.obj.command, item.obj, ask_params=True)
        else:
            entry: HistoryEntry = item.obj
            self.request_run(entry.command, self._command_of(item), ask_params=False)

    def request_run(self, text: str, command: Optional[Command], ask_params: bool) -> None:
        if command and command.dangerous and self.store.config.get("confirm_dangerous", True):
            lines: List[List[Seg]] = [[("Cette commande est marquée comme dangereuse :", self.s_warn)], []]
            for chunk in wrap(text, 52):
                lines.append([("❯ ", self.s_err_b), (chunk, self.s_bold)])
            lines += [[], [("y", self.s_acc_b), (" exécuter    ", self.s_muted), ("n", self.s_acc_b), (" annuler", self.s_muted)]]
            self.modal = Modal(
                "confirm", "▲ CONFIRMATION", lines,
                on_yes=lambda: self.execute(text, command, ask_params), danger=True,
            )
        else:
            self.execute(text, command, ask_params)

    def _echo(self, text: str, style: Style) -> None:
        self.term.write(paint(text, style, self.mode))

    def execute(self, text: str, command: Optional[Command], ask_params: bool = True) -> None:
        """Quitte l'écran plein écran, lance la commande, puis revient au hub."""
        full = text
        rc = 0
        self.term.suspend()
        try:
            self.term.write("\n")
            if ask_params and command and command.params:
                self._echo(f"  paramètres : {command.params}\n", self.s_muted)
                try:
                    self._echo("  arguments ❯ ", self.s_acc)
                    extra = sys.stdin.readline().strip()
                except (EOFError, KeyboardInterrupt):
                    extra = ""
                if extra:
                    full = f"{text} {extra}"
            self._echo("  ❯ ", self.s_acc_b)
            self._echo(full + "\n\n", self.s_bold)
            rc = self.runner(full)
            if rc == 0:
                self._echo("\n  ✔ terminé (code 0)\n", self.s_ok)
            else:
                self._echo(f"\n  ✖ code de sortie {rc}\n", self.s_err)
            self._echo("  ↵ Entrée pour revenir au hub ", self.s_muted)
            self.waiter()
        finally:
            self.term.resume()
        self.store.record_run(command, full, rc)
        self.dirty = True
        label = command.name if command else full
        self.notify(f"{'✔' if rc == 0 else '✖'} {label} — code {rc}", "ok" if rc == 0 else "error")

    # ------------------------------------------------------------------ #
    # Édition : ajouter / modifier / supprimer / réordonner
    # ------------------------------------------------------------------ #
    def _form_key(self, m: Modal, key: str) -> None:
        f = m.fields[m.idx]
        m.error = ""
        if key in ("esc", "ctrl-c"):
            self.modal = None
        elif key in ("tab", "down"):
            m.idx = (m.idx + 1) % len(m.fields)
        elif key in ("shift-tab", "up"):
            m.idx = (m.idx - 1) % len(m.fields)
        elif key == "enter":
            values = {x.key: x.value for x in m.fields}
            err = m.on_submit(values) if m.on_submit else None
            if err:
                m.error = err
            else:
                self.modal = None
        elif f.kind == "bool":
            if key in (" ", "left", "right", "x"):
                f.value = not f.value
        elif f.kind == "choice":
            if f.options and key in ("left", "right", " "):
                vals = [v for v, _ in f.options]
                i = vals.index(f.value) if f.value in vals else 0
                f.value = vals[(i + (-1 if key == "left" else 1)) % len(vals)]
        else:  # text
            if key == "backspace":
                f.value = str(f.value)[:-1]
            elif key == "ctrl-u":
                f.value = ""
            elif len(key) == 1 and key.isprintable():
                f.value = str(f.value) + key

    def _focus_item(self, obj: Any) -> None:
        """Replace le curseur sur `obj` après un ajout ou une modification."""
        for i, it in enumerate(self.list_items()):
            if it.obj is obj:
                self.cursor = i
                return
        self.cursor = max(0, min(self.cursor, len(self.list_items()) - 1))

    def add_entry(self, force_command: bool = False) -> None:
        sec = self.current_section()
        if sec.kind == "history":
            self.notify("Choisissez une autre section pour ajouter une entrée", "warn")
        elif sec.kind == "shortcuts" and not force_command and not self.query.strip():
            self._shortcut_form(None)
        else:
            self._command_form(None)

    def edit_entry(self) -> None:
        item = self.current_item()
        if item is None or item.kind == "history":
            return
        if item.kind == "shortcut":
            self._shortcut_form(item.obj)
        else:
            self._command_form(item.obj)

    def delete_entry(self) -> None:
        item = self.current_item()
        if item is None or item.kind == "history":
            return
        what = "ce raccourci" if item.kind == "shortcut" else "cette commande"
        label = item.obj.name
        lines: List[List[Seg]] = [
            [(f"Supprimer {what} ?", self.s_text)],
            [],
            [("❯ ", self.s_err_b), (truncate(label, 48), self.s_bold)],
            [],
            [("y", self.s_acc_b), (" supprimer    ", self.s_muted), ("n", self.s_acc_b), (" annuler", self.s_muted)],
        ]

        def do_delete() -> None:
            if item.kind == "shortcut":
                self.store.delete_shortcut(item.obj)
            else:
                self.store.delete_command(item.obj)
            self.cursor = max(0, min(self.cursor, len(self.list_items()) - 1))
            self.notify(f"Supprimé — {label}", "ok")

        self.modal = Modal("confirm", "▲ SUPPRESSION", lines, on_yes=do_delete, danger=True)

    def reorder_shortcut(self, delta: int) -> None:
        item = self.current_item()
        if item is None or item.kind != "shortcut" or self.query.strip():
            return
        if self.store.move_shortcut(item.obj, delta):
            self.cursor += delta  # les raccourcis sont en tête de la section Navigation

    def _shortcut_form(self, sc: Optional[Shortcut]) -> None:
        fields = [
            Field("name", "Nom", sc.name if sc else "", placeholder="(déduit du dossier)"),
            Field("path", "Dossier", sc.path if sc else self._cwd(), placeholder="~/Projets"),
        ]

        def submit(v: Dict[str, Any]) -> Optional[str]:
            path = str(v["path"]).strip()
            if not path:
                return "Le dossier est obligatoire"
            if sc is None:
                target = self.store.add_shortcut(str(v["name"]), path)
            else:
                self.store.update_shortcut(sc, str(v["name"]), path)
                target = sc
            self._focus_item(target)
            if not target.exists():
                self.notify(f"Enregistré, mais le dossier n'existe pas : {path}", "warn")
            else:
                self.notify(f"{'Raccourci modifié' if sc else 'Raccourci ajouté'} — {target.name}", "ok")
            return None

        title = "MODIFIER LE RACCOURCI" if sc else "NOUVEAU RACCOURCI"
        self.modal = Modal("form", title, [], fields=fields, on_submit=submit)

    def _command_form(self, cmd: Optional[Command]) -> None:
        cats = [(c.id, c.name) for c in self.store.categories]
        if cmd and cmd.category and cmd.category not in {i for i, _ in cats}:
            cats.append((cmd.category, cmd.category.capitalize()))
        sec = self.current_section()
        default_cat = cmd.category if cmd else (sec.id if sec.kind in ("category", "shortcuts") else (cats[0][0] if cats else ""))
        cats = cats or [("", "—")]
        fields = [
            Field("name", "Nom", cmd.name if cmd else "", placeholder="(déduit de la commande)"),
            Field("command", "Commande", cmd.command if cmd else "", placeholder="ex. docker ps -a"),
            Field("description", "Description", cmd.description if cmd else ""),
            Field("category", "Catégorie", default_cat, "choice", cats),
            Field("params", "Paramètres", cmd.params if cmd else "", placeholder="si rempli : demandés avant lancement"),
            Field("dangerous", "Dangereuse", cmd.dangerous if cmd else False, "bool"),
        ]

        def submit(v: Dict[str, Any]) -> Optional[str]:
            command = str(v["command"]).strip()
            if not command:
                return "La commande est obligatoire"
            kw = dict(description=str(v["description"]), category=str(v["category"]),
                      params=str(v["params"]), dangerous=bool(v["dangerous"]))
            if cmd is None:
                target = self.store.add_command(str(v["name"]), command, **kw)
            else:
                self.store.update_command(cmd, str(v["name"]), command, **kw)
                target = cmd
            self._focus_item(target)
            self.notify(f"{'Commande modifiée' if cmd else 'Commande ajoutée'} — {target.name}", "ok")
            return None

        title = "MODIFIER LA COMMANDE" if cmd else "NOUVELLE COMMANDE"
        self.modal = Modal("form", title, [], fields=fields, on_submit=submit)

    def _form_lines(self, m: Modal) -> List[List[Seg]]:
        lines: List[List[Seg]] = []
        for i, f in enumerate(m.fields):
            active = i == m.idx
            marker: Seg = ("▸ ", self.s_acc_b) if active else ("  ", self.s_faint)
            label: Seg = (f"{f.label:<{FORM_LABEL_W}}", self.s_acc_b if active else self.s_muted)
            if f.kind == "bool":
                text, style = ("[x] oui" if f.value else "[ ] non"), (self.s_warn if f.value else self.s_text)
            elif f.kind == "choice":
                names = dict(f.options)
                text, style = f"‹ {names.get(f.value, f.value or '—')} ›", self.s_acc2_b if active else self.s_text
            else:
                raw = str(f.value)
                if not raw and not active:
                    text, style = f.placeholder, self.s_faint
                else:
                    shown = raw + ("▏" if active else "")
                    if str_width(shown) > FORM_VALUE_W:  # on garde la fin : c'est là qu'on tape
                        shown = "…" + shown[-(FORM_VALUE_W - 1):]
                    text, style = shown, self.s_bold if active else self.s_text
                    if not raw and active and f.placeholder:
                        text, style = "▏" + truncate(f.placeholder, FORM_VALUE_W - 1), self.s_faint
            text = truncate(text, FORM_VALUE_W)
            pad = " " * max(0, FORM_VALUE_W - str_width(text))
            lines.append([marker, label, (text + pad, style)])
        lines.append([])
        if m.error:
            lines.append([("  ✖ " + m.error, self.s_err_b)])
        else:
            lines.append([("  Tab", self.s_acc_b), (" champ suivant   ", self.s_muted),
                          ("↵", self.s_acc_b), (" enregistrer   ", self.s_muted),
                          ("Échap", self.s_acc_b), (" annuler", self.s_muted)])
        return lines

    # ------------------------------------------------------------------ #
    # Boucle principale
    # ------------------------------------------------------------------ #
    def run(self) -> Optional[str]:
        term = self.term
        reader = KeyReader(term.fd)
        last_size: Optional[Tuple[int, int]] = None
        try:
            term.start()
            while not self.quit:
                size = term.size()
                if self.dirty or size != last_size:
                    canvas = self.draw(*size)
                    term.write("\x1b[?2026h" + canvas.render(self.mode) + "\x1b[?2026l")
                    last_size, self.dirty = size, False
                try:
                    key = reader.poll(0.1)
                except (EOFError, KeyboardInterrupt):
                    break
                if self.toast and time.monotonic() > self.toast[2]:
                    self.toast, self.dirty = None, True
                if key:
                    self.handle_key(key)
        finally:
            term.stop()
        return self.cd_target

    # ------------------------------------------------------------------ #
    # Rendu
    # ------------------------------------------------------------------ #
    def draw(self, W: int, H: int) -> Canvas:
        t = self.theme
        cv = Canvas(W, H, self.s_base)
        if W < MIN_W or H < MIN_H:
            msg = f"Agrandissez le terminal (min {MIN_W}×{MIN_H}, actuel {W}×{H})"
            cv.put(max(0, (W - str_width(msg)) // 2), H // 2, truncate(msg, W), self.s_acc)
            return cv

        full = self._use_full_header(W, H)
        hh = self._draw_header(cv, full)
        body_h = H - hh - 1
        side_w = 26 if W >= 100 else 22 if W >= 76 else 18
        main_x = 1 + side_w + 1
        main_w = W - main_x - 1
        det_h = 9 if body_h >= 26 else 7 if body_h >= 19 else 0
        list_h = body_h - det_h

        self._draw_sidebar(cv, 1, hh, side_w, body_h)
        self._draw_list(cv, main_x, hh, main_w, list_h)
        if det_h:
            self._draw_details(cv, main_x, hh + list_h, main_w, det_h)
        self._draw_footer(cv, H - 1)
        if self.modal:
            self._draw_modal(cv)
        return cv

    # -- en-tête ---------------------------------------------------------- #
    def _logo(self) -> List[str]:
        cfg = self.store.config
        if not cfg.get("show_logo", True) or str(cfg.get("logo_mode", "ascii")).lower() != "ascii":
            return []
        logo = cfg.get("ascii_logo") or []
        return [str(line).rstrip() for line in logo] if isinstance(logo, list) else []

    def _use_full_header(self, W: int, H: int) -> bool:
        logo = self._logo()
        return bool(logo) and H >= 30 and W >= max(str_width(x) for x in logo) + 4

    def _cwd(self) -> str:
        try:
            return _short_path(os.getcwd())
        except OSError:
            return "?"

    def _gradient_line(self, cv: Canvas, y: int) -> None:
        t = self.theme
        width = cv.w - 2
        for i in range(width):
            col = mix(t.accent, t.accent2, i / max(1, width - 1))
            cv.put(1 + i, y, "━", Style(fg=col))

    def _draw_header(self, cv: Canvas, full: bool) -> int:
        t = self.theme
        W = cv.w
        st = self.store
        n_fav = sum(c.favorite for c in st.commands)
        if full:
            logo = self._logo()
            lw = max(str_width(x) for x in logo)
            for y, line in enumerate(logo):
                for x, ch in enumerate(line):
                    if ch != " ":
                        col = mix(t.accent, t.accent2, 0.85 * x / max(1, lw) + 0.15 * y / max(1, len(logo)))
                        cv.put(2 + x, 1 + y, ch, Style(fg=col, bold=True))
            ix = 2 + lw + 4
            avail = W - 2 - ix
            if avail >= 24:
                title = "T E R M I N A L   H U B"
                x = ix
                for ch, col in gradient_text(title, t.accent, t.accent2):
                    x += cv.put(x, 1, ch, Style(fg=col, bold=True))
                cv.put(ix, 2, f"v{__version__}", self.s_acc)
                cv.put(ix + len(__version__) + 3, 2, "hub de commandes", self.s_muted, maxw=max(0, avail - len(__version__) - 3))
                cv.put(ix, 3, "─" * min(avail, 34), self.s_faint)
                cv.put(ix, 4, self.user, self.s_text, maxw=avail)
                cv.put(ix, 5, "⌂ " + self._cwd(), self.s_muted, maxw=avail)
                x = ix
                x += cv.put(x, 6, "● ", self.s_ok)
                x += cv.put(x, 6, f"{len(st.commands)} commandes", self.s_text)
                x += cv.put(x, 6, "   ★ ", self.s_warn)
                x += cv.put(x, 6, f"{n_fav}", self.s_text)
                x += cv.put(x, 6, "   ↺ ", self.s_acc2)
                cv.put(x, 6, f"{len(st.history)}", self.s_text, maxw=max(0, W - 1 - x))
            self._gradient_line(cv, 1 + len(logo))
            return len(logo) + 2
        # compact
        cv.put(1, 0, "▌", self.s_acc_b)
        x = 3
        for ch, col in gradient_text("YOUNS TERMINAL HUB", t.accent, t.accent2):
            x += cv.put(x, 0, ch, Style(fg=col, bold=True))
        x += cv.put(x + 1, 0, f"v{__version__}", self.s_faint) + 1
        right = f"{self.user}   ⌂ {self._cwd()}"
        room = W - 2 - x - 2
        if room > 8:
            right = truncate(right, room)
            cv.put(W - 1 - str_width(right), 0, right, self.s_muted)
        self._gradient_line(cv, 1)
        return 2

    # -- barre latérale -------------------------------------------------- #
    def _panel_border(self, focused: bool) -> Style:
        return Style(fg=self.theme.accent if focused else self.theme.border, bg=self.theme.panel)

    def _draw_sidebar(self, cv: Canvas, x: int, y: int, w: int, h: int) -> None:
        t = self.theme
        focused = self.focus == "side" and not self.searching
        border = self._panel_border(focused)
        cv.box(x, y, w, h, border, fill=self.s_panel, title="SECTIONS",
               title_style=border.but(bold=True, fg=t.accent if focused else t.muted))
        self.current_section()  # recale l'index de section si besoin
        secs = self.sections()
        rows: List[Optional[int]] = []  # None = séparateur
        for i, s in enumerate(secs):
            if s.kind == "history" and rows:
                rows.append(None)
            rows.append(i)
            if s.kind == "favorites":
                rows.append(None)
        visible = h - 2
        sel_row = rows.index(self.section_idx)
        self.side_off = _window(self.side_off, sel_row, visible, len(rows))
        inner_x, inner_w = x + 1, w - 2
        for r in range(visible):
            idx = self.side_off + r
            if idx >= len(rows):
                break
            yy = y + 1 + r
            si = rows[idx]
            if si is None:
                cv.put(inner_x + 1, yy, "─" * (inner_w - 2), self.s_faint)
                continue
            sec = secs[si]
            selected = si == self.section_idx and not self.query
            if selected:
                bg = t.sel_bg if focused else mix(t.panel or (10, 15, 27), t.accent, 0.07)
                cv.fill(inner_x, yy, inner_w, 1, Style(bg=bg))
                cv.put(inner_x, yy, "▌", self.s_acc_b if focused else self.s_acc2)
            gstyle = self.s_acc if selected else self.s_acc2
            cv.put(inner_x + 2, yy, sec.glyph, gstyle)
            count = str(sec.count)
            label_w = max(0, inner_w - 5 - len(count) - 1)
            cv.put(inner_x + 4, yy, truncate(sec.label, label_w), self.s_bold if selected else self.s_muted)
            cv.put(inner_x + inner_w - len(count) - 1, yy, count, self.s_muted if selected else self.s_faint)

    # -- liste ------------------------------------------------------------ #
    def _draw_list(self, cv: Canvas, x: int, y: int, w: int, h: int) -> None:
        t = self.theme
        focused = self.focus == "list" or self.searching
        border = self._panel_border(focused)
        items = self.list_items()
        sec = self.current_section()
        title = f"RÉSULTATS · {self.query.strip()}" if self.query.strip() else sec.label.upper()
        cv.box(
            x, y, w, h, border, fill=self.s_panel,
            title=title, title_style=border.but(bold=True, fg=t.accent if focused else t.muted),
            right_title=str(len(items)), right_style=Style(fg=t.accent2, bg=t.panel, bold=True),
        )
        inner_x, inner_w = x + 1, w - 2

        # barre de recherche
        sy = y + 1
        cv.put(inner_x + 1, sy, "/", self.s_acc_b if self.searching else self.s_acc2_b)
        if self.query or self.searching:
            shown = truncate(self.query, inner_w - 6)
            nx = inner_x + 3
            nx += cv.put(nx, sy, shown, self.s_bold)
            if self.searching:
                cv.put(nx, sy, "▏", self.s_acc_b)
        else:
            cv.put(inner_x + 3, sy, "Rechercher une commande…", self.s_faint)
        cv.put(x, y + 2, "├" + "─" * (w - 2) + "┤", border)

        top = y + 3
        visible = max(1, h - 4)
        self.page_size = visible
        if not items:
            self._draw_empty(cv, inner_x, top, inner_w)
            return
        self.cursor = max(0, min(self.cursor, len(items) - 1))
        self.list_off = _window(self.list_off, self.cursor, visible, len(items))

        cmd_items = [i.obj for i in items if i.kind == "command"]
        if cmd_items:
            name_w = min(24, max(8, max(str_width(c.name) for c in cmd_items)))
        else:
            name_w = 11 if items[0].kind == "history" else 14
        name_w = min(name_w, max(6, inner_w // 3))

        for r in range(visible):
            idx = self.list_off + r
            if idx >= len(items):
                break
            self._draw_row(cv, inner_x, top + r, inner_w, items[idx], idx == self.cursor, focused, name_w)

        if len(items) > visible:  # barre de défilement sur la bordure droite
            track = visible
            thumb = max(1, round(track * visible / len(items)))
            pos = round((track - thumb) * self.list_off / max(1, len(items) - visible))
            for k in range(thumb):
                cv.put(x + w - 1, top + pos + k, "┃", Style(fg=t.accent2, bg=t.panel))

    def _draw_empty(self, cv: Canvas, x: int, y: int, w: int) -> None:
        if self.query.strip():
            msg, hint = f"Aucun résultat pour « {self.query.strip()} »", "Échap pour effacer la recherche"
        else:
            sec = self.current_section()
            if sec.kind == "favorites":
                msg, hint = "Aucun favori pour l'instant", "Placez-vous sur une commande et appuyez sur f"
            elif sec.kind == "history":
                msg, hint = "Historique vide", "Les commandes lancées apparaîtront ici"
            else:
                msg, hint = "Rien à afficher", "Appuyez sur a pour ajouter une entrée"
        cv.put(x + 2, y + 1, truncate(msg, w - 4), self.s_muted)
        cv.put(x + 2, y + 2, truncate(hint, w - 4), self.s_faint)

    def _draw_row(self, cv: Canvas, x: int, y: int, w: int, item: Item, selected: bool, focused: bool, name_w: int) -> None:
        t = self.theme
        if selected:
            bg = t.sel_bg if focused else mix(t.panel or (10, 15, 27), t.accent, 0.07)
            cv.fill(x, y, w, 1, Style(bg=bg))
            cv.put(x, y, "▌", self.s_acc_b if focused else self.s_acc2)
        tx = x + 4
        name_style = self.s_bold if selected else self.s_text
        if item.kind == "command":
            c: Command = item.obj
            cv.put(x + 2, y, "★" if c.favorite else "·", self.s_warn if c.favorite else self.s_faint)
            right = ("▲ " if c.dangerous else "") + (f"×{c.use_count}" if c.use_count else "")
            right_w = str_width(right)
            cv.put(tx, y, truncate(c.name, name_w), name_style)
            cmd_x = tx + name_w + 2
            avail = w - (cmd_x - x) - (right_w + 2 if right else 1)
            if avail >= 6:
                cv.put(cmd_x, y, truncate(c.command, avail), self.s_acc if selected else self.s_muted)
            if right:
                rx = x + w - right_w - 1
                if c.dangerous:
                    cv.put(rx, y, "▲", self.s_err_b)
                    cv.put(rx + 2, y, right[2:], self.s_muted)
                else:
                    cv.put(rx, y, right, self.s_muted)
        elif item.kind == "shortcut":
            s: Shortcut = item.obj
            ok = s.exists()
            cv.put(x + 2, y, "▸", self.s_acc2)
            cv.put(tx, y, truncate(s.name, name_w), name_style)
            cmd_x = tx + name_w + 2
            avail = w - (cmd_x - x) - 3
            if avail >= 6:
                cv.put(cmd_x, y, truncate(s.path, avail), self.s_acc if selected else self.s_muted)
            cv.put(x + w - 2, y, "✔" if ok else "✖", self.s_ok if ok else self.s_err)
        else:
            h: HistoryEntry = item.obj
            when = h.when()
            ok = h.exit_code == 0
            cv.put(x + 2, y, "✔" if ok else "✖", self.s_ok if ok else self.s_err)
            cv.put(tx, y, when.strftime("%d/%m %H:%M") if when else "—", self.s_muted)
            cmd_x = tx + name_w + 2
            avail = w - (cmd_x - x) - 1
            if avail >= 6:
                cv.put(cmd_x, y, truncate(h.command, avail), name_style if selected else self.s_text)

    # -- détails --------------------------------------------------------- #
    def _detail_lines(self, item: Item, width: int) -> List[List[Seg]]:
        lines: List[List[Seg]] = []
        if item.kind == "command":
            c: Command = item.obj
            head: List[Seg] = [(c.name, self.s_acc_b)]
            if c.favorite:
                head.append(("  ★ favori", self.s_warn))
            if c.dangerous:
                head.append(("  ▲ dangereuse", self.s_err_b))
            head.append((f"  {self.store.category_name(c.category)}", self.s_acc2))
            lines.append(head)
            lines.append([("❯ ", self.s_ok), (c.command, self.s_bold)])
            for chunk in wrap(c.description, width)[:3] if c.description else []:
                lines.append([(chunk, self.s_muted)])
            if c.params:
                lines.append([("paramètres  ", self.s_faint), (c.params, self.s_text)])
            if c.example:
                lines.append([("exemple     ", self.s_faint), (c.example, self.s_acc2)])
            lines.append([("utilisée    ", self.s_faint), (f"{c.use_count} fois", self.s_text)])
        elif item.kind == "shortcut":
            s: Shortcut = item.obj
            ok = s.exists()
            lines.append([(s.name, self.s_acc_b), ("  raccourci dossier", self.s_acc2)])
            lines.append([("❯ ", self.s_ok), ("cd " + s.resolved(), self.s_bold)])
            lines.append([("✔ le dossier existe", self.s_ok) if ok else ("✖ dossier introuvable", self.s_err)])
            lines.append([("↵ s'y déplacer   e modifier   d supprimer   J/K réordonner", self.s_faint)])
        else:
            h: HistoryEntry = item.obj
            when = h.when()
            ok = h.exit_code == 0
            lines.append([(h.name or "commande libre", self.s_acc_b), ("  historique", self.s_acc2)])
            lines.append([("❯ ", self.s_ok), (h.command, self.s_bold)])
            lines.append([
                (when.strftime("%d/%m/%Y %H:%M:%S") if when else "date inconnue", self.s_muted),
                ("   ✔ succès" if ok else f"   ✖ code {h.exit_code}", self.s_ok if ok else self.s_err),
            ])
            lines.append([("↵ Entrée pour relancer", self.s_faint)])
        return lines

    def _draw_details(self, cv: Canvas, x: int, y: int, w: int, h: int) -> None:
        border = self._panel_border(False)
        cv.box(x, y, w, h, border, fill=self.s_panel, title="DÉTAILS", title_style=border.but(fg=self.theme.muted, bold=True))
        item = self.current_item()
        if item is None:
            cv.put(x + 3, y + 1, "Aucune sélection", self.s_faint)
            return
        inner_w = w - 6
        for r, line in enumerate(self._detail_lines(item, inner_w)[: h - 2]):
            cx = x + 3
            for text, style in line:
                cx += cv.put(cx, y + 1 + r, text, style, maxw=max(0, x + w - 2 - cx))

    # -- pied de page ---------------------------------------------------- #
    def _hints(self) -> List[Tuple[str, str]]:
        if self.modal:
            if self.modal.kind == "form":
                return [("Tab", "champ suivant"), ("↵", "enregistrer"), ("Échap", "annuler")]
            return [("y/n", "répondre")] if self.modal.kind == "confirm" else [("touche", "fermer")]
        if self.searching:
            return [("saisie", "filtrer"), ("↑↓", "naviguer"), ("↵", "valider"), ("Échap", "effacer")]
        sec = self.current_section()
        hints = [("↑↓", "naviguer"), ("←→", "panneaux"), ("↵", "valider" if sec.kind == "shortcuts" else "lancer"),
                 ("/", "chercher"), ("f", "favori")]
        if sec.kind == "history":
            hints.append(("x", "vider"))
        else:
            hints += [("a", "ajouter"), ("e", "modifier"), ("d", "suppr.")]
        hints += [("?", "aide"), ("q", "quitter"), ("r", "recharger")]
        return hints

    def _draw_footer(self, cv: Canvas, y: int) -> None:
        t = self.theme
        W = cv.w
        cv.fill(0, y, W, 1, Style(fg=t.muted, bg=t.panel))
        if self.toast:
            text, kind, _ = self.toast
            style = {"ok": self.s_ok, "error": self.s_err_b, "warn": self.s_warn}.get(kind, self.s_acc)
            right_segs: List[Seg] = [(truncate(text, max(10, W // 2)), style)]
        else:
            right_segs = [("● ", self.s_ok), (f"{t.name} · {t.accent_name}", self.s_muted)]
        right_w = sum(str_width(s) for s, _ in right_segs)
        budget = W - 2 - right_w - 3
        x = 1
        for i, (key, label) in enumerate(self._hints()):
            need = str_width(key) + 1 + str_width(label) + (3 if i else 0)
            if x - 1 + need > budget:
                break
            if i:
                x += cv.put(x, y, " │ ", self.s_faint)
            x += cv.put(x, y, key, self.s_acc_b)
            x += cv.put(x, y, " " + label, self.s_muted)
        rx = W - 1 - right_w
        for text, style in right_segs:
            rx += cv.put(rx, y, text, style)

    # -- fenêtres modales ------------------------------------------------ #
    def _help_modal(self) -> Modal:
        def head(text: str) -> List[Seg]:
            return [(text, self.s_acc2_b)]

        def row(key: str, desc: str) -> List[Seg]:
            return [(f"  {key:<14}", self.s_acc_b), (desc, self.s_text)]

        lines: List[List[Seg]] = [
            head("NAVIGATION"),
            row("↑ ↓  j k", "parcourir la liste"),
            row("← →  Tab", "changer de panneau"),
            row("g  G", "début / fin"),
            row("PgUp  PgDn", "page précédente / suivante"),
            [],
            head("ACTIONS"),
            row("↵  Entrée", "lancer la commande / aller au dossier"),
            row("f", "ajouter / retirer des favoris"),
            row("/", "rechercher (Échap pour effacer)"),
            row("a", "ajouter (raccourci dans Navigation, sinon commande)"),
            row("A", "ajouter une commande (même dans Navigation)"),
            row("e", "modifier l'entrée sélectionnée"),
            row("d  Suppr", "supprimer l'entrée (avec confirmation)"),
            row("J  K", "descendre / monter un raccourci de dossier"),
            row("x", "vider l'historique (vue Historique)"),
            row("r", "recharger les fichiers JSON"),
            row("q  Échap", "quitter"),
            [],
            [(f"  Youns Terminal Hub v{__version__}", self.s_faint)],
        ]
        return Modal("help", "AIDE · RACCOURCIS", lines)

    def _draw_modal(self, cv: Canvas) -> None:
        t = self.theme
        m = self.modal
        assert m is not None
        if m.kind == "form":
            m.lines = self._form_lines(m)
        content_w = max((sum(str_width(s) for s, _ in line) for line in m.lines), default=0)
        w = min(cv.w - 4, max(content_w + 6, str_width(m.title) + 8, 44))
        h = min(cv.h - 2, len(m.lines) + 2)
        x, y = (cv.w - w) // 2, (cv.h - h) // 2
        bg = mix(t.panel or (10, 15, 27), t.accent, 0.06)
        border = Style(fg=t.danger if m.danger else t.accent, bg=bg)
        cv.box(x, y, w, h, border, fill=Style(fg=t.text, bg=bg), title=m.title, title_style=border.but(bold=True))
        for r, line in enumerate(m.lines[: h - 2]):
            cx = x + 2
            for text, style in line:
                cx += cv.put(cx, y + 1 + r, text, style, maxw=max(0, x + w - 2 - cx))
