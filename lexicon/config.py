"""Yapılandırma: varsayılanlar, JSON dosyasından yükleme ve doğrulama."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

SORT_KEYS = ("cpu", "mem", "pid", "name")


class ConfigError(ValueError):
    """Yapılandırma dosyası geçersiz."""


@dataclass
class Thresholds:
    cpu_warn: float = 80.0
    cpu_crit: float = 95.0
    mem_warn: float = 85.0
    mem_crit: float = 95.0
    swap_warn: float = 50.0
    swap_crit: float = 80.0
    disk_warn: float = 85.0
    disk_crit: float = 95.0
    temp_warn: float = 75.0
    temp_crit: float = 90.0
    battery_low: float = 20.0
    battery_crit: float = 10.0


@dataclass
class Config:
    interval: float = 1.0
    history_size: int = 120
    process_limit: int = 15
    sort: str = "cpu"
    thresholds: Thresholds = field(default_factory=Thresholds)


def default_config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
    return Path(base) / "lexicon" / "config.json"


def load_config(path: Optional[Path] = None) -> Config:
    """Yapılandırmayı yükler. Açıkça verilen bir yol yoksa hata verir;
    varsayılan yol yoksa sessizce varsayılanları kullanır."""
    config = Config()
    target = path if path is not None else default_config_path()
    if not target.exists():
        if path is not None:
            raise ConfigError(f"yapılandırma dosyası bulunamadı: {target}")
        return config
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"{target} okunamadı: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError("yapılandırma kökü bir JSON nesnesi olmalı")
    apply_overrides(config, data)
    return config


def apply_overrides(config: Config, data: dict) -> None:
    for key, value in data.items():
        if key == "thresholds":
            if not isinstance(value, dict):
                raise ConfigError("'thresholds' bir nesne olmalı")
            for tkey, tvalue in value.items():
                if not hasattr(config.thresholds, tkey):
                    raise ConfigError(f"bilinmeyen eşik: {tkey}")
                if isinstance(tvalue, bool) or not isinstance(tvalue, (int, float)):
                    raise ConfigError(f"eşik sayı olmalı: {tkey}")
                setattr(config.thresholds, tkey, float(tvalue))
        elif key == "interval":
            config.interval = _number(key, value)
        elif key == "history_size":
            config.history_size = int(_number(key, value))
        elif key == "process_limit":
            config.process_limit = int(_number(key, value))
        elif key == "sort":
            config.sort = str(value)
        else:
            raise ConfigError(f"bilinmeyen ayar: {key}")
    validate(config)


def validate(config: Config) -> None:
    if not 0.1 <= config.interval <= 60:
        raise ConfigError("interval 0.1 ile 60 saniye arasında olmalı")
    if config.history_size < 10:
        raise ConfigError("history_size en az 10 olmalı")
    if config.process_limit < 1:
        raise ConfigError("process_limit en az 1 olmalı")
    if config.sort not in SORT_KEYS:
        raise ConfigError(f"sort şunlardan biri olmalı: {', '.join(SORT_KEYS)}")


def _number(key: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"'{key}' sayı olmalı")
    return float(value)
