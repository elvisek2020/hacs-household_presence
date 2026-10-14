"""Groups of members and several people home in Home Assistant (FR-GRP, FR-HH-07)."""

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant import config_entries
from homeassistant.config_entries import ConfigSubentryDataWithId
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_time_changed,
)

from custom_components.household_presence import const as c

from .conftest import GPS, KID, PARENT, PC, SCHOOL, member_subentry, setup_entry

OTHER = "device_tracker.other_phone"
GROUP = ConfigSubentryDataWithId(
    data={c.CONF_NAME: "Adults", c.CONF_MEMBERS: ["parent_id", "other_id"], c.CONF_MIN_COUNT: 1},
    subentry_id="adults_id",
    subentry_type=c.SUBENTRY_GROUP,
    title="Adults",
    unique_id="group_adults",
)


def _entry() -> MockConfigEntry:
    other = member_subentry(
        "other_id",
        "Other",
        {c.CONF_SIGNALS: [{c.CONF_ENTITY_ID: OTHER, c.CONF_KIND: "home_away"}]},
    )
    return MockConfigEntry(
        domain=c.DOMAIN,
        title="Home",
        data={},
        options={**c.DEFAULT_OPTIONS, c.CONF_STARTUP_GRACE: 0},
        subentries_data=[PARENT, KID, other, GROUP],
        entry_id="entry_id",
    )


async def _wait(hass: HomeAssistant, freezer: FrozenDateTimeFactory, minutes: float) -> None:
    for _ in range(int(minutes * 2)):
        freezer.tick(timedelta(seconds=30))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()


async def test_group_and_multiple_entities(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, fake_calendar
) -> None:
    hass.config.language = "cs"
    hass.states.async_set(GPS, "home")
    hass.states.async_set(OTHER, "home")
    hass.states.async_set(PC, "off")
    hass.states.async_set(SCHOOL, "off")
    entry = _entry()
    await setup_entry(hass, entry)

    group = hass.states.get("binary_sensor.hp_group_adults_home")
    assert group.state == "on"
    assert group.attributes["count"] == 2
    assert group.attributes["device_class"] == "presence"
    assert hass.states.get("sensor.hp_group_adults_expected_return").state == "unknown"
    multiple = hass.states.get("binary_sensor.hp_multiple_home")
    assert multiple.state == "on"
    assert multiple.attributes["min"] == 2
    entity = er.async_get(hass).async_get("binary_sensor.hp_group_adults_home")
    assert entity.unique_id == "entry_id_adults_id_home"
    assert entity.config_subentry_id == "adults_id"

    events = async_capture_events(hass, c.EVENT_PRESENCE)
    hass.states.async_set(GPS, "not_home")
    await _wait(hass, freezer, 16)
    assert hass.states.get("binary_sensor.hp_group_adults_home").state == "on"
    assert hass.states.get("binary_sensor.hp_multiple_home").state == "off"
    hass.states.async_set(OTHER, "not_home")
    await _wait(hass, freezer, 16)
    assert hass.states.get("binary_sensor.hp_group_adults_home").state == "off"
    by_type = {e.data["type"]: e.data for e in events}
    assert by_type["multiple_ended"]["message"] == "Doma méně než 2 lidí"
    assert by_type["multiple_ended"]["entity_id"] == "binary_sensor.hp_multiple_home"
    assert by_type["group_away"]["message"] == "Skupina Adults: pryč"
    assert by_type["group_away"]["entity_id"] == "binary_sensor.hp_group_adults_home"


async def test_group_flow(
    hass: HomeAssistant, config_entry: MockConfigEntry, fake_calendar
) -> None:
    await setup_entry(hass, config_entry)
    result = await hass.config_entries.subentries.async_init(
        (config_entry.entry_id, c.SUBENTRY_GROUP),
        context={"source": config_entries.SOURCE_USER},
    )
    assert result["step_id"] == "group"
    flow_id = result["flow_id"]
    result = await hass.config_entries.subentries.async_configure(
        flow_id, {c.CONF_NAME: "Parents", c.CONF_MEMBERS: [], c.CONF_MIN_COUNT: 1}
    )
    assert result["errors"] == {c.CONF_MEMBERS: "no_members_selected"}
    result = await hass.config_entries.subentries.async_configure(
        flow_id, {c.CONF_NAME: "Parents", c.CONF_MEMBERS: ["parent_id"], c.CONF_MIN_COUNT: 2}
    )
    assert result["errors"] == {c.CONF_MIN_COUNT: "min_count_too_high"}
    result = await hass.config_entries.subentries.async_configure(
        flow_id,
        {c.CONF_NAME: "Parents", c.CONF_MEMBERS: ["parent_id", "kid_id"], c.CONF_MIN_COUNT: 1},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    sub = next(s for s in config_entry.subentries.values() if s.title == "Parents")
    assert sub.unique_id == "group_parents"
    assert hass.states.get("binary_sensor.hp_group_parents_home") is not None

    # Reconfigure: change the minimum without a reload.
    runtime = config_entry.runtime_data
    result = await config_entry.start_subentry_reconfigure_flow(hass, sub.subentry_id)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {c.CONF_NAME: "Parents", c.CONF_MEMBERS: ["parent_id", "kid_id"], c.CONF_MIN_COUNT: 2},
    )
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()
    assert config_entry.runtime_data is runtime
    assert runtime.engine.groups[sub.subentry_id].min_count == 2

    # A group cannot take the name of an existing group.
    result = await hass.config_entries.subentries.async_init(
        (config_entry.entry_id, c.SUBENTRY_GROUP),
        context={"source": config_entries.SOURCE_USER},
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {c.CONF_NAME: "parents", c.CONF_MEMBERS: ["kid_id"], c.CONF_MIN_COUNT: 1},
    )
    assert result["errors"] == {c.CONF_NAME: "name_exists"}


async def test_group_flow_needs_members(hass: HomeAssistant, fake_calendar) -> None:
    entry = MockConfigEntry(domain=c.DOMAIN, title="Home", data={}, options=dict(c.DEFAULT_OPTIONS))
    await setup_entry(hass, entry)
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, c.SUBENTRY_GROUP),
        context={"source": config_entries.SOURCE_USER},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_members"


async def test_group_since_entity(hass: HomeAssistant, fake_calendar) -> None:
    hass.states.async_set(GPS, "home")
    hass.states.async_set(OTHER, "home")
    await setup_entry(hass, _entry())
    state = hass.states.get("sensor.hp_group_adults_since")
    assert state is not None
    assert state.attributes["device_class"] == "timestamp"
    assert state.state != "unknown"
