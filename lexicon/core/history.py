"""Sabit boyutlu geçmiş tamponları (sparkline ve trend grafikleri için)."""

from __future__ import annotations

from collections import deque
from typing import Optional

from ..models import Snapshot


class History:
    def __init__(self, size: int = 120) -> None:
        self.size = size
        self._series: dict[str, deque[float]] = {}

    def push(self, key: str, value: Optional[float]) -> None:
        if value is None:
            return
        series = self._series.get(key)
        if series is None:
            series = self._series[key] = deque(maxlen=self.size)
        series.append(float(value))

    def get(self, key: str) -> list[float]:
        return list(self._series.get(key, ()))

    def record(self, snap: Snapshot) -> None:
        if snap.cpu:
            self.push("cpu", snap.cpu.percent)
            self.push("load1", snap.cpu.load[0])
        if snap.memory:
            self.push("mem", snap.memory.percent)
            self.push("swap", snap.memory.swap_percent)
        if snap.network:
            self.push("net_rx", snap.network.rx_bps)
            self.push("net_tx", snap.network.tx_bps)
        if snap.disk:
            self.push("disk_io", sum(d.read_bps + d.write_bps for d in snap.disk.io))
