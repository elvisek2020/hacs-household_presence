"""Setup, entities of the contract, runtime behaviour and services."""

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er, issue_registry as ir
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_time_changed,
)

from custom_components.household_presence import const as c
from custom_components.household_presence.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .conftest import GPS, PC, SCHOOL, WIFI, setup_entry

CONTRACT = [
    "binary_sensor.hp_someone_home",
    "binary_sensor.hp_long_away",
    "binary_sensor.hp_someone_approaching",
    "sensor.hp_people_home",
    "sensor.hp_household_state",
    "sensor.hp_away_since",
    "sensor.hp_expected_return",
    "sensor.hp_expected_return_confidence",
    "sensor.hp_expected_return_error",
    "select.hp_mode",
    "switch.hp_guest",
    "datetime.hp_away_until",
    "event.hp_household",
    "binary_sensor.hp_parent_home",
    "sensor.hp_parent_state",
    "sensor.hp_parent_expected_return",
    "select.hp_parent_mode",
    "datetime.hp_parent_away_until",
    "binary_sensor.hp_kid_home",
]


async def _wait(hass: HomeAssistant, freezer: FrozenDateTimeFactory, minutes: float) -> None:
    for _ in range(int(minutes * 2)):
        freezer.tick(timedelta(seconds=30))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()


@pytest.fixture(autouse=True)
def _language(hass: HomeAssistant) -> None:
    hass.config.language = "cs"


async def test_setup_creates_contract_entities(
    hass: HomeAssistant, config_entry: MockConfigEntry, fake_calendar
) -> None:
    hass.states.async_set(GPS, "home")
    hass.states.async_set(PC, "on")
    hass.states.async_set(SCHOOL, "off")
    await setup_entry(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED
    for entity_id in CONTRACT:
        assert hass.states.get(entity_id) is not None, entity_id
    registry = er.async_get(hass)
    entry = registry.async_get("binary_sensor.hp_parent_home")
    assert entry.unique_id == "entry_id_parent_id_home"
    assert entry.config_subentry_id == "parent_id"
    assert entry.translation_key == "home"

    someone = hass.states.get("binary_sensor.hp_someone_home")
    assert someone.state == "on"
    assert someone.attributes["device_class"] == "presence"
    assert someone.attributes["count"] == 2
    assert sorted(someone.attributes["people"]) == ["Kid", "Parent"]
    assert hass.states.get("sensor.hp_people_home").state == "2"
    assert hass.states.get("sensor.hp_household_state").state == "home"
    assert hass.states.get("sensor.hp_expected_return").state == "unknown"
    assert hass.states.get("select.hp_mode").state == "auto"


async def test_departure_and_arrival_events(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
    fake_calendar,
) -> None:
    freezer.move_to("2026-10-12 08:00:00+02:00")
    hass.states.async_set(GPS, "home")
    hass.states.async_set(PC, "off")
    hass.states.async_set(SCHOOL, "off")
    await setup_entry(hass, config_entry)
    events = async_capture_events(hass, c.EVENT_PRESENCE)

    hass.states.async_set(GPS, "not_home")
    await hass.async_block_till_done()
    assert hass.states.get("sensor.hp_parent_state").state == "just_left"
    assert hass.states.get("binary_sensor.hp_parent_home").state == "on"
    await _wait(hass, freezer, 16)
    assert hass.states.get("binary_sensor.hp_parent_home").state == "off"
    assert hass.states.get("sensor.hp_parent_state").state == "away"
    # The kid is unknown (hold_last without a signal), so the parent was the last one.
    assert [e.data["type"] for e in events] == ["left", "last_left"]
    assert events[0].data["message"] == "Odchod: Parent"
    assert events[0].data["entity_id"] == "binary_sensor.hp_parent_home"

    hass.states.async_set(GPS, "home")
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.hp_parent_home").state == "on"
    assert [e.data["type"] for e in events[-2:]] == ["arrived", "first_arrived"]
    assert events[-1].data["message"] == "Někdo je doma"
    event_state = hass.states.get("event.hp_household")
    assert event_state.attributes["event_type"] == "first_arrived"


async def test_plan_from_calendar_and_expected_return(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
    fake_calendar,
) -> None:
    freezer.move_to("2026-10-12 07:00:00+02:00")
    start = dt_util.parse_datetime("2026-10-12 08:00:00+02:00")
    fake_calendar(SCHOOL, start, start + timedelta(hours=4))
    hass.states.async_set(GPS, "not_home")
    hass.states.async_set(WIFI, "not_home")
    hass.states.async_set(PC, "on")
    await setup_entry(hass, config_entry)
    hass.states.async_set(PC, "off")
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.hp_kid_home").state == "on"
    await _wait(hass, freezer, 60)
    assert hass.states.get("binary_sensor.hp_kid_home").state == "off"
    assert hass.states.get("binary_sensor.hp_kid_home").attributes["method"] == "plan"
    assert hass.states.get("binary_sensor.hp_someone_home").state == "off"
    expected = hass.states.get("sensor.hp_expected_return")
    assert dt_util.parse_datetime(expected.state) == start + timedelta(hours=4, minutes=30)
    assert expected.attributes["source"] == "planned"
    assert expected.attributes["person"] == "Kid"
    assert expected.attributes["confidence"] >= 0.5
    assert hass.states.get("sensor.hp_expected_return_confidence").state == "80"
    assert hass.states.get("sensor.hp_household_state").state == "away"


async def test_controls_mode_guest_and_away_until(
    hass: HomeAssistant, config_entry: MockConfigEntry, fake_calendar
) -> None:
    hass.states.async_set(GPS, "not_home")
    hass.states.async_set(WIFI, "not_home")
    hass.states.async_set(PC, "off")
    hass.states.async_set(SCHOOL, "off")
    await setup_entry(hass, config_entry)

    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.hp_guest"}, blocking=True
    )
    assert hass.states.get("binary_sensor.hp_someone_home").state == "on"
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.hp_guest"}, blocking=True
    )

    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": "select.hp_mode", "option": "force_away"},
        blocking=True,
    )
    assert hass.states.get("binary_sensor.hp_someone_home").state == "off"
    assert hass.states.get("select.hp_mode").state == "force_away"

    until = dt_util.now() + timedelta(days=2)
    await hass.services.async_call(
        "datetime",
        "set_value",
        {"entity_id": "datetime.hp_away_until", "datetime": until},
        blocking=True,
    )
    assert hass.states.get("binary_sensor.hp_long_away").state == "on"
    assert hass.states.get("sensor.hp_household_state").state == "long_away"

    await hass.services.async_call(
        c.DOMAIN, "set_away_until", {"until": until, "member": "kid"}, blocking=True
    )
    assert hass.states.get("datetime.hp_kid_away_until").state != "unknown"
    await hass.services.async_call(c.DOMAIN, "clear_away_until", {"member": "Kid"}, blocking=True)
    assert hass.states.get("datetime.hp_kid_away_until").state == "unknown"

    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": "select.hp_kid_mode", "option": "force_home"},
        blocking=True,
    )
    assert hass.states.get("binary_sensor.hp_kid_home").attributes["method"] == "manual"

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            c.DOMAIN, "set_away_until", {"until": until, "member": "nobody"}, blocking=True
        )
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            c.DOMAIN,
            "set_away_until",
            {"until": dt_util.now() - timedelta(hours=1)},
            blocking=True,
        )
    await hass.services.async_call(c.DOMAIN, "reset_learning", {}, blocking=True)


async def test_state_survives_reload(
    hass: HomeAssistant, config_entry: MockConfigEntry, fake_calendar
) -> None:
    hass.states.async_set(GPS, "home")
    hass.states.async_set(PC, "off")
    hass.states.async_set(SCHOOL, "off")
    await setup_entry(hass, config_entry)
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": "select.hp_mode", "option": "vacation"},
        blocking=True,
    )
    assert await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("select.hp_mode").state == "vacation"


async def test_repairs_for_missing_signal_and_calendar(
    hass: HomeAssistant, config_entry: MockConfigEntry, fake_calendar
) -> None:
    hass.states.async_set(GPS, "home")
    await setup_entry(hass, config_entry)
    registry = ir.async_get(hass)
    issues = {i for (d, i) in registry.issues if d == c.DOMAIN}
    assert f"signal_missing.kid_id.{PC}" in issues
    assert f"calendar_unavailable.{SCHOOL}" in issues

    hass.states.async_set(PC, "off")
    await hass.async_block_till_done()
    issues = {i for (d, i) in registry.issues if d == c.DOMAIN}
    assert f"signal_missing.kid_id.{PC}" not in issues


async def test_options_change_applies_without_reload(
    hass: HomeAssistant, config_entry: MockConfigEntry, fake_calendar
) -> None:
    hass.states.async_set(GPS, "home")
    hass.states.async_set(PC, "off")
    hass.states.async_set(SCHOOL, "off")
    await setup_entry(hass, config_entry)
    runtime = config_entry.runtime_data
    hass.config_entries.async_update_entry(
        config_entry, options={**config_entry.options, c.CONF_DEPARTURE_DELAY: 30}
    )
    await hass.async_block_till_done()
    assert config_entry.runtime_data is runtime
    assert runtime.engine.config.departure_delay == timedelta(minutes=30)


async def test_diagnostics_redact_names(
    hass: HomeAssistant, config_entry: MockConfigEntry, fake_calendar
) -> None:
    hass.states.async_set(GPS, "home")
    hass.states.async_set(PC, "off")
    hass.states.async_set(SCHOOL, "off")
    await setup_entry(hass, config_entry)
    data = await async_get_config_entry_diagnostics(hass, config_entry)
    text = str(data)
    assert "Parent" not in text
    assert SCHOOL not in text
    assert data["household"]["someone_home"] is True
    assert "_household" in data["learning"]
    assert data["groups"] == {}


async def test_unload(hass: HomeAssistant, config_entry: MockConfigEntry, fake_calendar) -> None:
    await setup_entry(hass, config_entry)
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.NOT_LOADED


async def test_failed_calendar_is_retried(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
    fake_calendar,
) -> None:
    hass.states.async_set(PC, "off")
    await setup_entry(hass, config_entry)
    runtime = config_entry.runtime_data
    assert not runtime.calendars[SCHOOL].ok
    fake_calendar(SCHOOL, dt_util.now(), dt_util.now() + timedelta(hours=1))
    await _wait(hass, freezer, 1.5)
    assert runtime.calendars[SCHOOL].ok
    assert len(runtime.calendars[SCHOOL].events) == 1


async def test_integration_reload_during_plan_is_not_an_arrival(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
    fake_calendar,
) -> None:
    freezer.move_to("2026-10-12 06:00:00+02:00")
    start = dt_util.parse_datetime("2026-10-12 08:00:00+02:00")
    fake_calendar(SCHOOL, start, start + timedelta(hours=4))
    hass.states.async_set(GPS, "home")
    hass.states.async_set(PC, "on")
    await setup_entry(hass, config_entry)
    await _wait(hass, freezer, 3 * 60)
    assert hass.states.get("binary_sensor.hp_kid_home").state == "off"
    # The integration providing the signal reloads: unavailable, then on again.
    hass.states.async_set(PC, "unavailable")
    await _wait(hass, freezer, 0.5)
    hass.states.async_set(PC, "on")
    await _wait(hass, freezer, 30)
    assert hass.states.get("binary_sensor.hp_kid_home").state == "off"
    # The memory survives a reload of this integration too.
    assert await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()
    hass.states.async_set(PC, "unavailable")
    await _wait(hass, freezer, 0.5)
    hass.states.async_set(PC, "on")
    await _wait(hass, freezer, 10)
    assert hass.states.get("binary_sensor.hp_kid_home").state == "off"
