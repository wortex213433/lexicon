"""RAM ve swap kullanımı (/proc/meminfo)."""

from __future__ import annotations

from ..models import MemStats
from .base import Collector, Context, DataUnavailable, read_required


def parse_meminfo(text: str) -> dict[str, int]:
    """Değerleri bayt cinsine çevirir."""
    out: dict[str, int] = {}
    for line in text.splitlines():
        key, sep, rest = line.partition(":")
        if not sep:
            continue
        fields = rest.split()
        if not fields:
            continue
        try:
            value = int(fields[0])
        except ValueError:
            continue
        unit = fields[1].lower() if len(fields) > 1 else "kb"
        out[key.strip()] = value * 1024 if unit == "kb" else value
    return out


class MemoryCollector(Collector):
    name = "memory"

    def collect(self, ctx: Context) -> MemStats:
        info = parse_meminfo(read_required(ctx.proc / "meminfo", "/proc/meminfo"))
        total = info.get("MemTotal")
        if not total:
            raise DataUnavailable("MemTotal /proc/meminfo içinde yok")

        buffers = info.get("Buffers", 0)
        cached = info.get("Cached", 0) + info.get("SReclaimable", 0)
        available = info.get("MemAvailable")
        if available is None:  # Çok eski çekirdekler için yedek hesap
            available = info.get("MemFree", 0) + buffers + cached

        swap_total = info.get("SwapTotal", 0)
        swap_free = info.get("SwapFree", 0)
        return MemStats(
            total=total,
            available=min(available, total),
            cached=cached,
            buffers=buffers,
            swap_total=swap_total,
            swap_used=max(swap_total - swap_free, 0),
        )
