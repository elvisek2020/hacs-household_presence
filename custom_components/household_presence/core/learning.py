"""Learning of habits and arrival times (FR-LEARN-01..06).

Each member and the household keep one record per local day: the presence in
every half hour and the minutes of arrivals. Predictions weight the records by
age with exponential forgetting.
"""

from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, tzinfo
from typing import Any

SLOTS = 48
SLOT_MINUTES = 30
HISTORY_DAYS = 70
MAX_ERRORS = 50
FALSE_DEPARTURE = timedelta(minutes=30)
HIT_MINUTES = 30
MAX_CONFIDENCE = 0.9
_MIN_CONFIDENCE = 0.05


def slot_of(local: datetime) -> int:
    """Return the half hour slot of a local time."""
    return min(SLOTS - 1, (local.hour * 60 + local.minute) // SLOT_MINUTES)


def minute_of(local: datetime) -> int:
    """Return the minute of the local day."""
    return local.hour * 60 + local.minute


@dataclass(kw_only=True)
class DayRecord:
    """Presence of one key on one local day."""

    day: date
    workday: bool
    excluded: bool = False
    slots: list[int | None] = field(default_factory=lambda: [None] * SLOTS)
    arrivals: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize compactly for the Store."""
        return {
            "day": self.day.isoformat(),
            "workday": self.workday,
            "excluded": self.excluded,
            "slots": "".join("-" if s is None else str(s) for s in self.slots),
            "arrivals": list(self.arrivals),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> DayRecord:
        """Restore from the Store."""
        raw = str(data.get("slots", ""))
        slots: list[int | None] = [None if ch == "-" else int(ch) for ch in raw[:SLOTS]]
        slots += [None] * (SLOTS - len(slots))
        return cls(
            day=date.fromisoformat(data["day"]),
            workday=bool(data.get("workday", True)),
            excluded=bool(data.get("excluded", False)),
            slots=slots,
            arrivals=[int(a) for a in data.get("arrivals", [])],
        )


@dataclass(kw_only=True)
class Metrics:
    """Accuracy of predictions and false departures (FR-LEARN-06)."""

    errors: deque[float] = field(default_factory=lambda: deque(maxlen=MAX_ERRORS))
    arrivals: int = 0
    predicted: int = 0
    false_departures: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Serialize for the Store."""
        return {
            "errors": list(self.errors),
            "arrivals": self.arrivals,
            "predicted": self.predicted,
            "false_departures": self.false_departures,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Metrics:
        """Restore from the Store."""
        return cls(
            errors=deque((float(e) for e in data.get("errors", [])), maxlen=MAX_ERRORS),
            arrivals=int(data.get("arrivals", 0)),
            predicted=int(data.get("predicted", 0)),
            false_departures=int(data.get("false_departures", 0)),
        )

    def summary(self) -> dict[str, Any]:
        """Return MAE, median, coverage and hit rate for diagnostics."""
        errors = sorted(abs(e) for e in self.errors)
        return {
            "samples": len(errors),
            "mae_min": round(sum(errors) / len(errors), 1) if errors else None,
            "median_abs_error_min": errors[len(errors) // 2] if errors else None,
            "hit_rate_30min": self.hit_rate(),
            "coverage": round(self.predicted / self.arrivals, 2) if self.arrivals else None,
            "arrivals": self.arrivals,
            "false_departures": self.false_departures,
        }

    def hit_rate(self) -> float | None:
        """Return the share of predictions within 30 min, None with few samples."""
        if len(self.errors) < 5:
            return None
        return round(sum(1 for e in self.errors if abs(e) <= HIT_MINUTES) / len(self.errors), 2)


@dataclass(frozen=True, kw_only=True)
class Prediction:
    """Result of a learned prediction."""

    at: datetime | None
    confidence: float
    ready: bool


def _weighted_quantile(values: list[tuple[int, float]], q: float, total: float) -> int | None:
    cum = 0.0
    for value, weight in sorted(values):
        cum += weight
        if cum / total >= q:
            return value
    return None


class Learner:
    """Day records, predictions and metrics for members and the household."""

    def __init__(self, *, half_life_weeks: float, min_samples: int, tz: tzinfo) -> None:
        """Initialize the learner."""
        self.half_life_weeks = half_life_weeks
        self.min_samples = min_samples
        self.tz = tz
        self.records: dict[str, list[DayRecord]] = {}
        self.current: dict[str, DayRecord] = {}
        self.metrics: dict[str, Metrics] = {}

    # --- recording -------------------------------------------------------------

    def observe(
        self,
        key: str,
        now: datetime,
        *,
        home: bool | None,
        excluded: bool,
        workday: bool,
    ) -> None:
        """Record the presence of ``key`` in the current slot."""
        local = now.astimezone(self.tz)
        record = self._record(key, local.date(), workday)
        record.workday = workday
        record.excluded = record.excluded or excluded
        if home is None:
            return
        slot = slot_of(local)
        record.slots[slot] = 1 if home or record.slots[slot] == 1 else 0

    def arrival(
        self,
        key: str,
        at: datetime,
        *,
        predicted: datetime | None,
        away_since: datetime | None,
        workday: bool,
    ) -> float | None:
        """Record an arrival and its prediction error in minutes."""
        local = at.astimezone(self.tz)
        self._record(key, local.date(), workday).arrivals.append(minute_of(local))
        metrics = self.metrics.setdefault(key, Metrics())
        metrics.arrivals += 1
        if away_since is not None and at - away_since < FALSE_DEPARTURE:
            metrics.false_departures += 1
        if predicted is None:
            return None
        metrics.predicted += 1
        error = round((at - predicted).total_seconds() / 60, 1)
        metrics.errors.append(error)
        return error

    def _record(self, key: str, day: date, workday: bool) -> DayRecord:
        record = self.current.get(key)
        if record is not None and record.day == day:
            return record
        if record is not None:
            history = self.records.setdefault(key, [])
            history.append(record)
            cutoff = day - timedelta(days=HISTORY_DAYS)
            self.records[key] = [r for r in history if r.day > cutoff]
        record = DayRecord(day=day, workday=workday)
        self.current[key] = record
        return record

    def reset(self, keys: Iterable[str] | None = None) -> None:
        """Forget learned data of the given keys, all when None."""
        targets = list(keys) if keys is not None else {*self.records, *self.current, *self.metrics}
        for key in targets:
            self.records.pop(key, None)
            self.current.pop(key, None)
            self.metrics.pop(key, None)

    def forget(self, keep: Iterable[str]) -> None:
        """Drop data of keys that no longer exist."""
        keep_set = set(keep)
        self.reset([k for k in {*self.records, *self.current, *self.metrics} if k not in keep_set])

    # --- prediction ------------------------------------------------------------

    def _weight(self, record: DayRecord, today: date) -> float:
        age = (today - record.day).days
        return 0.5 ** (age / (self.half_life_weeks * 7))

    def _usable(self, key: str, local: datetime, workday: bool) -> list[DayRecord]:
        history = [
            r
            for r in self.records.get(key, [])
            if not r.excluded and r.workday == workday and r.day < local.date()
        ]
        same_day = [r for r in history if r.day.weekday() == local.weekday()]
        return same_day if len(same_day) >= self.min_samples else history

    def predict(self, key: str, now: datetime, *, workday: bool) -> Prediction:
        """Predict the next arrival of an absent ``key`` today (FR-LEARN-03)."""
        local = now.astimezone(self.tz)
        slot = slot_of(local)
        minute = minute_of(local)
        relevant = [r for r in self._usable(key, local, workday) if r.slots[slot] == 0]
        if len(relevant) < self.min_samples:
            return Prediction(at=None, confidence=0.0, ready=False)
        today = local.date()
        total = 0.0
        arrived: list[tuple[int, float]] = []
        for record in relevant:
            weight = self._weight(record, today)
            total += weight
            nxt = next((a for a in sorted(record.arrivals) if a >= minute), None)
            if nxt is not None:
                arrived.append((nxt, weight))
        predicted = _weighted_quantile(arrived, 0.5, total) if total else None
        if predicted is None:
            return Prediction(at=None, confidence=0.0, ready=True)
        # Wall clock minutes, so a DST change keeps the habit at the same local time.
        at = datetime.combine(
            today, (datetime.min + timedelta(minutes=predicted)).time(), tzinfo=self.tz
        )
        at = max(at, now + timedelta(minutes=1))
        return Prediction(at=at, confidence=self._confidence(key, arrived, total), ready=True)

    def _confidence(self, key: str, arrived: list[tuple[int, float]], total: float) -> float:
        arrived_weight = sum(w for _, w in arrived)
        q25 = _weighted_quantile(arrived, 0.25, arrived_weight) or 0
        q75 = _weighted_quantile(arrived, 0.75, arrived_weight) or 0
        spread = 1 - min(1.0, (q75 - q25) / 240)
        samples = total / (total + 2)
        metrics = self.metrics.get(key)
        hit = metrics.hit_rate() if metrics else None
        accuracy = 1.0 if hit is None else 0.5 + 0.5 * hit
        value = MAX_CONFIDENCE * samples * spread * accuracy
        return round(max(_MIN_CONFIDENCE, min(MAX_CONFIDENCE, value)), 2)

    def profile(self, key: str) -> list[list[float | None]]:
        """Return p(home) per weekday and slot with a Beta(1, 1) prior (diagnostics)."""
        today = max((r.day for r in self.records.get(key, [])), default=date.min)
        home = [[0.0] * SLOTS for _ in range(7)]
        seen = [[0.0] * SLOTS for _ in range(7)]
        for record in self.records.get(key, []):
            if record.excluded:
                continue
            weight = self._weight(record, today)
            day = record.day.weekday()
            for slot, value in enumerate(record.slots):
                if value is None:
                    continue
                seen[day][slot] += weight
                home[day][slot] += weight * value
        return [
            [
                round((home[d][s] + 1) / (seen[d][s] + 2), 2) if seen[d][s] else None
                for s in range(SLOTS)
            ]
            for d in range(7)
        ]

    # --- persistence ------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialize for the Store."""
        return {
            "records": {k: [r.to_dict() for r in v] for k, v in self.records.items()},
            "current": {k: r.to_dict() for k, r in self.current.items()},
            "metrics": {k: m.to_dict() for k, m in self.metrics.items()},
        }

    def restore(self, data: Mapping[str, Any]) -> None:
        """Restore from the Store, invalid parts are skipped."""
        try:
            self.records = {
                k: [DayRecord.from_dict(r) for r in v]
                for k, v in (data.get("records") or {}).items()
            }
            self.current = {
                k: DayRecord.from_dict(r) for k, r in (data.get("current") or {}).items()
            }
            self.metrics = {k: Metrics.from_dict(m) for k, m in (data.get("metrics") or {}).items()}
        except KeyError, ValueError, TypeError:
            self.records, self.current, self.metrics = {}, {}, {}
