"""Approach detection from distance and direction entities (FR-APPR-01/02)."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from .model import ApproachConfig, EntityReading

MIN_STEP_KM = 0.05
TOWARDS = "towards"
_UNIT_FACTORS = {"km": 1.0, "m": 0.001, "mi": 1.609344, "ft": 0.0003048, "yd": 0.0009144}


def distance_km(reading: EntityReading | None) -> float | None:
    """Return the distance in km, None when not numeric."""
    if reading is None or not reading.available:
        return None
    try:
        value = float(reading.state)
    except ValueError:
        return None
    unit = str(reading.attributes.get("unit_of_measurement") or "km").casefold()
    return value * _UNIT_FACTORS.get(unit, 1.0)


@dataclass(kw_only=True)
class ApproachTracker:
    """Consecutive decreasing distance readings of one member."""

    last_km: float | None = None
    last_changed: datetime | None = None
    decreasing: int = 0

    def update(
        self,
        cfg: ApproachConfig,
        distance: EntityReading | None,
        direction: EntityReading | None,
        now: datetime,
    ) -> datetime | None:
        """Process the current readings, return the ETA when approaching."""
        km = distance_km(distance)
        if km is None or distance is None:
            return None
        if distance.last_changed != self.last_changed:
            if self.last_km is not None:
                if km < self.last_km - MIN_STEP_KM:
                    self.decreasing += 1
                elif km > self.last_km + MIN_STEP_KM:
                    self.decreasing = 0
            self.last_km = km
            self.last_changed = distance.last_changed
        if km <= 0 or km > cfg.threshold_km:
            return None
        towards = (
            direction is not None and direction.available and direction.state.casefold() == TOWARDS
        )
        confirmed = self.decreasing >= cfg.confirmations or (
            towards and self.decreasing >= max(1, cfg.confirmations - 1)
        )
        if not confirmed:
            return None
        return now + timedelta(hours=km / cfg.speed_kmh)

    def reset(self) -> None:
        """Forget the readings, e.g. after arrival."""
        self.last_km = None
        self.last_changed = None
        self.decreasing = 0
