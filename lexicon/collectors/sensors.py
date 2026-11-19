"""Donanım sıcaklık sensörleri: thermal_zone ve hwmon arayüzleri."""

from __future__ import annotations

from ..models import SensorReading
from .base import Collector, Context, read_int, read_text

PLAUSIBLE_RANGE = (-50.0, 150.0)  # bozuk sensör değerlerini ele


class SensorCollector(Collector):
    name = "sensors"

    def collect(self, ctx: Context) -> list[SensorReading]:
        readings: list[SensorReading] = []

        for zone in sorted(ctx.sys.glob("class/thermal/thermal_zone*")):
            temp = read_int(zone / "temp")
            if temp is None:
                continue
            label = (read_text(zone / "type") or zone.name).strip()
            self._add(readings, label, temp / 1000.0)

        for chip_dir in sorted(ctx.sys.glob("class/hwmon/hwmon*")):
            chip = (read_text(chip_dir / "name") or chip_dir.name).strip()
            for input_file in sorted(chip_dir.glob("temp*_input")):
                value = read_int(input_file)
                if value is None:
                    continue
                idx = input_file.name[len("temp"):-len("_input")]
                sub_label = read_text(chip_dir / f"temp{idx}_label")
                label = f"{chip} {sub_label.strip()}" if sub_label else f"{chip} temp{idx}"
                self._add(readings, label, value / 1000.0)

        return readings

    @staticmethod
    def _add(readings: list[SensorReading], label: str, celsius: float) -> None:
        low, high = PLAUSIBLE_RANGE
        if low <= celsius <= high:
            readings.append(SensorReading(label=label, celsius=round(celsius, 1)))
