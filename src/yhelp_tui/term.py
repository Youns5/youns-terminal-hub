"""Gestion du terminal : écran alternatif, mode caractère par caractère."""

from __future__ import annotations

import os
import shutil
import sys
import termios
import tty
from typing import Optional, Tuple

_ENTER = "\x1b[?1049h\x1b[?25l\x1b[?7l\x1b[2J"
_LEAVE = "\x1b[0m\x1b[?7h\x1b[?25h\x1b[?1049l"


class Terminal:
    """Active/désactive l'interface plein écran et restaure toujours le terminal."""

    def __init__(self, fd_in: Optional[int] = None, out=None):
        self.fd = sys.stdin.fileno() if fd_in is None else fd_in
        self.out = sys.stdout if out is None else out
        self._saved = None
        self.active = False

    def write(self, text: str) -> None:
        self.out.write(text)
        self.out.flush()

    def start(self) -> None:
        if self.active:
            return
        self._saved = termios.tcgetattr(self.fd)
        tty.setcbreak(self.fd)
        self.write(_ENTER)
        self.active = True

    def stop(self) -> None:
        if not self.active:
            return
        self.write(_LEAVE)
        if self._saved is not None:
            termios.tcsetattr(self.fd, termios.TCSADRAIN, self._saved)
        self.active = False

    # Suspendre = rendre la main au shell (ex. pour exécuter une commande).
    suspend = stop
    resume = start

    def __enter__(self) -> "Terminal":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()

    def size(self) -> Tuple[int, int]:
        try:
            s = os.get_terminal_size(self.out.fileno())
            if s.columns > 0 and s.lines > 0:
                return s.columns, s.lines
        except (OSError, ValueError):
            pass
        s = shutil.get_terminal_size((80, 24))
        return s.columns, s.lines
