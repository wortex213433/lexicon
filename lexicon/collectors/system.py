"""Sistem kimliği: ana makine adı, OS, çekirdek, mimari, çalışma süresi, cihaz."""

from __future__ import annotations

import os
import socket
from typing import Optional

from ..models import SystemInfo
from .base import Collector, Context, read_text


def parse_os_release(text: str) -> Optional[str]:
    for line in text.splitlines():
        if line.startswith("PRETTY_NAME="):
            return line.split("=", 1)[1].strip().strip('"')
    return None


def parse_build_prop(text: str) -> dict[str, str]:
    props = {}
    for line in text.splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, _, value = line.partition("=")
            props[key.strip()] = value.strip()
    return props


def _device_name(ctx: Context) -> Optional[str]:
    props = parse_build_prop(read_text(ctx.build_prop) or "")
    model = props.get("ro.product.model")
    if model:
        maker = props.get("ro.product.manufacturer")
        return f"{maker} {model}".strip() if maker else model
    for candidate in ("product_name", "sys_vendor"):
        value = read_text(ctx.sys / "class" / "dmi" / "id" / candidate)
        if value and value.strip() and value.strip().lower() != "unknown":
            return value.strip()
    return None


def _uptime(ctx: Context) -> Optional[float]:
    text = read_text(ctx.proc / "uptime")
    if not text:
        return None
    try:
        return float(text.split()[0])
    except (ValueError, IndexError):
        return None


class SystemCollector(Collector):
    name = "system"

    def collect(self, ctx: Context) -> SystemInfo:
        uname = os.uname()
        hostname = (read_text(ctx.proc / "sys" / "kernel" / "hostname") or socket.gethostname()).strip()
        kernel = (read_text(ctx.proc / "sys" / "kernel" / "osrelease") or uname.release).strip()
        os_name = parse_os_release(read_text(ctx.etc / "os-release") or "") or uname.sysname
        return SystemInfo(
            hostname=hostname,
            os_name=os_name,
            kernel=kernel,
            arch=uname.machine,
            uptime_s=_uptime(ctx),
            device=_device_name(ctx),
        )
