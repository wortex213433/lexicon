"""Veri kaynakları (collector'lar). Yeni bir modül eklemek için `Collector`
sınıfından türetip `build_collectors` listesine eklemek yeterlidir."""

from __future__ import annotations

from .base import Collector, Context, DataUnavailable, make_context
from .cpu import CpuCollector
from .disk import DiskCollector
from .memory import MemoryCollector
from .network import NetworkCollector
from .power import PowerCollector
from .processes import ProcessCollector
from .sensors import SensorCollector
from .system import SystemCollector


def build_collectors() -> list[Collector]:
    return [
        SystemCollector(),
        CpuCollector(),
        MemoryCollector(),
        DiskCollector(),
        NetworkCollector(),
        ProcessCollector(),
        SensorCollector(),
        PowerCollector(),
    ]


__all__ = [
    "Collector",
    "Context",
    "DataUnavailable",
    "make_context",
    "build_collectors",
]
