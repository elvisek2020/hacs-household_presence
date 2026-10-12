"""Event entity of the household (FR-EVT-01)."""

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .core.model import Event, EventType
from .entity import HouseholdPresenceEntity
from .runtime import HouseholdPresenceConfigEntry

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HouseholdPresenceConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the event entity."""
    async_add_entities([HouseholdEvent(entry.runtime_data, "household")])


class HouseholdEvent(HouseholdPresenceEntity, EventEntity):
    """Arrivals, departures, long absence and mode changes."""

    _platform = "event"
    _attr_event_types = [t.value for t in EventType]

    @property
    def available(self) -> bool:
        """Events are always available once set up."""
        return True

    async def async_added_to_hass(self) -> None:
        """Subscribe to presence events."""
        await super().async_added_to_hass()
        self.async_on_remove(self.runtime.async_add_event_listener(self._handle_event))

    @callback
    def _handle_event(self, event: Event) -> None:
        attributes: dict[str, str | int | float | None] = {
            "person": event.name,
            "at": event.at.isoformat(),
        }
        attributes.update({k: v for k, v in event.data.items() if isinstance(v, str | int | float)})
        self._trigger_event(event.type.value, attributes)
        self.async_write_ha_state()
