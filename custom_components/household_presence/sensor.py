"""Sensors of the contract (kap. 8 PRD)."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .core.model import (
    ExpectedReturn,
    HouseholdState,
    HouseholdView,
    PersonState,
    PersonView,
)
from .entity import HouseholdPresenceEntity
from .runtime import HouseholdPresenceConfigEntry

PARALLEL_UPDATES = 0


def _return_attrs(value: ExpectedReturn | None, *, person: bool) -> dict[str, Any]:
    if value is None:
        return {}
    attrs: dict[str, Any] = {"source": value.source.value, "confidence": value.confidence}
    if person:
        attrs["person"] = value.name
    return attrs


@dataclass(frozen=True, kw_only=True)
class HouseholdSensorDescription(SensorEntityDescription):
    """Household sensor with value and attribute functions."""

    value_fn: Callable[[HouseholdView], Any]
    attrs_fn: Callable[[HouseholdView], dict[str, Any]] = lambda _v: {}


@dataclass(frozen=True, kw_only=True)
class PersonSensorDescription(SensorEntityDescription):
    """Member sensor with value and attribute functions."""

    value_fn: Callable[[PersonView], Any]
    attrs_fn: Callable[[PersonView], dict[str, Any]] = lambda _v: {}


def _at(value: ExpectedReturn | None) -> datetime | None:
    return value.at if value else None


HOUSEHOLD_SENSORS: tuple[HouseholdSensorDescription, ...] = (
    HouseholdSensorDescription(
        key="people_home",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda v: v.count,
    ),
    HouseholdSensorDescription(
        key="household_state",
        device_class=SensorDeviceClass.ENUM,
        options=[s.value for s in HouseholdState],
        value_fn=lambda v: v.state.value,
        attrs_fn=lambda v: {"reason": v.reason.value},
    ),
    HouseholdSensorDescription(
        key="away_since",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda v: v.away_since,
    ),
    HouseholdSensorDescription(
        key="expected_return",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda v: _at(v.expected_return),
        attrs_fn=lambda v: _return_attrs(v.expected_return, person=True),
    ),
    HouseholdSensorDescription(
        key="expected_return_confidence",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda v: round(v.expected_return.confidence * 100) if v.expected_return else None,
    ),
    HouseholdSensorDescription(
        key="expected_return_error",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda v: v.last_return_error,
    ),
)

PERSON_SENSORS: tuple[PersonSensorDescription, ...] = (
    PersonSensorDescription(
        key="state",
        device_class=SensorDeviceClass.ENUM,
        options=[s.value for s in PersonState],
        value_fn=lambda v: v.state.value,
    ),
    PersonSensorDescription(
        key="expected_return",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda v: _at(v.expected_return),
        attrs_fn=lambda v: _return_attrs(v.expected_return, person=False),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HouseholdPresenceConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensors."""
    runtime = entry.runtime_data
    async_add_entities(HouseholdSensor(runtime, d) for d in HOUSEHOLD_SENSORS)
    for member in runtime.engine.members.values():
        async_add_entities(
            (PersonSensor(runtime, d, member) for d in PERSON_SENSORS),
            config_subentry_id=member.member_id,
        )
    for group in runtime.engine.groups.values():
        async_add_entities(
            [GroupReturnSensor(runtime, "expected_return", group)],
            config_subentry_id=group.group_id,
        )


class HouseholdSensor(HouseholdPresenceEntity, SensorEntity):
    """Sensor of the household."""

    _platform = "sensor"
    entity_description: HouseholdSensorDescription

    def __init__(self, runtime, description: HouseholdSensorDescription) -> None:
        """Initialize."""
        self.entity_description = description
        super().__init__(runtime, description.key)

    @property
    def native_value(self) -> Any:
        """Return the value."""
        view = self.household
        return self.entity_description.value_fn(view) if view else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the attributes."""
        view = self.household
        return self.entity_description.attrs_fn(view) if view else {}


class PersonSensor(HouseholdPresenceEntity, SensorEntity):
    """Sensor of one member."""

    _platform = "sensor"
    entity_description: PersonSensorDescription

    def __init__(self, runtime, description: PersonSensorDescription, member) -> None:
        """Initialize."""
        self.entity_description = description
        super().__init__(runtime, description.key, member)

    @property
    def native_value(self) -> Any:
        """Return the value."""
        view = self.person
        return self.entity_description.value_fn(view) if view else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the attributes."""
        view = self.person
        return self.entity_description.attrs_fn(view) if view else {}


class GroupReturnSensor(HouseholdPresenceEntity, SensorEntity):
    """Nearest return of a member of the group while the group is away (FR-GRP-03)."""

    _platform = "sensor"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    @property
    def native_value(self) -> datetime | None:
        """Return the expected return."""
        view = self.group
        return _at(view.expected_return) if view else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return source, person and confidence."""
        view = self.group
        return _return_attrs(view.expected_return, person=True) if view else {}
