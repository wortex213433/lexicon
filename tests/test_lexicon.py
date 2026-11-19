"""Lexicon birim testleri. Yalnızca standart kütüphane: `python -m unittest`.

Collector testleri sahte bir /proc ve /sys ağacı üzerinde çalışır; böylece
gerçek makinenin durumundan bağımsız, tekrarlanabilir sonuçlar elde edilir.
"""

from __future__ import annotations

import dataclasses
import json
import tempfile
import unittest
from pathlib import Path

from lexicon.collectors import (
    CpuCollector,
    DiskCollector,
    MemoryCollector,
    NetworkCollector,
    ProcessCollector,
    SensorCollector,
    PowerCollector,
    SystemCollector,
)
from lexicon.collectors.base import Context, DataUnavailable
from lexicon.collectors.cpu import parse_stat, usage_percent
from lexicon.collectors.disk import parse_diskstats, parse_mounts
from lexicon.collectors.memory import parse_meminfo
from lexicon.collectors.network import parse_netdev
from lexicon.collectors.processes import parse_rss, parse_stat as parse_proc_stat
from lexicon.config import Config, ConfigError, apply_overrides, validate
from lexicon.core.alerts import evaluate
from lexicon.core.engine import Engine
from lexicon.core.history import History
from lexicon.export import to_jsonable
from lexicon.models import (
    CpuCore,
    CpuStats,
    DiskMount,
    MemStats,
    Snapshot,
)
from lexicon.ui.dashboard import ViewState, build_lines, sort_processes
from lexicon.ui.format import ASCII, UNICODE, bar, duration, human_bytes, sparkline, truncate


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class FakeTree(unittest.TestCase):
    """Her test için geçici bir /proc, /sys, /etc ağacı kurar."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.ctx_now = 100.0
        self.ctx = Context(
            proc=root / "proc",
            sys=root / "sys",
            etc=root / "etc",
            build_prop=root / "system" / "build.prop",
            ncpu=2,
            page_size=4096,
            clk_tck=100,
            now=self.ctx_now,
        )
        (self.ctx.proc / "sys" / "kernel").mkdir(parents=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def advance(self, seconds: float) -> None:
        self.ctx = dataclasses.replace(self.ctx, now=self.ctx.now + seconds)


class ParserTests(unittest.TestCase):
    def test_parse_stat_handles_aggregate_and_cores(self) -> None:
        text = "cpu  100 0 50 800 50 0 0 0 0 0\ncpu0 50 0 25 400 25 0 0 0 0 0\nintr 1\n"
        result = parse_stat(text)
        self.assertEqual(set(result), {"cpu", "cpu0"})
        self.assertEqual(result["cpu"], (850, 1000))

    def test_usage_percent_uses_deltas(self) -> None:
        self.assertAlmostEqual(usage_percent((850, 1000), (1650, 2000)), 20.0)
        self.assertEqual(usage_percent((5, 5), (5, 5)), 0.0)

    def test_meminfo_converts_kb_to_bytes(self) -> None:
        info = parse_meminfo("MemTotal: 2048 kB\nMemAvailable: 1024 kB\nSwapTotal: 0 kB\n")
        self.assertEqual(info["MemTotal"], 2048 * 1024)
        self.assertEqual(info["MemAvailable"], 1024 * 1024)

    def test_mounts_unescape_spaces(self) -> None:
        mounts = parse_mounts("/dev/sda1 /mnt/my\\040disk ext4 rw 0 0\n")
        self.assertEqual(mounts, [("/dev/sda1", "/mnt/my disk", "ext4")])

    def test_diskstats_keeps_whole_disks_only(self) -> None:
        text = (
            "   8  0 sda 1 0 100 0 2 0 200 0 0 0 0\n"
            "   8  1 sda1 1 0 100 0 2 0 200 0 0 0 0\n"
            "   7  0 loop0 1 0 100 0 2 0 200 0 0 0 0\n"
            " 259  0 nvme0n1 1 0 100 0 2 0 300 0 0 0 0\n"
        )
        result = parse_diskstats(text)
        self.assertEqual(set(result), {"sda", "nvme0n1"})
        self.assertEqual(result["sda"], (100, 200))

    def test_netdev_skips_headers(self) -> None:
        text = (
            "Inter-|   Receive\n face |bytes\n"
            "  eth0: 1000 10 1 2 0 0 0 0 500 5 3 4 0 0 0 0\n"
        )
        result = parse_netdev(text)
        self.assertEqual(result["eth0"]["rx_bytes"], 1000)
        self.assertEqual(result["eth0"]["tx_bytes"], 500)
        self.assertEqual(result["eth0"]["tx_errs"], 3)

    def test_proc_stat_survives_parentheses_in_name(self) -> None:
        line = "42 (my (weird) name) S 1 42 42 0 -1 0 0 0 0 0 7 3 0 0 20 0 1 0 1 0 0"
        comm, state, ticks = parse_proc_stat(line)
        self.assertEqual(comm, "my (weird) name")
        self.assertEqual(state, "S")
        self.assertEqual(ticks, 10)

    def test_rss_from_statm(self) -> None:
        self.assertEqual(parse_rss("1000 250 0 0 0 0 0", 4096), 250 * 4096)
        self.assertEqual(parse_rss(None, 4096), 0)


class CollectorTests(FakeTree):
    def test_cpu_reports_percent_frequency_and_load(self) -> None:
        write(self.ctx.proc / "stat", "cpu  100 0 50 850 0 0 0 0\ncpu0 50 0 25 425 0 0 0 0\ncpu1 50 0 25 425 0 0 0 0\n")
        write(self.ctx.proc / "loadavg", "0.50 0.40 0.30 1/200 999\n")
        write(self.ctx.proc / "cpuinfo", "processor : 0\nmodel name : Test CPU @ 2GHz\n")
        for core in (0, 1):
            write(self.ctx.sys / "devices/system/cpu" / f"cpu{core}" / "cpufreq" / "scaling_cur_freq", "1800000\n")

        collector = CpuCollector()
        first = collector.collect(self.ctx)
        self.assertEqual(first.percent, 0.0)  # ilk örnek referans

        self.advance(1.0)
        write(self.ctx.proc / "stat", "cpu  200 0 100 1700 0 0 0 0\ncpu0 100 0 50 850 0 0 0 0\ncpu1 100 0 50 850 0 0 0 0\n")
        stats = collector.collect(self.ctx)
        # toplam Δ=1000, boşta Δ=850 → meşgul %15
        self.assertAlmostEqual(stats.percent, 15.0, places=3)
        self.assertEqual(stats.model, "Test CPU @ 2GHz")
        self.assertEqual(len(stats.cores), 2)
        self.assertAlmostEqual(stats.freq_mhz, 1800.0)
        self.assertEqual(stats.load, (0.5, 0.4, 0.3))

    def test_cpu_raises_when_stat_missing(self) -> None:
        with self.assertRaises(DataUnavailable):
            CpuCollector().collect(self.ctx)

    def test_memory_prefers_mem_available(self) -> None:
        write(self.ctx.proc / "meminfo",
              "MemTotal: 1000 kB\nMemFree: 100 kB\nMemAvailable: 400 kB\nBuffers: 10 kB\n"
              "Cached: 200 kB\nSwapTotal: 500 kB\nSwapFree: 250 kB\n")
        stats = MemoryCollector().collect(self.ctx)
        self.assertAlmostEqual(stats.percent, 60.0)
        self.assertAlmostEqual(stats.swap_percent, 50.0)

    def test_network_rates_from_counter_deltas(self) -> None:
        base = "Inter-|\n face |\n"
        write(self.ctx.proc / "net" / "dev", base + "  wlan0: 1000 0 0 0 0 0 0 0 1000 0 0 0 0 0 0 0\n  lo: 5 0 0 0 0 0 0 0 5 0 0 0 0 0 0 0\n")
        write(self.ctx.sys / "class/net/wlan0/operstate", "up\n")
        collector = NetworkCollector()
        collector.collect(self.ctx)
        self.advance(2.0)
        write(self.ctx.proc / "net" / "dev", base + "  wlan0: 3000 0 0 0 0 0 0 0 5000 0 0 0 0 0 0 0\n  lo: 5 0 0 0 0 0 0 0 5 0 0 0 0 0 0 0\n")
        stats = collector.collect(self.ctx)
        self.assertEqual([i.name for i in stats.ifaces], ["wlan0"])
        self.assertAlmostEqual(stats.ifaces[0].rx_bps, 1000.0)
        self.assertAlmostEqual(stats.ifaces[0].tx_bps, 2000.0)
        self.assertEqual(stats.ifaces[0].state, "up")

    def test_process_cpu_and_running_count(self) -> None:
        write(self.ctx.proc / "1" / "stat", "1 (init) S " + " ".join(["0"] * 10) + " 100 100 0 0 20 0 1 0 1 0 0\n")
        write(self.ctx.proc / "1" / "statm", "100 50 0 0 0 0 0\n")
        write(self.ctx.proc / "2" / "stat", "2 (busy) R " + " ".join(["0"] * 10) + " 0 0 0 0 20 0 1 0 1 0 0\n")
        write(self.ctx.proc / "2" / "statm", "100 10 0 0 0 0 0\n")
        write(self.ctx.proc / "cpuinfo", "")  # gereksiz ama boş olması zararsız
        collector = ProcessCollector()
        collector.collect(self.ctx)

        self.advance(1.0)
        write(self.ctx.proc / "2" / "stat", "2 (busy) R " + " ".join(["0"] * 10) + " 50 50 0 0 20 0 1 0 1 0 0\n")
        stats = collector.collect(self.ctx)
        busy = next(p for p in stats.items if p.pid == 2)
        self.assertAlmostEqual(busy.cpu_percent, 100.0)  # 100 tik / 100 tck / 1 s
        self.assertEqual(stats.running, 1)
        self.assertEqual(busy.rss_bytes, 10 * 4096)

    def test_sensors_read_thermal_and_hwmon(self) -> None:
        write(self.ctx.sys / "class/thermal/thermal_zone0/type", "cpu-thermal\n")
        write(self.ctx.sys / "class/thermal/thermal_zone0/temp", "52000\n")
        write(self.ctx.sys / "class/hwmon/hwmon0/name", "nvme\n")
        write(self.ctx.sys / "class/hwmon/hwmon0/temp1_input", "41500\n")
        write(self.ctx.sys / "class/hwmon/hwmon0/temp1_label", "Composite\n")
        readings = SensorCollector().collect(self.ctx)
        labels = {r.label: r.celsius for r in readings}
        self.assertEqual(labels["cpu-thermal"], 52.0)
        self.assertEqual(labels["nvme Composite"], 41.5)

    def test_battery_absent_returns_none(self) -> None:
        self.assertIsNone(PowerCollector().collect(self.ctx))

    def test_battery_present(self) -> None:
        write(self.ctx.sys / "class/power_supply/BAT0/type", "Battery\n")
        write(self.ctx.sys / "class/power_supply/BAT0/capacity", "18\n")
        write(self.ctx.sys / "class/power_supply/BAT0/status", "Discharging\n")
        battery = PowerCollector().collect(self.ctx)
        self.assertEqual((battery.percent, battery.status), (18.0, "Discharging"))

    def test_system_uses_os_release_and_build_prop(self) -> None:
        write(self.ctx.proc / "uptime", "3600.5 100.0\n")
        write(self.ctx.proc / "sys/kernel/hostname", "phone\n")
        write(self.ctx.proc / "sys/kernel/osrelease", "5.10.0\n")
        write(self.ctx.etc / "os-release", 'NAME=Fedora\nPRETTY_NAME="Fedora Linux 40"\n')
        write(self.ctx.build_prop, "ro.product.manufacturer=Acme\nro.product.model=Zed 9\n")
        info = SystemCollector().collect(self.ctx)
        self.assertEqual(info.hostname, "phone")
        self.assertEqual(info.os_name, "Fedora Linux 40")
        self.assertEqual(info.device, "Acme Zed 9")
        self.assertEqual(info.uptime_s, 3600.5)

    def test_disk_collector_uses_injected_statvfs(self) -> None:
        write(self.ctx.proc / "mounts", "/dev/sda1 / ext4 rw 0 0\nproc /proc proc rw 0 0\ntmpfs /tmp tmpfs rw 0 0\n")
        write(self.ctx.proc / "diskstats", "   8  0 sda 1 0 100 0 2 0 200 0 0 0 0\n")

        class FakeStat:
            f_blocks = 1000
            f_bfree = 300
            f_bavail = 250
            f_frsize = 4096

        collector = DiskCollector(statvfs=lambda _path: FakeStat())
        collector.collect(self.ctx)
        self.advance(1.0)
        write(self.ctx.proc / "diskstats", "   8  0 sda 1 0 100 0 2 0 300 0 0 0 0\n")
        stats = collector.collect(self.ctx)
        self.assertEqual([m.mountpoint for m in stats.mounts], ["/"])
        # 1000 blok toplam, 300 boş → used=700 → %70
        self.assertAlmostEqual(stats.mounts[0].percent, 70.0, places=3)
        self.assertEqual(stats.io[0].write_bps, 100 * 512.0)

    def test_disk_raises_without_mounts_file(self) -> None:
        with self.assertRaises(DataUnavailable):
            DiskCollector(statvfs=lambda _p: None).collect(self.ctx)


class EngineTests(FakeTree):
    def test_failing_collector_is_isolated(self) -> None:
        class Boom:
            name = "boom"

            def collect(self, ctx):
                raise ValueError("kaput")

        class Ok:
            name = "system"

            def collect(self, ctx):
                from lexicon.models import SystemInfo
                return SystemInfo("h", "os", "k", "x86_64")

        engine = Engine(Config(), collectors=[Boom(), Ok()], context_factory=lambda: self.ctx)
        snap = engine.sample()
        self.assertIsNotNone(snap.system)
        self.assertIn("boom", snap.errors)
        self.assertIn("ValueError", snap.errors["boom"])

    def test_prime_does_not_record_history(self) -> None:
        write(self.ctx.proc / "stat", "cpu  100 0 50 850 0 0 0 0\n")
        write(self.ctx.proc / "loadavg", "0.1 0.1 0.1 1/1 1\n")
        engine = Engine(Config(), collectors=[CpuCollector()], context_factory=lambda: self.ctx)
        engine.prime()
        self.assertEqual(engine.history.get("cpu"), [])
        engine.sample()
        self.assertEqual(len(engine.history.get("cpu")), 1)


class AlertTests(unittest.TestCase):
    def test_thresholds_produce_levels(self) -> None:
        from lexicon.config import Thresholds
        snap = Snapshot(
            timestamp=0,
            cpu=CpuStats(model="m", count=1, percent=97.0, load=(0, 0, 0)),
            memory=MemStats(total=100, available=50, cached=0, buffers=0, swap_total=0, swap_used=0),
            disk=None,
        )
        alerts = evaluate(snap, Thresholds())
        self.assertEqual([(a.source, a.level) for a in alerts], [("cpu", "crit")])

    def test_low_battery_only_when_discharging(self) -> None:
        from lexicon.config import Thresholds
        from lexicon.models import BatteryInfo
        snap = Snapshot(timestamp=0, battery=BatteryInfo("BAT0", 8.0, "Charging"))
        self.assertEqual(evaluate(snap, Thresholds()), [])
        snap.battery = BatteryInfo("BAT0", 8.0, "Discharging")
        self.assertEqual(evaluate(snap, Thresholds())[0].level, "crit")


class ConfigTests(unittest.TestCase):
    def test_overrides_apply_and_validate(self) -> None:
        config = Config()
        apply_overrides(config, {"interval": 2, "thresholds": {"cpu_warn": 70}, "sort": "mem"})
        self.assertEqual(config.interval, 2.0)
        self.assertEqual(config.thresholds.cpu_warn, 70.0)
        self.assertEqual(config.sort, "mem")

    def test_unknown_key_is_rejected(self) -> None:
        with self.assertRaises(ConfigError):
            apply_overrides(Config(), {"intervall": 1})

    def test_bad_interval_rejected(self) -> None:
        with self.assertRaises(ConfigError):
            validate(Config(interval=0))

    def test_bool_is_not_a_number(self) -> None:
        with self.assertRaises(ConfigError):
            apply_overrides(Config(), {"interval": True})


class RenderTests(unittest.TestCase):
    def _snapshot(self) -> Snapshot:
        from lexicon.models import (
            DiskIO,
            DiskStats,
            NetIface,
            NetStats,
            ProcInfo,
            ProcStats,
            SensorReading,
            SystemInfo,
        )
        return Snapshot(
            timestamp=1_700_000_000,
            system=SystemInfo("host", "Linux", "6.1", "aarch64", uptime_s=93784, device="Acme Zed"),
            cpu=CpuStats("Cortex-A55", 4, 42.0, (0.5, 0.4, 0.3), 1800.0,
                         [CpuCore(i, 40.0 + i, 1800.0) for i in range(4)]),
            memory=MemStats(total=8 * 1024**3, available=3 * 1024**3, cached=1024**3, buffers=0,
                            swap_total=2 * 1024**3, swap_used=1024**3),
            disk=DiskStats(
                mounts=[DiskMount("/", "sda1", "ext4", 100 * 1024**3, 40 * 1024**3, 60 * 1024**3)],
                io=[DiskIO("sda", 1024.0, 2048.0)],
            ),
            network=NetStats([NetIface("wlan0", 1e6, 2e5, 10**9, 10**8, state="up")]),
            processes=ProcStats(
                total=3, running=1,
                items=[
                    ProcInfo(1, "init", "S", 0.0, 1000),
                    ProcInfo(2, "node", "R", 23.0, 120 * 1024**2),
                    ProcInfo(3, "bash", "S", 1.0, 12 * 1024**2),
                ],
            ),
            sensors=[SensorReading("cpu-thermal", 61.0)],
            errors={"sensors": "örnek not"},
        )

    def test_build_lines_respects_width(self) -> None:
        snap = self._snapshot()
        state = ViewState(glyphs=ASCII)
        for width in (60, 80, 120):
            lines = build_lines(snap, History(), state, width=width, height=None)
            for line in lines:
                self.assertLessEqual(sum(len(s.text) for s in line), max(width, 40))

    def test_process_table_respects_height(self) -> None:
        snap = self._snapshot()
        lines = build_lines(snap, History(), ViewState(glyphs=ASCII), width=100, height=30)
        text = "\n".join("".join(s.text for s in line) for line in lines)
        self.assertIn("node", text)
        self.assertLessEqual(len(lines), len(build_lines(snap, History(), ViewState(glyphs=ASCII), width=100)))

    def test_sort_by_memory_puts_biggest_first(self) -> None:
        snap = self._snapshot()
        ordered = sort_processes(snap.processes.items, "mem")
        self.assertEqual(ordered[0].name, "node")

    def test_json_export_is_serializable_and_has_derived_fields(self) -> None:
        snap = self._snapshot()
        data = to_jsonable(snap)
        json.dumps(data)  # hata verirse test başarısız olur
        self.assertEqual(data["schema"], 1)
        self.assertAlmostEqual(data["memory"]["percent"], 62.5)

    def test_format_helpers(self) -> None:
        self.assertEqual(human_bytes(1536), "1.5 KiB")
        self.assertEqual(duration(93784), "1g 2s 3dk")
        self.assertEqual(duration(59), "0dk")
        self.assertEqual(bar(50, 10, ASCII), "#####.....")
        self.assertEqual(truncate("abcdefgh", 5, UNICODE), "abcd…")
        self.assertEqual(len(sparkline([1, 2, 3], 6, UNICODE)), 6)


if __name__ == "__main__":
    unittest.main()
