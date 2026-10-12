"""Common fixtures of the Home Assistant tests."""

from collections.abc import Callable
from datetime import datetime
from typing import Any

from homeassistant.config_entries import ConfigSubentryDataWithId
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.household_presence import const as c

GPS = "device_tracker.parent_phone"
WIFI = "device_tracker.parent_wifi"
PC = "binary_sensor.kid_pc"
SCHOOL = "calendar.kid_school"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations in every test."""
    return


def member_subentry(subentry_id: str, name: str, data: dict[str, Any]) -> ConfigSubentryDataWithId:
    """Return subentry data of a member."""
    return ConfigSubentryDataWithId(
        data={c.CONF_NAME: name, **data},
        subentry_id=subentry_id,
        subentry_type=c.SUBENTRY_MEMBER,
        title=name,
        unique_id=name.lower(),
    )


PARENT = member_subentry(
    "parent_id",
    "Parent",
    {
        c.CONF_SIGNALS: [
            {c.CONF_ENTITY_ID: GPS, c.CONF_KIND: "home_away", c.CONF_TRUST: "high"},
            {c.CONF_ENTITY_ID: WIFI, c.CONF_KIND: "home_only"},
        ]
    },
)
KID = member_subentry(
    "kid_id",
    "Kid",
    {
        c.CONF_SIGNALS: [{c.CONF_ENTITY_ID: PC, c.CONF_KIND: "home_only"}],
        c.CONF_POLICY: "hold_last",
        c.CONF_PLAN: {c.CONF_CALENDARS: [SCHOOL]},
    },
)


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """Return a household with two members and no startup grace."""
    return MockConfigEntry(
        domain=c.DOMAIN,
        title="Home",
        data={},
        options={**c.DEFAULT_OPTIONS, c.CONF_STARTUP_GRACE: 0},
        subentries_data=[PARENT, KID],
        entry_id="entry_id",
    )


@pytest.fixture
def calendar_events() -> dict[str, list[dict[str, Any]]]:
    """Events returned by the fake calendar.get_events service."""
    return {}


@pytest.fixture
def fake_calendar(
    hass: HomeAssistant, calendar_events: dict[str, list[dict[str, Any]]]
) -> Callable[[str, datetime, datetime, str], None]:
    """Register a fake calendar.get_events service and return an event adder."""

    async def get_events(call: ServiceCall) -> dict[str, Any]:
        ids = call.data["entity_id"]
        ids = [ids] if isinstance(ids, str) else ids
        return {e: {"events": calendar_events.get(e, [])} for e in ids}

    hass.services.async_register(
        "calendar", "get_events", get_events, supports_response=SupportsResponse.ONLY
    )

    def add(entity_id: str, start: datetime, end: datetime, summary: str = "Lesson") -> None:
        hass.states.async_set(entity_id, "off")
        calendar_events.setdefault(entity_id, []).append(
            {"start": start.isoformat(), "end": end.isoformat(), "summary": summary}
        )

    return add


async def setup_entry(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Add and set up the entry."""
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
