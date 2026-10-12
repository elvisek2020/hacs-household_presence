"""Configuration and data model of the presence engine (NFR-04)."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from enum import StrEnum
from typing import Any
import unicodedata

from .. import const as c

UNAVAILABLE_STATES = frozenset({"unavailable", "unknown", "none", ""})


class SignalKind(StrEnum):
    """Meaning of a signal entity (FR-SIG-01)."""

    HOME_AWAY = "home_away"
    HOME_ONLY = "home_only"
    AWAY_ONLY = "away_only"


class Trust(StrEnum):
    """How much a signal is trusted (FR-SIG-08)."""

    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


class NoSignalPolicy(StrEnum):
    """What happens when no signal says home (FR-PER-03, FR-PER-05)."""

    HOLD_LAST = "hold_last"
    AWAY_AFTER_DELAY = "away_after_delay"


class Reading(StrEnum):
    """Interpreted value of one signal."""

    HOME = "home"
    AWAY = "away"
    NONE = "none"
    UNAVAILABLE = "unavailable"


class PersonState(StrEnum):
    """State machine of a member (FR-PER-01)."""

    UNKNOWN = "unknown"
    HOME = "home"
    JUST_ARRIVED = "just_arrived"
    JUST_LEFT = "just_left"
    AWAY = "away"


HOME_LIKE = frozenset({PersonState.HOME, PersonState.JUST_ARRIVED, PersonState.JUST_LEFT})


class Method(StrEnum):
    """Why a member is in the current state (contract attribute ``method``)."""

    SIGNAL = "signal"
    PLAN = "plan"
    MANUAL = "manual"


class Mode(StrEnum):
    """Household mode (FR-MODE-01)."""

    AUTO = "auto"
    FORCE_HOME = "force_home"
    FORCE_AWAY = "force_away"
    VACATION = "vacation"


class PersonMode(StrEnum):
    """Manual mode of a member (FR-PER-09)."""

    AUTO = "auto"
    FORCE_HOME = "force_home"
    FORCE_AWAY = "force_away"


class HouseholdState(StrEnum):
    """Household state (FR-HH-05)."""

    HOME = "home"
    AWAY = "away"
    LONG_AWAY = "long_away"


class Reason(StrEnum):
    """Reason attribute of the household state."""

    SIGNALS = "signals"
    GUEST = "guest"
    HOUSEHOLD_SIGNAL = "household_signal"
    MANUAL = "manual"
    VACATION = "vacation"
    AWAY_UNTIL = "away_until"
    CALENDAR = "calendar"
    DURATION = "duration"
    PREDICTION = "prediction"


class ReturnSource(StrEnum):
    """Source of an expected return (FR-RET-01)."""

    PLANNED = "planned"
    APPROACHING = "approaching"
    LEARNED = "learned"


class EventType(StrEnum):
    """Events of the household (FR-EVT-01)."""

    ARRIVED = "arrived"
    LEFT = "left"
    FIRST_ARRIVED = "first_arrived"
    LAST_LEFT = "last_left"
    LONG_AWAY_STARTED = "long_away_started"
    LONG_AWAY_ENDED = "long_away_ended"
    MODE_CHANGED = "mode_changed"


# --- helpers ------------------------------------------------------------------


def parse_time(value: Any, default: time | None = None) -> time | None:
    """Parse ``HH:MM[:SS]`` into a time, return ``default`` when empty."""
    if isinstance(value, time):
        return value
    if not value:
        return default
    parts = [int(p) for p in str(value).split(":")]
    while len(parts) < 3:
        parts.append(0)
    return time(parts[0], parts[1], parts[2])


def in_window(local: time, start: time, end: time) -> bool:
    """Return True when ``local`` is in [start, end), the window may wrap midnight."""
    if start == end:
        return False
    if start < end:
        return start <= local < end
    return local >= start or local < end


def fold(text: str) -> str:
    """Lower-case text without diacritics, used for keyword matching."""
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).casefold()


def split_keywords(value: Any) -> tuple[str, ...]:
    """Split a comma separated string (or list) into folded keywords."""
    if not value:
        return ()
    items = value if isinstance(value, list | tuple) else str(value).split(",")
    return tuple(fold(str(item).strip()) for item in items if str(item).strip())


def _states(value: Any) -> tuple[str, ...]:
    if not value:
        return ()
    items = value if isinstance(value, list | tuple) else str(value).split(",")
    return tuple(str(item).strip() for item in items if str(item).strip())


def _minutes(value: Any, default: float = 0) -> timedelta:
    return timedelta(minutes=float(default if value is None or value == "" else value))


def _hours_or_none(value: Any) -> timedelta | None:
    if value is None or value == "" or float(value) <= 0:
        return None
    return timedelta(hours=float(value))


def default_home_states(entity_id: str) -> tuple[str, ...]:
    """Default states meaning home for a domain (FR-SIG-02)."""
    domain = entity_id.split(".", 1)[0]
    if domain in ("person", "device_tracker"):
        return ("home",)
    return ("on", "home")


# --- configuration --------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class SignalConfig:
    """One signal of a member or of the household."""

    entity_id: str
    kind: SignalKind = SignalKind.HOME_ONLY
    home_states: tuple[str, ...] = ()
    away_states: tuple[str, ...] = ()
    arrival_delay: timedelta = timedelta(0)
    max_on: timedelta | None = None
    valid_from: time | None = None
    valid_to: time | None = None
    trust: Trust = Trust.NORMAL

    @classmethod
    def from_data(cls, data: Mapping[str, Any]) -> SignalConfig:
        """Build from stored subentry data."""
        entity_id = str(data[c.CONF_ENTITY_ID])
        kind = SignalKind(data.get(c.CONF_KIND, SignalKind.HOME_ONLY))
        home = _states(data.get(c.CONF_HOME_STATES)) or default_home_states(entity_id)
        away = _states(data.get(c.CONF_AWAY_STATES))
        if kind is SignalKind.AWAY_ONLY and not away:
            away = ("on",)
        return cls(
            entity_id=entity_id,
            kind=kind,
            home_states=home,
            away_states=away,
            arrival_delay=_minutes(data.get(c.CONF_ARRIVAL_DELAY)),
            max_on=_hours_or_none(data.get(c.CONF_MAX_ON)),
            valid_from=parse_time(data.get(c.CONF_VALID_FROM)),
            valid_to=parse_time(data.get(c.CONF_VALID_TO)),
            trust=Trust(data.get(c.CONF_TRUST, Trust.NORMAL)),
        )


@dataclass(frozen=True, kw_only=True)
class PlanConfig:
    """Planned absence of a member from calendars (FR-PLAN-01..03)."""

    calendars: tuple[str, ...]
    keywords: tuple[str, ...] = ()
    gap_bridge: timedelta = timedelta(minutes=45)
    lead: timedelta = timedelta(minutes=20)
    trail: timedelta = timedelta(minutes=30)
    certain: bool = True
    all_day: bool = False

    @classmethod
    def from_data(cls, data: Mapping[str, Any] | None) -> PlanConfig | None:
        """Build from stored data, None when no calendar is configured."""
        if not data or not data.get(c.CONF_CALENDARS):
            return None
        d = {**c.DEFAULT_PLAN, **data}
        return cls(
            calendars=tuple(d[c.CONF_CALENDARS]),
            keywords=split_keywords(d.get(c.CONF_TITLE_FILTER)),
            gap_bridge=_minutes(d[c.CONF_GAP_BRIDGE]),
            lead=_minutes(d[c.CONF_LEAD]),
            trail=_minutes(d[c.CONF_TRAIL]),
            certain=bool(d[c.CONF_CERTAIN]),
            all_day=bool(d[c.CONF_ALL_DAY]),
        )


@dataclass(frozen=True, kw_only=True)
class ApproachConfig:
    """Approach detection of a member (FR-APPR-01)."""

    distance_entity: str
    direction_entity: str | None = None
    threshold_km: float = 15.0
    confirmations: int = 2
    speed_kmh: float = 50.0

    @classmethod
    def from_data(cls, data: Mapping[str, Any] | None) -> ApproachConfig | None:
        """Build from stored data, None when no distance entity is configured."""
        if not data or not data.get(c.CONF_DISTANCE_ENTITY):
            return None
        d = {**c.DEFAULT_APPROACH, **data}
        return cls(
            distance_entity=str(d[c.CONF_DISTANCE_ENTITY]),
            direction_entity=d.get(c.CONF_DIRECTION_ENTITY) or None,
            threshold_km=float(d[c.CONF_THRESHOLD_KM]),
            confirmations=max(1, int(d[c.CONF_CONFIRMATIONS])),
            speed_kmh=max(1.0, float(d[c.CONF_SPEED_KMH])),
        )


@dataclass(frozen=True, kw_only=True)
class NightWindow:
    """Night window in local time (FR-PER-06)."""

    start: time
    end: time

    def contains(self, local: time) -> bool:
        """Return True when the local time is inside the window."""
        return in_window(local, self.start, self.end)


@dataclass(frozen=True, kw_only=True)
class MemberConfig:
    """One household member (config subentry ``member``)."""

    member_id: str
    name: str
    slug: str
    signals: tuple[SignalConfig, ...] = ()
    policy: NoSignalPolicy = NoSignalPolicy.AWAY_AFTER_DELAY
    departure_delay: timedelta | None = None
    night_mode: str = c.NIGHT_INHERIT
    night: NightWindow | None = None
    plan: PlanConfig | None = None
    approach: ApproachConfig | None = None

    @classmethod
    def from_data(cls, member_id: str, slug: str, data: Mapping[str, Any]) -> MemberConfig:
        """Build from subentry data."""
        night_mode = data.get(c.CONF_NIGHT_MODE, c.NIGHT_INHERIT)
        night = None
        if night_mode == c.NIGHT_CUSTOM:
            start = parse_time(data.get(c.CONF_NIGHT_START), time(22))
            end = parse_time(data.get(c.CONF_NIGHT_END), time(7))
            assert start is not None
            assert end is not None
            night = NightWindow(start=start, end=end)
        delay = data.get(c.CONF_MEMBER_DEPARTURE_DELAY)
        return cls(
            member_id=member_id,
            name=str(data.get(c.CONF_NAME) or slug),
            slug=slug,
            signals=tuple(SignalConfig.from_data(s) for s in data.get(c.CONF_SIGNALS, [])),
            policy=NoSignalPolicy(data.get(c.CONF_POLICY, NoSignalPolicy.AWAY_AFTER_DELAY)),
            departure_delay=None if delay in (None, "") else _minutes(delay),
            night_mode=night_mode,
            night=night,
            plan=PlanConfig.from_data(data.get(c.CONF_PLAN)),
            approach=ApproachConfig.from_data(data.get(c.CONF_APPROACH)),
        )

    @property
    def can_leave(self) -> bool:
        """Return False when nothing can ever move the member away (FR-REP-01)."""
        if self.plan is not None or self.policy is NoSignalPolicy.AWAY_AFTER_DELAY:
            return True
        return any(s.kind is not SignalKind.HOME_ONLY for s in self.signals)


@dataclass(frozen=True, kw_only=True)
class HouseholdConfig:
    """Options of the household (main config entry)."""

    departure_delay: timedelta = timedelta(minutes=15)
    startup_grace: timedelta = timedelta(minutes=5)
    just_arrived: timedelta = timedelta(minutes=10)
    unavailable_timeout: timedelta = timedelta(hours=6)
    night: NightWindow | None = None
    door_entities: tuple[str, ...] = ()
    door_window: timedelta = timedelta(minutes=10)
    household_signals: tuple[SignalConfig, ...] = ()
    long_away_after: timedelta = timedelta(hours=24)
    return_horizon: timedelta = timedelta(hours=12)
    long_away_prediction: bool = True
    long_away_prediction_min: timedelta = timedelta(hours=2)
    guest_auto_off: str = c.GUEST_OFF_NEVER
    guest_off_time: time = time(4)
    guest_off_after: timedelta = timedelta(hours=24)
    vacation_calendars: tuple[str, ...] = ()
    vacation_keywords: tuple[str, ...] = ()
    workday_entity: str | None = None
    half_life_weeks: float = 4.0
    min_samples: int = 3

    @classmethod
    def from_options(cls, options: Mapping[str, Any]) -> HouseholdConfig:
        """Build from config entry options merged with defaults."""
        o = {**c.DEFAULT_OPTIONS, **options}
        night = None
        if o[c.CONF_NIGHT_ENABLED]:
            start = parse_time(o[c.CONF_NIGHT_START], time(22))
            end = parse_time(o[c.CONF_NIGHT_END], time(7))
            assert start is not None
            assert end is not None
            night = NightWindow(start=start, end=end)
        return cls(
            departure_delay=_minutes(o[c.CONF_DEPARTURE_DELAY]),
            startup_grace=_minutes(o[c.CONF_STARTUP_GRACE]),
            just_arrived=_minutes(o[c.CONF_JUST_ARRIVED]),
            unavailable_timeout=timedelta(hours=float(o[c.CONF_UNAVAILABLE_HOURS])),
            night=night,
            door_entities=tuple(o[c.CONF_DOOR_ENTITIES] or ()),
            door_window=_minutes(o[c.CONF_DOOR_WINDOW]),
            household_signals=tuple(
                SignalConfig(entity_id=e, kind=SignalKind.HOME_ONLY, home_states=("on", "home"))
                for e in o[c.CONF_HOUSEHOLD_SIGNALS] or ()
            ),
            long_away_after=timedelta(hours=float(o[c.CONF_LONG_AWAY_HOURS])),
            return_horizon=timedelta(hours=float(o[c.CONF_RETURN_HORIZON])),
            long_away_prediction=bool(o[c.CONF_LONG_AWAY_PREDICTION]),
            long_away_prediction_min=timedelta(hours=float(o[c.CONF_LONG_AWAY_PREDICTION_MIN])),
            guest_auto_off=str(o[c.CONF_GUEST_AUTO_OFF]),
            guest_off_time=parse_time(o[c.CONF_GUEST_OFF_TIME], time(4)) or time(4),
            guest_off_after=timedelta(hours=float(o[c.CONF_GUEST_OFF_HOURS])),
            vacation_calendars=tuple(o[c.CONF_VACATION_CALENDARS] or ()),
            vacation_keywords=split_keywords(o[c.CONF_VACATION_KEYWORDS]),
            workday_entity=o.get(c.CONF_WORKDAY_ENTITY) or None,
            half_life_weeks=max(0.5, float(o[c.CONF_HALF_LIFE_WEEKS])),
            min_samples=max(1, int(o[c.CONF_MIN_SAMPLES])),
        )

    def night_for(self, member: MemberConfig) -> NightWindow | None:
        """Return the effective night window of a member."""
        if member.night_mode == c.NIGHT_OFF:
            return None
        if member.night_mode == c.NIGHT_CUSTOM:
            return member.night
        return self.night

    def delay_for(self, member: MemberConfig) -> timedelta:
        """Return the effective departure delay of a member."""
        return (
            member.departure_delay if member.departure_delay is not None else self.departure_delay
        )


# --- runtime inputs -------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class EntityReading:
    """State of one entity as seen by the engine."""

    state: str
    last_changed: datetime
    attributes: Mapping[str, Any] = field(default_factory=dict)

    @property
    def available(self) -> bool:
        """Return True for a usable state."""
        return self.state.casefold() not in UNAVAILABLE_STATES


@dataclass(frozen=True, kw_only=True)
class CalendarEvent:
    """One calendar event, times are aware datetimes."""

    start: datetime
    end: datetime
    summary: str = ""
    all_day: bool = False


@dataclass(frozen=True, kw_only=True)
class CalendarData:
    """Cached events of one calendar."""

    ok: bool
    events: tuple[CalendarEvent, ...] = ()


@dataclass(frozen=True, kw_only=True)
class Snapshot:
    """Everything the engine sees in one step."""

    now: datetime
    entities: Mapping[str, EntityReading] = field(default_factory=dict)
    calendars: Mapping[str, CalendarData] = field(default_factory=dict)

    def get(self, entity_id: str) -> EntityReading | None:
        """Return the reading of an entity or None when it does not exist."""
        return self.entities.get(entity_id)


# --- outputs ----------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class Event:
    """Something worth a logbook line (FR-EVT-01)."""

    type: EventType
    at: datetime
    member_id: str | None = None
    name: str | None = None
    data: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class Problem:
    """Configuration or signal problem shown as a repair issue (FR-REP-01)."""

    key: str
    kind: str
    placeholders: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class ExpectedReturn:
    """Expected return with its source and confidence."""

    at: datetime
    source: ReturnSource
    confidence: float
    member_id: str | None = None
    name: str | None = None


@dataclass(frozen=True, kw_only=True)
class SignalView:
    """Diagnostic view of one signal."""

    entity_id: str
    kind: SignalKind
    reading: Reading
    raw: str | None
    stuck: bool = False
    pending_until: datetime | None = None


@dataclass(frozen=True, kw_only=True)
class PersonView:
    """Output of one member for the entities."""

    member_id: str
    name: str
    state: PersonState
    since: datetime | None
    method: Method
    sources: tuple[str, ...]
    available: bool
    mode: PersonMode
    away_until: datetime | None
    expected_return: ExpectedReturn | None
    approaching: bool
    signals: Sequence[SignalView] = ()

    @property
    def is_home(self) -> bool | None:
        """Return the binary presence, None when unknown."""
        if self.state is PersonState.UNKNOWN:
            return None
        return self.state in HOME_LIKE


@dataclass(frozen=True, kw_only=True)
class HouseholdView:
    """Output of the household for the entities."""

    someone_home: bool
    people: tuple[str, ...]
    count: int
    since: datetime | None
    state: HouseholdState
    reason: Reason
    long_away: bool
    away_since: datetime | None
    expected_return: ExpectedReturn | None
    approaching: tuple[str, ...]
    mode: Mode
    guest: bool
    away_until: datetime | None
    last_return_error: float | None


@dataclass(frozen=True, kw_only=True)
class StepResult:
    """Result of one engine step."""

    household: HouseholdView
    persons: Mapping[str, PersonView]
    events: Sequence[Event] = ()
    problems: Sequence[Problem] = ()
