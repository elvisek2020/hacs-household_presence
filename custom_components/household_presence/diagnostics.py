"""Diagnostics: options, members, live state, learning and metrics (FR-DIAG-01)."""

from dataclasses import asdict
from datetime import datetime
from enum import Enum
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import const as c
from .core.engine import HOUSEHOLD_KEY
from .runtime import HouseholdPresenceConfigEntry

TO_REDACT = {
    c.CONF_NAME,
    "title",
    "people",
    "approaching",
    c.CONF_CALENDARS,
    c.CONF_VACATION_CALENDARS,
    c.CONF_VACATION_KEYWORDS,
    c.CONF_TITLE_FILTER,
}


def _plain(value: Any) -> Any:
    """Make dataclass output JSON friendly."""
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(v) for v in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    return value


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: HouseholdPresenceConfigEntry
) -> dict[str, Any]:
    """Return diagnostics of the household."""
    runtime = entry.runtime_data
    engine = runtime.engine
    result = runtime.result
    learner = engine.learner
    keys = [*engine.members, HOUSEHOLD_KEY]
    data = {
        "options": dict(entry.options),
        "members": {
            sub_id: {"title": sub.title, "data": dict(sub.data)}
            for sub_id, sub in entry.subentries.items()
        },
        "household": _plain(asdict(result.household)) if result else None,
        "persons": (
            {mid: _plain(asdict(view)) for mid, view in result.persons.items()} if result else None
        ),
        "groups": (
            {gid: _plain(asdict(view)) for gid, view in result.groups.items()} if result else None
        ),
        "problems": [p.kind for p in result.problems] if result else [],
        "calendar_cache": {
            "fetched_at": _plain(runtime.calendars_fetched_at),
            "events": {
                cal: len(d.events) if d.ok else None for cal, d in runtime.calendars.items()
            },
        },
        "learning": {
            key: {
                "days": len(learner.records.get(key, [])),
                "profile": learner.profile(key),
                "metrics": learner.metrics[key].summary() if key in learner.metrics else None,
            }
            for key in keys
        },
        "store": {k: v for k, v in engine.to_dict().items() if k != "learning"},
    }
    redacted = async_redact_data(data, TO_REDACT)
    # Calendar entity ids are redacted as keys too.
    cache = redacted["calendar_cache"]
    cache["events"] = {f"calendar_{i}": v for i, v in enumerate(cache["events"].values())}
    return redacted
