"""Collector'lar için ortak altyapı: bağlam, güvenli okuma, temel sınıf.

Kök dizinler (/proc, /sys, /etc) `LEXICON_PROC`, `LEXICON_SYS`, `LEXICON_ETC`
ortam değişkenleriyle değiştirilebilir. Bu sayede testler sahte bir dosya
ağacı üzerinde çalışır ve farklı cihaz düzenleri simüle edilebilir.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


class DataUnavailable(RuntimeError):
    """Kaynak bu ortamda yok ya da okunamıyor. Hata değil, bilgilendirmedir."""


@dataclass(frozen=True)
class Context:
    proc: Path
    sys: Path
    etc: Path
    build_prop: Path
    ncpu: int
    page_size: int
    clk_tck: int
    now: float  # monotonic saat; hız (rate) hesapları için


def make_context(now: Optional[float] = None) -> Context:
    def root(var: str, default: str) -> Path:
        return Path(os.environ.get(var, default))

    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
    except (ValueError, OSError):
        page_size = 4096
    try:
        clk_tck = os.sysconf("SC_CLK_TCK")
    except (ValueError, OSError):
        clk_tck = 100

    return Context(
        proc=root("LEXICON_PROC", "/proc"),
        sys=root("LEXICON_SYS", "/sys"),
        etc=root("LEXICON_ETC", "/etc"),
        build_prop=root("LEXICON_BUILD_PROP", "/system/build.prop"),
        ncpu=os.cpu_count() or 1,
        page_size=page_size,
        clk_tck=clk_tck,
        now=time.monotonic() if now is None else now,
    )


def read_text(path: Path) -> Optional[str]:
    """Dosyayı okur; yoksa ya da izin yoksa None döner (istisna fırlatmaz)."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def read_int(path: Path) -> Optional[int]:
    text = read_text(path)
    if text is None:
        return None
    try:
        return int(text.strip())
    except ValueError:
        return None


def read_required(path: Path, label: str) -> str:
    text = read_text(path)
    if text is None:
        raise DataUnavailable(f"{label} okunamadı ({path})")
    return text


class Collector:
    """Her veri kaynağı bu sınıftan türer.

    `collect` bir model nesnesi (ya da listesi) döndürür. Kaynak yoksa
    `DataUnavailable` fırlatır; diğer istisnalar Engine tarafından yakalanır.
    Hız hesabı gereken collector'lar önceki örneği kendi içinde tutar.
    """

    name: str = "base"

    def collect(self, ctx: Context) -> Any:  # pragma: no cover - arayüz
        raise NotImplementedError
