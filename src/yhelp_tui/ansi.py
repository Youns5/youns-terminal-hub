"""Primitives d'affichage : couleurs, largeur des caractères et canevas.

Tout est écrit avec la bibliothèque standard : aucune dépendance externe.
Le rendu se fait dans un canevas en mémoire (grille de cellules), puis il est
converti en une seule chaîne ANSI, ce qui évite le scintillement.
"""

from __future__ import annotations

import dataclasses
import os
import unicodedata
from dataclasses import dataclass
from typing import List, Mapping, Optional, Sequence, Tuple

RGB = Tuple[int, int, int]

TRUECOLOR = "truecolor"
COLOR256 = "256"
NOCOLOR = "none"


# --------------------------------------------------------------------------- #
# Couleurs
# --------------------------------------------------------------------------- #
def hex_to_rgb(value: str) -> RGB:
    """Convertit « #0af » ou « #00aaff » en tuple RGB. Lève ValueError sinon."""
    h = value.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        raise ValueError(f"couleur invalide : {value!r}")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def mix(a: RGB, b: RGB, t: float) -> RGB:
    """Interpolation linéaire entre deux couleurs (t entre 0 et 1)."""
    t = max(0.0, min(1.0, t))
    return (
        int(round(a[0] + (b[0] - a[0]) * t)),
        int(round(a[1] + (b[1] - a[1]) * t)),
        int(round(a[2] + (b[2] - a[2]) * t)),
    )


_CUBE = (0, 95, 135, 175, 215, 255)


def rgb_to_256(color: RGB) -> int:
    """Couleur la plus proche dans la palette xterm-256."""

    def nearest(v: int) -> int:
        return min(range(6), key=lambda i: abs(_CUBE[i] - v))

    def dist(a: RGB, b: RGB) -> int:
        return sum((x - y) ** 2 for x, y in zip(a, b))

    ri, gi, bi = (nearest(v) for v in color)
    cube_rgb = (_CUBE[ri], _CUBE[gi], _CUBE[bi])
    cube_idx = 16 + 36 * ri + 6 * gi + bi

    level = round(sum(color) / 3)
    gray_i = min(23, max(0, round((level - 8) / 10)))
    gray = 8 + 10 * gray_i
    if dist(color, cube_rgb) <= dist(color, (gray, gray, gray)):
        return cube_idx
    return 232 + gray_i


def detect_color_mode(env: Optional[Mapping[str, str]] = None) -> str:
    """Détermine le mode de couleur du terminal (truecolor, 256 ou aucun)."""
    env = os.environ if env is None else env
    forced = env.get("YHELP_COLOR", "").lower()
    if forced in (TRUECOLOR, COLOR256, NOCOLOR):
        return forced
    if env.get("NO_COLOR") or env.get("TERM") == "dumb":
        return NOCOLOR
    colorterm = env.get("COLORTERM", "").lower()
    term = env.get("TERM", "").lower()
    if colorterm in ("truecolor", "24bit") or "direct" in term or "truecolor" in term:
        return TRUECOLOR
    if env.get("TERM_PROGRAM") == "Apple_Terminal":
        return COLOR256
    return COLOR256


# --------------------------------------------------------------------------- #
# Style
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Style:
    fg: Optional[RGB] = None
    bg: Optional[RGB] = None
    bold: bool = False
    dim: bool = False
    italic: bool = False
    underline: bool = False

    def but(self, **changes) -> "Style":
        return dataclasses.replace(self, **changes)


def sgr(style: Style, mode: str) -> str:
    """Séquence SGR complète (repart toujours de zéro) pour un style."""
    parts = ["0"]
    if style.bold:
        parts.append("1")
    if style.dim:
        parts.append("2")
    if style.italic:
        parts.append("3")
    if style.underline:
        parts.append("4")
    if mode != NOCOLOR:
        for base, color in ((38, style.fg), (48, style.bg)):
            if color is None:
                continue
            if mode == TRUECOLOR:
                parts.append(f"{base};2;{color[0]};{color[1]};{color[2]}")
            else:
                parts.append(f"{base};5;{rgb_to_256(color)}")
    return "\x1b[" + ";".join(parts) + "m"


def paint(text: str, style: Style, mode: str) -> str:
    """Enveloppe un texte dans un style (utilisé hors plein écran)."""
    return f"{sgr(style, mode)}{text}\x1b[0m"


# --------------------------------------------------------------------------- #
# Largeur des caractères
# --------------------------------------------------------------------------- #
def char_width(ch: str) -> int:
    """Nombre de colonnes occupées par un caractère (0, 1 ou 2)."""
    o = ord(ch)
    if o == 0 or o < 32 or 0x7F <= o < 0xA0:
        return 0
    if o in (0x200D, 0xFE0E, 0xFE0F) or 0x200B <= o <= 0x200F:
        return 0
    if unicodedata.combining(ch):
        return 0
    if 0x1F300 <= o <= 0x1FAFF:
        return 2
    if unicodedata.east_asian_width(ch) in ("W", "F"):
        return 2
    return 1


def str_width(text: str) -> int:
    return sum(char_width(c) for c in text)


def truncate(text: str, width: int, ellipsis: str = "…") -> str:
    """Tronque à `width` colonnes (avec points de suspension si nécessaire)."""
    if width <= 0:
        return ""
    if str_width(text) <= width:
        return text
    out: List[str] = []
    used = 0
    for ch in text:
        cw = char_width(ch)
        if used + cw > width - 1:
            break
        out.append(ch)
        used += cw
    return "".join(out) + ellipsis


def pad(text: str, width: int) -> str:
    """Tronque puis complète avec des espaces pour atteindre `width` colonnes."""
    text = truncate(text, width)
    return text + " " * max(0, width - str_width(text))


def wrap(text: str, width: int) -> List[str]:
    """Retour à la ligne par mots, en tenant compte de la largeur réelle."""
    if width <= 0:
        return []
    lines: List[str] = []
    for para in str(text).splitlines() or [""]:
        cur, curw = "", 0
        for word in para.split():
            ww = str_width(word)
            if ww > width:  # mot plus long que la ligne : coupe dure
                if cur:
                    lines.append(cur)
                chunk, cw = "", 0
                for ch in word:
                    w = char_width(ch)
                    if cw + w > width:
                        lines.append(chunk)
                        chunk, cw = "", 0
                    chunk += ch
                    cw += w
                cur, curw = chunk, cw
            elif cur and curw + 1 + ww > width:
                lines.append(cur)
                cur, curw = word, ww
            elif cur:
                cur += " " + word
                curw += 1 + ww
            else:
                cur, curw = word, ww
        lines.append(cur)
    return lines


# --------------------------------------------------------------------------- #
# Canevas
# --------------------------------------------------------------------------- #
Cell = Tuple[str, Style]


class Canvas:
    """Grille de cellules (caractère, style) rendue en une seule écriture."""

    def __init__(self, width: int, height: int, base: Style):
        self.w = max(0, width)
        self.h = max(0, height)
        self.base = base
        self.cells: List[List[Cell]] = [
            [(" ", base) for _ in range(self.w)] for _ in range(self.h)
        ]

    # -- écriture ---------------------------------------------------------- #
    def _clear_wide(self, x: int, y: int) -> None:
        """Évite les demi-caractères larges quand on écrase une cellule."""
        row = self.cells[y]
        ch, st = row[x]
        if ch == "" and x > 0:
            row[x - 1] = (" ", row[x - 1][1])
        elif char_width(ch) == 2 and x + 1 < self.w:
            row[x + 1] = (" ", row[x + 1][1])

    def put(
        self,
        x: int,
        y: int,
        text: str,
        style: Optional[Style] = None,
        maxw: Optional[int] = None,
    ) -> int:
        """Écrit un texte ; renvoie le nombre de colonnes consommées.

        Un style sans fond hérite du fond déjà présent dans la cellule.
        """
        if y < 0 or y >= self.h:
            return 0
        style = style or self.base
        limit = self.w if maxw is None else min(self.w, x + maxw)
        start = x
        for ch in text:
            cw = char_width(ch)
            if cw == 0:
                continue
            if x < 0:
                x += cw
                continue
            if x + cw > limit:
                break
            self._clear_wide(x, y)
            st = style
            if style.bg is None:
                st = style.but(bg=self.cells[y][x][1].bg)
            self.cells[y][x] = (ch, st)
            if cw == 2:
                self._clear_wide(x + 1, y)
                self.cells[y][x + 1] = ("", st)
            x += cw
        return x - start

    def fill(self, x: int, y: int, w: int, h: int, style: Style, ch: str = " ") -> None:
        for yy in range(max(0, y), min(self.h, y + h)):
            for xx in range(max(0, x), min(self.w, x + w)):
                self.cells[yy][xx] = (ch, style)

    def box(
        self,
        x: int,
        y: int,
        w: int,
        h: int,
        border: Style,
        fill: Optional[Style] = None,
        title: str = "",
        title_style: Optional[Style] = None,
        right_title: str = "",
        right_style: Optional[Style] = None,
    ) -> None:
        """Cadre à coins arrondis, avec titres optionnels dans la bordure."""
        if w < 2 or h < 2:
            return
        if fill is not None:
            self.fill(x + 1, y + 1, w - 2, h - 2, fill)
        self.put(x, y, "╭" + "─" * (w - 2) + "╮", border)
        self.put(x, y + h - 1, "╰" + "─" * (w - 2) + "╯", border)
        for r in range(1, h - 1):
            self.put(x, y + r, "│", border)
            self.put(x + w - 1, y + r, "│", border)
        if title:
            self.put(x + 2, y, f" {title} ", title_style or border, maxw=max(0, w - 4))
        if right_title:
            label = f" {right_title} "
            tw = str_width(label)
            if tw + 4 < w:
                self.put(x + w - 2 - tw, y, label, right_style or border)

    # -- sortie ------------------------------------------------------------ #
    def text_lines(self) -> List[str]:
        """Contenu brut (sans style) — pratique pour les tests."""
        return ["".join(ch for ch, _ in row) for row in self.cells]

    def render(self, mode: str) -> str:
        out: List[str] = []
        last: Optional[Style] = None
        for y, row in enumerate(self.cells):
            out.append(f"\x1b[{y + 1};1H")
            for ch, st in row:
                if ch == "":
                    continue
                if st != last:
                    out.append(sgr(st, mode))
                    last = st
                out.append(ch)
        out.append("\x1b[0m")
        return "".join(out)


def gradient_text(text: str, start: RGB, end: RGB, offset: float = 0.0, span: float = 1.0) -> List[Tuple[str, RGB]]:
    """Découpe un texte en (caractère, couleur) selon un dégradé horizontal."""
    n = max(1, len(text) - 1)
    return [(ch, mix(start, end, offset + span * i / n)) for i, ch in enumerate(text)]


__all__: Sequence[str] = [
    "Canvas",
    "Style",
    "RGB",
    "TRUECOLOR",
    "COLOR256",
    "NOCOLOR",
    "char_width",
    "detect_color_mode",
    "gradient_text",
    "hex_to_rgb",
    "mix",
    "pad",
    "paint",
    "rgb_to_256",
    "sgr",
    "str_width",
    "truncate",
    "wrap",
]
