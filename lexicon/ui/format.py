"""Metin biçimlendirme yardımcıları: bayt, hız, süre, çubuk, sparkline.

Unicode destekleyen terminallerde blok karakterleri, desteklemeyenlerde ASCII
kullanılır (bkz. `glyphs_for_locale`).
"""

from __future__ import annotations

import locale
from dataclasses import dataclass
from typing import Optional, Sequence


@dataclass(frozen=True)
class Glyphs:
    full: str
    empty: str
    spark: str
    ellipsis: str
    down: str
    up: str
    dot: str


UNICODE = Glyphs(
    full="█", empty="░", spark=" ▁▂▃▄▅▆▇█", ellipsis="…", down="↓", up="↑", dot="·",
)
ASCII = Glyphs(
    full="#", empty=".", spark=" .:-=+*#@", ellipsis="~", down="v", up="^", dot="|",
)


def glyphs_for_locale() -> Glyphs:
    encoding = (locale.getpreferredencoding(False) or "").lower()
    return UNICODE if "utf" in encoding else ASCII


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def human_bytes(n: float) -> str:
    units = ("B", "KiB", "MiB", "GiB", "TiB", "PiB")
    value = float(max(n, 0))
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} PiB"  # yalnızca erişilemez bir yol; tip denetimi için


def human_rate(bps: float) -> str:
    return f"{human_bytes(bps)}/s"


def duration(seconds: float) -> str:
    total = int(max(seconds, 0))
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    parts = []
    if days:
        parts.append(f"{days}g")
    if days or hours:
        parts.append(f"{hours}s")
    parts.append(f"{minutes}dk")
    return " ".join(parts)


def level_for(value: float, warn: float, crit: float) -> str:
    if value >= crit:
        return "crit"
    if value >= warn:
        return "warn"
    return "ok"


def filled_cells(percent: float, width: int) -> int:
    return round(clamp(percent) * width / 100.0)


def bar(percent: float, width: int, g: Glyphs) -> str:
    filled = filled_cells(percent, width)
    return g.full * filled + g.empty * (width - filled)


def sparkline(values: Sequence[float], width: int, g: Glyphs, maxv: Optional[float] = None) -> str:
    if width <= 0:
        return ""
    recent = list(values)[-width:]
    if not recent:
        return ""
    top = maxv if maxv is not None else max(max(recent), 1e-9)
    levels = len(g.spark) - 1
    chars = []
    for v in recent:
        idx = round(clamp(v / top * 100.0, 0.0, 100.0) * levels / 100.0)
        chars.append(g.spark[idx])
    return "".join(chars).rjust(width)


def truncate(text: str, width: int, g: Glyphs) -> str:
    if len(text) <= width:
        return text
    if width <= 1:
        return text[:width]
    return text[: width - 1] + g.ellipsis
