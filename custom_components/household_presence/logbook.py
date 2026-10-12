"""Logbook descriptions of presence events (FR-EVT-01)."""

from collections.abc import Callable
from typing import Any

from homeassistant.components.logbook import (
    LOGBOOK_ENTRY_ENTITY_ID,
    LOGBOOK_ENTRY_MESSAGE,
    LOGBOOK_ENTRY_NAME,
)
from homeassistant.core import Event, HomeAssistant, callback

from .const import DOMAIN, EVENT_PRESENCE


@callback
def async_describe_events(
    hass: HomeAssistant,
    async_describe_event: Callable[[str, str, Callable[[Event], dict[str, Any]]], None],
) -> None:
    """Describe presence events."""

    @callback
    def describe(event: Event) -> dict[str, Any]:
        data = event.data
        description: dict[str, Any] = {
            LOGBOOK_ENTRY_NAME: data.get("name") or "Household Presence",
            LOGBOOK_ENTRY_MESSAGE: data.get("message", ""),
        }
        if data.get("entity_id"):
            description[LOGBOOK_ENTRY_ENTITY_ID] = data["entity_id"]
        return description

    async_describe_event(DOMAIN, EVENT_PRESENCE, describe)
