"""CPU kullanımı, çekirdek başına değer, frekans, yük ortalaması ve model."""

from __future__ import annotations

import os
from typing import Optional

from ..models import CpuCore, CpuStats
from .base import Collector, Context, DataUnavailable, read_int, read_required, read_text

Counters = tuple[int, int]  # (idle_toplam, toplam)


def parse_stat(text: str) -> dict[str, Counters]:
    """/proc/stat içindeki 'cpu' ve 'cpuN' satırlarını ayrıştırır."""
    result: dict[str, Counters] = {}
    for line in text.splitlines():
        if not line.startswith("cpu"):
            continue
        parts = line.split()
        try:
            values = [int(v) for v in parts[1:9]]
        except ValueError:
            continue
        if len(values) < 4:
            continue
        values += [0] * (8 - len(values))
        _user, _nice, _system, idle, iowait, _irq, _softirq, _steal = values
        result[parts[0]] = (idle + iowait, sum(values))
    return result


def usage_percent(prev: Counters, cur: Counters) -> float:
    d_total = cur[1] - prev[1]
    d_idle = cur[0] - prev[0]
    if d_total <= 0:
        return 0.0
    busy = 1.0 - d_idle / d_total
    return max(0.0, min(100.0, busy * 100.0))


def parse_loadavg(text: Optional[str]) -> tuple[float, float, float]:
    if not text:
        return (0.0, 0.0, 0.0)
    try:
        a, b, c = (float(x) for x in text.split()[:3])
    except ValueError:
        return (0.0, 0.0, 0.0)
    return (a, b, c)


def parse_model(cpuinfo: str) -> Optional[str]:
    for line in cpuinfo.splitlines():
        key, _, value = line.partition(":")
        if key.strip().lower() in ("model name", "hardware", "cpu model") and value.strip():
            return value.strip()
    return None


class CpuCollector(Collector):
    name = "cpu"

    def __init__(self) -> None:
        self._prev: dict[str, Counters] = {}
        self._model: Optional[str] = None

    def collect(self, ctx: Context) -> CpuStats:
        stat = parse_stat(read_required(ctx.proc / "stat", "/proc/stat"))
        if not stat:
            raise DataUnavailable("/proc/stat içinde CPU satırı bulunamadı")

        percents = {
            label: usage_percent(self._prev[label], cur) if label in self._prev else 0.0
            for label, cur in stat.items()
        }
        self._prev = stat

        freqs = self._frequencies(ctx)
        cores = sorted(
            (
                CpuCore(index=int(label[3:]), percent=percents[label], freq_mhz=freqs.get(int(label[3:])))
                for label in stat
                if label != "cpu" and label[3:].isdigit()
            ),
            key=lambda c: c.index,
        )
        freq_values = [c.freq_mhz for c in cores if c.freq_mhz]
        avg_freq = sum(freq_values) / len(freq_values) if freq_values else None

        return CpuStats(
            model=self._get_model(ctx),
            count=len(cores) or ctx.ncpu,
            percent=percents.get("cpu", 0.0),
            load=parse_loadavg(read_text(ctx.proc / "loadavg")),
            freq_mhz=avg_freq,
            cores=cores,
        )

    def _get_model(self, ctx: Context) -> str:
        if self._model is None:
            model = parse_model(read_text(ctx.proc / "cpuinfo") or "")
            self._model = model or os.uname().machine
        return self._model

    @staticmethod
    def _frequencies(ctx: Context) -> dict[int, float]:
        result: dict[int, float] = {}
        pattern = "devices/system/cpu/cpu[0-9]*/cpufreq/scaling_cur_freq"
        for path in sorted(ctx.sys.glob(pattern)):
            khz = read_int(path)
            index = path.parent.parent.name[3:]
            if khz is not None and index.isdigit():
                result[int(index)] = khz / 1000.0
        return result
