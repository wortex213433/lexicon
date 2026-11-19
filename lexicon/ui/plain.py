"""Düz metin çıktısı: `--once` ve `--plain` modları. Renk ve imleç kontrolü yok;
pipe'lara, loglara ve curses'ün desteklenmediği ortamlara uygundur."""

from __future__ import annotations

import shutil
from typing import Iterable

from ..core.history import History
from ..models import Snapshot
from .dashboard import ViewState, build_lines


def render_plain(snap: Snapshot, history: History, state: ViewState, width: int | None = None) -> str:
    cols = width or shutil.get_terminal_size((100, 24)).columns
    lines = build_lines(snap, history, state, width=min(cols, 120), height=None)
    return "\n".join("".join(seg.text for seg in line).rstrip() for line in lines)


def print_stream(snapshots: Iterable[Snapshot], history: History, state: ViewState, out) -> None:
    for index, snap in enumerate(snapshots):
        if index:
            out.write("\n" + "=" * 60 + "\n\n")
        out.write(render_plain(snap, history, state) + "\n")
        out.flush()
