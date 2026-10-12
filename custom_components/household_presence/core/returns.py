"""Expected return of members and the household (FR-RET-01..04)."""

from collections.abc import Iterable
from datetime import datetime

from .model import ExpectedReturn, MemberConfig, ReturnSource
from .person import PersonRuntime

CONF_PERSON_AWAY_UNTIL = 0.95
CONF_HOUSEHOLD_AWAY_UNTIL = 0.9
CONF_VACATION_CALENDAR = 0.85
CONF_PLAN = 0.8
CONF_APPROACH = 0.8


def person_return(
    member: MemberConfig,
    rt: PersonRuntime,
    now: datetime,
    *,
    household_away_until: datetime | None,
    vacation_end: datetime | None,
    plan_end: datetime | None,
    approach_eta: datetime | None,
    learned: tuple[datetime, float] | None,
) -> ExpectedReturn | None:
    """Return the expected return of an absent member, None when home or unknown."""
    if rt.is_home or rt.since is None:
        return None

    def make(at: datetime, source: ReturnSource, confidence: float) -> ExpectedReturn:
        return ExpectedReturn(
            at=at,
            source=source,
            confidence=confidence,
            member_id=member.member_id,
            name=member.name,
        )

    planned = next(
        (
            make(at, ReturnSource.PLANNED, conf)
            for at, conf in (
                (rt.away_until, CONF_PERSON_AWAY_UNTIL),
                (household_away_until, CONF_HOUSEHOLD_AWAY_UNTIL),
                (vacation_end, CONF_VACATION_CALENDAR),
                (plan_end, CONF_PLAN),
            )
            if at is not None and at > now
        ),
        None,
    )
    approaching = (
        make(approach_eta, ReturnSource.APPROACHING, CONF_APPROACH)
        if approach_eta is not None and approach_eta > now
        else None
    )
    if approaching is not None and (planned is None or approaching.at < planned.at):
        return approaching
    if planned is not None:
        return planned
    if learned is not None and learned[0] > now:
        return make(learned[0], ReturnSource.LEARNED, learned[1])
    return None


def household_return(
    returns: Iterable[ExpectedReturn | None],
    now: datetime,
    *,
    someone_home: bool,
    household_away_until: datetime | None,
) -> ExpectedReturn | None:
    """Return the nearest return of anybody while nobody is home (FR-RET-02/03)."""
    if someone_home:
        return None
    candidates = [r for r in returns if r is not None and r.at > now]
    if not candidates and household_away_until is not None and household_away_until > now:
        candidates.append(
            ExpectedReturn(
                at=household_away_until,
                source=ReturnSource.PLANNED,
                confidence=CONF_HOUSEHOLD_AWAY_UNTIL,
            )
        )
    return min(candidates, key=lambda r: r.at, default=None)
