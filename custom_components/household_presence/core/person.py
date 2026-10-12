"""State machine of one household member (FR-PER-01..09)."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Any

from .model import (
    HOME_LIKE,
    Event,
    EventType,
    MemberConfig,
    Method,
    NightWindow,
    NoSignalPolicy,
    PersonMode,
    PersonState,
    Reading,
    Trust,
)
from .plan import Block
from .signals import SignalEval


def _dt(value: Any) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


@dataclass(kw_only=True)
class PersonRuntime:
    """Mutable state of a member kept across steps and restarts."""

    state: PersonState = PersonState.UNKNOWN
    since: datetime | None = None
    method: Method = Method.SIGNAL
    sources: tuple[str, ...] = ()
    left_at: datetime | None = None
    arrived_at: datetime | None = None
    mode: PersonMode = PersonMode.AUTO
    manual_set_at: datetime | None = None
    away_until: datetime | None = None
    unavailable_since: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize for the Store."""
        return {
            "state": self.state.value,
            "since": _iso(self.since),
            "method": self.method.value,
            "sources": list(self.sources),
            "left_at": _iso(self.left_at),
            "arrived_at": _iso(self.arrived_at),
            "mode": self.mode.value,
            "manual_set_at": _iso(self.manual_set_at),
            "away_until": _iso(self.away_until),
            "unavailable_since": _iso(self.unavailable_since),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> PersonRuntime:
        """Restore from the Store, unknown values fall back to defaults."""
        try:
            return cls(
                state=PersonState(data.get("state", PersonState.UNKNOWN)),
                since=_dt(data.get("since")),
                method=Method(data.get("method", Method.SIGNAL)),
                sources=tuple(data.get("sources") or ()),
                left_at=_dt(data.get("left_at")),
                arrived_at=_dt(data.get("arrived_at")),
                mode=PersonMode(data.get("mode", PersonMode.AUTO)),
                manual_set_at=_dt(data.get("manual_set_at")),
                away_until=_dt(data.get("away_until")),
                unavailable_since=_dt(data.get("unavailable_since")),
            )
        except ValueError, TypeError:
            return cls()

    @property
    def is_home(self) -> bool:
        """Return True when the member counts as home."""
        return self.state in HOME_LIKE


@dataclass(frozen=True, kw_only=True)
class PersonContext:
    """Inputs of one member step that do not come from its own signals."""

    now: datetime
    local: time
    grace: bool
    delay: timedelta
    just_arrived: timedelta
    unavailable_timeout: timedelta
    night: NightWindow | None = None
    local_left: time | None = None
    door_activity: datetime | None = None
    door_window: timedelta = timedelta(minutes=10)
    plan_block: Block | None = None


@dataclass(kw_only=True)
class PersonStepResult:
    """What happened to a member in one step."""

    events: list[Event] = field(default_factory=list)
    trusted_home_since: datetime | None = None
    manual_cleared: bool = False


def trusted_home_since(evals: Sequence[SignalEval]) -> datetime | None:
    """Return when the newest high-trust HOME signal changed (FR-SIG-08)."""
    times = [
        e.changed_at
        for e in evals
        if e.value is Reading.HOME and e.config.trust is Trust.HIGH and e.changed_at
    ]
    return max(times, default=None)


def _night_allows(cfg: MemberConfig, rt: PersonRuntime, ctx: PersonContext) -> bool:
    """Policy departures at night need a door change (FR-PER-06)."""
    if ctx.night is None:
        return True
    local_left = ctx.local_left or ctx.local
    if not (ctx.night.contains(ctx.local) or ctx.night.contains(local_left)):
        return True
    if ctx.door_activity is None or rt.left_at is None:
        return False
    return ctx.door_activity >= rt.left_at - ctx.door_window


def step(
    cfg: MemberConfig,
    rt: PersonRuntime,
    evals: Sequence[SignalEval],
    ctx: PersonContext,
) -> PersonStepResult:
    """Advance the state machine of one member."""
    now = ctx.now
    result = PersonStepResult(trusted_home_since=trusted_home_since(evals))

    if rt.away_until is not None and now >= rt.away_until:
        rt.away_until = None

    if (
        (rt.mode is PersonMode.FORCE_AWAY or rt.away_until is not None)
        and result.trusted_home_since is not None
        and (rt.manual_set_at is None or result.trusted_home_since > rt.manual_set_at)
    ):
        rt.mode = PersonMode.AUTO
        rt.away_until = None
        result.manual_cleared = True

    home = [e for e in evals if e.value is Reading.HOME]
    all_unavailable = bool(evals) and all(e.value is Reading.UNAVAILABLE for e in evals)
    if all_unavailable:
        rt.unavailable_since = rt.unavailable_since or now
    else:
        rt.unavailable_since = None
    unavailable_long = (
        all_unavailable
        and rt.unavailable_since is not None
        and now - rt.unavailable_since >= ctx.unavailable_timeout
    )

    strong = any(e.value is Reading.AWAY for e in evals)
    policy = (
        cfg.policy is NoSignalPolicy.AWAY_AFTER_DELAY
        and any(e.value is not Reading.UNAVAILABLE for e in evals)
        and not home
    )
    planned = ctx.plan_block is not None

    if rt.mode is PersonMode.FORCE_HOME:
        _to_home(cfg, rt, ctx, result, Method.MANUAL, ())
    elif rt.mode is PersonMode.FORCE_AWAY or rt.away_until is not None:
        _to_away_now(cfg, rt, ctx, result)
    elif home:
        _to_home(cfg, rt, ctx, result, Method.SIGNAL, tuple(e.config.entity_id for e in home))
    elif unavailable_long:
        if rt.state is not PersonState.UNKNOWN:
            rt.state = PersonState.UNKNOWN
            rt.since = now
            rt.left_at = None
            rt.sources = ()
    elif strong or policy or planned:
        method = Method.PLAN if planned and not strong and not policy else Method.SIGNAL
        _to_away_delayed(cfg, rt, ctx, result, method, night_check=policy and not strong)
    elif (
        rt.state is PersonState.AWAY
        and rt.method is Method.PLAN
        and cfg.policy is NoSignalPolicy.HOLD_LAST
    ):
        # The plan ended and nothing contradicts it: assume the member came back.
        _to_home(cfg, rt, ctx, result, Method.PLAN, ())
    else:
        _hold(rt, ctx)
    return result


def _event(cfg: MemberConfig, kind: EventType, at: datetime, method: Method) -> Event:
    return Event(
        type=kind,
        at=at,
        member_id=cfg.member_id,
        name=cfg.name,
        data={"method": method.value},
    )


def _to_home(
    cfg: MemberConfig,
    rt: PersonRuntime,
    ctx: PersonContext,
    result: PersonStepResult,
    method: Method,
    sources: tuple[str, ...],
) -> None:
    now = ctx.now
    if rt.state is PersonState.AWAY:
        rt.state = PersonState.JUST_ARRIVED
        rt.arrived_at = now
        rt.since = now
        result.events.append(_event(cfg, EventType.ARRIVED, now, method))
    elif rt.state is PersonState.UNKNOWN:
        rt.state = PersonState.HOME
        rt.since = now
    elif rt.state is PersonState.JUST_LEFT:
        rt.state = PersonState.HOME
    _promote_arrival(rt, ctx)
    rt.left_at = None
    rt.method = method
    rt.sources = sources


def _to_away_now(
    cfg: MemberConfig, rt: PersonRuntime, ctx: PersonContext, result: PersonStepResult
) -> None:
    now = ctx.now
    if rt.state in HOME_LIKE:
        result.events.append(_event(cfg, EventType.LEFT, now, Method.MANUAL))
    if rt.state is not PersonState.AWAY:
        rt.state = PersonState.AWAY
        rt.since = now
    rt.left_at = None
    rt.arrived_at = None
    rt.method = Method.MANUAL
    rt.sources = ()


def _to_away_delayed(
    cfg: MemberConfig,
    rt: PersonRuntime,
    ctx: PersonContext,
    result: PersonStepResult,
    method: Method,
    *,
    night_check: bool,
) -> None:
    now = ctx.now
    if ctx.grace:
        return
    if rt.state is PersonState.UNKNOWN:
        rt.state = PersonState.AWAY
        rt.since = now
        rt.method = method
        rt.sources = ()
    elif rt.state in (PersonState.HOME, PersonState.JUST_ARRIVED):
        rt.state = PersonState.JUST_LEFT
        rt.left_at = now
        rt.arrived_at = None
    elif rt.state is PersonState.JUST_LEFT:
        left_at = rt.left_at or now
        rt.left_at = left_at
        if now - left_at < ctx.delay:
            return
        if not night_check or _night_allows(cfg, rt, ctx):
            rt.state = PersonState.AWAY
            rt.since = left_at
            rt.left_at = None
            rt.method = method
            rt.sources = ()
            result.events.append(_event(cfg, EventType.LEFT, left_at, method))
        elif ctx.night is not None and not ctx.night.contains(ctx.local):
            # The night is over and the signals did not come back: start the
            # departure delay again from the morning.
            rt.left_at = now
    elif rt.state is PersonState.AWAY and rt.method is not method and method is Method.SIGNAL:
        rt.method = method


def _promote_arrival(rt: PersonRuntime, ctx: PersonContext) -> None:
    if (
        rt.state is PersonState.JUST_ARRIVED
        and rt.arrived_at is not None
        and ctx.now - rt.arrived_at >= ctx.just_arrived
    ):
        rt.state = PersonState.HOME
        rt.arrived_at = None


def _hold(rt: PersonRuntime, ctx: PersonContext) -> None:
    if rt.state is PersonState.JUST_LEFT:
        rt.state = PersonState.HOME
        rt.left_at = None
    _promote_arrival(rt, ctx)
