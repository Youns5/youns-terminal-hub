"""Données : commandes, catégories, raccourcis, historique et configuration.

Les fichiers JSON de l'utilisateur vivent dans ``~/.config/yhelp`` (ou
``$YHELP_HOME``) et non dans le dépôt : mises à jour du projet et données
personnelles ne se mélangent donc jamais. Au premier lancement, les valeurs
par défaut fournies avec le programme sont copiées.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULTS_DIR = Path(__file__).resolve().parent / "defaults"
FILES = ("config.json", "commands.json", "categories.json", "shortcuts.json", "history.json")

DEFAULT_CONFIG: Dict[str, Any] = {
    "theme": "dark",
    "accent_color": "cyan",
    "show_logo": True,
    "logo_mode": "ascii",
    "ascii_logo": [],
    "icons": "glyph",
    "background": "solid",
    "confirm_dangerous": True,
    "history_limit": 200,
}


def default_config_dir(env: Optional[Dict[str, str]] = None) -> Path:
    env = os.environ if env is None else env
    if env.get("YHELP_HOME"):
        return Path(env["YHELP_HOME"]).expanduser()
    base = env.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "yhelp"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "item"


def _str(value: Any) -> str:
    return "" if value is None else str(value)


def _int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


# --------------------------------------------------------------------------- #
# Modèles
# --------------------------------------------------------------------------- #
@dataclass
class Command:
    id: str
    name: str
    command: str
    description: str = ""
    category: str = ""
    params: str = ""
    example: str = ""
    favorite: bool = False
    use_count: int = 0
    dangerous: bool = False

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> Optional["Command"]:
        command = _str(d.get("command")).strip()
        if not command:
            return None
        name = _str(d.get("name")).strip() or command.split()[0]
        return cls(
            id=_str(d.get("id")).strip() or _slug(name),
            name=name,
            command=command,
            description=_str(d.get("description")),
            category=_str(d.get("category")),
            params=_str(d.get("params")),
            example=_str(d.get("example")),
            favorite=bool(d.get("favorite", False)),
            use_count=_int(d.get("use_count", 0)),
            dangerous=bool(d.get("dangerous", False)),
        )


@dataclass
class Category:
    id: str
    name: str
    icon: str = "◆"

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> Optional["Category"]:
        cid = _str(d.get("id")).strip()
        if not cid:
            return None
        return cls(id=cid, name=_str(d.get("name")).strip() or cid.capitalize(), icon=_str(d.get("icon")) or "◆")


@dataclass
class Shortcut:
    id: str
    name: str
    path: str

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> Optional["Shortcut"]:
        path = _str(d.get("path")).strip()
        if not path:
            return None
        name = _str(d.get("name")).strip() or Path(path).name or path
        return cls(id=_str(d.get("id")).strip() or _slug(name), name=name, path=path)

    def resolved(self) -> str:
        return os.path.expandvars(os.path.expanduser(self.path))

    def exists(self) -> bool:
        return os.path.isdir(self.resolved())


@dataclass
class HistoryEntry:
    timestamp: str
    id: str
    name: str
    command: str
    exit_code: int = 0

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> Optional["HistoryEntry"]:
        command = _str(d.get("command")).strip()
        if not command:
            return None
        try:
            code = int(d.get("exit_code", 0))
        except (TypeError, ValueError):
            code = 0
        return cls(_str(d.get("timestamp")), _str(d.get("id")), _str(d.get("name")), command, code)

    def when(self) -> Optional[datetime]:
        try:
            return datetime.fromisoformat(self.timestamp)
        except ValueError:
            return None


def _free_id(base: str, items: list) -> str:
    """Identifiant unique (`base`, `base-2`, `base-3`…) par rapport à `items`."""
    taken = {i.id for i in items}
    if base not in taken:
        return base
    n = 2
    while f"{base}-{n}" in taken:
        n += 1
    return f"{base}-{n}"


def _unique_ids(items: list) -> list:
    seen: Dict[str, int] = {}
    for item in items:
        n = seen.get(item.id, 0) + 1
        seen[item.id] = n
        if n > 1:
            item.id = f"{item.id}-{n}"
    return items


# --------------------------------------------------------------------------- #
# Store
# --------------------------------------------------------------------------- #
class Store:
    def __init__(self, root: Path, defaults: Path = DEFAULTS_DIR):
        self.root = Path(root)
        self.defaults = Path(defaults)
        self.warnings: List[str] = []
        self.config: Dict[str, Any] = dict(DEFAULT_CONFIG)
        self.commands: List[Command] = []
        self.categories: List[Category] = []
        self.shortcuts: List[Shortcut] = []
        self.history: List[HistoryEntry] = []
        self.load()

    # -- fichiers ---------------------------------------------------------- #
    def _bundled(self, name: str) -> Any:
        if name == "history.json":
            return []
        with open(self.defaults / name, encoding="utf-8") as fh:
            return json.load(fh)

    def _write(self, name: str, data: Any) -> bool:
        path = self.root / name
        tmp = path.with_name(path.name + ".tmp")
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, ensure_ascii=False)
                fh.write("\n")
            os.replace(tmp, path)
            return True
        except OSError as exc:
            self.warnings.append(f"écriture de {name} impossible : {exc}")
            return False

    def _read(self, name: str, expected: type) -> Any:
        path = self.root / name
        for _ in range(2):
            try:
                with open(path, encoding="utf-8") as fh:
                    data = json.load(fh)
                if not isinstance(data, expected):
                    raise ValueError(f"type inattendu ({type(data).__name__})")
                return data
            except FileNotFoundError:
                self._write(name, self._bundled(name))
            except (ValueError, OSError) as exc:
                try:
                    os.replace(path, path.with_name(path.name + ".bak"))
                except OSError:
                    pass
                self.warnings.append(f"{name} illisible ({exc}) — copie dans {name}.bak, valeurs par défaut restaurées")
                self._write(name, self._bundled(name))
        return self._bundled(name)  # dossier non inscriptible : on reste en mémoire

    def load(self) -> None:
        self.warnings = []
        cfg = self._read("config.json", dict)
        self.config = {**DEFAULT_CONFIG, **cfg}
        if not self.config.get("ascii_logo"):
            self.config["ascii_logo"] = self._bundled("config.json").get("ascii_logo", [])

        def many(name: str, model) -> list:
            raw = self._read(name, list)
            out = [model.from_dict(d) for d in raw if isinstance(d, dict)]
            return [x for x in out if x is not None]

        self.commands = _unique_ids(many("commands.json", Command))
        self.categories = _unique_ids(many("categories.json", Category))
        self.shortcuts = _unique_ids(many("shortcuts.json", Shortcut))
        self.history = many("history.json", HistoryEntry)

    reload = load

    # -- requêtes ---------------------------------------------------------- #
    def command_by_id(self, cid: str) -> Optional[Command]:
        return next((c for c in self.commands if c.id == cid), None)

    def category_name(self, cid: str) -> str:
        cat = next((c for c in self.categories if c.id == cid), None)
        return cat.name if cat else (cid.capitalize() if cid else "—")

    # -- mutations --------------------------------------------------------- #
    def save_commands(self) -> bool:
        return self._write("commands.json", [asdict(c) for c in self.commands])

    def save_history(self) -> bool:
        return self._write("history.json", [asdict(h) for h in self.history])

    def save_shortcuts(self) -> bool:
        return self._write("shortcuts.json", [asdict(s) for s in self.shortcuts])

    # -- raccourcis de dossiers : ajouter / modifier / supprimer / ordonner -- #
    def add_shortcut(self, name: str, path: str) -> Shortcut:
        path = path.strip()
        name = name.strip() or Path(os.path.expanduser(path)).name or path
        sc = Shortcut(id=_free_id(_slug(name), self.shortcuts), name=name, path=path)
        self.shortcuts.append(sc)
        self.save_shortcuts()
        return sc

    def update_shortcut(self, sc: Shortcut, name: str, path: str) -> None:
        sc.path = path.strip()
        sc.name = name.strip() or Path(os.path.expanduser(sc.path)).name or sc.path
        self.save_shortcuts()

    def delete_shortcut(self, sc: Shortcut) -> None:
        self.shortcuts = [s for s in self.shortcuts if s is not sc]
        self.save_shortcuts()

    def move_shortcut(self, sc: Shortcut, delta: int) -> bool:
        """Décale un raccourci vers le haut (-1) ou le bas (+1). Renvoie False en bout de liste."""
        i = self.shortcuts.index(sc)
        j = i + delta
        if not 0 <= j < len(self.shortcuts):
            return False
        self.shortcuts[i], self.shortcuts[j] = self.shortcuts[j], self.shortcuts[i]
        self.save_shortcuts()
        return True

    # -- commandes : ajouter / modifier / supprimer ------------------------- #
    def add_command(self, name: str, command: str, description: str = "", category: str = "",
                    params: str = "", dangerous: bool = False) -> Command:
        command = command.strip()
        name = name.strip() or command.split()[0]
        cmd = Command(id=_free_id(_slug(name), self.commands), name=name, command=command,
                      description=description.strip(), category=category, params=params.strip(),
                      dangerous=dangerous)
        self.commands.append(cmd)
        self.save_commands()
        return cmd

    def update_command(self, cmd: Command, name: str, command: str, description: str = "",
                       category: str = "", params: str = "", dangerous: bool = False) -> None:
        cmd.command = command.strip()
        cmd.name = name.strip() or cmd.command.split()[0]
        cmd.description = description.strip()
        cmd.category = category
        cmd.params = params.strip()
        cmd.dangerous = dangerous
        self.save_commands()

    def delete_command(self, cmd: Command) -> None:
        self.commands = [c for c in self.commands if c is not cmd]
        self.save_commands()

    def toggle_favorite(self, cmd: Command) -> bool:
        cmd.favorite = not cmd.favorite
        self.save_commands()
        return cmd.favorite

    def record_run(self, cmd: Optional[Command], full_command: str, exit_code: int) -> None:
        entry = HistoryEntry(
            timestamp=datetime.now().isoformat(timespec="seconds"),
            id=cmd.id if cmd else "",
            name=cmd.name if cmd else "",
            command=full_command,
            exit_code=exit_code,
        )
        self.history.insert(0, entry)
        limit = _int(self.config.get("history_limit")) or 200
        del self.history[limit:]
        self.save_history()
        if cmd:
            cmd.use_count += 1
            self.save_commands()

    def clear_history(self) -> None:
        self.history = []
        self.save_history()

    def reset(self) -> List[str]:
        """Remet les fichiers par défaut (les anciens sont conservés en .bak)."""
        moved = []
        for name in FILES:
            path = self.root / name
            if path.exists():
                os.replace(path, path.with_name(path.name + ".bak"))
                moved.append(name)
        self.load()
        return moved
