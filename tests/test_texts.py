"""Logbook descriptions, sentences and calendar parsing."""

from datetime import datetime
from zoneinfo import ZoneInfo

from homeassistant.core import Event as HAEvent, HomeAssistant

from custom_components.household_presence import explain, logbook
from custom_components.household_presence.const import DOMAIN, EVENT_PRESENCE
from custom_components.household_presence.core.model import Event, EventType
from custom_components.household_presence.runtime import _parse_event

TZ = ZoneInfo("Europe/Prague")
AT = datetime(2026, 10, 12, 7, 42, tzinfo=TZ)


def test_messages_in_czech_and_english() -> None:
    left = Event(type=EventType.LAST_LEFT, at=AT)
    assert explain.message(left, "cs", TZ) == "Nikdo doma od 7:42"
    assert explain.message(left, "en", TZ) == "Nobody home since 7:42"
    long_away = Event(
        type=EventType.LONG_AWAY_STARTED,
        at=AT,
        data={"reason": "away_until", "until": datetime(2026, 10, 18, 18, tzinfo=TZ).isoformat()},
    )
    assert explain.message(long_away, "cs", TZ) == "Dlouhodobě pryč: pryč do neděle 18. 10. 18:00"
    assert explain.message(long_away, "en", TZ) == "Away for long: away until Sunday 18 Oct 18:00"
    mode = Event(type=EventType.MODE_CHANGED, at=AT, data={"to": "auto", "reason": "arrival"})
    assert explain.message(mode, "cs", TZ) == "Režim: automaticky (příchod domů)"
    arrived = Event(type=EventType.ARRIVED, at=AT, name="Alex")
    assert explain.message(arrived, "cs", TZ) == "Příchod: Alex"


def test_logbook_description(hass: HomeAssistant) -> None:
    described = {}

    def register(domain, event_name, callback):
        described[(domain, event_name)] = callback

    logbook.async_describe_events(hass, register)
    describe = described[(DOMAIN, EVENT_PRESENCE)]
    event = HAEvent(
        EVENT_PRESENCE,
        {"name": "Alex", "message": "Příchod: Alex", "entity_id": "binary_sensor.hp_alex_home"},
    )
    assert describe(event) == {
        "name": "Alex",
        "message": "Příchod: Alex",
        "entity_id": "binary_sensor.hp_alex_home",
    }
    assert "entity_id" not in describe(HAEvent(EVENT_PRESENCE, {"message": "x"}))


def test_parse_calendar_events() -> None:
    timed = _parse_event(
        {"start": "2026-10-12T08:00:00+02:00", "end": "2026-10-12T08:45:00+02:00", "summary": "M"},
        TZ,
    )
    assert timed is not None
    assert not timed.all_day
    assert timed.end.hour == 8
    all_day = _parse_event({"start": "2026-10-12", "end": "2026-10-13"}, TZ)
    assert all_day is not None
    assert all_day.all_day
    assert all_day.start == datetime(2026, 10, 12, tzinfo=TZ)
    assert _parse_event({"start": "2026-10-12"}, TZ) is None
