"""Snapshot ve alt yapıların veri modelleri.

Bu modüldeki sınıflar saf veri taşır; I/O içermez. Collector'lar bunları
doldurur, UI ve dışa aktarım katmanları ise yalnızca okur.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


def _percent(part: float, whole: float) -> float:
    return 100.0 * part / whole if whole > 0 else 0.0


@dataclass
class SystemInfo:
    hostname: str
    os_name: str
    kernel: str
    arch: str
    uptime_s: Optional[float] = None
    device: Optional[str] = None


@dataclass
class CpuCore:
    index: int
    percent: float
    freq_mhz: Optional[float] = None


@dataclass
class CpuStats:
    model: str
    count: int
    percent: float
    load: tuple[float, float, float]
    freq_mhz: Optional[float] = None
    cores: list[CpuCore] = field(default_factory=list)


@dataclass
class MemStats:
    total: int
    available: int
    cached: int
    buffers: int
    swap_total: int
    swap_used: int

    @property
    def used(self) -> int:
        return max(self.total - self.available, 0)

    @property
    def percent(self) -> float:
        return _percent(self.used, self.total)

    @property
    def swap_percent(self) -> float:
        return _percent(self.swap_used, self.swap_total)


@dataclass
class DiskMount:
    mountpoint: str
    device: str
    fstype: str
    total: int
    used: int
    free: int

    @property
    def percent(self) -> float:
        return _percent(self.used, self.total)


@dataclass
class DiskIO:
    device: str
    read_bps: float
    write_bps: float


@dataclass
class DiskStats:
    mounts: list[DiskMount] = field(default_factory=list)
    io: list[DiskIO] = field(default_factory=list)


@dataclass
class NetIface:
    name: str
    rx_bps: float
    tx_bps: float
    rx_total: int
    tx_total: int
    errors: int = 0
    drops: int = 0
    state: str = "unknown"


@dataclass
class NetStats:
    ifaces: list[NetIface] = field(default_factory=list)

    @property
    def rx_bps(self) -> float:
        return sum(i.rx_bps for i in self.ifaces)

    @property
    def tx_bps(self) -> float:
        return sum(i.tx_bps for i in self.ifaces)


@dataclass
class ProcInfo:
    pid: int
    name: str
    state: str
    cpu_percent: float
    rss_bytes: int


@dataclass
class ProcStats:
    total: int
    running: int
    items: list[ProcInfo] = field(default_factory=list)


@dataclass
class SensorReading:
    label: str
    celsius: float


@dataclass
class BatteryInfo:
    name: str
    percent: float
    status: str


@dataclass
class Alert:
    level: str  # "warn" | "crit"
    source: str
    message: str


@dataclass
class Snapshot:
    timestamp: float
    system: Optional[SystemInfo] = None
    cpu: Optional[CpuStats] = None
    memory: Optional[MemStats] = None
    disk: Optional[DiskStats] = None
    network: Optional[NetStats] = None
    processes: Optional[ProcStats] = None
    sensors: list[SensorReading] = field(default_factory=list)
    battery: Optional[BatteryInfo] = None
    alerts: list[Alert] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)
