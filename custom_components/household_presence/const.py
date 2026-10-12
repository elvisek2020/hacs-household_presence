"""Constants of the Household Presence integration.

The module deliberately has no Home Assistant imports so the pure engine in
``core/`` can share the configuration keys (NFR-04).
"""

from typing import Final

DOMAIN: Final = "household_presence"
ENTITY_PREFIX: Final = "hp"
SUBENTRY_MEMBER: Final = "member"

UPDATE_INTERVAL_S: Final = 30
CALENDAR_REFRESH_S: Final = 900
CALENDAR_RETRY_S: Final = 60
CALENDAR_LOOKBACK_H: Final = 24
CALENDAR_LOOKAHEAD_H: Final = 48

STORAGE_VERSION: Final = 1
STORAGE_FORMAT: Final = 1
SAVE_DELAY_S: Final = 10

EVENT_PRESENCE: Final = "household_presence_event"

DEFAULT_TITLE: Final = "Household"

# --- Household options -------------------------------------------------------
CONF_DEPARTURE_DELAY: Final = "departure_delay"  # minutes
CONF_STARTUP_GRACE: Final = "startup_grace"  # minutes
CONF_JUST_ARRIVED: Final = "just_arrived"  # minutes
CONF_UNAVAILABLE_HOURS: Final = "unavailable_hours"
CONF_NIGHT_ENABLED: Final = "night_enabled"
CONF_NIGHT_START: Final = "night_start"  # "HH:MM:SS"
CONF_NIGHT_END: Final = "night_end"
CONF_DOOR_ENTITIES: Final = "door_entities"
CONF_DOOR_WINDOW: Final = "door_window"  # minutes
CONF_HOUSEHOLD_SIGNALS: Final = "household_signals"
CONF_LONG_AWAY_HOURS: Final = "long_away_hours"
CONF_RETURN_HORIZON: Final = "return_horizon"  # hours
CONF_LONG_AWAY_PREDICTION: Final = "long_away_prediction"
CONF_LONG_AWAY_PREDICTION_MIN: Final = "long_away_prediction_min"  # hours
CONF_GUEST_AUTO_OFF: Final = "guest_auto_off"
CONF_GUEST_OFF_TIME: Final = "guest_off_time"
CONF_GUEST_OFF_HOURS: Final = "guest_off_hours"
CONF_VACATION_CALENDARS: Final = "vacation_calendars"
CONF_VACATION_KEYWORDS: Final = "vacation_keywords"
CONF_WORKDAY_ENTITY: Final = "workday_entity"
CONF_HALF_LIFE_WEEKS: Final = "half_life_weeks"
CONF_MIN_SAMPLES: Final = "min_samples"

GUEST_OFF_NEVER: Final = "never"
GUEST_OFF_AT_TIME: Final = "at_time"
GUEST_OFF_AFTER: Final = "after_hours"
GUEST_OFF_OPTIONS: Final = (GUEST_OFF_NEVER, GUEST_OFF_AT_TIME, GUEST_OFF_AFTER)

DEFAULT_OPTIONS: Final[dict[str, object]] = {
    CONF_DEPARTURE_DELAY: 15,
    CONF_STARTUP_GRACE: 5,
    CONF_JUST_ARRIVED: 10,
    CONF_UNAVAILABLE_HOURS: 6,
    CONF_NIGHT_ENABLED: True,
    CONF_NIGHT_START: "22:00:00",
    CONF_NIGHT_END: "07:00:00",
    CONF_DOOR_ENTITIES: [],
    CONF_DOOR_WINDOW: 10,
    CONF_HOUSEHOLD_SIGNALS: [],
    CONF_LONG_AWAY_HOURS: 24,
    CONF_RETURN_HORIZON: 12,
    CONF_LONG_AWAY_PREDICTION: True,
    CONF_LONG_AWAY_PREDICTION_MIN: 2,
    CONF_GUEST_AUTO_OFF: GUEST_OFF_NEVER,
    CONF_GUEST_OFF_TIME: "04:00:00",
    CONF_GUEST_OFF_HOURS: 24,
    CONF_VACATION_CALENDARS: [],
    CONF_VACATION_KEYWORDS: "",
    CONF_HALF_LIFE_WEEKS: 4,
    CONF_MIN_SAMPLES: 3,
}

# --- Member subentry -----------------------------------------------------------
CONF_NAME: Final = "name"
CONF_POLICY: Final = "no_signal_policy"
CONF_MEMBER_DEPARTURE_DELAY: Final = "departure_delay"
CONF_NIGHT_MODE: Final = "night_mode"
CONF_SIGNALS: Final = "signals"
CONF_PLAN: Final = "plan"
CONF_APPROACH: Final = "approach"

NIGHT_INHERIT: Final = "inherit"
NIGHT_CUSTOM: Final = "custom"
NIGHT_OFF: Final = "off"
NIGHT_MODES: Final = (NIGHT_INHERIT, NIGHT_CUSTOM, NIGHT_OFF)

# Signal
CONF_ENTITY_ID: Final = "entity_id"
CONF_KIND: Final = "kind"
CONF_HOME_STATES: Final = "home_states"
CONF_AWAY_STATES: Final = "away_states"
CONF_ARRIVAL_DELAY: Final = "arrival_delay"  # minutes
CONF_MAX_ON: Final = "max_on"  # hours
CONF_VALID_FROM: Final = "valid_from"
CONF_VALID_TO: Final = "valid_to"
CONF_TRUST: Final = "trust"

# Plan
CONF_CALENDARS: Final = "calendars"
CONF_TITLE_FILTER: Final = "title_filter"
CONF_GAP_BRIDGE: Final = "gap_bridge"  # minutes
CONF_LEAD: Final = "lead"  # minutes
CONF_TRAIL: Final = "trail"  # minutes
CONF_CERTAIN: Final = "certain"
CONF_ALL_DAY: Final = "all_day"

DEFAULT_PLAN: Final[dict[str, object]] = {
    CONF_CALENDARS: [],
    CONF_TITLE_FILTER: "",
    CONF_GAP_BRIDGE: 45,
    CONF_LEAD: 20,
    CONF_TRAIL: 30,
    CONF_CERTAIN: True,
    CONF_ALL_DAY: False,
}

# Approach
CONF_DISTANCE_ENTITY: Final = "distance_entity"
CONF_DIRECTION_ENTITY: Final = "direction_entity"
CONF_THRESHOLD_KM: Final = "threshold_km"
CONF_CONFIRMATIONS: Final = "confirmations"
CONF_SPEED_KMH: Final = "speed_kmh"

DEFAULT_APPROACH: Final[dict[str, object]] = {
    CONF_THRESHOLD_KM: 15,
    CONF_CONFIRMATIONS: 2,
    CONF_SPEED_KMH: 50,
}
