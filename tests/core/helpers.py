"""Fake household driving the engine without Home Assistant."""

from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from custom_components.household_presence import const as c
from custom_components.household_presence.core.engine import PresenceEngine
from custom_components.household_presence.core.model import (
    CalendarData,
    CalendarEvent,
    EntityReading,
    Event,
    EventType,
    HouseholdConfig,
    MemberConfig,
    PersonView,
    Snapshot,
    StepResult,
)

TZ = ZoneInfo("Europe/Prague")
# Monday 12 October 2026, 08:00 local time.
T0 = datetime(2026, 10, 12, 8, 0, tzinfo=TZ)


def sig(entity_id: str, kind: str = "home_only", **extra: Any) -> dict[str, Any]:
    """Return signal data as stored in a subentry."""
    return {c.CONF_ENTITY_ID: entity_id, c.CONF_KIND: kind, **extra}


def member(name: str, *signals: dict[str, Any], **extra: Any) -> dict[str, Any]:
    """Return member data as stored in a subentry."""
    return {c.CONF_NAME: name, c.CONF_SIGNALS: list(signals), **extra}


def plan(*calendars: str, **extra: Any) -> dict[str, Any]:
    """Return plan data of a member."""
    return {c.CONF_CALENDARS: list(calendars), **extra}


class House:
    """Fake household: entity states, calendars and a clock."""

    def __init__(
        self,
        members: Iterable[Mapping[str, Any]],
        options: Mapping[str, Any] | None = None,
        *,
        now: datetime = T0,
        grace: bool = False,
    ) -> None:
        """Create the house; the startup grace is off unless asked for."""
        opts = {c.CONF_STARTUP_GRACE: 5 if grace else 0, **(options or {})}
        self.options = opts
        self.member_data = [dict(m) for m in members]
        self.now = now
        self.states: dict[str, tuple[str, datetime, dict[str, Any]]] = {}
        self.calendars: dict[str, CalendarData] = {}
        self.events: list[Event] = []
        self.result: StepResult | None = None
        self.engine = PresenceEngine(HouseholdConfig.from_options(opts), self._configs(), TZ)

    def _configs(self) -> list[MemberConfig]:
        return [
            MemberConfig.from_data(m[c.CONF_NAME].lower(), m[c.CONF_NAME].lower(), m)
            for m in self.member_data
        ]

    # --- inputs -------------------------------------------------------------------

    def set(self, entity_id: str, state: str, *, step: bool = True, **attributes: Any) -> None:
        """Set a state; last_changed moves only on a real change."""
        old = self.states.get(entity_id)
        changed = old[1] if old is not None and old[0] == state else self.now
        self.states[entity_id] = (state, changed, attributes)
        if step:
            self.step()

    def remove(self, entity_id: str) -> None:
        """Remove an entity from the state machine."""
        self.states.pop(entity_id, None)

    def calendar(
        self,
        entity_id: str,
        events: Iterable[tuple[datetime, datetime, str]] = (),
        *,
        ok: bool = True,
    ) -> None:
        """Set the cached events of a calendar."""
        self.calendars[entity_id] = CalendarData(
            ok=ok,
            events=tuple(
                CalendarEvent(start=s, end=e, summary=t, all_day=False) for s, e, t in events
            ),
        )

    # --- driving ------------------------------------------------------------------

    def snapshot(self) -> Snapshot:
        """Return the snapshot of the current state."""
        return Snapshot(
            now=self.now,
            entities={
                e: EntityReading(state=s, last_changed=t, attributes=a)
                for e, (s, t, a) in self.states.items()
            },
            calendars=dict(self.calendars),
        )

    def step(self) -> StepResult:
        """Run one engine step."""
        self.result = self.engine.step(self.snapshot())
        self.events.extend(self.result.events)
        return self.result

    def run(self, minutes: float, every: float = 0.5) -> StepResult:
        """Advance the clock, stepping every ``every`` minutes."""
        end = self.now + timedelta(minutes=minutes)
        while self.now < end:
            self.now = min(end, self.now + timedelta(minutes=every))
            self.step()
        assert self.result is not None
        return self.result

    def run_until(self, when: datetime, every: float = 0.5) -> StepResult:
        """Advance the clock to ``when``."""
        return self.run((when - self.now).total_seconds() / 60, every)

    def restart(self) -> None:
        """Simulate a restart: serialize, create a new engine and restore."""
        data = self.engine.to_dict()
        self.engine = PresenceEngine(
            HouseholdConfig.from_options(self.options), self._configs(), TZ
        )
        self.engine.restore(data)

    # --- outputs ------------------------------------------------------------------

    def person(self, name: str) -> PersonView:
        """Return the view of a member."""
        assert self.result is not None
        return self.result.persons[name.lower()]

    @property
    def hh(self):
        """Return the household view."""
        assert self.result is not None
        return self.result.household

    def event_types(self, name: str | None = None) -> list[EventType]:
        """Return the types of collected events, optionally of one member."""
        return [e.type for e in self.events if name is None or e.name == name]

    def problems(self) -> set[str]:
        """Return kinds of current problems."""
        assert self.result is not None
        return {p.kind for p in self.result.problems}
