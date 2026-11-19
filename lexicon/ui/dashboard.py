"""Dashboard düzeni. Saf fonksiyonlar: snapshot + geçmiş + görünüm durumu → satırlar.

Çıktı bir `Line` listesidir; her `Seg` bir metin parçası ve bir stil adı taşır.
Stiller (`ok`, `warn`, `crit`, `dim` ...) TUI'de renge, düz metinde yok sayılır.
Bu ayrım sayesinde aynı düzen hem curses hem de `--once` çıktısında kullanılır.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from ..config import Thresholds
from ..core.history import History
from ..models import ProcInfo, Snapshot
from .format import (
    UNICODE,
    Glyphs,
    duration,
    filled_cells,
    human_bytes,
    human_rate,
    level_for,
    sparkline,
    truncate,
)

SORT_LABELS = {"cpu": "CPU", "mem": "BELLEK", "pid": "PID", "name": "AD"}


@dataclass(frozen=True)
class Seg:
    text: str
    style: str = ""


Line = list  # list[Seg]


@dataclass
class ViewState:
    sort: str = "cpu"
    scroll: int = 0
    paused: bool = False
    platform_label: str = "Linux"
    glyphs: Glyphs = UNICODE
    thresholds: Thresholds = field(default_factory=Thresholds)
    process_rows: Optional[int] = None  # None: ekrana sığdığı kadar


# --------------------------------------------------------------------------- #
# Yardımcılar
# --------------------------------------------------------------------------- #

def sort_processes(items: list[ProcInfo], key: str) -> list[ProcInfo]:
    if key == "mem":
        return sorted(items, key=lambda p: (-p.rss_bytes, p.pid))
    if key == "pid":
        return sorted(items, key=lambda p: p.pid)
    if key == "name":
        return sorted(items, key=lambda p: (p.name.lower(), p.pid))
    return sorted(items, key=lambda p: (-p.cpu_percent, -p.rss_bytes, p.pid))


def _bar_width(width: int) -> int:
    return min(30, max(10, width - 60))


def _spark_line(label: str, values: list[float], width: int, g: Glyphs, maxv: Optional[float] = None) -> Optional[Line]:
    """Geçmiş verisi yoksa (ör. tek seferlik rapor) satır üretmez."""
    if not values:
        return None
    return [Seg(label, "dim"), Seg(sparkline(values, width - len(label), g, maxv=maxv), "accent")]


def _bar(percent: float, width: int, g: Glyphs, style: str) -> list[Seg]:
    filled = filled_cells(percent, width)
    return [Seg(g.full * filled, style), Seg(g.empty * (width - filled), "dim")]


def _title(text: str, width: int) -> Line:
    head = f"── {text} "
    return [Seg(head, "title"), Seg("─" * max(width - len(head), 0), "dim")]


def _warn(text: str) -> Line:
    return [Seg(text, "warn")]


def _append_opt(out: list[Line], line: Optional[Line]) -> None:
    if line is not None:
        out.append(line)


def _fit(line: Line, width: int) -> Line:
    out: Line = []
    used = 0
    for seg in line:
        if used >= width:
            break
        text = seg.text[: width - used]
        out.append(Seg(text, seg.style))
        used += len(text)
    return out


# --------------------------------------------------------------------------- #
# Bölümler
# --------------------------------------------------------------------------- #

def _header(snap: Snapshot, state: ViewState) -> list[Line]:
    g = state.glyphs
    s = snap.system
    host = s.hostname if s else "?"
    line1: Line = [
        Seg(" LEXICON ", "header"),
        Seg(
            f" {host} {g.dot} {state.platform_label} {g.dot} "
            f"{s.os_name if s else '?'} {g.dot} çekirdek {s.kernel if s else '?'}"
            + (f" {s.arch}" if s else ""),
            "bold",
        ),
    ]
    facts = []
    if s and s.uptime_s is not None:
        facts.append(f"açık {duration(s.uptime_s)}")
    if snap.cpu:
        l1, l5, l15 = snap.cpu.load
        facts.append(f"yük {l1:.2f} {l5:.2f} {l15:.2f}")
    if snap.processes:
        facts.append(f"süreç {snap.processes.total} ({snap.processes.running} çalışıyor)")
    facts.append(time.strftime("%H:%M:%S", time.localtime(snap.timestamp)))
    line2: Line = [Seg(" " + f" {g.dot} ".join(facts), "dim")]
    lines = [line1, line2]
    if s and s.device:
        lines.append([Seg(f" cihaz: {s.device}", "dim")])
    return lines


def _cpu(snap: Snapshot, history: History, state: ViewState, width: int) -> list[Line]:
    g, th = state.glyphs, state.thresholds
    cpu = snap.cpu
    model = f" · {cpu.model} · {cpu.count} çekirdek" if cpu else ""
    out: list[Line] = [_title(f"CPU{model}", width)]
    if cpu is None:
        return out + [_warn("CPU verisi yok")]

    bw = _bar_width(width)
    style = level_for(cpu.percent, th.cpu_warn, th.cpu_crit)
    freq = f"   frekans {cpu.freq_mhz:.0f} MHz" if cpu.freq_mhz else ""
    out.append(
        [Seg("Toplam  ", "bold"), *_bar(cpu.percent, bw, g, style),
         Seg(f" {cpu.percent:5.1f}%", "bold"), Seg(freq, "dim")]
    )

    cols = max(1, width // 22)
    for start in range(0, len(cpu.cores), cols):
        row: Line = []
        for core in cpu.cores[start:start + cols]:
            core_style = level_for(core.percent, th.cpu_warn, th.cpu_crit)
            row.append(Seg(f"{core.index:>3} ", "dim"))
            row += _bar(core.percent, 8, g, core_style)
            row.append(Seg(f" {core.percent:5.1f}%  ", "dim"))
        out.append(row)

    _append_opt(out, _spark_line("geçmiş ", history.get("cpu"), width, g, maxv=100.0))
    return out


def _memory(snap: Snapshot, history: History, state: ViewState, width: int) -> list[Line]:
    g, th = state.glyphs, state.thresholds
    out: list[Line] = [_title("BELLEK", width)]
    mem = snap.memory
    if mem is None:
        return out + [_warn("RAM verisi yok")]

    bw = _bar_width(width)
    out.append([
        Seg("RAM      ", "bold"),
        *_bar(mem.percent, bw, g, level_for(mem.percent, th.mem_warn, th.mem_crit)),
        Seg(f" {mem.percent:5.1f}%", "bold"),
        Seg(f"  {human_bytes(mem.used)} / {human_bytes(mem.total)}"
            f"  (önbellek {human_bytes(mem.cached)})", "dim"),
    ])
    swap_style = level_for(mem.swap_percent, th.swap_warn, th.swap_crit)
    swap_note = (f"  {human_bytes(mem.swap_used)} / {human_bytes(mem.swap_total)}"
                 if mem.swap_total else "  swap yok")
    out.append([
        Seg("SWAP     ", "bold"),
        *_bar(mem.swap_percent, bw, g, swap_style),
        Seg(f" {mem.swap_percent:5.1f}%", "bold"),
        Seg(swap_note, "dim"),
    ])
    _append_opt(out, _spark_line("geçmiş  ", history.get("mem"), width, g, maxv=100.0))
    return out


def _disk(snap: Snapshot, state: ViewState, width: int) -> list[Line]:
    g, th = state.glyphs, state.thresholds
    out: list[Line] = [_title("DİSK", width)]
    disk = snap.disk
    if disk is None:
        return out + [_warn("Disk verisi yok")]

    bw = min(20, _bar_width(width))
    if not disk.mounts:
        out.append([Seg("Bağlama noktası bulunamadı", "dim")])
    for mount in disk.mounts[:8]:
        style = level_for(mount.percent, th.disk_warn, th.disk_crit)
        label = truncate(mount.mountpoint, 18, g).ljust(18)
        out.append([
            Seg(f"{label} ", "bold"),
            *_bar(mount.percent, bw, g, style),
            Seg(f" {mount.percent:5.1f}%  {human_bytes(mount.used)} / {human_bytes(mount.total)}"
                f"  {mount.fstype}", "dim"),
        ])

    if disk.io:
        read = sum(d.read_bps for d in disk.io)
        write = sum(d.write_bps for d in disk.io)
        out.append([Seg("G/Ç      ", "bold"),
                    Seg(f"{g.down} okuma {human_rate(read)}   {g.up} yazma {human_rate(write)}", "accent")])
        busiest = sorted(disk.io, key=lambda d: -(d.read_bps + d.write_bps))[:3]
        for d in busiest:
            out.append([Seg(f"  {d.device:<10} {g.down} {human_rate(d.read_bps)}  "
                            f"{g.up} {human_rate(d.write_bps)}", "dim")])
    return out


def _network(snap: Snapshot, history: History, state: ViewState, width: int) -> list[Line]:
    g = state.glyphs
    out: list[Line] = [_title("AĞ", width)]
    net = snap.network
    if net is None:
        return out + [_warn("Ağ verisi yok")]
    if not net.ifaces:
        out.append([Seg("Arayüz bulunamadı", "dim")])

    for iface in net.ifaces:
        row: Line = [
            Seg(f"{iface.name:<10} ", "bold"),
            Seg(f"{g.down} {human_rate(iface.rx_bps):>13}  ", "accent"),
            Seg(f"{g.up} {human_rate(iface.tx_bps):>13}  ", "accent"),
            Seg(f"toplam {g.down}{human_bytes(iface.rx_total)} {g.up}{human_bytes(iface.tx_total)}  ",
                "dim"),
            Seg(iface.state, "ok" if iface.state == "up" else "dim"),
        ]
        if iface.errors or iface.drops:
            row.append(Seg(f"  hata {iface.errors} düşen {iface.drops}", "warn"))
        out.append(row)

    _append_opt(out, _spark_line(f"geçmiş {g.down} ", history.get("net_rx"), width, g))
    return out


def _sensors(snap: Snapshot, state: ViewState, width: int) -> list[Line]:
    g, th = state.glyphs, state.thresholds
    out: list[Line] = [_title("SICAKLIK & PİL", width)]
    hottest = sorted(snap.sensors, key=lambda s: -s.celsius)[:6]
    if not hottest:
        out.append([Seg("Sıcaklık sensörü okunamadı (Android/Termux'ta kısıtlı olabilir)", "dim")])
    for sensor in hottest:
        style = level_for(sensor.celsius, th.temp_warn, th.temp_crit)
        out.append([
            Seg(f"{truncate(sensor.label, 28, g):<28} ", "bold"),
            Seg(f"{sensor.celsius:5.1f} °C", style),
        ])

    battery = snap.battery
    if battery is not None:
        discharging = battery.status.lower() == "discharging"
        if discharging and battery.percent <= th.battery_crit:
            style = "crit"
        elif discharging and battery.percent <= th.battery_low:
            style = "warn"
        else:
            style = "ok"
        out.append([
            Seg("Pil      ", "bold"),
            *_bar(battery.percent, 20, g, style),
            Seg(f" {battery.percent:4.0f}%  {battery.status}", "dim"),
        ])
    return out


def _alerts(snap: Snapshot, width: int) -> list[Line]:
    out: list[Line] = [_title(f"UYARILAR ({len(snap.alerts)})", width)]
    if not snap.alerts:
        return out + [[Seg("Her şey normal görünüyor.", "ok")]]
    for alert in snap.alerts[:5]:
        tag = "KRİTİK" if alert.level == "crit" else "UYARI"
        out.append([Seg(f"[{tag}] ", alert.level), Seg(alert.message, alert.level)])
    return out


def _errors(snap: Snapshot, state: ViewState, width: int) -> list[Line]:
    if not snap.errors:
        return []
    out: list[Line] = [_title("KAYNAK NOTLARI", width)]
    for source, message in sorted(snap.errors.items()):
        out.append([Seg(f" {state.glyphs.dot} {source}: {message}", "dim")])
    return out


def _processes(snap: Snapshot, state: ViewState, width: int, remaining: Optional[int]) -> list[Line]:
    g, th = state.glyphs, state.thresholds
    procs = snap.processes
    if procs is None:
        return [_title("SÜREÇLER", width), _warn("Süreç bilgisi yok")]

    ordered = sort_processes(procs.items, state.sort)
    capacity = len(ordered)
    if state.process_rows is not None:
        capacity = min(capacity, state.process_rows)
    if remaining is not None:
        capacity = min(capacity, max(remaining, 0))

    max_offset = max(len(ordered) - capacity, 0)
    offset = min(max(state.scroll, 0), max_offset)
    view = ordered[offset:offset + capacity]

    span = f"  [{offset + 1}-{offset + len(view)} / {len(ordered)}]" if ordered else ""
    title = (f"SÜREÇLER · sıralama: {SORT_LABELS[state.sort]} · "
             f"{procs.total} süreç ({procs.running} çalışıyor){span}")
    out: list[Line] = [_title(title, width)]
    out.append([Seg(f"{'PID':>7}  {'CPU%':>6}  {'BELLEK':>10}  D  AD", "header")])

    for proc in view:
        cpu_style = level_for(proc.cpu_percent, th.cpu_warn, th.cpu_crit)
        out.append([
            Seg(f"{proc.pid:>7}  "),
            Seg(f"{proc.cpu_percent:>6.1f}", "" if cpu_style == "ok" else cpu_style),
            Seg(f"  {human_bytes(proc.rss_bytes):>10}  {proc.state}  {proc.name}"),
        ])
    if not view:
        out.append([Seg("Gösterilecek süreç yok (ekran çok küçük olabilir)", "dim")])
    return out


# --------------------------------------------------------------------------- #
# Giriş noktası
# --------------------------------------------------------------------------- #

def build_lines(
    snap: Snapshot,
    history: History,
    state: ViewState,
    width: int,
    height: Optional[int] = None,
) -> list[Line]:
    """Tüm dashboard'u satırlara çevirir. `height` verilirse süreç tablosu
    kalan alana göre kırpılır; verilmezse (düz metin çıktısı) hepsi yazılır."""
    w = max(int(width), 40)
    lines: list[Line] = []
    lines += _header(snap, state)
    lines += _cpu(snap, history, state, w)
    lines += _memory(snap, history, state, w)
    lines += _disk(snap, state, w)
    lines += _network(snap, history, state, w)
    lines += _sensors(snap, state, w)
    lines += _alerts(snap, w)
    lines += _errors(snap, state, w)
    remaining = None if height is None else height - len(lines) - 2
    lines += _processes(snap, state, w, remaining)
    return [_fit(line, w) for line in lines]
