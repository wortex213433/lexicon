"""Örnekleme motoru: collector'ları çalıştırır, Snapshot üretir, geçmişi besler.

Motor, bir collector'ın hatasının diğerlerini etkilemesine izin vermez. Her
kaynağın durumu `Snapshot.errors` içinde raporlanır; UI bunu gösterebilir.
"""

from __future__ import annotations

import time
from typing import Callable, Iterator, Optional, Sequence

from ..collectors import Collector, Context, DataUnavailable, build_collectors, make_context
from ..config import Config
from ..models import Snapshot
from .alerts import evaluate
from .history import History


class Engine:
    def __init__(
        self,
        config: Config,
        collectors: Optional[Sequence[Collector]] = None,
        context_factory: Callable[[], Context] = make_context,
    ) -> None:
        self.config = config
        self.collectors = list(collectors) if collectors is not None else build_collectors()
        self.history = History(config.history_size)
        self._context_factory = context_factory
        self.last: Optional[Snapshot] = None

    def prime(self) -> None:
        """Hız hesaplarının ilk referans noktasını alır; geçmişe yazmaz."""
        self.sample(record_history=False)

    def sample(self, record_history: bool = True) -> Snapshot:
        ctx = self._context_factory()
        values: dict[str, object] = {}
        errors: dict[str, str] = {}

        for collector in self.collectors:
            try:
                values[collector.name] = collector.collect(ctx)
            except DataUnavailable as exc:
                values[collector.name] = None
                errors[collector.name] = str(exc)
            except Exception as exc:  # noqa: BLE001 - tek kaynak tüm motoru düşürmemeli
                values[collector.name] = None
                errors[collector.name] = f"{type(exc).__name__}: {exc}"

        snap = Snapshot(
            timestamp=time.time(),
            system=values.get("system"),  # type: ignore[arg-type]
            cpu=values.get("cpu"),  # type: ignore[arg-type]
            memory=values.get("memory"),  # type: ignore[arg-type]
            disk=values.get("disk"),  # type: ignore[arg-type]
            network=values.get("network"),  # type: ignore[arg-type]
            processes=values.get("processes"),  # type: ignore[arg-type]
            sensors=values.get("sensors") or [],  # type: ignore[arg-type]
            battery=values.get("battery"),  # type: ignore[arg-type]
            errors=errors,
        )
        snap.alerts = evaluate(snap, self.config.thresholds)
        if record_history:
            self.history.record(snap)
        self.last = snap
        return snap

    def stream(self, count: Optional[int] = None, interval: Optional[float] = None) -> Iterator[Snapshot]:
        """Belirli aralıklarla snapshot üretir. `count` None ise sonsuzdur."""
        step = self.config.interval if interval is None else interval
        self.prime()
        emitted = 0
        while count is None or emitted < count:
            time.sleep(step)
            yield self.sample()
            emitted += 1
