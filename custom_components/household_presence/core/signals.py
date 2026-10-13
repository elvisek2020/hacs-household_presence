"""Interpretation of signal entities (FR-SIG-01..08)."""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, time
from typing import Any

from .model import EntityReading, Reading, SignalConfig, SignalKind, SignalView, in_window


@dataclass(frozen=True, kw_only=True)
class SignalEval:
    """Interpreted value of one signal in one step."""

    config: SignalConfig
    value: Reading
    raw: str | None = None
    changed_at: datetime | None = None
    stuck: bool = False
    held_by_plan: bool = False
    pending_until: datetime | None = None

    def view(self) -> SignalView:
        """Return the diagnostic view."""
        return SignalView(
            entity_id=self.config.entity_id,
            kind=self.config.kind,
            reading=self.value,
            raw=self.raw,
            stuck=self.stuck,
            pending_until=self.pending_until,
        )


def _matches(state: str, states: tuple[str, ...]) -> bool:
    folded = state.casefold()
    return any(folded == s.casefold() for s in states)


def raw_reading(cfg: SignalConfig, state: str) -> Reading:
    """Map a raw state to HOME / AWAY / NONE ignoring time based rules."""
    if cfg.kind is SignalKind.HOME_AWAY:
        if _matches(state, cfg.home_states):
            return Reading.HOME
        if cfg.away_states and not _matches(state, cfg.away_states):
            return Reading.NONE
        return Reading.AWAY
    if cfg.kind is SignalKind.HOME_ONLY:
        return Reading.HOME if _matches(state, cfg.home_states) else Reading.NONE
    return Reading.AWAY if _matches(state, cfg.away_states) else Reading.NONE


def evaluate(
    cfg: SignalConfig,
    reading: EntityReading | None,
    now: datetime,
    local: time,
    plan_start: datetime | None = None,
) -> SignalEval:
    """Evaluate one signal.

    ``plan_start`` is the start of the running plan block; a HOME signal that did
    not change since then is held by the plan and says nothing (FR-SIG-07).
    """
    if reading is None or not reading.available:
        return SignalEval(
            config=cfg,
            value=Reading.UNAVAILABLE,
            raw=None if reading is None else reading.state,
        )
    value = raw_reading(cfg, reading.state)
    base = {"config": cfg, "raw": reading.state, "changed_at": reading.last_changed}
    if (
        cfg.valid_from is not None
        and cfg.valid_to is not None
        and not in_window(local, cfg.valid_from, cfg.valid_to)
    ):
        return SignalEval(value=Reading.NONE, **base)
    if value is not Reading.HOME:
        return SignalEval(value=value, **base)
    age = now - reading.last_changed
    if cfg.max_on is not None and age > cfg.max_on:
        return SignalEval(value=Reading.NONE, stuck=True, **base)
    if plan_start is not None and reading.last_changed < plan_start:
        return SignalEval(value=Reading.NONE, held_by_plan=True, **base)
    if age < cfg.arrival_delay:
        return SignalEval(
            value=Reading.NONE,
            pending_until=reading.last_changed + cfg.arrival_delay,
            **base,
        )
    return SignalEval(value=Reading.HOME, **base)


@dataclass(kw_only=True)
class _Remembered:
    state: str
    changed: datetime


class SignalMemory:
    """Last available value of each signal and when it really changed.

    Home Assistant moves ``last_changed`` on ``home → unavailable → home`` (an
    integration reload, a short outage). Such a round trip is not a change, so
    the plan hold, ``max_on`` and ``arrival_delay`` use the remembered time
    (FR-SIG-09). The memory survives restarts in the Store.
    """

    def __init__(self) -> None:
        """Initialize an empty memory."""
        self._items: dict[str, _Remembered] = {}

    def effective(self, entity_id: str, reading: EntityReading | None) -> EntityReading | None:
        """Return the reading with the time of its last real change."""
        if reading is None or not reading.available:
            return reading
        item = self._items.get(entity_id)
        if item is None or item.state.casefold() != reading.state.casefold():
            self._items[entity_id] = _Remembered(state=reading.state, changed=reading.last_changed)
            return reading
        if item.changed == reading.last_changed:
            return reading
        return replace(reading, last_changed=item.changed)

    def keep(self, entity_ids: set[str]) -> None:
        """Forget entities that are no longer watched."""
        self._items = {k: v for k, v in self._items.items() if k in entity_ids}

    def to_dict(self) -> dict[str, dict[str, str]]:
        """Serialize for the Store."""
        return {
            k: {"state": v.state, "changed": v.changed.isoformat()} for k, v in self._items.items()
        }

    def restore(self, data: Mapping[str, Any] | None) -> None:
        """Restore from the Store, invalid items are skipped."""
        self._items = {}
        for entity_id, item in (data or {}).items():
            try:
                self._items[entity_id] = _Remembered(
                    state=str(item["state"]), changed=datetime.fromisoformat(item["changed"])
                )
            except KeyError, TypeError, ValueError:
                continue
