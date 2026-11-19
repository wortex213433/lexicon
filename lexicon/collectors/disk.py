"""Disk kullanımı (bağlama noktaları) ve disk G/Ç hızları.

Bağlama noktaları /proc/mounts üzerinden okunur; sanal dosya sistemleri
(proc, sysfs, tmpfs, cgroup ...) elenir. G/Ç istatistikleri /proc/diskstats
üzerinden, yalnızca tam diskler için (sda, vda, nvme0n1, mmcblk0 ...) alınır.
"""

from __future__ import annotations

import os
import re
from typing import Callable, Optional

from ..models import DiskIO, DiskMount, DiskStats
from .base import Collector, Context, DataUnavailable, read_text

PSEUDO_FS = frozenset({
    "proc", "sysfs", "devtmpfs", "devpts", "tmpfs", "squashfs", "autofs", "mqueue",
    "debugfs", "tracefs", "securityfs", "pstore", "bpf", "configfs", "fusectl",
    "hugetlbfs", "rpc_pipefs", "nsfs", "efivarfs", "binfmt_misc", "ramfs", "overlay",
    "fuse.portal", "fuse.lxcfs",
})
SKIP_MOUNT_PREFIXES = ("/proc", "/sys", "/dev", "/run", "/snap")
WHOLE_DISK_RE = re.compile(r"^(sd[a-z]+|hd[a-z]+|vd[a-z]+|xvd[a-z]+|nvme\d+n\d+|mmcblk\d+|dm-\d+)$")
SECTOR_BYTES = 512


def _unescape(text: str) -> str:
    return (
        text.replace("\\040", " ")
        .replace("\\011", "\t")
        .replace("\\012", "\n")
        .replace("\\134", "\\")
    )


def parse_mounts(text: str) -> list[tuple[str, str, str]]:
    """(aygıt, bağlama noktası, dosya sistemi) üçlüleri döner."""
    out = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 3:
            out.append((parts[0], _unescape(parts[1]), parts[2]))
    return out


def parse_diskstats(text: str) -> dict[str, tuple[int, int]]:
    """Tam disklerin (okunan_sektör, yazılan_sektör) değerlerini döner."""
    out: dict[str, tuple[int, int]] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 10:
            continue
        name = parts[2]
        if not WHOLE_DISK_RE.match(name):
            continue
        try:
            out[name] = (int(parts[5]), int(parts[9]))
        except ValueError:
            continue
    return out


class DiskCollector(Collector):
    name = "disk"

    def __init__(
        self,
        statvfs: Callable[[str], os.statvfs_result] = os.statvfs,
        max_mounts: int = 12,
    ) -> None:
        self._statvfs = statvfs
        self._max_mounts = max_mounts
        self._prev: Optional[tuple[float, dict[str, tuple[int, int]]]] = None

    def collect(self, ctx: Context) -> DiskStats:
        mounts_text = read_text(ctx.proc / "mounts")
        if mounts_text is None:
            raise DataUnavailable("/proc/mounts okunamadı")

        mounts = self._mounts(mounts_text) or self._fallback_mounts()
        io_now = parse_diskstats(read_text(ctx.proc / "diskstats") or "")
        return DiskStats(mounts=mounts, io=self._io_rates(io_now, ctx.now))

    def _mounts(self, text: str) -> list[DiskMount]:
        seen: set[str] = set()
        result: list[DiskMount] = []
        for device, mountpoint, fstype in parse_mounts(text):
            if fstype in PSEUDO_FS or fstype.startswith("cgroup"):
                continue
            if mountpoint.startswith(SKIP_MOUNT_PREFIXES) or device in seen:
                continue
            seen.add(device)
            mount = self._stat(mountpoint, device, fstype)
            if mount is not None:
                result.append(mount)
            if len(result) >= self._max_mounts:
                break
        return result

    def _fallback_mounts(self) -> list[DiskMount]:
        """/proc/mounts erişilemediğinde (ör. bazı Termux kurulumları) kök ve ev dizini."""
        candidates = dict.fromkeys(["/", os.path.expanduser("~")])
        result = [m for m in (self._stat(p, "-", "-") for p in candidates) if m is not None]
        return result

    def _stat(self, mountpoint: str, device: str, fstype: str) -> Optional[DiskMount]:
        try:
            st = self._statvfs(mountpoint)
        except OSError:
            return None
        total = st.f_blocks * st.f_frsize
        if total == 0:
            return None
        free = st.f_bavail * st.f_frsize
        used = (st.f_blocks - st.f_bfree) * st.f_frsize
        return DiskMount(mountpoint=mountpoint, device=device, fstype=fstype, total=total, used=used, free=free)

    def _io_rates(self, counts: dict[str, tuple[int, int]], now: float) -> list[DiskIO]:
        prev = self._prev
        self._prev = (now, counts)
        if prev is None or now - prev[0] <= 0:
            return []
        dt = now - prev[0]
        rates = []
        for name, (read_sectors, write_sectors) in sorted(counts.items()):
            if name not in prev[1]:
                continue
            p_read, p_write = prev[1][name]
            rates.append(
                DiskIO(
                    device=name,
                    read_bps=max(read_sectors - p_read, 0) * SECTOR_BYTES / dt,
                    write_bps=max(write_sectors - p_write, 0) * SECTOR_BYTES / dt,
                )
            )
        return rates
