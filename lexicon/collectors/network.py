"""Ağ arayüzleri: anlık hız, toplam trafik, hata ve düşen paket sayıları."""

from __future__ import annotations

from typing import Optional

from ..models import NetIface, NetStats
from .base import Collector, Context, read_required, read_text

SKIP_IFACES = frozenset({"lo"})


def parse_netdev(text: str) -> dict[str, dict[str, int]]:
    """/proc/net/dev satırlarını arayüz başına sözlüğe çevirir."""
    out: dict[str, dict[str, int]] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue  # başlık satırları
        name, _, rest = line.partition(":")
        fields = rest.split()
        if len(fields) < 12:
            continue
        try:
            v = [int(x) for x in fields[:12]]
        except ValueError:
            continue
        out[name.strip()] = {
            "rx_bytes": v[0],
            "rx_errs": v[2],
            "rx_drop": v[3],
            "tx_bytes": v[8],
            "tx_errs": v[10],
            "tx_drop": v[11],
        }
    return out


class NetworkCollector(Collector):
    name = "network"

    def __init__(self) -> None:
        self._prev: Optional[tuple[float, dict[str, dict[str, int]]]] = None

    def collect(self, ctx: Context) -> NetStats:
        counters = parse_netdev(read_required(ctx.proc / "net" / "dev", "/proc/net/dev"))
        prev = self._prev
        self._prev = (ctx.now, counters)
        dt = ctx.now - prev[0] if prev else 0.0

        ifaces = []
        for name in sorted(counters):
            if name in SKIP_IFACES:
                continue
            cur = counters[name]
            rx_bps = tx_bps = 0.0
            if prev and dt > 0 and name in prev[1]:
                old = prev[1][name]
                rx_bps = max(cur["rx_bytes"] - old["rx_bytes"], 0) / dt
                tx_bps = max(cur["tx_bytes"] - old["tx_bytes"], 0) / dt
            state = (read_text(ctx.sys / "class" / "net" / name / "operstate") or "unknown").strip()
            ifaces.append(
                NetIface(
                    name=name,
                    rx_bps=rx_bps,
                    tx_bps=tx_bps,
                    rx_total=cur["rx_bytes"],
                    tx_total=cur["tx_bytes"],
                    errors=cur["rx_errs"] + cur["tx_errs"],
                    drops=cur["rx_drop"] + cur["tx_drop"],
                    state=state,
                )
            )
        return NetStats(ifaces=ifaces)
