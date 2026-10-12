"""Learning, predictions and approach (FR-LEARN, FR-APPR)."""

from datetime import date, datetime, timedelta

from custom_components.household_presence import const as c
from custom_components.household_presence.core.approach import ApproachTracker, distance_km
from custom_components.household_presence.core.learning import DayRecord, Learner, slot_of
from custom_components.household_presence.core.model import (
    ApproachConfig,
    EntityReading,
    PersonState,
    Reason,
    ReturnSource,
)

from .helpers import TZ, House, member, sig

GPS = "device_tracker.parent_phone"


def at(day: int, hour: int, minute: int = 0, month: int = 10) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=TZ)


def commute(house: House, day: int, leave: int, back: int, month: int = 10) -> None:
    """One day: home at night, away from ``leave`` to ``back`` o'clock."""
    house.run_until(at(day, leave, month=month), every=15)
    house.set(GPS, "not_home")
    house.run_until(at(day, back, month=month), every=15)
    house.set(GPS, "home")


def test_learned_return_after_four_mondays():
    house = House([member("Parent", sig(GPS, "home_away"))], now=at(5, 0))
    house.set(GPS, "home")
    for day in (5, 12, 19, 26):
        commute(house, day, 7, 16)
        if day != 26:
            house.run_until(at(day + 1, 0), every=30)
            # Rest of the week at home so that only Mondays carry information.
            house.run_until(at(day + 7, 0), every=60)
    # Monday 2 November, away since 7:00.
    house.run_until(at(2, 7, month=11), every=60)
    house.set(GPS, "not_home")
    house.run(60, every=15)
    view = house.person("parent")
    assert view.state is PersonState.AWAY
    assert view.expected_return is not None
    assert view.expected_return.source is ReturnSource.LEARNED
    assert view.expected_return.at == at(2, 16, month=11)
    assert 0.3 < view.expected_return.confidence <= 0.9
    assert house.hh.expected_return.at == at(2, 16, month=11)
    house.run_until(at(2, 16, 10, month=11), every=15)
    house.set(GPS, "home")
    assert house.engine.last_errors["parent"] == 10.0
    metrics = house.engine.learner.metrics["parent"].summary()
    assert metrics["arrivals"] >= 1


def test_prediction_needs_samples():
    learner = Learner(half_life_weeks=4, min_samples=3, tz=TZ)
    prediction = learner.predict("x", at(12, 10), workday=True)
    assert prediction.at is None
    assert not prediction.ready


def test_model_says_nobody_returns_makes_long_away():
    learner_house = House(
        [member("Parent", sig(GPS, "home_away"))],
        {c.CONF_MIN_SAMPLES: 2},
        now=at(1, 0),
    )
    house = learner_house
    house.set(GPS, "home")
    # Two Fridays away for the whole weekend.
    for friday in (2, 9):
        house.run_until(at(friday, 15), every=60)
        house.set(GPS, "not_home")
        house.run_until(at(friday + 2, 18), every=60)
        house.set(GPS, "home")
    house.run_until(at(16, 15), every=60)
    house.set(GPS, "not_home")
    house.run(2 * 60 + 16, every=5)
    assert house.hh.long_away
    assert house.hh.reason is Reason.PREDICTION


def test_dst_keeps_local_time():
    learner = Learner(half_life_weeks=4, min_samples=2, tz=TZ)
    # Sundays 18 and 25 October (DST ends on 25 October 2026).
    for day in (11, 18, 25):
        record = DayRecord(day=date(2026, 10, day), workday=False)
        for slot in range(48):
            record.slots[slot] = 0 if 18 <= slot < 34 else 1
        record.arrivals.append(17 * 60)
        learner.records.setdefault("p", []).append(record)
    prediction = learner.predict("p", at(1, 12, month=11), workday=False)
    assert prediction.at == at(1, 17, month=11)
    assert prediction.at.utcoffset() == timedelta(hours=1)


def test_slot_of_local_time():
    assert slot_of(at(12, 0, 0)) == 0
    assert slot_of(at(12, 23, 59)) == 47
    assert slot_of(at(12, 7, 31)) == 15


def test_excluded_days_are_not_used():
    learner = Learner(half_life_weeks=4, min_samples=1, tz=TZ)
    record = DayRecord(day=date(2026, 10, 5), workday=True, excluded=True)
    record.slots = [0] * 48
    record.arrivals = [16 * 60]
    learner.records["p"] = [record]
    assert learner.predict("p", at(12, 10), workday=True).at is None


def test_profile_and_reset():
    learner = Learner(half_life_weeks=4, min_samples=1, tz=TZ)
    learner.observe("p", at(12, 10), home=True, excluded=False, workday=True)
    learner.observe("p", at(13, 10), home=False, excluded=False, workday=True)
    profile = learner.profile("p")
    assert profile[0][20] == round(2 / 3, 2)
    data = learner.to_dict()
    other = Learner(half_life_weeks=4, min_samples=1, tz=TZ)
    other.restore(data)
    assert other.profile("p") == profile
    other.reset()
    assert other.records == {}


def test_approach_needs_decreasing_distance():
    cfg = ApproachConfig(distance_entity="sensor.d", threshold_km=15, confirmations=2)
    tracker = ApproachTracker()
    now = at(12, 17)
    readings = [30, 14, 12, 10]
    eta = None
    for i, km in enumerate(readings):
        eta = tracker.update(
            cfg,
            EntityReading(state=str(km), last_changed=now + timedelta(minutes=i)),
            None,
            now + timedelta(minutes=i),
        )
        if i < 2:
            assert eta is None
    assert eta == now + timedelta(minutes=3) + timedelta(hours=10 / 50)


def test_approach_in_meters_and_engine_source():
    assert (
        distance_km(
            EntityReading(
                state="1500", last_changed=at(12, 1), attributes={"unit_of_measurement": "m"}
            )
        )
        == 1.5
    )
    house = House(
        [
            member(
                "Parent",
                sig(GPS, "home_away"),
                approach={
                    c.CONF_DISTANCE_ENTITY: "sensor.parent_distance",
                    c.CONF_THRESHOLD_KM: 20,
                },
            )
        ],
        now=at(12, 10),
    )
    house.set(GPS, "not_home")
    house.run(20)
    for km in (25, 18, 12, 8):
        house.set("sensor.parent_distance", str(km), unit_of_measurement="km")
        house.run(5)
    assert house.hh.approaching == ("Parent",)
    assert house.hh.expected_return.source is ReturnSource.APPROACHING
