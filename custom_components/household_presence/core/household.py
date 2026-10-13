"""Household aggregation, modes, guest and long absence (FR-HH, FR-MODE, FR-GUEST)."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, tzinfo
from typing import Any

from .. import const as c
from .model import (
    CalendarEvent,
    Event,
    EventType,
    ExpectedReturn,
    HouseholdConfig,
    HouseholdState,
    Mode,
    Reason,
)


def _dt(value: Any) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


@dataclass(kw_only=True)
class HouseholdRuntime:
    """Mutable state of the household kept across steps and restarts."""

    mode: Mode = Mode.AUTO
    mode_set_at: datetime | None = None
    guest: bool = False
    guest_on_at: datetime | None = None
    away_until: datetime | None = None
    away_until_set_at: datetime | None = None
    someone_home: bool | None = None
    since: datetime | None = None
    away_since: datetime | None = None
    long_away: bool = False
    pending_events: list[Event] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize for the Store."""
        return {
            "mode": self.mode.value,
            "mode_set_at": _iso(self.mode_set_at),
            "guest": self.guest,
            "guest_on_at": _iso(self.guest_on_at),
            "away_until": _iso(self.away_until),
            "away_until_set_at": _iso(self.away_until_set_at),
            "someone_home": self.someone_home,
            "since": _iso(self.since),
            "away_since": _iso(self.away_since),
            "long_away": self.long_away,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> HouseholdRuntime:
        """Restore from the Store, invalid data falls back to defaults."""
        try:
            return cls(
                mode=Mode(data.get("mode", Mode.AUTO)),
                mode_set_at=_dt(data.get("mode_set_at")),
                guest=bool(data.get("guest", False)),
                guest_on_at=_dt(data.get("guest_on_at")),
                away_until=_dt(data.get("away_until")),
                away_until_set_at=_dt(data.get("away_until_set_at")),
                someone_home=data.get("someone_home"),
                since=_dt(data.get("since")),
                away_since=_dt(data.get("away_since")),
                long_away=bool(data.get("long_away", False)),
            )
        except ValueError, TypeError:
            return cls()

    def set_mode(self, mode: Mode, now: datetime, *, reason: str = "manual") -> None:
        """Change the mode and queue an event."""
        if mode is self.mode:
            return
        old = self.mode
        self.mode = mode
        self.mode_set_at = now
        self.pending_events.append(
            Event(
                type=EventType.MODE_CHANGED,
                at=now,
                data={"from": old.value, "to": mode.value, "reason": reason},
            )
        )


def guest_deadline(cfg: HouseholdConfig, rt: HouseholdRuntime, tz: tzinfo) -> datetime | None:
    """Return when the guest switch turns itself off (FR-GUEST-02)."""
    if not rt.guest or rt.guest_on_at is None:
        return None
    if cfg.guest_auto_off == c.GUEST_OFF_AFTER:
        return rt.guest_on_at + cfg.guest_off_after
    if cfg.guest_auto_off == c.GUEST_OFF_AT_TIME:
        local = rt.guest_on_at.astimezone(tz)
        deadline = datetime.combine(local.date(), cfg.guest_off_time, tzinfo=tz)
        if deadline <= local:
            deadline = datetime.combine(
                local.date() + timedelta(days=1), cfg.guest_off_time, tzinfo=tz
            )
        return deadline
    return None


def apply_manual_rules(
    cfg: HouseholdConfig,
    rt: HouseholdRuntime,
    now: datetime,
    tz: tzinfo,
    trusted_home_since: Iterable[datetime],
) -> None:
    """Expire manual states and end them on a confirmed arrival (FR-MODE-02/03)."""
    newest = max(trusted_home_since, default=None)
    if rt.away_until is not None and (
        now >= rt.away_until
        or (newest is not None and (rt.away_until_set_at is None or newest > rt.away_until_set_at))
    ):
        expired = now >= rt.away_until
        rt.away_until = None
        rt.away_until_set_at = None
        if rt.mode is Mode.VACATION:
            rt.set_mode(Mode.AUTO, now, reason="away_until" if expired else "arrival")
    if (
        rt.mode in (Mode.FORCE_AWAY, Mode.VACATION)
        and newest is not None
        and (rt.mode_set_at is None or newest > rt.mode_set_at)
    ):
        rt.set_mode(Mode.AUTO, now, reason="arrival")
    deadline = guest_deadline(cfg, rt, tz)
    if deadline is not None and now >= deadline:
        rt.guest = False
        rt.guest_on_at = None


@dataclass(frozen=True, kw_only=True)
class Presence:
    """Who is home according to members, guest and household signals."""

    someone_home: bool
    reason: Reason
    people: tuple[str, ...]


def presence(rt: HouseholdRuntime, people: tuple[str, ...], household_signal: bool) -> Presence:
    """Aggregate the household presence (FR-HH-01, FR-MODE-01)."""
    if rt.mode is Mode.FORCE_HOME:
        return Presence(someone_home=True, reason=Reason.MANUAL, people=people)
    if rt.mode is Mode.FORCE_AWAY:
        return Presence(someone_home=False, reason=Reason.MANUAL, people=people)
    if rt.mode is Mode.VACATION:
        return Presence(someone_home=False, reason=Reason.VACATION, people=people)
    if people:
        return Presence(someone_home=True, reason=Reason.SIGNALS, people=people)
    if rt.guest:
        return Presence(someone_home=True, reason=Reason.GUEST, people=people)
    if household_signal:
        return Presence(someone_home=True, reason=Reason.HOUSEHOLD_SIGNAL, people=people)
    return Presence(someone_home=False, reason=Reason.SIGNALS, people=people)


def long_away_reason(
    cfg: HouseholdConfig,
    rt: HouseholdRuntime,
    now: datetime,
    *,
    vacation_event: CalendarEvent | None,
    expected_return: ExpectedReturn | None,
    model_ready: bool,
) -> Reason | None:
    """Return why the household is away for long, None when it is not (FR-HH-04)."""
    if rt.someone_home:
        return None
    if rt.mode is Mode.VACATION:
        return Reason.VACATION
    if rt.away_until is not None and rt.away_until > now:
        return Reason.AWAY_UNTIL
    if vacation_event is not None:
        return Reason.CALENDAR
    away_for = now - rt.away_since if rt.away_since is not None else timedelta(0)
    if away_for >= cfg.long_away_after:
        return Reason.DURATION
    if cfg.long_away_prediction and away_for >= cfg.long_away_prediction_min:
        if expected_return is not None:
            if expected_return.at - now > cfg.return_horizon:
                return Reason.PREDICTION
        elif model_ready:
            return Reason.PREDICTION
    return None


def update_presence(
    rt: HouseholdRuntime,
    pres: Presence,
    now: datetime,
    last_departure: datetime | None,
) -> list[Event]:
    """Track transitions of ``someone_home`` (FR-HH-03, FR-EVT-01)."""
    events: list[Event] = []
    previous = rt.someone_home
    if previous is None:
        rt.someone_home = pres.someone_home
        rt.since = now
        if not pres.someone_home:
            rt.away_since = min(last_departure or now, now)
        return events
    if pres.someone_home == previous:
        return events
    rt.someone_home = pres.someone_home
    if pres.someone_home:
        rt.since = now
        rt.away_since = None
        events.append(Event(type=EventType.FIRST_ARRIVED, at=now, data={"reason": pres.reason}))
    else:
        left = min(last_departure or now, now)
        rt.since = left
        rt.away_since = left
        events.append(Event(type=EventType.LAST_LEFT, at=left, data={"reason": pres.reason}))
    return events


def update_long_away(rt: HouseholdRuntime, reason: Reason | None, now: datetime) -> list[Event]:
    """Track transitions of the long absence."""
    long_away = reason is not None
    if long_away == rt.long_away:
        return []
    rt.long_away = long_away
    kind = EventType.LONG_AWAY_STARTED if long_away else EventType.LONG_AWAY_ENDED
    data: dict[str, Any] = {"reason": reason.value} if reason is not None else {}
    if long_away and rt.away_until is not None:
        data["until"] = rt.away_until.isoformat()
    return [Event(type=kind, at=now, data=data)]


def household_state(pres: Presence, long_reason: Reason | None) -> tuple[HouseholdState, Reason]:
    """Return the enum state and its reason (FR-HH-05)."""
    if pres.someone_home:
        return HouseholdState.HOME, pres.reason
    if long_reason is not None:
        return HouseholdState.LONG_AWAY, long_reason
    return HouseholdState.AWAY, pres.reason


def forced(mode: Mode) -> bool | None:
    """Return the forced presence of a manual mode, None in auto (FR-MODE-01)."""
    if mode is Mode.FORCE_HOME:
        return True
    if mode in (Mode.FORCE_AWAY, Mode.VACATION):
        return False
    return None


@dataclass(kw_only=True)
class Flag:
    """On/off state with the time of its last change (multiple home, groups)."""

    on: bool | None = None
    since: datetime | None = None

    def update(self, value: bool, now: datetime) -> bool:
        """Set the value; return True on a real change (not the first value)."""
        if self.on is value:
            return False
        first = self.on is None
        self.on = value
        self.since = now
        return not first

    def to_dict(self) -> dict[str, Any]:
        """Serialize for the Store."""
        return {"on": self.on, "since": _iso(self.since)}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> Flag:
        """Restore from the Store."""
        if not data:
            return cls()
        try:
            on = data.get("on")
            return cls(on=on if isinstance(on, bool) else None, since=_dt(data.get("since")))
        except ValueError, TypeError:
            return cls()
