"""Human readable logbook sentences in Czech and English (FR-EVT-01).

Member names come from the configuration, so the sentences avoid Czech
grammatical gender ("Příchod: …" instead of "… přišel").
"""

from datetime import datetime, tzinfo

from .core.model import Event, EventType

_WEEKDAYS_CS_GENITIVE = ("pondělí", "úterý", "středy", "čtvrtka", "pátku", "soboty", "neděle")
_WEEKDAYS_EN = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

_TEXTS = {
    "cs": {
        EventType.ARRIVED: "Příchod: {name}",
        EventType.LEFT: "Odchod: {name}",
        EventType.FIRST_ARRIVED: "Někdo je doma",
        EventType.LAST_LEFT: "Nikdo doma od {time}",
        EventType.LONG_AWAY_STARTED: "Dlouhodobě pryč: {reason}",
        EventType.LONG_AWAY_ENDED: "Konec dlouhodobé nepřítomnosti",
        EventType.MODE_CHANGED: "Režim: {mode}",
        EventType.MULTIPLE_HOME: "Víc lidí doma ({count})",
        EventType.MULTIPLE_ENDED: "Doma méně než {min} lidí",
        EventType.GROUP_HOME: "Skupina {name}: doma",
        EventType.GROUP_AWAY: "Skupina {name}: pryč",
    },
    "en": {
        EventType.ARRIVED: "Arrived: {name}",
        EventType.LEFT: "Left: {name}",
        EventType.FIRST_ARRIVED: "Someone is home",
        EventType.LAST_LEFT: "Nobody home since {time}",
        EventType.LONG_AWAY_STARTED: "Away for long: {reason}",
        EventType.LONG_AWAY_ENDED: "Long absence ended",
        EventType.MODE_CHANGED: "Mode: {mode}",
        EventType.MULTIPLE_HOME: "Several people home ({count})",
        EventType.MULTIPLE_ENDED: "Fewer than {min} people home",
        EventType.GROUP_HOME: "Group {name}: home",
        EventType.GROUP_AWAY: "Group {name}: away",
    },
}

_REASONS = {
    "cs": {
        "vacation": "dovolená",
        "away_until": "pryč",
        "calendar": "podle kalendáře",
        "duration": "dlouho nikdo doma",
        "prediction": "nikdo se brzy nevrátí",
    },
    "en": {
        "vacation": "vacation",
        "away_until": "away",
        "calendar": "per calendar",
        "duration": "nobody home for long",
        "prediction": "nobody returns soon",
    },
}

_MODES = {
    "cs": {
        "auto": "automaticky",
        "force_home": "vynutit doma",
        "force_away": "vynutit pryč",
        "vacation": "dovolená",
    },
    "en": {
        "auto": "automatic",
        "force_home": "force home",
        "force_away": "force away",
        "vacation": "vacation",
    },
}

_MODE_REASON = {"cs": {"arrival": " (příchod domů)"}, "en": {"arrival": " (arrival)"}}
_UNTIL = {"cs": " do {when}", "en": " until {when}"}


def _lang(language: str | None) -> str:
    return "cs" if (language or "").lower().startswith("cs") else "en"


def _clock(value: datetime) -> str:
    return f"{value.hour}:{value.minute:02d}"


def format_when(value: datetime, tz: tzinfo, language: str | None) -> str:
    """Format a moment like ``neděle 18:00`` (in genitive for Czech ``do …``)."""
    local = value.astimezone(tz)
    if _lang(language) == "cs":
        day = _WEEKDAYS_CS_GENITIVE[local.weekday()]
        return f"{day} {local.day}. {local.month}. {_clock(local)}"
    return f"{_WEEKDAYS_EN[local.weekday()]} {local.day} {local:%b} {_clock(local)}"


def message(event: Event, language: str | None, tz: tzinfo) -> str:
    """Return the logbook sentence of an event."""
    lang = _lang(language)
    template = _TEXTS[lang][event.type]
    data = event.data
    text = template.format(
        name=event.name or "",
        time=_clock(event.at.astimezone(tz)),
        reason=_REASONS[lang].get(str(data.get("reason")), str(data.get("reason", ""))),
        mode=_MODES[lang].get(str(data.get("to")), str(data.get("to", ""))),
        count=data.get("count", ""),
        min=data.get("min", ""),
    )
    if event.type is EventType.LONG_AWAY_STARTED and data.get("until"):
        until = datetime.fromisoformat(str(data["until"]))
        text += _UNTIL[lang].format(when=format_when(until, tz, language))
    if event.type is EventType.MODE_CHANGED:
        text += _MODE_REASON[lang].get(str(data.get("reason")), "")
    return text
