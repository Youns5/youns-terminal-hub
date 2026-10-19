#!/usr/bin/env python3
"""Génère un aperçu PNG de l'interface à partir du vrai tampon de rendu.

Outil de maintenance (Pillow requis) : ``python scripts/render_preview.py out.png [LARGEURxHAUTEUR]``.
Le rendu est celui de `App.draw`, pas une maquette.
"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from yhelp_tui.ansi import char_width  # noqa: E402
from yhelp_tui.app import App  # noqa: E402
from yhelp_tui.store import Store  # noqa: E402

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"


def render(canvas, path, size=16):
    font, bold = ImageFont.truetype(FONT, size), ImageFont.truetype(BOLD, size)
    cw = round(font.getlength("M"))
    ch = int(size * 1.35)
    img = Image.new("RGB", (canvas.w * cw, canvas.h * ch), (6, 9, 17))
    d = ImageDraw.Draw(img)
    for y, row in enumerate(canvas.cells):
        for x, (c, st) in enumerate(row):
            if c == "":
                continue
            w = char_width(c) or 1
            if st.bg:
                d.rectangle([x * cw, y * ch, (x + w) * cw - 1, (y + 1) * ch - 1], fill=st.bg)
    for y, row in enumerate(canvas.cells):
        for x, (c, st) in enumerate(row):
            if c in ("", " "):
                continue
            fg = st.fg or (205, 218, 238)
            if st.dim:
                fg = tuple(int(v * 0.6) for v in fg)
            d.text((x * cw, y * ch), c, font=bold if st.bold else font, fill=fg)
    img.save(path)


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "preview.png"
    w, h = (int(v) for v in (sys.argv[2] if len(sys.argv) > 2 else "110x34").split("x"))
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp))
        os.environ.setdefault("YHELP_COLOR", "truecolor")
        app = App(store)
        for cmd, favorite, uses in (("sys-info", True, 14), ("git-status", True, 9), ("disk", False, 3)):
            c = store.command_by_id(cmd)
            c.favorite, c.use_count = favorite, uses
        render(app.draw(w, h), out)
    print(out)
