"""Komut satırı arayüzü.

Örnekler:
  lexicon                    etkileşimli TUI
  lexicon --once             tek bir rapor yazdır ve çık
  lexicon --json --count 5   5 adet JSON snapshot (diğer araçlar için)
  lexicon --plain            TUI yerine düz metin akışı
  lexicon --doctor           bu ortamda hangi kaynakların okunabildiğini göster
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Callable, Optional, Sequence

from . import __version__
from .collectors.base import Context, make_context, read_text
from .config import SORT_KEYS, Config, ConfigError, load_config
from .core.engine import Engine
from .export import to_jsonable
from .platform_info import PlatformInfo, detect_platform
from .ui.dashboard import ViewState
from .ui.format import glyphs_for_locale
from .ui.plain import print_stream, render_plain

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lexicon",
        description="Lexicon: Linux ve Termux için modüler sistem monitörü.",
    )
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--once", action="store_true", help="tek bir rapor yazdır ve çık")
    modes.add_argument("--json", action="store_true", help="snapshot'ları JSON satırları olarak yaz")
    modes.add_argument("--plain", action="store_true", help="TUI yerine düz metin akışı")
    modes.add_argument("--doctor", action="store_true", help="kaynak erişilebilirlik raporu")

    parser.add_argument("--interval", type=float, help="örnekleme aralığı (saniye)")
    parser.add_argument("--count", type=int, help="--json/--plain için örnek sayısı")
    parser.add_argument("--sort", choices=SORT_KEYS, help="süreç sıralama anahtarı")
    parser.add_argument("--config", type=Path, metavar="YOL", help="yapılandırma dosyası")
    parser.add_argument("--width", type=int, help="düz metin çıktısının genişliği")
    parser.add_argument("--version", action="version", version=f"lexicon {__version__}")
    return parser


def _apply_cli_overrides(config: Config, args: argparse.Namespace) -> None:
    if args.interval is not None:
        if not 0.1 <= args.interval <= 60:
            raise ConfigError("--interval 0.1 ile 60 arasında olmalı")
        config.interval = args.interval
    if args.sort is not None:
        config.sort = args.sort


def _sample_gap(config: Config) -> float:
    """Tek seferlik raporlarda CPU/ağ hızlarının oluşması için kısa bekleme."""
    return max(0.3, min(config.interval, 1.0))


def run_once(engine: Engine, config: Config, platform: PlatformInfo, width: Optional[int]) -> int:
    engine.prime()
    time.sleep(_sample_gap(config))
    snap = engine.sample()
    state = _view_state(config, platform, process_rows=config.process_limit)
    print(render_plain(snap, engine.history, state, width=width))
    return 0


def run_json(engine: Engine, count: Optional[int]) -> int:
    for snap in engine.stream(count=count):
        sys.stdout.write(json.dumps(to_jsonable(snap), ensure_ascii=False, separators=(",", ":")) + "\n")
        sys.stdout.flush()
    return 0


def run_plain(engine: Engine, config: Config, platform: PlatformInfo, count: Optional[int]) -> int:
    state = _view_state(config, platform, process_rows=config.process_limit)
    print_stream(engine.stream(count=count), engine.history, state, sys.stdout)
    return 0


def run_tui(engine: Engine, config: Config, platform: PlatformInfo) -> int:
    from .ui import curses_app  # curses yalnızca gerektiğinde içe aktarılır

    return curses_app.run(engine, config, platform.label)


def _view_state(config: Config, platform: PlatformInfo, process_rows: Optional[int] = None) -> ViewState:
    return ViewState(
        sort=config.sort,
        platform_label=platform.label,
        glyphs=glyphs_for_locale(),
        thresholds=config.thresholds,
        process_rows=process_rows,
    )


# --------------------------------------------------------------------------- #
# Doctor
# --------------------------------------------------------------------------- #

def _probe(label: str, ok: bool, detail: str = "") -> str:
    mark = "OK  " if ok else "YOK "
    return f"  [{mark}] {label}" + (f"  — {detail}" if detail else "")


def _first_pid(proc: Path) -> Optional[str]:
    try:
        with os.scandir(proc) as entries:
            return next((e.name for e in entries if e.name.isdigit()), None)
    except OSError:
        return None


def run_doctor(ctx: Context, platform: PlatformInfo, config_path: Optional[Path]) -> int:
    """Her veri kaynağını dener ve hangilerinin bu ortamda kullanılabildiğini raporlar."""
    print(f"Lexicon {__version__} · {platform.label} · {platform.kernel} · {platform.arch} · Python {platform.python}")
    if not platform.supported:
        print("  [UYARI] Lexicon Linux ve Android/Termux için tasarlandı.")
    print()

    def exists_readable(path: Path) -> bool:
        return read_text(path) is not None

    first_pid = _first_pid(ctx.proc)
    freq_ok = bool(list(ctx.sys.glob("devices/system/cpu/cpu[0-9]*/cpufreq/scaling_cur_freq")))
    thermal_ok = bool(list(ctx.sys.glob("class/thermal/thermal_zone*/temp")) or list(ctx.sys.glob("class/hwmon/hwmon*/temp*_input")))
    battery_ok = any(
        (read_text(p / "type") or "").strip() == "Battery"
        for p in (ctx.sys / "class" / "power_supply").glob("*")
    ) if (ctx.sys / "class" / "power_supply").is_dir() else False

    checks: list[tuple[str, bool, str]] = [
        ("CPU kullanımı (/proc/stat)", exists_readable(ctx.proc / "stat"), ""),
        ("CPU yükü (/proc/loadavg)", exists_readable(ctx.proc / "loadavg"), ""),
        ("CPU frekansı (cpufreq)", freq_ok, "izin kısıtlı olabilir"),
        ("RAM / swap (/proc/meminfo)", exists_readable(ctx.proc / "meminfo"), ""),
        ("Bağlama noktaları (/proc/mounts)", exists_readable(ctx.proc / "mounts"), "yoksa kök dizine düşülür"),
        ("Disk G/Ç (/proc/diskstats)", exists_readable(ctx.proc / "diskstats"), ""),
        ("Ağ trafiği (/proc/net/dev)", exists_readable(ctx.proc / "net" / "dev"), ""),
        ("Süreç listesi (/proc/[pid]/stat)", first_pid is not None and exists_readable(ctx.proc / first_pid / "stat"), ""),
        ("Çalışma süresi (/proc/uptime)", exists_readable(ctx.proc / "uptime"), ""),
        ("Sıcaklık sensörleri (thermal/hwmon)", thermal_ok, "Android'de SELinux engelleyebilir"),
        ("Pil durumu (power_supply)", battery_ok, "masaüstü/sunucuda pil olmayabilir"),
    ]
    for label, ok, detail in checks:
        print(_probe(label, ok, "" if ok else detail))

    print()
    cfg_path = config_path or Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "lexicon" / "config.json"
    print(f"Yapılandırma: {cfg_path} ({'bulundu' if cfg_path.exists() else 'yok, varsayılanlar kullanılıyor'})")
    print(f"Kök dizinler: proc={ctx.proc} sys={ctx.sys} etc={ctx.etc}")
    if platform.is_termux and not all(c[1] for c in checks[:7]):
        print("\nİpucu: Termux'ta birçok /proc kaydı kısıtlıdır. Eksik kaynaklar atlanır; "
              "Lexicon kalan verileri göstermeye devam eder.")
    return 0


# --------------------------------------------------------------------------- #
# Giriş
# --------------------------------------------------------------------------- #

def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    platform = detect_platform()
    ctx_factory: Callable[[], Context] = make_context

    if args.doctor:
        return run_doctor(ctx_factory(), platform, args.config)

    try:
        config = load_config(args.config)
        _apply_cli_overrides(config, args)
    except ConfigError as exc:
        print(f"lexicon: yapılandırma hatası: {exc}", file=sys.stderr)
        return 2

    engine = Engine(config, context_factory=ctx_factory)
    try:
        if args.once:
            return run_once(engine, config, platform, args.width)
        if args.json:
            return run_json(engine, args.count)
        if args.plain or not sys.stdout.isatty():  # pipe/log: TUI anlamsız, düz metne geç
            return run_plain(engine, config, platform, args.count)
        return run_tui(engine, config, platform)
    except KeyboardInterrupt:
        return 130
    except RuntimeError as exc:
        print(f"lexicon: {exc}", file=sys.stderr)
        return 1
    except BrokenPipeError:  # `lexicon --json | head` gibi kullanımlar
        try:
            sys.stdout.close()
        finally:
            return 0
