"""Base entity of the integration (NFR-06)."""

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, ENTITY_PREFIX
from .core.model import HouseholdView, MemberConfig, PersonView
from .runtime import HouseholdPresenceRuntime

MANUFACTURER = "Household Presence"


class HouseholdPresenceEntity(Entity):
    """Entity of the household or of one member.

    The contract binds ``unique_id`` and ``translation_key``; the entity id is
    suggested as ``hp_<key>`` or ``hp_<member>_<key>``.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _platform: str

    def __init__(
        self,
        runtime: HouseholdPresenceRuntime,
        key: str,
        member: MemberConfig | None = None,
    ) -> None:
        """Initialize the entity."""
        self.runtime = runtime
        self.member_id = member.member_id if member else None
        self._attr_translation_key = key
        entry = runtime.entry
        if member is None:
            self._attr_unique_id = f"{entry.entry_id}_{key}"
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, entry.entry_id)},
                name=entry.title,
                manufacturer=MANUFACTURER,
                model="Household",
                entry_type=DeviceEntryType.SERVICE,
            )
            self.entity_id = f"{self._platform}.{ENTITY_PREFIX}_{key}"
        else:
            self._attr_unique_id = f"{entry.entry_id}_{member.member_id}_{key}"
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, member.member_id)},
                name=member.name,
                manufacturer=MANUFACTURER,
                model="Member",
                entry_type=DeviceEntryType.SERVICE,
            )
            self.entity_id = f"{self._platform}.{ENTITY_PREFIX}_{member.slug}_{key}"

    @property
    def household(self) -> HouseholdView | None:
        """Return the last household view."""
        result = self.runtime.result
        return result.household if result else None

    @property
    def person(self) -> PersonView | None:
        """Return the last view of the member of this entity."""
        result = self.runtime.result
        if result is None or self.member_id is None:
            return None
        return result.persons.get(self.member_id)

    @property
    def available(self) -> bool:
        """Return False until the first step or when the member is gone."""
        if self.runtime.result is None:
            return False
        if self.member_id is None:
            return True
        view = self.person
        return view is not None and view.available

    async def async_added_to_hass(self) -> None:
        """Subscribe to runtime updates."""
        self.async_on_remove(self.runtime.async_add_listener(self.async_write_ha_state))


def iso(value) -> str | None:
    """Return an ISO string for attributes."""
    return value.isoformat() if value is not None else None
