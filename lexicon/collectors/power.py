"""Batarya durumu (/sys/class/power_supply). Batarya yoksa None döner."""

from __future__ import annotations

from typing import Optional

from ..models import BatteryInfo
from .base import Collector, Context, read_int, read_text


class PowerCollector(Collector):
    name = "battery"

    def collect(self, ctx: Context) -> Optional[BatteryInfo]:
        base = ctx.sys / "class" / "power_supply"
        if not base.is_dir():
            return None
        for supply in sorted(base.iterdir()):
            if (read_text(supply / "type") or "").strip() != "Battery":
                continue
            capacity = read_int(supply / "capacity")
            if capacity is None:
                continue
            status = (read_text(supply / "status") or "Unknown").strip()
            return BatteryInfo(name=supply.name, percent=float(capacity), status=status)
        return None
