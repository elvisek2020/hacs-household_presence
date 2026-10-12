"""Config flow, options flow and the member subentry flow."""

from collections.abc import Mapping
import copy
from typing import Any

from homeassistant.config_entries import (
    SOURCE_USER,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.core import callback
from homeassistant.helpers import selector as sel
from homeassistant.util import slugify
import voluptuous as vol

from . import const as c
from .core.model import NoSignalPolicy, SignalKind, Trust

# --- selector helpers ---------------------------------------------------------------


def _number(
    minimum: float, maximum: float, step: float = 1, unit: str | None = None
) -> sel.NumberSelector:
    config = sel.NumberSelectorConfig(
        min=minimum, max=maximum, step=step, mode=sel.NumberSelectorMode.BOX
    )
    if unit:
        config["unit_of_measurement"] = unit
    return sel.NumberSelector(config)


def _choice(options: list[str], key: str) -> sel.SelectSelector:
    return sel.SelectSelector(
        sel.SelectSelectorConfig(
            options=options, translation_key=key, mode=sel.SelectSelectorMode.DROPDOWN
        )
    )


def _entity(domain: str | list[str] | None = None, *, multiple: bool = False) -> sel.EntitySelector:
    config = sel.EntitySelectorConfig(multiple=multiple)
    if domain:
        config["domain"] = domain
    return sel.EntitySelector(config)


_BOOL = sel.BooleanSelector()
_TIME = sel.TimeSelector()
_TEXT = sel.TextSelector()
_TEXT_LIST = sel.TextSelector(sel.TextSelectorConfig(multiple=True))
_MINUTES = _number(0, 1440, 1, "min")
_HOURS = _number(0, 720, 0.5, "h")


def _required(key: str, values: Mapping[str, Any], default: Any) -> vol.Required:
    return vol.Required(key, default=values.get(key, default))


def _optional(key: str, values: Mapping[str, Any]) -> vol.Optional:
    value = values.get(key)
    if value in (None, "", []):
        return vol.Optional(key)
    return vol.Optional(key, description={"suggested_value": value})


def _apply(values: Mapping[str, Any], schema: vol.Schema, user_input: Mapping[str, Any]) -> dict:
    """Merge a form into stored values; cleared optional fields are removed."""
    result = dict(values)
    for marker in schema.schema:
        key = str(marker)
        if key in user_input:
            result[key] = user_input[key]
        elif isinstance(marker, vol.Optional) and not isinstance(marker, vol.Required):
            result.pop(key, None)
    return result


# --- household options ---------------------------------------------------------------


def _general_schema(o: Mapping[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            _required(c.CONF_DEPARTURE_DELAY, o, 15): _MINUTES,
            _required(c.CONF_STARTUP_GRACE, o, 5): _MINUTES,
            _required(c.CONF_JUST_ARRIVED, o, 10): _MINUTES,
            _required(c.CONF_UNAVAILABLE_HOURS, o, 6): _HOURS,
        }
    )


def _night_schema(o: Mapping[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            _required(c.CONF_NIGHT_ENABLED, o, True): _BOOL,
            _required(c.CONF_NIGHT_START, o, "22:00:00"): _TIME,
            _required(c.CONF_NIGHT_END, o, "07:00:00"): _TIME,
            _required(c.CONF_DOOR_ENTITIES, o, []): _entity(multiple=True),
            _required(c.CONF_DOOR_WINDOW, o, 10): _MINUTES,
        }
    )


def _long_away_schema(o: Mapping[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            _required(c.CONF_LONG_AWAY_HOURS, o, 24): _HOURS,
            _required(c.CONF_LONG_AWAY_PREDICTION, o, True): _BOOL,
            _required(c.CONF_LONG_AWAY_PREDICTION_MIN, o, 2): _HOURS,
            _required(c.CONF_RETURN_HORIZON, o, 12): _HOURS,
        }
    )


def _guest_schema(o: Mapping[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            _required(c.CONF_GUEST_AUTO_OFF, o, c.GUEST_OFF_NEVER): _choice(
                list(c.GUEST_OFF_OPTIONS), "guest_auto_off"
            ),
            _required(c.CONF_GUEST_OFF_TIME, o, "04:00:00"): _TIME,
            _required(c.CONF_GUEST_OFF_HOURS, o, 24): _HOURS,
        }
    )


def _signals_schema(o: Mapping[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            _required(c.CONF_HOUSEHOLD_SIGNALS, o, []): _entity(multiple=True),
            _optional(c.CONF_WORKDAY_ENTITY, o): _entity("binary_sensor"),
        }
    )


def _vacation_schema(o: Mapping[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            _required(c.CONF_VACATION_CALENDARS, o, []): _entity("calendar", multiple=True),
            _optional(c.CONF_VACATION_KEYWORDS, o): _TEXT,
        }
    )


def _learning_schema(o: Mapping[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            _required(c.CONF_HALF_LIFE_WEEKS, o, 4): _number(0.5, 52, 0.5),
            _required(c.CONF_MIN_SAMPLES, o, 3): _number(1, 20, 1),
        }
    )


OPTION_STEPS = {
    "general": _general_schema,
    "night": _night_schema,
    "long_away": _long_away_schema,
    "guest": _guest_schema,
    "household_signals": _signals_schema,
    "vacation": _vacation_schema,
    "learning": _learning_schema,
}


class HouseholdPresenceConfigFlow(ConfigFlow, domain=c.DOMAIN):
    """Create the household."""

    VERSION = 1
    MINOR_VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Name the household and choose the departure delay."""
        if user_input is not None:
            return self.async_create_entry(
                title=user_input[c.CONF_NAME].strip() or c.DEFAULT_TITLE,
                data={},
                options={
                    **c.DEFAULT_OPTIONS,
                    c.CONF_DEPARTURE_DELAY: user_input[c.CONF_DEPARTURE_DELAY],
                },
            )
        default_name = "Domácnost" if self.hass.config.language == "cs" else c.DEFAULT_TITLE
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(c.CONF_NAME, default=default_name): _TEXT,
                    vol.Required(c.CONF_DEPARTURE_DELAY, default=15): _MINUTES,
                }
            ),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return HouseholdPresenceOptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Members are subentries."""
        return {c.SUBENTRY_MEMBER: MemberSubentryFlowHandler}


class HouseholdPresenceOptionsFlow(OptionsFlow):
    """Household options grouped in a menu."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show the menu."""
        return self.async_show_menu(step_id="init", menu_options=list(OPTION_STEPS))

    async def _async_form(
        self, step_id: str, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        options = {**c.DEFAULT_OPTIONS, **self.config_entry.options}
        schema = OPTION_STEPS[step_id](options)
        if user_input is not None:
            return self.async_create_entry(data=_apply(options, schema, user_input))
        return self.async_show_form(step_id=step_id, data_schema=schema)

    async def async_step_general(self, user_input=None) -> ConfigFlowResult:
        """Delays and timeouts."""
        return await self._async_form("general", user_input)

    async def async_step_night(self, user_input=None) -> ConfigFlowResult:
        """Night window and doors."""
        return await self._async_form("night", user_input)

    async def async_step_long_away(self, user_input=None) -> ConfigFlowResult:
        """Long absence."""
        return await self._async_form("long_away", user_input)

    async def async_step_guest(self, user_input=None) -> ConfigFlowResult:
        """Guest auto-off."""
        return await self._async_form("guest", user_input)

    async def async_step_household_signals(self, user_input=None) -> ConfigFlowResult:
        """Anonymous household signals and the workday entity."""
        return await self._async_form("household_signals", user_input)

    async def async_step_vacation(self, user_input=None) -> ConfigFlowResult:
        """Vacation calendars."""
        return await self._async_form("vacation", user_input)

    async def async_step_learning(self, user_input=None) -> ConfigFlowResult:
        """Learning parameters."""
        return await self._async_form("learning", user_input)


# --- member subentry -----------------------------------------------------------------


def _member_schema(d: Mapping[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(c.CONF_NAME, default=d.get(c.CONF_NAME, "")): _TEXT,
            _required(c.CONF_POLICY, d, NoSignalPolicy.AWAY_AFTER_DELAY.value): _choice(
                [p.value for p in NoSignalPolicy], "no_signal_policy"
            ),
            _optional(c.CONF_MEMBER_DEPARTURE_DELAY, d): _MINUTES,
            _required(c.CONF_NIGHT_MODE, d, c.NIGHT_INHERIT): _choice(
                list(c.NIGHT_MODES), "night_mode"
            ),
            _optional(c.CONF_NIGHT_START, d): _TIME,
            _optional(c.CONF_NIGHT_END, d): _TIME,
        }
    )


def _signal_schema(d: Mapping[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                c.CONF_ENTITY_ID, default=d.get(c.CONF_ENTITY_ID, vol.UNDEFINED)
            ): _entity(),
            _required(c.CONF_KIND, d, SignalKind.HOME_ONLY.value): _choice(
                [k.value for k in SignalKind], "signal_kind"
            ),
            _optional(c.CONF_HOME_STATES, d): _TEXT_LIST,
            _optional(c.CONF_AWAY_STATES, d): _TEXT_LIST,
            _required(c.CONF_ARRIVAL_DELAY, d, 0): _MINUTES,
            _optional(c.CONF_MAX_ON, d): _HOURS,
            _optional(c.CONF_VALID_FROM, d): _TIME,
            _optional(c.CONF_VALID_TO, d): _TIME,
            _required(c.CONF_TRUST, d, Trust.NORMAL.value): _choice(
                [t.value for t in Trust], "trust"
            ),
        }
    )


def _plan_schema(d: Mapping[str, Any]) -> vol.Schema:
    d = {**c.DEFAULT_PLAN, **d}
    return vol.Schema(
        {
            _required(c.CONF_CALENDARS, d, []): _entity("calendar", multiple=True),
            _optional(c.CONF_TITLE_FILTER, d): _TEXT,
            _required(c.CONF_GAP_BRIDGE, d, 45): _MINUTES,
            _required(c.CONF_LEAD, d, 20): _MINUTES,
            _required(c.CONF_TRAIL, d, 30): _MINUTES,
            _required(c.CONF_CERTAIN, d, True): _BOOL,
            _required(c.CONF_ALL_DAY, d, False): _BOOL,
        }
    )


def _approach_schema(d: Mapping[str, Any]) -> vol.Schema:
    d = {**c.DEFAULT_APPROACH, **d}
    return vol.Schema(
        {
            _optional(c.CONF_DISTANCE_ENTITY, d): _entity(["sensor", "number", "input_number"]),
            _optional(c.CONF_DIRECTION_ENTITY, d): _entity("sensor"),
            _required(c.CONF_THRESHOLD_KM, d, 15): _number(0.1, 500, 0.1, "km"),
            _required(c.CONF_CONFIRMATIONS, d, 2): _number(1, 10, 1),
            _required(c.CONF_SPEED_KMH, d, 50): _number(1, 200, 1, "km/h"),
        }
    )


class MemberSubentryFlowHandler(ConfigSubentryFlow):
    """Add or edit a household member with its signals, plan and approach."""

    def __init__(self) -> None:
        """Initialize the flow."""
        self._data: dict[str, Any] = {}
        self._edit_index: int | None = None

    @property
    def _signals(self) -> list[dict[str, Any]]:
        return self._data.setdefault(c.CONF_SIGNALS, [])

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        """Start adding a member."""
        self._data = {c.CONF_SIGNALS: []}
        return await self.async_step_member()

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Start editing a member."""
        self._data = copy.deepcopy(dict(self._get_reconfigure_subentry().data))
        return await self.async_step_member()

    def _duplicate(self, slug: str) -> bool:
        entry = self._get_entry()
        own = None if self.source == SOURCE_USER else self._reconfigure_subentry_id
        return any(
            sub.unique_id == slug
            for sub_id, sub in entry.subentries.items()
            if sub.subentry_type == c.SUBENTRY_MEMBER and sub_id != own
        )

    async def async_step_member(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Name, policy, departure delay and night window."""
        errors: dict[str, str] = {}
        schema = _member_schema(self._data)
        if user_input is not None:
            name = str(user_input[c.CONF_NAME]).strip()
            slug = slugify(name)
            if not slug:
                errors[c.CONF_NAME] = "invalid_name"
            elif self._duplicate(slug):
                errors[c.CONF_NAME] = "name_exists"
            else:
                self._data = _apply(self._data, schema, {**user_input, c.CONF_NAME: name})
                return await self.async_step_menu()
        return self.async_show_form(step_id="member", data_schema=schema, errors=errors)

    async def async_step_menu(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        """Choose what to configure next."""
        options = ["add_signal"]
        if self._signals:
            options += ["edit_signal", "remove_signal"]
        options += ["plan", "approach", "finish"]
        lines = [f"- {s[c.CONF_ENTITY_ID]} ({s.get(c.CONF_KIND)})" for s in self._signals]
        return self.async_show_menu(
            step_id="menu",
            menu_options=options,
            description_placeholders={
                "name": str(self._data.get(c.CONF_NAME, "")),
                "signals": "\n".join(lines) or "-",
            },
        )

    async def async_step_add_signal(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Add a new signal."""
        self._edit_index = None
        return await self.async_step_signal()

    async def async_step_edit_signal(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Pick a signal to edit."""
        if user_input is not None:
            ids = [s[c.CONF_ENTITY_ID] for s in self._signals]
            self._edit_index = ids.index(user_input[c.CONF_ENTITY_ID])
            return await self.async_step_signal()
        return self.async_show_form(
            step_id="edit_signal",
            data_schema=vol.Schema(
                {
                    vol.Required(c.CONF_ENTITY_ID): sel.SelectSelector(
                        sel.SelectSelectorConfig(
                            options=[s[c.CONF_ENTITY_ID] for s in self._signals]
                        )
                    )
                }
            ),
        )

    async def async_step_signal(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Edit the fields of one signal."""
        current = self._signals[self._edit_index] if self._edit_index is not None else {}
        schema = _signal_schema(current)
        errors: dict[str, str] = {}
        if user_input is not None:
            signal = _apply(current, schema, user_input)
            entity_id = signal[c.CONF_ENTITY_ID]
            others = [
                s[c.CONF_ENTITY_ID] for i, s in enumerate(self._signals) if i != self._edit_index
            ]
            if entity_id in others:
                errors[c.CONF_ENTITY_ID] = "signal_exists"
            else:
                if self._edit_index is None:
                    self._signals.append(signal)
                else:
                    self._signals[self._edit_index] = signal
                self._edit_index = None
                return await self.async_step_menu()
        return self.async_show_form(step_id="signal", data_schema=schema, errors=errors)

    async def async_step_remove_signal(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Remove signals."""
        if user_input is not None:
            remove = set(user_input.get(c.CONF_SIGNALS, []))
            self._data[c.CONF_SIGNALS] = [
                s for s in self._signals if s[c.CONF_ENTITY_ID] not in remove
            ]
            return await self.async_step_menu()
        return self.async_show_form(
            step_id="remove_signal",
            data_schema=vol.Schema(
                {
                    vol.Optional(c.CONF_SIGNALS, default=[]): sel.SelectSelector(
                        sel.SelectSelectorConfig(
                            options=[s[c.CONF_ENTITY_ID] for s in self._signals],
                            multiple=True,
                        )
                    )
                }
            ),
        )

    async def async_step_plan(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        """Planned absence from calendars."""
        current = self._data.get(c.CONF_PLAN) or {}
        schema = _plan_schema(current)
        if user_input is not None:
            plan = _apply({**c.DEFAULT_PLAN, **current}, schema, user_input)
            if plan.get(c.CONF_CALENDARS):
                self._data[c.CONF_PLAN] = plan
            else:
                self._data.pop(c.CONF_PLAN, None)
            return await self.async_step_menu()
        return self.async_show_form(step_id="plan", data_schema=schema)

    async def async_step_approach(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Approach detection."""
        current = self._data.get(c.CONF_APPROACH) or {}
        schema = _approach_schema(current)
        if user_input is not None:
            approach = _apply({**c.DEFAULT_APPROACH, **current}, schema, user_input)
            if approach.get(c.CONF_DISTANCE_ENTITY):
                self._data[c.CONF_APPROACH] = approach
            else:
                self._data.pop(c.CONF_APPROACH, None)
            return await self.async_step_menu()
        return self.async_show_form(step_id="approach", data_schema=schema)

    async def async_step_finish(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Save the member; a member needs a signal or a plan."""
        if user_input is not None:
            return await self.async_step_menu()
        if not self._signals and not self._data.get(c.CONF_PLAN):
            return self.async_show_form(
                step_id="finish", data_schema=vol.Schema({}), errors={"base": "no_signals"}
            )
        name = str(self._data[c.CONF_NAME])
        slug = slugify(name)
        if self.source == SOURCE_USER:
            return self.async_create_entry(title=name, data=self._data, unique_id=slug)
        return self.async_update_and_abort(
            self._get_entry(),
            self._get_reconfigure_subentry(),
            title=name,
            data=self._data,
            unique_id=slug,
        )
