"""Base entity of the integration (NFR-06)."""

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, ENTITY_PREFIX
from .core.model import GroupConfig, GroupView, HouseholdView, MemberConfig, PersonView
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
        member: MemberConfig | GroupConfig | None = None,
    ) -> None:
        """Initialize the entity of the household, a member or a group."""
        self.runtime = runtime
        self.group_id = member.group_id if isinstance(member, GroupConfig) else None
        self.member_id = member.member_id if isinstance(member, MemberConfig) else None
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
            subject_id = self.group_id or self.member_id
            self._attr_unique_id = f"{entry.entry_id}_{subject_id}_{key}"
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, str(subject_id))},
                name=member.name,
                manufacturer=MANUFACTURER,
                model="Group" if self.group_id else "Member",
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
    def group(self) -> GroupView | None:
        """Return the last view of the group of this entity."""
        result = self.runtime.result
        if result is None or self.group_id is None:
            return None
        return result.groups.get(self.group_id)

    @property
    def available(self) -> bool:
        """Return False until the first step or when the member is gone."""
        if self.runtime.result is None:
            return False
        if self.group_id is not None:
            return self.group is not None
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
