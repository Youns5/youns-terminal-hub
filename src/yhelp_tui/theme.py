"""Thèmes : palette sombre premium, cyan néon et touches violettes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

from .ansi import RGB, hex_to_rgb, mix

ACCENTS = {
    "cyan": (0, 229, 255),
    "violet": (167, 112, 255),
    "purple": (167, 112, 255),
    "green": (46, 255, 160),
    "magenta": (255, 72, 208),
    "pink": (255, 72, 208),
    "amber": (255, 184, 48),
    "orange": (255, 140, 50),
    "blue": (74, 158, 255),
    "red": (255, 84, 104),
}

_BASES = {
    "dark": dict(
        bg=(6, 9, 17), panel=(10, 15, 27), border=(36, 50, 76),
        text=(205, 218, 238), muted=(112, 128, 158), faint=(66, 80, 106),
    ),
    "midnight": dict(
        bg=(10, 7, 20), panel=(15, 11, 30), border=(52, 40, 84),
        text=(214, 208, 238), muted=(128, 118, 164), faint=(76, 66, 108),
    ),
}

VIOLET = ACCENTS["violet"]
CYAN = ACCENTS["cyan"]


@dataclass(frozen=True)
class Theme:
    name: str
    accent_name: str
    accent: RGB
    accent2: RGB
    bg: Optional[RGB]
    panel: Optional[RGB]
    sel_bg: RGB
    border: RGB
    text: RGB
    muted: RGB
    faint: RGB
    success: RGB = (46, 255, 160)
    warning: RGB = (255, 196, 64)
    danger: RGB = (255, 84, 104)


def parse_accent(value: Any) -> "tuple[str, RGB]":
    """« cyan », « violet » ou « #00e5ff » → (nom, RGB). Défaut : cyan."""
    text = str(value or "cyan").strip().lower()
    if text in ACCENTS:
        return text, ACCENTS[text]
    try:
        return text, hex_to_rgb(text)
    except ValueError:
        return "cyan", ACCENTS["cyan"]


def build_theme(config: Mapping[str, Any]) -> Theme:
    name = str(config.get("theme", "dark")).lower()
    if name not in _BASES:
        name = "dark"
    base = _BASES[name]
    accent_name, accent = parse_accent(config.get("accent_color"))
    accent2 = CYAN if accent == VIOLET else VIOLET
    if accent == accent2:
        accent2 = mix(accent, (255, 255, 255), 0.35)
    transparent = str(config.get("background", "solid")).lower() == "transparent"
    panel = base["panel"]
    return Theme(
        name=name,
        accent_name=accent_name,
        accent=accent,
        accent2=accent2,
        bg=None if transparent else base["bg"],
        panel=None if transparent else panel,
        sel_bg=mix(panel, accent, 0.16),
        border=base["border"],
        text=base["text"],
        muted=base["muted"],
        faint=base["faint"],
    )
