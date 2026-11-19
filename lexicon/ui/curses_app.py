"""Etkileşimli curses arayüzü.

Tuşlar:
  q / Esc      çıkış
  p            duraklat / devam
  s            sıralamayı değiştir (CPU → BELLEK → PID → AD)
  j / ↓, k / ↑ süreç listesini kaydır
  PgDn / PgUp  10'arlı kaydır, g / Home başa dön
  r            hemen yenile
  + / -        örnekleme aralığını değiştir
"""

from __future__ import annotations

import curses
import time

from ..config import SORT_KEYS, Config
from ..core.engine import Engine
from ..models import Snapshot
from .dashboard import SORT_LABELS, ViewState, build_lines
from .format import Glyphs, glyphs_for_locale, truncate

__all__ = ["run", "MIN_INTERVAL", "MAX_INTERVAL"]

MIN_INTERVAL = 0.2
MAX_INTERVAL = 10.0
MIN_SIZE = (60, 12)  # (genişlik, yükseklik)


def _init_palette() -> dict[str, int]:
    attrs: dict[str, int] = {
        "": 0,
        "dim": curses.A_DIM,
        "bold": curses.A_BOLD,
        "ok": 0,
        "warn": curses.A_BOLD,
        "crit": curses.A_BOLD | curses.A_REVERSE,
        "accent": 0,
        "title": curses.A_BOLD,
        "header": curses.A_REVERSE,
    }
    if not curses.has_colors():
        return attrs

    curses.start_color()
    try:
        curses.use_default_colors()
        background = -1
    except curses.error:
        background = curses.COLOR_BLACK

    pairs = {
        "ok": (curses.COLOR_GREEN, background),
        "warn": (curses.COLOR_YELLOW, background),
        "crit": (curses.COLOR_RED, background),
        "accent": (curses.COLOR_CYAN, background),
        "title": (curses.COLOR_MAGENTA, background),
        "header": (curses.COLOR_BLACK, curses.COLOR_CYAN),
    }
    for index, (name, (fg, bg)) in enumerate(pairs.items(), start=1):
        curses.init_pair(index, fg, bg)
        extra = curses.A_BOLD if name in ("crit", "title", "header") else 0
        attrs[name] = curses.color_pair(index) | extra
    return attrs


def _draw(
    stdscr: "curses._CursesWindow",
    snap: Snapshot,
    engine: Engine,
    state: ViewState,
    attrs: dict[str, int],
    interval: float,
    glyphs: Glyphs,
) -> None:
    height, width = stdscr.getmaxyx()
    stdscr.erase()
    if width < MIN_SIZE[0] or height < MIN_SIZE[1]:
        _safe_add(stdscr, 0, 0, "Terminal çok küçük; en az 60x12 önerilir.", 0)
        stdscr.refresh()
        return

    body_height = height - 1
    lines = build_lines(snap, engine.history, state, width=width - 1, height=body_height)
    for y, line in enumerate(lines[:body_height]):
        x = 0
        for seg in line:
            if seg.text:
                _safe_add(stdscr, y, x, seg.text, attrs.get(seg.style, 0))
                x += len(seg.text)

    mode = "devam" if state.paused else "duraklat"
    footer = (
        f" q çıkış · p {mode} · s sıralama: {SORT_LABELS[state.sort]} · "
        f"j/k kaydır · +/- aralık {interval:.1f}s · r yenile "
    )
    footer = truncate(footer, width - 1, glyphs).ljust(width - 1)
    _safe_add(stdscr, height - 1, 0, footer, attrs["header"])
    stdscr.refresh()


def _safe_add(stdscr, y: int, x: int, text: str, attr: int) -> None:
    try:
        stdscr.addstr(y, x, text, attr)
    except curses.error:
        pass  # ekran sınırı dışına yazım; son hücre ve küçük terminaller için


def _run(stdscr, engine: Engine, config: Config, platform_label: str) -> int:
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    stdscr.keypad(True)
    attrs = _init_palette()
    glyphs = glyphs_for_locale()
    state = ViewState(
        sort=config.sort,
        platform_label=platform_label,
        glyphs=glyphs,
        thresholds=config.thresholds,
    )

    interval = config.interval
    engine.prime()
    snap = engine.sample()
    last = time.monotonic()
    stdscr.timeout(200)  # tuş yanıtları için 5 Hz döngü; örnekleme aralığı ayrıdır

    while True:
        now = time.monotonic()
        if not state.paused and now - last >= interval:
            snap = engine.sample()
            last = now
        _draw(stdscr, snap, engine, state, attrs, interval, glyphs)

        key = stdscr.getch()
        if key == -1:
            continue
        if key in (ord("q"), ord("Q"), 27):
            break
        if key in (ord("p"), ord("P")):
            state.paused = not state.paused
        elif key in (ord("s"), ord("S")):
            state.sort = SORT_KEYS[(SORT_KEYS.index(state.sort) + 1) % len(SORT_KEYS)]
            state.scroll = 0
        elif key in (curses.KEY_DOWN, ord("j")):
            state.scroll += 1
        elif key in (curses.KEY_UP, ord("k")):
            state.scroll = max(0, state.scroll - 1)
        elif key == curses.KEY_NPAGE:
            state.scroll += 10
        elif key == curses.KEY_PPAGE:
            state.scroll = max(0, state.scroll - 10)
        elif key in (curses.KEY_HOME, ord("g")):
            state.scroll = 0
        elif key in (ord("r"), ord("R")):
            snap = engine.sample()
            last = time.monotonic()
        elif key in (ord("+"), ord("=")):
            interval = min(MAX_INTERVAL, round(interval + 0.5, 1))
        elif key in (ord("-"), ord("_")):
            interval = max(MIN_INTERVAL, round(interval - 0.5, 1))
        elif key == curses.KEY_RESIZE:
            stdscr.clear()
    return 0


def run(engine: Engine, config: Config, platform_label: str) -> int:
    """TUI'yi başlatır ve çıkış kodunu döndürür."""
    try:
        return curses.wrapper(_run, engine, config, platform_label)
    except curses.error as exc:  # TERM tanımsız ya da terminal desteklenmiyor
        raise RuntimeError(f"etkileşimli terminal başlatılamadı: {exc}") from exc
