"""Snapshot'ı JSON'a dönüştürür. Diğer CLI araçlarının veri kaynağı olarak
kullanılabilmesi için kararlı bir şema sağlar (`lexicon --json`)."""

from __future__ import annotations

import dataclasses
import json
from typing import Any

from .models import Snapshot

SCHEMA_VERSION = 1


def to_jsonable(snap: Snapshot) -> dict[str, Any]:
    data = dataclasses.asdict(snap)
    data["schema"] = SCHEMA_VERSION
    if snap.memory:
        data["memory"]["percent"] = round(snap.memory.percent, 2)
        data["memory"]["swap_percent"] = round(snap.memory.swap_percent, 2)
    if snap.disk:
        for mount, raw in zip(snap.disk.mounts, data["disk"]["mounts"]):
            raw["percent"] = round(mount.percent, 2)
    return data


def dumps(snap: Snapshot) -> str:
    return json.dumps(to_jsonable(snap), ensure_ascii=False, separators=(",", ":"))
