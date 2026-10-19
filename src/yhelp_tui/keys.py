"""Lecture du clavier : décodage des séquences d'échappement (stdlib uniquement)."""

from __future__ import annotations

import os
import re
import select
from collections import deque
from typing import Deque, List, Optional, Tuple

_CSI = re.compile(rb"\x1b\[([0-9;?<>=]*)([ -/]*)([@-~])")
_SS3 = re.compile(rb"\x1bO([@-~])")

_FINALS = {
    b"A": "up",
    b"B": "down",
    b"C": "right",
    b"D": "left",
    b"H": "home",
    b"F": "end",
    b"Z": "shift-tab",
}
_TILDE = {1: "home", 2: "insert", 3: "delete", 4: "end", 5: "pgup", 6: "pgdn", 7: "home", 8: "end"}
_CTRL = {
    0x03: "ctrl-c",
    0x04: "ctrl-d",
    0x08: "backspace",
    0x09: "tab",
    0x0A: "enter",
    0x0C: "ctrl-l",
    0x0D: "enter",
    0x15: "ctrl-u",
    0x7F: "backspace",
}


def parse_keys(buf: bytes) -> Tuple[List[str], bytes]:
    """Décode un tampon d'octets en noms de touches.

    Renvoie (touches, reste) ; `reste` contient une séquence incomplète (ou un
    simple Échap) qu'il faudra compléter ou résoudre après un court délai.
    """
    keys: List[str] = []
    i, n = 0, len(buf)
    while i < n:
        b = buf[i]
        if b == 0x1B:
            rest = buf[i:]
            if len(rest) == 1:
                return keys, rest
            if rest[1:2] == b"[":
                m = _CSI.match(rest)
                if not m:
                    if len(rest) < 32 and not re.search(rb"[@-~]", rest[2:]):
                        return keys, rest  # séquence incomplète
                    i += 2  # séquence malformée : on l'ignore
                    continue
                params, final = m.group(1), m.group(3)
                name: Optional[str] = None
                if final == b"~":
                    first = params.split(b";")[0]
                    if first.isdigit():
                        name = _TILDE.get(int(first))
                else:
                    name = _FINALS.get(final)
                if name:
                    keys.append(name)
                i += m.end()
                continue
            if rest[1:2] == b"O":
                m = _SS3.match(rest)
                if not m:
                    return keys, rest
                name = _FINALS.get(m.group(1))
                if name:
                    keys.append(name)
                i += m.end()
                continue
            keys.append("esc")
            i += 1
            continue
        if b < 0x20 or b == 0x7F:
            name = _CTRL.get(b)
            if name:
                keys.append(name)
            i += 1
            continue
        if b < 0x80:
            keys.append(chr(b))
            i += 1
            continue
        need = 2 if 0xC0 <= b < 0xE0 else 3 if 0xE0 <= b < 0xF0 else 4 if 0xF0 <= b < 0xF8 else 1
        if i + need > n:
            return keys, buf[i:]
        try:
            keys.append(buf[i : i + need].decode("utf-8"))
        except UnicodeDecodeError:
            pass
        i += need
    return keys, b""


class KeyReader:
    """Lit des touches depuis un descripteur de fichier avec délai d'attente."""

    ESC_DELAY = 0.04

    def __init__(self, fd: int):
        self.fd = fd
        self.pending = b""
        self.queue: Deque[str] = deque()

    def _wait(self, timeout: float) -> bool:
        ready, _, _ = select.select([self.fd], [], [], timeout)
        return bool(ready)

    def _read(self) -> bytes:
        data = os.read(self.fd, 4096)
        if not data:
            raise EOFError("entrée standard fermée")
        return data

    def poll(self, timeout: float) -> Optional[str]:
        """Renvoie la prochaine touche, ou None si le délai est écoulé."""
        if self.queue:
            return self.queue.popleft()
        if not self._wait(timeout):
            return None
        self.pending += self._read()
        while True:
            keys, rest = parse_keys(self.pending)
            self.queue.extend(keys)
            self.pending = rest
            if not rest:
                break
            if self._wait(self.ESC_DELAY):
                self.pending += self._read()
                continue
            if rest == b"\x1b":
                self.queue.append("esc")
            self.pending = b""
            break
        return self.queue.popleft() if self.queue else None
