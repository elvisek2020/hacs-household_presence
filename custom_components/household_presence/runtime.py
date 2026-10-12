"""Runtime glue between Home Assistant and the pure presence engine."""

from collections.abc import Callable
from datetime import date, datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, Event as HAEvent, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er, issue_registry as ir
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util, slugify

from . import explain
from .const import (
    CALENDAR_LOOKAHEAD_H,
    CALENDAR_LOOKBACK_H,
    CALENDAR_REFRESH_S,
    CALENDAR_RETRY_S,
    DOMAIN,
    ENTITY_PREFIX,
    EVENT_PRESENCE,
    SAVE_DELAY_S,
    STORAGE_VERSION,
    SUBENTRY_MEMBER,
    UPDATE_INTERVAL_S,
)
from .core.engine import PresenceEngine
from .core.model import (
    CalendarData,
    CalendarEvent,
    EntityReading,
    Event,
    HouseholdConfig,
    MemberConfig,
    Mode,
    PersonMode,
    Snapshot,
    StepResult,
)

_LOGGER = logging.getLogger(__name__)

type HouseholdPresenceConfigEntry = ConfigEntry[HouseholdPresenceRuntime]


def member_slug(subentry_unique_id: str | None, title: str) -> str:
    """Return the slug used in entity ids of a member."""
    return subentry_unique_id or slugify(title)


def member_configs(entry: ConfigEntry) -> list[MemberConfig]:
    """Build member configurations from the subentries."""
    return [
        MemberConfig.from_data(sub_id, member_slug(sub.unique_id, sub.title), sub.data)
        for sub_id, sub in entry.subentries.items()
        if sub.subentry_type == SUBENTRY_MEMBER
    ]


def structure_of(entry: ConfigEntry) -> tuple[Any, ...]:
    """Return what requires a reload when it changes (NFR-09)."""
    return (
        entry.title,
        tuple(
            sorted(
                (sub_id, sub.title, sub.unique_id)
                for sub_id, sub in entry.subentries.items()
                if sub.subentry_type == SUBENTRY_MEMBER
            )
        ),
    )


def _parse_event(raw: dict[str, Any], tz: Any) -> CalendarEvent | None:
    """Parse one event of ``calendar.get_events``."""
    start_raw, end_raw = raw.get("start"), raw.get("end")
    if not start_raw or not end_raw:
        return None
    all_day = "T" not in str(start_raw)
    if all_day:
        start = datetime.combine(date.fromisoformat(str(start_raw)), datetime.min.time(), tz)
        end = datetime.combine(date.fromisoformat(str(end_raw)), datetime.min.time(), tz)
    else:
        start = dt_util.parse_datetime(str(start_raw))
        end = dt_util.parse_datetime(str(end_raw))
        if start is None or end is None:
            return None
        if start.tzinfo is None:
            start = start.replace(tzinfo=tz)
        if end.tzinfo is None:
            end = end.replace(tzinfo=tz)
    return CalendarEvent(
        start=start, end=end, summary=str(raw.get("summary") or ""), all_day=all_day
    )


class HouseholdPresenceRuntime:
    """Watches entities, runs the engine and publishes the result."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the runtime."""
        self.hass = hass
        self.entry = entry
        self.tz = dt_util.get_default_time_zone()
        self.store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        self.structure = structure_of(entry)
        self.engine = PresenceEngine(
            HouseholdConfig.from_options(entry.options), member_configs(entry), self.tz
        )
        self.result: StepResult | None = None
        self.calendars: dict[str, CalendarData] = {}
        self.calendars_fetched_at: datetime | None = None
        self._listeners: list[CALLBACK_TYPE] = []
        self._event_listeners: list[Callable[[Event], None]] = []
        self._unsubs: list[CALLBACK_TYPE] = []
        self._state_unsub: CALLBACK_TYPE | None = None
        self._issues: set[str] = set()
        self._active = False
        self._calendar_task_running = False

    # --- lifecycle ------------------------------------------------------------------

    async def async_load(self) -> None:
        """Restore the stored state (NFR-03)."""
        try:
            data = await self.store.async_load()
        except Exception:
            _LOGGER.exception("Cannot load stored presence state, starting fresh")
            data = None
        self.engine.restore(data)
        registry = ir.async_get(self.hass)
        self._issues = {issue_id for (domain, issue_id) in registry.issues if domain == DOMAIN}

    async def async_start(self) -> None:
        """Subscribe to changes, fetch calendars and run the first step."""
        self._active = True
        self._subscribe()
        self._unsubs.append(
            async_track_time_interval(
                self.hass, self._handle_tick, timedelta(seconds=UPDATE_INTERVAL_S)
            )
        )
        self._unsubs.append(
            async_track_time_interval(
                self.hass, self._handle_calendar_tick, timedelta(seconds=CALENDAR_REFRESH_S)
            )
        )
        await self.async_refresh_calendars()
        self.async_step()

    async def async_stop(self) -> None:
        """Unsubscribe and save immediately."""
        self._active = False
        if self._state_unsub is not None:
            self._state_unsub()
            self._state_unsub = None
        while self._unsubs:
            self._unsubs.pop()()
        await self.store.async_save(self.engine.to_dict())

    @callback
    def apply_config(self) -> None:
        """Apply changed options or member values without a reload (NFR-09)."""
        self.engine.reconfigure(
            HouseholdConfig.from_options(self.entry.options), member_configs(self.entry)
        )
        self._subscribe()
        self.entry.async_create_background_task(
            self.hass, self._async_refresh_and_step(), f"{DOMAIN}_apply_config"
        )

    async def _async_refresh_and_step(self) -> None:
        await self.async_refresh_calendars()
        self.async_step()

    @callback
    def _subscribe(self) -> None:
        if self._state_unsub is not None:
            self._state_unsub()
        entities = sorted(self.engine.watched_entities())
        self._state_unsub = (
            async_track_state_change_event(self.hass, entities, self._handle_state)
            if entities
            else None
        )

    @callback
    def _handle_state(self, _event: HAEvent[Any]) -> None:
        self.async_step()

    @callback
    def _handle_tick(self, now: datetime) -> None:
        if self._calendar_retry_due(now):
            self._handle_calendar_tick(now)
        self.async_step()

    def _calendar_retry_due(self, now: datetime) -> bool:
        """Retry failed calendars every minute, e.g. right after HA starts."""
        if self._calendar_task_running or not any(not d.ok for d in self.calendars.values()):
            return False
        fetched = self.calendars_fetched_at
        return fetched is None or now - fetched >= timedelta(seconds=CALENDAR_RETRY_S)

    @callback
    def _handle_calendar_tick(self, _now: datetime) -> None:
        if self._calendar_task_running:
            return
        self._calendar_task_running = True
        self.entry.async_create_background_task(
            self.hass, self._async_calendar_task(), f"{DOMAIN}_calendars"
        )

    async def _async_calendar_task(self) -> None:
        try:
            await self._async_refresh_and_step()
        finally:
            self._calendar_task_running = False

    # --- calendars ----------------------------------------------------------------------

    async def async_refresh_calendars(self) -> None:
        """Fetch events of all calendars used by the engine (FR-PLAN-04)."""
        now = dt_util.now()
        start = now - timedelta(hours=CALENDAR_LOOKBACK_H)
        end = now + timedelta(hours=CALENDAR_LOOKAHEAD_H)
        fresh: dict[str, CalendarData] = {}
        for entity_id in sorted(self.engine.calendar_entities()):
            fresh[entity_id] = await self._async_fetch_calendar(entity_id, start, end)
        self.calendars = fresh
        self.calendars_fetched_at = now

    async def _async_fetch_calendar(
        self, entity_id: str, start: datetime, end: datetime
    ) -> CalendarData:
        state = self.hass.states.get(entity_id)
        if state is None or state.state == "unavailable":
            return CalendarData(ok=False)
        try:
            response = await self.hass.services.async_call(
                "calendar",
                "get_events",
                {"entity_id": entity_id, "start_date_time": start, "end_date_time": end},
                blocking=True,
                return_response=True,
            )
        except Exception as err:
            _LOGGER.warning("Cannot read calendar %s: %s", entity_id, err)
            return CalendarData(ok=False)
        raw_events = ((response or {}).get(entity_id) or {}).get("events") or []
        events = tuple(
            e for raw in raw_events if isinstance(raw, dict) and (e := _parse_event(raw, self.tz))
        )
        return CalendarData(ok=True, events=events)

    # --- step -----------------------------------------------------------------------------

    def _snapshot(self) -> Snapshot:
        entities: dict[str, EntityReading] = {}
        for entity_id in self.engine.watched_entities():
            state = self.hass.states.get(entity_id)
            if state is not None:
                entities[entity_id] = EntityReading(
                    state=state.state,
                    last_changed=state.last_changed,
                    attributes=dict(state.attributes),
                )
        return Snapshot(now=dt_util.utcnow(), entities=entities, calendars=self.calendars)

    @callback
    def async_step(self) -> None:
        """Run one engine step; never raises (NFR-01)."""
        if not self._active:
            return
        try:
            result = self.engine.step(self._snapshot())
        except Exception:
            _LOGGER.exception("Presence step failed, keeping the previous result")
            return
        self.result = result
        try:
            for event in result.events:
                self._publish_event(event)
            self._sync_issues(result)
        except Exception:
            _LOGGER.exception("Publishing presence events failed")
        self.store.async_delay_save(self.engine.to_dict, SAVE_DELAY_S)
        for listener in list(self._listeners):
            listener()

    # --- events and issues ----------------------------------------------------------------

    def _member_entity_id(self, member_id: str | None) -> str | None:
        registry = er.async_get(self.hass)
        if member_id is None:
            return (
                registry.async_get_entity_id(
                    "binary_sensor", DOMAIN, f"{self.entry.entry_id}_someone_home"
                )
                or f"binary_sensor.{ENTITY_PREFIX}_someone_home"
            )
        return registry.async_get_entity_id(
            "binary_sensor", DOMAIN, f"{self.entry.entry_id}_{member_id}_home"
        )

    @callback
    def _publish_event(self, event: Event) -> None:
        message = explain.message(event, self.hass.config.language, self.tz)
        self.hass.bus.async_fire(
            EVENT_PRESENCE,
            {
                "type": event.type.value,
                "member": event.name,
                "member_id": event.member_id,
                "at": event.at.isoformat(),
                "message": message,
                "name": event.name or self.entry.title,
                "entity_id": self._member_entity_id(event.member_id),
                **{k: v for k, v in event.data.items() if isinstance(v, str | int | float)},
            },
        )
        for listener in list(self._event_listeners):
            listener(event)

    @callback
    def _sync_issues(self, result: StepResult) -> None:
        current = {p.key: p for p in result.problems}
        for key, problem in current.items():
            if key not in self._issues:
                ir.async_create_issue(
                    self.hass,
                    DOMAIN,
                    key,
                    is_fixable=False,
                    severity=ir.IssueSeverity.WARNING,
                    translation_key=problem.kind,
                    translation_placeholders=dict(problem.placeholders),
                )
        for key in self._issues - current.keys():
            ir.async_delete_issue(self.hass, DOMAIN, key)
        self._issues = set(current)

    # --- listeners ------------------------------------------------------------------

    @callback
    def async_add_listener(self, listener: CALLBACK_TYPE) -> CALLBACK_TYPE:
        """Register an entity update callback."""
        self._listeners.append(listener)

        @callback
        def remove() -> None:
            self._listeners.remove(listener)

        return remove

    @callback
    def async_add_event_listener(self, listener: Callable[[Event], None]) -> CALLBACK_TYPE:
        """Register a callback for presence events (event entity)."""
        self._event_listeners.append(listener)

        @callback
        def remove() -> None:
            self._event_listeners.remove(listener)

        return remove

    # --- user actions ---------------------------------------------------------------

    def find_member(self, name_or_id: str) -> str | None:
        """Return the member id by id, slug or name (case-insensitive)."""
        wanted = name_or_id.strip().casefold()
        for mid, member in self.engine.members.items():
            if wanted in (mid.casefold(), member.slug.casefold(), member.name.casefold()):
                return mid
        return None

    async def _async_after_action(self) -> None:
        self.async_step()
        await self.store.async_save(self.engine.to_dict())

    async def async_set_mode(self, mode: Mode) -> None:
        """Set the household mode."""
        self.engine.set_mode(mode, dt_util.utcnow())
        await self._async_after_action()

    async def async_set_person_mode(self, member_id: str, mode: PersonMode) -> None:
        """Set the manual mode of a member."""
        self.engine.set_person_mode(member_id, mode, dt_util.utcnow())
        await self._async_after_action()

    async def async_set_guest(self, on: bool) -> None:
        """Switch the guest on or off."""
        self.engine.set_guest(on, dt_util.utcnow())
        await self._async_after_action()

    async def async_set_away_until(
        self, value: datetime | None, member_id: str | None = None
    ) -> None:
        """Set or clear the planned return of the household or a member."""
        self.engine.set_away_until(value, dt_util.utcnow(), member_id)
        await self._async_after_action()

    async def async_reset_learning(self, member_id: str | None = None) -> None:
        """Forget learned habits."""
        self.engine.reset_learning(member_id)
        await self._async_after_action()
