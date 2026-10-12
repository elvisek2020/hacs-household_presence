"""Binary sensors of the contract (kap. 8 PRD)."""

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .entity import HouseholdPresenceEntity, iso
from .runtime import HouseholdPresenceConfigEntry

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HouseholdPresenceConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the binary sensors."""
    runtime = entry.runtime_data
    async_add_entities(
        [SomeoneHomeSensor(runtime), LongAwaySensor(runtime), SomeoneApproachingSensor(runtime)]
    )
    for member in runtime.engine.members.values():
        async_add_entities(
            [MemberHomeSensor(runtime, "home", member)], config_subentry_id=member.member_id
        )


class _Base(HouseholdPresenceEntity, BinarySensorEntity):
    _platform = "binary_sensor"


class SomeoneHomeSensor(_Base):
    """Someone is home (FR-HH-01)."""

    _attr_device_class = BinarySensorDeviceClass.PRESENCE
    _unrecorded_attributes = frozenset({"since"})

    def __init__(self, runtime) -> None:
        """Initialize."""
        super().__init__(runtime, "someone_home")

    @property
    def is_on(self) -> bool | None:
        """Return True when someone is home."""
        view = self.household
        return view.someone_home if view else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return count, people and since."""
        view = self.household
        if view is None:
            return {}
        return {"count": view.count, "people": list(view.people), "since": iso(view.since)}


class LongAwaySensor(_Base):
    """The household is away for long (FR-HH-04)."""

    def __init__(self, runtime) -> None:
        """Initialize."""
        super().__init__(runtime, "long_away")

    @property
    def is_on(self) -> bool | None:
        """Return True during a long absence."""
        view = self.household
        return view.long_away if view else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the reason."""
        view = self.household
        return {"reason": view.reason.value} if view and view.long_away else {}


class SomeoneApproachingSensor(_Base):
    """Someone is heading home (FR-APPR-02)."""

    def __init__(self, runtime) -> None:
        """Initialize."""
        super().__init__(runtime, "someone_approaching")

    @property
    def is_on(self) -> bool | None:
        """Return True while someone approaches."""
        view = self.household
        return bool(view.approaching) if view else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return who approaches."""
        view = self.household
        return {"people": list(view.approaching)} if view else {}


class MemberHomeSensor(_Base):
    """A member is home (FR-PER-01)."""

    _attr_device_class = BinarySensorDeviceClass.PRESENCE
    _unrecorded_attributes = frozenset({"since", "sources"})

    @property
    def is_on(self) -> bool | None:
        """Return True when the member is home, None when unknown."""
        view = self.person
        return view.is_home if view else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return since, sources and method."""
        view = self.person
        if view is None:
            return {}
        return {
            "since": iso(view.since),
            "sources": list(view.sources),
            "method": view.method.value,
        }
