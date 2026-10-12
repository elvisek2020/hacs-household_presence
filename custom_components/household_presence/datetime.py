"""Planned return of the household and of members (FR-MODE-03, FR-PER-09)."""

from datetime import datetime

from homeassistant.components.datetime import DateTimeEntity
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
    """Set up the away-until entities."""
    runtime = entry.runtime_data
    async_add_entities([AwayUntil(runtime, "away_until")])
    for member in runtime.engine.members.values():
        async_add_entities(
            [AwayUntil(runtime, "away_until", member)], config_subentry_id=member.member_id
        )


class AwayUntil(HouseholdPresenceEntity, DateTimeEntity):
    """Away until; cleared automatically once it passes."""

    _platform = "datetime"

    @property
    def native_value(self) -> datetime | None:
        """Return the planned return."""
        if self.member_id is None:
            view = self.household
            return view.away_until if view else None
        person = self.person
        return person.away_until if person else None

    async def async_set_value(self, value: datetime) -> None:
        """Set the planned return; a time in the past clears it."""
        await self.runtime.async_set_away_until(value, self.member_id)
