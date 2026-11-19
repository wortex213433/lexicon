"""Eşik tabanlı uyarılar. Saf fonksiyon: snapshot ve eşiklerden uyarı listesi üretir."""

from __future__ import annotations

from ..config import Thresholds
from ..models import Alert, Snapshot


def _check(
    alerts: list[Alert],
    source: str,
    label: str,
    value: float,
    warn: float,
    crit: float,
    unit: str = "%",
) -> None:
    if value >= crit:
        alerts.append(Alert("crit", source, f"{label} kritik seviyede: {value:.0f}{unit}"))
    elif value >= warn:
        alerts.append(Alert("warn", source, f"{label} yüksek: {value:.0f}{unit}"))


def evaluate(snap: Snapshot, th: Thresholds) -> list[Alert]:
    alerts: list[Alert] = []

    if snap.cpu:
        _check(alerts, "cpu", "CPU", snap.cpu.percent, th.cpu_warn, th.cpu_crit)
    if snap.memory:
        _check(alerts, "memory", "RAM", snap.memory.percent, th.mem_warn, th.mem_crit)
        if snap.memory.swap_total:
            _check(alerts, "swap", "Swap", snap.memory.swap_percent, th.swap_warn, th.swap_crit)
    if snap.disk:
        for mount in snap.disk.mounts:
            _check(alerts, "disk", f"Disk {mount.mountpoint}", mount.percent, th.disk_warn, th.disk_crit)
    for sensor in snap.sensors:
        _check(alerts, "sensor", sensor.label, sensor.celsius, th.temp_warn, th.temp_crit, unit=" °C")
    if snap.battery and snap.battery.status.lower() == "discharging":
        pct = snap.battery.percent
        if pct <= th.battery_crit:
            alerts.append(Alert("crit", "battery", f"Pil çok düşük: {pct:.0f}%"))
        elif pct <= th.battery_low:
            alerts.append(Alert("warn", "battery", f"Pil düşük: {pct:.0f}%"))

    return alerts
