"""Presence engine: one step turns a Snapshot into the household view (NFR-04)."""

from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import datetime, tzinfo
from typing import Any

from .. import const as c
from . import household as hh, person as per
from .approach import ApproachTracker
from .learning import Learner
from .model import (
    CalendarEvent,
    Event,
    EventType,
    ExpectedReturn,
    GroupConfig,
    GroupView,
    HouseholdConfig,
    HouseholdView,
    Mode,
    PersonMode,
    PersonState,
    PersonView,
    Problem,
    Reading,
    Snapshot,
    StepResult,
)
from .plan import Block, active_block, active_event, build_blocks, collect
from .returns import household_return, person_return
from .signals import SignalEval, SignalMemory, evaluate

HOUSEHOLD_KEY = "_household"


class PresenceEngine:
    """Members, household, returns and learning in one deterministic step."""

    def __init__(
        self,
        household: HouseholdConfig,
        members: Sequence[per.MemberConfig],
        tz: tzinfo,
        groups: Sequence[GroupConfig] = (),
    ) -> None:
        """Initialize the engine."""
        self.tz = tz
        self.config = household
        self.members: dict[str, per.MemberConfig] = {}
        self.persons: dict[str, per.PersonRuntime] = {}
        self.approach: dict[str, ApproachTracker] = {}
        self.household = hh.HouseholdRuntime()
        self.learner = Learner(
            half_life_weeks=household.half_life_weeks,
            min_samples=household.min_samples,
            tz=tz,
        )
        self.started_at: datetime | None = None
        self.last_result: StepResult | None = None
        self.last_errors: dict[str, float] = {}
        # Last known prediction of the running absence, used for the error metric.
        self._predictions: dict[str, ExpectedReturn] = {}
        self._signals: dict[str, list[SignalEval]] = {}
        self.memory = SignalMemory()
        self.groups: dict[str, GroupConfig] = {}
        self.group_flags: dict[str, hh.Flag] = {}
        self.multiple = hh.Flag()
        self.reconfigure(household, members, groups)

    # --- configuration ------------------------------------------------------------

    def reconfigure(
        self,
        household: HouseholdConfig,
        members: Sequence[per.MemberConfig],
        groups: Sequence[GroupConfig] = (),
    ) -> None:
        """Apply a new configuration and keep the runtime state of known members."""
        self.config = household
        self.learner.half_life_weeks = household.half_life_weeks
        self.learner.min_samples = household.min_samples
        self.members = {m.member_id: m for m in members}
        self.persons = {mid: self.persons.get(mid) or per.PersonRuntime() for mid in self.members}
        self.approach = {
            mid: self.approach.get(mid) or ApproachTracker()
            for mid, m in self.members.items()
            if m.approach is not None
        }
        self.groups = {g.group_id: g for g in groups}
        self.group_flags = {gid: self.group_flags.get(gid) or hh.Flag() for gid in self.groups}

    def watched_entities(self) -> set[str]:
        """Return entities whose change should trigger a step."""
        entities: set[str] = set(self.config.door_entities)
        entities.update(s.entity_id for s in self.config.household_signals)
        if self.config.workday_entity:
            entities.add(self.config.workday_entity)
        for member in self.members.values():
            entities.update(s.entity_id for s in member.signals)
            if member.approach is not None:
                entities.add(member.approach.distance_entity)
                if member.approach.direction_entity:
                    entities.add(member.approach.direction_entity)
        return entities

    def calendar_entities(self) -> set[str]:
        """Return calendars the runtime has to fetch."""
        calendars = set(self.config.vacation_calendars)
        for member in self.members.values():
            if member.plan is not None:
                calendars.update(member.plan.calendars)
        return calendars

    # --- user actions -----------------------------------------------------------------

    def set_mode(self, mode: Mode, now: datetime) -> None:
        """Set the household mode (FR-MODE-01)."""
        self.household.set_mode(mode, now)

    def set_guest(self, on: bool, now: datetime) -> None:
        """Switch the guest on or off (FR-GUEST-01)."""
        self.household.guest = on
        self.household.guest_on_at = now if on else None

    def set_away_until(
        self, value: datetime | None, now: datetime, member_id: str | None = None
    ) -> None:
        """Set or clear the planned return of the household or of one member."""
        if value is not None and value <= now:
            value = None
        if member_id is None:
            self.household.away_until = value
            self.household.away_until_set_at = now if value else None
            return
        rt = self.persons[member_id]
        rt.away_until = value
        rt.manual_set_at = now

    def set_person_mode(self, member_id: str, mode: PersonMode, now: datetime) -> None:
        """Set the manual mode of one member (FR-PER-09)."""
        rt = self.persons[member_id]
        rt.mode = mode
        rt.manual_set_at = now

    def reset_learning(self, member_id: str | None = None) -> None:
        """Forget learned data of one member or of everybody."""
        self.learner.reset(None if member_id is None else [member_id])
        self.last_errors.clear()

    # --- step ---------------------------------------------------------------------------

    def step(self, snap: Snapshot) -> StepResult:
        """Evaluate everything for ``snap.now``."""
        snap = self._effective(snap)
        cfg = self.config
        now = snap.now
        local_dt = now.astimezone(self.tz)
        local = local_dt.time()
        if self.started_at is None:
            self.started_at = now
        grace = now - self.started_at < cfg.startup_grace
        # Entities get a fresh last_changed when Home Assistant starts; such a
        # change is not a real transition during a plan (FR-SIG-07).
        startup_end = self.started_at + cfg.startup_grace
        problems: dict[str, Problem] = {}
        events: list[Event] = list(self.household.pending_events)
        self.household.pending_events.clear()

        door_activity = max(
            (
                r.last_changed
                for e in cfg.door_entities
                if (r := snap.get(e)) is not None and r.available
            ),
            default=None,
        )

        vacation_event: CalendarEvent | None = None
        if cfg.vacation_calendars:
            vac_events, failed = collect(
                cfg.vacation_calendars, snap.calendars, cfg.vacation_keywords, all_day=True
            )
            vacation_event = active_event(vac_events, now)
            self._calendar_problems(failed, problems, grace)

        trusted: list[datetime] = []
        plan_ends: dict[str, datetime | None] = {}
        before: dict[str, tuple[PersonState, datetime | None]] = {}
        for mid, member in self.members.items():
            rt = self.persons[mid]
            before[mid] = (rt.state, rt.since)
            block = self._plan_block(member, snap, now, problems, grace)
            plan_ends[mid] = block.end if block is not None else None
            certain = block if block is not None and member.plan and member.plan.certain else None
            evals = [
                evaluate(
                    s,
                    snap.get(s.entity_id),
                    now,
                    local,
                    plan_start=max(certain.start, startup_end) if certain else None,
                )
                for s in member.signals
            ]
            self._signals[mid] = evals
            self._signal_problems(member, evals, snap, problems, grace)
            ctx = per.PersonContext(
                now=now,
                local=local,
                grace=grace,
                delay=cfg.delay_for(member),
                just_arrived=cfg.just_arrived,
                unavailable_timeout=cfg.unavailable_timeout,
                night=cfg.night_for(member),
                local_left=rt.left_at.astimezone(self.tz).time() if rt.left_at else None,
                door_activity=door_activity,
                door_window=cfg.door_window,
                plan_block=certain,
            )
            result = per.step(member, rt, evals, ctx)
            events.extend(result.events)
            if result.trusted_home_since is not None:
                trusted.append(result.trusted_home_since)
            if not member.can_leave:
                problems[f"member_cannot_leave.{mid}"] = Problem(
                    key=f"member_cannot_leave.{mid}",
                    kind="member_cannot_leave",
                    placeholders={"member": member.name},
                )
            if (
                rt.unavailable_since is not None
                and now - rt.unavailable_since >= cfg.unavailable_timeout
            ):
                problems[f"member_unavailable.{mid}"] = Problem(
                    key=f"member_unavailable.{mid}",
                    kind="member_unavailable",
                    placeholders={"member": member.name},
                )

        household_signal = any(
            evaluate(s, snap.get(s.entity_id), now, local).value is Reading.HOME
            for s in cfg.household_signals
        )
        hh.apply_manual_rules(cfg, self.household, now, self.tz, trusted)
        events.extend(self.household.pending_events)
        self.household.pending_events.clear()

        people = tuple(self.members[mid].name for mid, rt in self.persons.items() if rt.is_home)
        pres = hh.presence(self.household, people, household_signal)
        last_departure = max(
            (rt.since for rt in self.persons.values() if not rt.is_home and rt.since),
            default=None,
        )
        events.extend(hh.update_presence(self.household, pres, now, last_departure))

        workday = self._workday(snap, local_dt)
        returns: dict[str, ExpectedReturn | None] = {}
        approaching: list[str] = []
        ready = True
        for mid, member in self.members.items():
            rt = self.persons[mid]
            eta = self._approach(mid, member, snap, now, rt)
            if eta is not None:
                approaching.append(member.name)
            learned = None
            if not rt.is_home and rt.state is not PersonState.UNKNOWN:
                prediction = self.learner.predict(mid, now, workday=workday)
                ready = ready and prediction.ready
                if prediction.at is not None:
                    learned = (prediction.at, prediction.confidence)
            returns[mid] = person_return(
                member,
                rt,
                now,
                household_away_until=self.household.away_until,
                vacation_end=vacation_event.end if vacation_event else None,
                plan_end=plan_ends[mid],
                approach_eta=eta,
                learned=learned,
            )
        absent = [rt for rt in self.persons.values() if not rt.is_home]
        expected = household_return(
            returns.values(),
            now,
            someone_home=pres.someone_home,
            household_away_until=self.household.away_until,
        )
        long_reason = hh.long_away_reason(
            cfg,
            self.household,
            now,
            vacation_event=vacation_event,
            expected_return=expected,
            model_ready=ready and bool(absent),
        )
        long_events = hh.update_long_away(self.household, long_reason, now)
        if long_events and long_events[0].type is EventType.LONG_AWAY_STARTED and vacation_event:
            long_events[0] = Event(
                type=long_events[0].type,
                at=now,
                data={**long_events[0].data, "until": vacation_event.end.isoformat()},
            )
        events.extend(long_events)

        multiple_view, groups_view = self._groups(returns, now, events)
        self._learn(events, before, now, workday, vacation_event)
        self._remember_predictions(returns, expected, pres.someone_home)
        state, reason = hh.household_state(pres, long_reason)

        persons_view = {
            mid: self._person_view(mid, returns[mid], approaching, now) for mid in self.members
        }
        view = HouseholdView(
            someone_home=pres.someone_home,
            people=people,
            count=len(people),
            since=self.household.since,
            state=state,
            reason=reason,
            long_away=long_reason is not None,
            away_since=None if pres.someone_home else self.household.away_since,
            expected_return=expected,
            approaching=tuple(approaching),
            mode=self.household.mode,
            guest=self.household.guest,
            away_until=self.household.away_until,
            last_return_error=self.last_errors.get(HOUSEHOLD_KEY),
            multiple_home=multiple_view,
            multiple_min=cfg.multiple_min,
        )
        result = StepResult(
            household=view,
            persons=persons_view,
            groups=groups_view,
            events=sorted(events, key=lambda e: e.at),
            problems=list(problems.values()),
        )
        self.last_result = result
        return result

    # --- step helpers ---------------------------------------------------------------------

    def _groups(
        self,
        returns: Mapping[str, ExpectedReturn | None],
        now: datetime,
        events: list[Event],
    ) -> tuple[bool, dict[str, GroupView]]:
        """Several people home and named groups (FR-HH-07, FR-GRP-02)."""
        override = hh.forced(self.household.mode)
        home = [mid for mid, rt in self.persons.items() if rt.is_home]
        multiple = override if override is not None else len(home) >= self.config.multiple_min
        if self.multiple.update(multiple, now):
            events.append(
                Event(
                    type=EventType.MULTIPLE_HOME if multiple else EventType.MULTIPLE_ENDED,
                    at=now,
                    data={"count": len(home), "min": self.config.multiple_min},
                )
            )
        views: dict[str, GroupView] = {}
        for gid, group in self.groups.items():
            present = [m for m in group.members if m in self.persons and m in home]
            on = override if override is not None else len(present) >= group.min_count
            flag = self.group_flags[gid]
            if flag.update(on, now):
                events.append(
                    Event(
                        type=EventType.GROUP_HOME if on else EventType.GROUP_AWAY,
                        at=now,
                        name=group.name,
                        group_id=gid,
                        data={"count": len(present)},
                    )
                )
            expected = None
            if not on:
                candidates = [r for m in group.members if (r := returns.get(m)) is not None]
                expected = min(candidates, key=lambda r: r.at, default=None)
            views[gid] = GroupView(
                group_id=gid,
                name=group.name,
                home=on,
                count=len(present),
                people=tuple(self.members[m].name for m in present),
                since=flag.since,
                expected_return=expected,
            )
        return multiple, views

    def _signal_entities(self) -> set[str]:
        entities = set(self.config.door_entities)
        entities.update(s.entity_id for s in self.config.household_signals)
        for member in self.members.values():
            entities.update(s.entity_id for s in member.signals)
        return entities

    def _effective(self, snap: Snapshot) -> Snapshot:
        """Replace last_changed of signals by the time of their last real change."""
        signals = self._signal_entities()
        self.memory.keep(signals)
        entities = dict(snap.entities)
        for entity_id in signals:
            reading = self.memory.effective(entity_id, entities.get(entity_id))
            if reading is not None:
                entities[entity_id] = reading
        return replace(snap, entities=entities)

    def _plan_block(
        self,
        member: per.MemberConfig,
        snap: Snapshot,
        now: datetime,
        problems: dict[str, Problem],
        grace: bool,
    ) -> Block | None:
        if member.plan is None:
            return None
        events, failed = collect(
            member.plan.calendars, snap.calendars, member.plan.keywords, all_day=member.plan.all_day
        )
        self._calendar_problems(failed, problems, grace)
        return active_block(build_blocks(member.plan, events), now)

    @staticmethod
    def _calendar_problems(
        failed: Sequence[str], problems: dict[str, Problem], grace: bool
    ) -> None:
        if grace:
            return
        for cal in failed:
            key = f"calendar_unavailable.{cal}"
            problems[key] = Problem(
                key=key, kind="calendar_unavailable", placeholders={"entity_id": cal}
            )

    @staticmethod
    def _signal_problems(
        member: per.MemberConfig,
        evals: Sequence[SignalEval],
        snap: Snapshot,
        problems: dict[str, Problem],
        grace: bool,
    ) -> None:
        for e in evals:
            entity_id = e.config.entity_id
            placeholders = {"member": member.name, "entity_id": entity_id}
            if e.stuck:
                key = f"signal_stuck.{member.member_id}.{entity_id}"
                problems[key] = Problem(key=key, kind="signal_stuck", placeholders=placeholders)
            if not grace and snap.get(entity_id) is None:
                key = f"signal_missing.{member.member_id}.{entity_id}"
                problems[key] = Problem(key=key, kind="signal_missing", placeholders=placeholders)

    def _workday(self, snap: Snapshot, local_dt: datetime) -> bool:
        entity = self.config.workday_entity
        reading = snap.get(entity) if entity else None
        if reading is not None and reading.available:
            return reading.state.casefold() == "on"
        return local_dt.weekday() < 5

    def _approach(
        self,
        mid: str,
        member: per.MemberConfig,
        snap: Snapshot,
        now: datetime,
        rt: per.PersonRuntime,
    ) -> datetime | None:
        cfg = member.approach
        tracker = self.approach.get(mid)
        if cfg is None or tracker is None:
            return None
        if rt.is_home:
            tracker.reset()
            return None
        direction = snap.get(cfg.direction_entity) if cfg.direction_entity else None
        return tracker.update(cfg, snap.get(cfg.distance_entity), direction, now)

    def _learn(
        self,
        events: Sequence[Event],
        before: Mapping[str, tuple[PersonState, datetime | None]],
        now: datetime,
        workday: bool,
        vacation_event: CalendarEvent | None,
    ) -> None:
        household = self.household
        hh_excluded = (
            household.mode is not Mode.AUTO
            or household.away_until is not None
            or vacation_event is not None
        )
        for event in events:
            if event.type is EventType.ARRIVED and event.member_id in self.members:
                mid = event.member_id
                previous = self._predictions.pop(mid, None)
                error = self.learner.arrival(
                    mid,
                    event.at,
                    predicted=previous.at if previous else None,
                    away_since=before[mid][1],
                    workday=workday,
                )
                if error is not None:
                    self.last_errors[mid] = error
            elif event.type is EventType.FIRST_ARRIVED:
                previous = self._predictions.pop(HOUSEHOLD_KEY, None)
                error = self.learner.arrival(
                    HOUSEHOLD_KEY,
                    event.at,
                    predicted=previous.at if previous else None,
                    away_since=None,
                    workday=workday,
                )
                if error is not None:
                    self.last_errors[HOUSEHOLD_KEY] = error
        for mid, rt in self.persons.items():
            excluded = (
                hh_excluded
                or rt.mode is not PersonMode.AUTO
                or rt.away_until is not None
                or rt.state is PersonState.UNKNOWN
            )
            home = None if rt.state is PersonState.UNKNOWN else rt.is_home
            self.learner.observe(mid, now, home=home, excluded=excluded, workday=workday)
        self.learner.observe(
            HOUSEHOLD_KEY,
            now,
            home=household.someone_home,
            excluded=hh_excluded,
            workday=workday,
        )

    def _remember_predictions(
        self,
        returns: Mapping[str, ExpectedReturn | None],
        expected: ExpectedReturn | None,
        someone_home: bool,
    ) -> None:
        for mid, value in returns.items():
            if self.persons[mid].is_home:
                self._predictions.pop(mid, None)
            elif value is not None:
                self._predictions[mid] = value
        if someone_home:
            self._predictions.pop(HOUSEHOLD_KEY, None)
        elif expected is not None:
            self._predictions[HOUSEHOLD_KEY] = expected

    def _person_view(
        self,
        mid: str,
        expected: ExpectedReturn | None,
        approaching: Sequence[str],
        now: datetime,
    ) -> PersonView:
        member = self.members[mid]
        rt = self.persons[mid]
        unavailable = (
            rt.state is PersonState.UNKNOWN
            and rt.unavailable_since is not None
            and now - rt.unavailable_since >= self.config.unavailable_timeout
        )
        return PersonView(
            member_id=mid,
            name=member.name,
            state=rt.state,
            since=rt.since,
            method=rt.method,
            sources=rt.sources,
            available=not unavailable,
            mode=rt.mode,
            away_until=rt.away_until,
            expected_return=expected,
            approaching=member.name in approaching,
            signals=[e.view() for e in self._signals.get(mid, [])],
        )

    # --- persistence ----------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialize the runtime state for the Store (NFR-03)."""
        return {
            "format": c.STORAGE_FORMAT,
            "persons": {mid: rt.to_dict() for mid, rt in self.persons.items()},
            "household": self.household.to_dict(),
            "learning": self.learner.to_dict(),
            "last_errors": dict(self.last_errors),
            "signals": self.memory.to_dict(),
            "multiple": self.multiple.to_dict(),
            "groups": {gid: f.to_dict() for gid, f in self.group_flags.items()},
        }

    def restore(self, data: Mapping[str, Any] | None) -> None:
        """Restore the runtime state; unknown members are dropped."""
        if not data or data.get("format") != c.STORAGE_FORMAT:
            return
        persons = data.get("persons") or {}
        for mid in self.members:
            if mid in persons:
                self.persons[mid] = per.PersonRuntime.from_dict(persons[mid])
        self.household = hh.HouseholdRuntime.from_dict(data.get("household") or {})
        self.learner.restore(data.get("learning") or {})
        self.memory.restore(data.get("signals"))
        self.multiple = hh.Flag.from_dict(data.get("multiple"))
        groups = data.get("groups") or {}
        self.group_flags = {gid: hh.Flag.from_dict(groups.get(gid)) for gid in self.groups}
        self.learner.forget([*self.members, HOUSEHOLD_KEY])
        self.last_errors = {
            k: float(v)
            for k, v in (data.get("last_errors") or {}).items()
            if isinstance(v, int | float)
        }
