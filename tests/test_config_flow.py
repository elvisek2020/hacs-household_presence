"""Config flow, options flow and the member subentry flow."""

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.household_presence import const as c

from .conftest import GPS, PC, SCHOOL, setup_entry


async def test_user_flow_creates_household(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        c.DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {c.CONF_NAME: "Home", c.CONF_DEPARTURE_DELAY: 20}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Home"
    assert result["data"] == {}
    assert result["options"][c.CONF_DEPARTURE_DELAY] == 20
    assert result["options"][c.CONF_LONG_AWAY_HOURS] == 24


async def test_single_instance(hass: HomeAssistant, config_entry: MockConfigEntry) -> None:
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        c.DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_options_flow_steps(
    hass: HomeAssistant, config_entry: MockConfigEntry, fake_calendar
) -> None:
    await setup_entry(hass, config_entry)
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    assert "night" in result["menu_options"]

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "night"}
    )
    assert result["step_id"] == "night"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            c.CONF_NIGHT_ENABLED: True,
            c.CONF_NIGHT_START: "23:00:00",
            c.CONF_NIGHT_END: "06:30:00",
            c.CONF_DOOR_ENTITIES: ["binary_sensor.front_door"],
            c.CONF_DOOR_WINDOW: 5,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options[c.CONF_NIGHT_START] == "23:00:00"
    assert config_entry.options[c.CONF_DOOR_ENTITIES] == ["binary_sensor.front_door"]
    await hass.async_block_till_done()
    assert config_entry.runtime_data.engine.config.door_entities == ("binary_sensor.front_door",)

    # Clearing an optional field removes it.
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "household_signals"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {c.CONF_HOUSEHOLD_SIGNALS: [], c.CONF_WORKDAY_ENTITY: "binary_sensor.workday"},
    )
    assert config_entry.options[c.CONF_WORKDAY_ENTITY] == "binary_sensor.workday"
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "household_signals"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {c.CONF_HOUSEHOLD_SIGNALS: []}
    )
    assert c.CONF_WORKDAY_ENTITY not in config_entry.options

    for step in ("general", "long_away", "guest", "vacation", "learning"):
        result = await hass.config_entries.options.async_init(config_entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"next_step_id": step}
        )
        assert result["type"] is FlowResultType.FORM
        result = await hass.config_entries.options.async_configure(result["flow_id"], {})
        assert result["type"] is FlowResultType.CREATE_ENTRY, step


async def _menu(hass: HomeAssistant, flow_id: str, step: str, data=None):
    result = await hass.config_entries.subentries.async_configure(flow_id, {"next_step_id": step})
    if data is not None:
        result = await hass.config_entries.subentries.async_configure(flow_id, data)
    return result


async def test_member_flow_with_signals_plan_and_approach(
    hass: HomeAssistant, config_entry: MockConfigEntry, fake_calendar
) -> None:
    await setup_entry(hass, config_entry)
    result = await hass.config_entries.subentries.async_init(
        (config_entry.entry_id, c.SUBENTRY_MEMBER),
        context={"source": config_entries.SOURCE_USER},
    )
    assert result["step_id"] == "member"
    flow_id = result["flow_id"]

    result = await hass.config_entries.subentries.async_configure(flow_id, {c.CONF_NAME: "kid"})
    assert result["errors"] == {c.CONF_NAME: "name_exists"}
    result = await hass.config_entries.subentries.async_configure(
        flow_id, {c.CONF_NAME: "Teen Ager", c.CONF_POLICY: "away_after_delay"}
    )
    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == ["add_signal", "plan", "approach", "finish"]

    result = await _menu(hass, flow_id, "finish")
    assert result["errors"] == {"base": "no_signals"}
    result = await hass.config_entries.subentries.async_configure(flow_id, {})
    assert result["type"] is FlowResultType.MENU

    result = await _menu(
        hass,
        flow_id,
        "add_signal",
        {c.CONF_ENTITY_ID: GPS, c.CONF_KIND: "home_away", c.CONF_TRUST: "high"},
    )
    assert result["type"] is FlowResultType.MENU
    assert "edit_signal" in result["menu_options"]
    result = await _menu(hass, flow_id, "add_signal", {c.CONF_ENTITY_ID: GPS})
    assert result["errors"] == {c.CONF_ENTITY_ID: "signal_exists"}
    result = await hass.config_entries.subentries.async_configure(
        flow_id,
        {
            c.CONF_ENTITY_ID: "sensor.teen_ssid",
            c.CONF_KIND: "home_only",
            c.CONF_HOME_STATES: ["HomeWiFi"],
            c.CONF_ARRIVAL_DELAY: 2,
        },
    )
    result = await _menu(hass, flow_id, "edit_signal", {c.CONF_ENTITY_ID: "sensor.teen_ssid"})
    assert result["step_id"] == "signal"
    result = await hass.config_entries.subentries.async_configure(
        flow_id,
        {c.CONF_ENTITY_ID: "sensor.teen_ssid", c.CONF_KIND: "home_only", c.CONF_MAX_ON: 12},
    )
    result = await _menu(hass, flow_id, "add_signal", {c.CONF_ENTITY_ID: PC})
    result = await _menu(hass, flow_id, "remove_signal", {c.CONF_SIGNALS: [PC]})
    result = await _menu(hass, flow_id, "plan", {c.CONF_CALENDARS: [SCHOOL]})
    result = await _menu(
        hass, flow_id, "approach", {c.CONF_DISTANCE_ENTITY: "sensor.teen_distance"}
    )
    result = await _menu(hass, flow_id, "finish")
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    sub = next(s for s in config_entry.subentries.values() if s.title == "Teen Ager")
    assert sub.unique_id == "teen_ager"
    signals = sub.data[c.CONF_SIGNALS]
    assert [s[c.CONF_ENTITY_ID] for s in signals] == [GPS, "sensor.teen_ssid"]
    # Editing dropped the cleared optional home states.
    assert c.CONF_HOME_STATES not in signals[1]
    assert signals[1][c.CONF_MAX_ON] == 12
    assert sub.data[c.CONF_PLAN][c.CONF_GAP_BRIDGE] == 45
    assert sub.data[c.CONF_APPROACH][c.CONF_THRESHOLD_KM] == 15
    # A new member reloads the entry and creates its entities.
    assert hass.states.get("binary_sensor.hp_teen_ager_home") is not None


async def test_member_reconfigure_applies_without_reload(
    hass: HomeAssistant, config_entry: MockConfigEntry, fake_calendar
) -> None:
    await setup_entry(hass, config_entry)
    runtime = config_entry.runtime_data
    result = await config_entry.start_subentry_reconfigure_flow(hass, "kid_id")
    assert result["step_id"] == "member"
    flow_id = result["flow_id"]
    result = await hass.config_entries.subentries.async_configure(
        flow_id,
        {c.CONF_NAME: "Kid", c.CONF_POLICY: "hold_last", c.CONF_MEMBER_DEPARTURE_DELAY: 30},
    )
    result = await _menu(hass, flow_id, "plan", {c.CONF_CALENDARS: []})
    result = await _menu(hass, flow_id, "finish")
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()
    assert config_entry.runtime_data is runtime
    member = runtime.engine.members["kid_id"]
    assert member.plan is None
    assert member.departure_delay is not None
    assert member.departure_delay.total_seconds() == 1800
