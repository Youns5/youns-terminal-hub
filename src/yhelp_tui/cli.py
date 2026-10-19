"""Point d'entrée en ligne de commande : ``yhelp-tui``."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import List, Optional

from . import __version__
from .store import Store, default_config_dir


def _print_list(store: Store) -> None:
    names = {c.id: c.name for c in store.categories}
    groups: dict = {}
    for cmd in store.commands:
        groups.setdefault(cmd.category or "autres", []).append(cmd)
    for cid, cmds in groups.items():
        print(f"\n[{names.get(cid, cid)}]")
        for c in cmds:
            flags = ("★" if c.favorite else " ") + ("▲" if c.dangerous else " ")
            print(f"  {flags} {c.name:<18} {c.command}")
    if store.shortcuts:
        print("\n[Raccourcis dossiers]")
        for s in store.shortcuts:
            print(f"    {s.name:<18} {s.path}")
    print()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="yhelp-tui",
        description="Youns Terminal Hub — hub de commandes pour le terminal.",
        epilog="Astuce : lancez plutôt la fonction shell « yhelp » (voir yhelp.sh) "
        "pour que les raccourcis de dossiers puissent changer votre répertoire courant.",
    )
    p.add_argument("-V", "--version", action="version", version=f"yhelp-tui {__version__}")
    p.add_argument("--list", action="store_true", help="affiche les commandes et quitte (sans interface)")
    p.add_argument("--where", action="store_true", help="affiche le dossier de configuration et quitte")
    p.add_argument("--config-dir", metavar="DIR", help="utilise un autre dossier de configuration")
    p.add_argument("--reset", action="store_true", help="restaure les fichiers par défaut (anciens fichiers gardés en .bak)")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.config_dir).expanduser() if args.config_dir else default_config_dir()

    if args.where:
        print(root)
        return 0

    store = Store(root)

    if args.reset:
        moved = store.reset()
        print(f"Configuration restaurée dans {root}" + (f" (sauvegardés : {', '.join(moved)})" if moved else ""))
        return 0

    if args.list:
        _print_list(store)
        for w in store.warnings:
            print(f"avertissement : {w}", file=sys.stderr)
        return 0

    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("yhelp-tui : un terminal interactif est requis (essayez --list).", file=sys.stderr)
        return 2

    from .app import App  # import tardif : termios n'existe pas partout
    from .term import Terminal

    app = App(store, Terminal())
    target = app.run()

    if target:
        cd_file = os.environ.get("YHELP_CD_FILE")
        if cd_file:
            try:
                Path(cd_file).write_text(target, encoding="utf-8")
            except OSError as exc:
                print(f"yhelp-tui : impossible d'écrire {cd_file} : {exc}", file=sys.stderr)
                return 1
        else:
            print(f"cd {target}")
            print("(chargez yhelp.sh dans votre shell pour que le changement de dossier soit appliqué)", file=sys.stderr)
    return 0
