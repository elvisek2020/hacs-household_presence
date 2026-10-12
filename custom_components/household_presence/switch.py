"""Guest switch (FR-GUEST-01)."""

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .entity import HouseholdPresenceEntity
from .runtime import HouseholdPresenceConfigEntry

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HouseholdPresenceConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the guest switch."""
    async_add_entities([GuestSwitch(entry.runtime_data, "guest")])


class GuestSwitch(HouseholdPresenceEntity, SwitchEntity):
    """A guest is home and counts as someone home."""

    _platform = "switch"

    @property
    def is_on(self) -> bool | None:
        """Return True when a guest is home."""
        view = self.household
        return view.guest if view else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the guest on."""
        await self.runtime.async_set_guest(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the guest off."""
        await self.runtime.async_set_guest(False)
