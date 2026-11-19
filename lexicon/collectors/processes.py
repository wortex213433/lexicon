"""Süreç listesi: PID, ad, durum, CPU yüzdesi ve yerleşik bellek (RSS).

CPU yüzdesi `top` ile aynı mantıkla tek çekirdek üzerinden hesaplanır; çok
çekirdekli süreçlerde 100'ü aşabilir.
"""

from __future__ import annotations

import os
from typing import Optional

from ..models import ProcInfo, ProcStats
from .base import Collector, Context, DataUnavailable, read_text


def parse_stat(text: Optional[str]) -> Optional[tuple[str, str, int]]:
    """(ad, durum, toplam_tik) döner. Ad parantezler içinde olabileceği için
    son ')' karakteri aranır."""
    if not text:
        return None
    lpar = text.find("(")
    rpar = text.rfind(")")
    if lpar < 0 or rpar < lpar:
        return None
    name = text[lpar + 1:rpar]
    fields = text[rpar + 1:].split()
    if len(fields) < 13:
        return None
    try:
        state = fields[0]
        ticks = int(fields[11]) + int(fields[12])  # utime + stime
    except ValueError:
        return None
    return name, state, ticks


def parse_rss(statm: Optional[str], page_size: int) -> int:
    if not statm:
        return 0
    parts = statm.split()
    try:
        return int(parts[1]) * page_size
    except (IndexError, ValueError):
        return 0


class ProcessCollector(Collector):
    name = "processes"

    def __init__(self) -> None:
        self._prev_ticks: dict[int, int] = {}
        self._prev_time: Optional[float] = None

    def collect(self, ctx: Context) -> ProcStats:
        try:
            entries = list(os.scandir(ctx.proc))
        except OSError as exc:
            raise DataUnavailable(f"süreç dizini okunamadı: {exc}") from exc

        dt = ctx.now - self._prev_time if self._prev_time is not None else 0.0
        ticks_now: dict[int, int] = {}
        items: list[ProcInfo] = []

        for entry in entries:
            if not entry.name.isdigit():
                continue
            pid = int(entry.name)
            parsed = parse_stat(read_text(ctx.proc / entry.name / "stat"))
            if parsed is None:  # süreç bu arada sonlandı ya da erişim yok
                continue
            name, state, ticks = parsed
            ticks_now[pid] = ticks

            cpu = 0.0
            prev = self._prev_ticks.get(pid)
            if prev is not None and dt > 0:
                cpu = max(ticks - prev, 0) / ctx.clk_tck / dt * 100.0
            rss = parse_rss(read_text(ctx.proc / entry.name / "statm"), ctx.page_size)
            items.append(ProcInfo(pid=pid, name=name, state=state, cpu_percent=cpu, rss_bytes=rss))

        self._prev_ticks = ticks_now
        self._prev_time = ctx.now
        return ProcStats(
            total=len(items),
            running=sum(1 for p in items if p.state == "R"),
            items=items,
        )
