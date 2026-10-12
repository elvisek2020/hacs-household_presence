"""Household Presence: who is home, long absence and expected return."""

from datetime import datetime

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import dt as dt_util
import voluptuous as vol

from .const import DOMAIN
from .runtime import HouseholdPresenceConfigEntry, HouseholdPresenceRuntime, structure_of

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.DATETIME,
    Platform.EVENT,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

ATTR_UNTIL = "until"
ATTR_MEMBER = "member"
SERVICE_SET_AWAY_UNTIL = "set_away_until"
SERVICE_CLEAR_AWAY_UNTIL = "clear_away_until"
SERVICE_RESET_LEARNING = "reset_learning"

_MEMBER_SCHEMA = vol.Schema({vol.Optional(ATTR_MEMBER): cv.string})
_SET_SCHEMA = _MEMBER_SCHEMA.extend({vol.Required(ATTR_UNTIL): cv.datetime})


def _runtime(hass: HomeAssistant) -> HouseholdPresenceRuntime:
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    if not entries:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="not_loaded")
    return entries[0].runtime_data


def _member(runtime: HouseholdPresenceRuntime, call: ServiceCall) -> str | None:
    name = call.data.get(ATTR_MEMBER)
    if not name:
        return None
    member_id = runtime.find_member(name)
    if member_id is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="unknown_member",
            translation_placeholders={"member": name},
        )
    return member_id


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the services (FR-MODE-03, FR-PER-09, FR-LEARN)."""

    async def set_away_until(call: ServiceCall) -> None:
        runtime = _runtime(hass)
        until: datetime = call.data[ATTR_UNTIL]
        if until.tzinfo is None:
            until = until.replace(tzinfo=dt_util.get_default_time_zone())
        if until <= dt_util.utcnow():
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="past_time")
        await runtime.async_set_away_until(until, _member(runtime, call))

    async def clear_away_until(call: ServiceCall) -> None:
        runtime = _runtime(hass)
        await runtime.async_set_away_until(None, _member(runtime, call))

    async def reset_learning(call: ServiceCall) -> None:
        runtime = _runtime(hass)
        await runtime.async_reset_learning(_member(runtime, call))

    hass.services.async_register(DOMAIN, SERVICE_SET_AWAY_UNTIL, set_away_until, _SET_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_CLEAR_AWAY_UNTIL, clear_away_until, _MEMBER_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_RESET_LEARNING, reset_learning, _MEMBER_SCHEMA)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: HouseholdPresenceConfigEntry) -> bool:
    """Set up the household from a config entry."""
    runtime = HouseholdPresenceRuntime(hass, entry)
    await runtime.async_load()
    entry.runtime_data = runtime
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await runtime.async_start()
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: HouseholdPresenceConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_stop()
    return unloaded


async def _async_update_listener(hass: HomeAssistant, entry: HouseholdPresenceConfigEntry) -> None:
    """Reload only when members are added, removed or renamed (NFR-09)."""
    runtime = entry.runtime_data
    if structure_of(entry) != runtime.structure:
        await hass.config_entries.async_reload(entry.entry_id)
    else:
        runtime.apply_config()
