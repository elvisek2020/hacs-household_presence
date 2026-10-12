"""Mode selects of the household and of members (FR-MODE-01, FR-PER-09)."""

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .core.model import Mode, PersonMode
from .entity import HouseholdPresenceEntity
from .runtime import HouseholdPresenceConfigEntry

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HouseholdPresenceConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the selects."""
    runtime = entry.runtime_data
    async_add_entities([HouseholdModeSelect(runtime, "mode")])
    for member in runtime.engine.members.values():
        async_add_entities(
            [PersonModeSelect(runtime, "mode", member)], config_subentry_id=member.member_id
        )


class HouseholdModeSelect(HouseholdPresenceEntity, SelectEntity):
    """Household mode."""

    _platform = "select"
    _attr_options = [m.value for m in Mode]

    @property
    def current_option(self) -> str | None:
        """Return the mode."""
        view = self.household
        return view.mode.value if view else None

    async def async_select_option(self, option: str) -> None:
        """Change the mode."""
        await self.runtime.async_set_mode(Mode(option))


class PersonModeSelect(HouseholdPresenceEntity, SelectEntity):
    """Manual mode of a member."""

    _platform = "select"
    _attr_options = [m.value for m in PersonMode]
    _attr_translation_key = "person_mode"

    def __init__(self, runtime, key, member) -> None:
        """Initialize, the translation key differs from the household mode."""
        super().__init__(runtime, key, member)
        self._attr_translation_key = "person_mode"

    @property
    def current_option(self) -> str | None:
        """Return the mode."""
        view = self.person
        return view.mode.value if view else None

    async def async_select_option(self, option: str) -> None:
        """Change the mode."""
        assert self.member_id is not None
        await self.runtime.async_set_person_mode(self.member_id, PersonMode(option))
