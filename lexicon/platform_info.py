"""Çalışma ortamı tespiti: Linux, Android veya Termux."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class PlatformInfo:
    is_termux: bool
    is_android: bool
    kernel: str
    arch: str
    python: str

    @property
    def label(self) -> str:
        if self.is_termux:
            return "Termux (Android)"
        if self.is_android:
            return "Android"
        return "Linux"

    @property
    def supported(self) -> bool:
        return sys.platform.startswith("linux") or sys.platform == "android"


def detect_platform() -> PlatformInfo:
    termux = bool(os.environ.get("TERMUX_VERSION")) or os.path.isdir("/data/data/com.termux")
    android = termux or bool(os.environ.get("ANDROID_ROOT")) or os.path.exists("/system/build.prop")
    uname = os.uname()
    return PlatformInfo(
        is_termux=termux,
        is_android=android,
        kernel=uname.release,
        arch=uname.machine,
        python=sys.version.split()[0],
    )
