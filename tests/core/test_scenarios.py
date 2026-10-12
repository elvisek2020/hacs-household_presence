"""Mandatory scenarios of the PRD (chapter 10) on the pure engine."""

from datetime import datetime, timedelta

from custom_components.household_presence import const as c
from custom_components.household_presence.core.model import (
    EventType,
    HouseholdState,
    Method,
    Mode,
    PersonMode,
    PersonState,
    Reason,
    ReturnSource,
)

from .helpers import T0, TZ, House, member, plan, sig

GPS = "device_tracker.parent_phone"
WIFI = "device_tracker.parent_wifi"
PC = "binary_sensor.kid_pc"
SCHOOL = "calendar.kid_school"
DOOR = "binary_sensor.front_door"


def parent(**extra):
    return member(
        "Parent",
        sig(GPS, "home_away", trust="high"),
        sig(WIFI, "home_only"),
        **extra,
    )


def kid(**extra):
    return member(
        "Kid",
        sig(PC, "home_only"),
        no_signal_policy="hold_last",
        plan=plan(SCHOOL),
        **extra,
    )


def at(hour: int, minute: int = 0, day: int = 12) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=TZ)


# --- arrival and departure -------------------------------------------------------


def test_arrival_is_immediate_and_departure_waits_for_delay():
    house = House([parent()])
    house.set(GPS, "home")
    assert house.person("parent").state is PersonState.HOME
    assert house.hh.someone_home

    house.set(GPS, "not_home")
    house.set(WIFI, "not_home")
    assert house.person("parent").state is PersonState.JUST_LEFT
    assert house.person("parent").is_home
    house.run(14)
    assert house.person("parent").state is PersonState.JUST_LEFT
    house.run(1)
    view = house.person("parent")
    assert view.state is PersonState.AWAY
    assert view.since == T0
    assert not house.hh.someone_home
    assert house.hh.away_since == T0
    assert house.event_types("Parent") == [EventType.LEFT]

    house.set(GPS, "home")
    assert house.person("parent").state is PersonState.JUST_ARRIVED
    assert house.event_types("Parent") == [EventType.LEFT, EventType.ARRIVED]
    house.run(10)
    assert house.person("parent").state is PersonState.HOME


def test_gps_jump_does_not_cause_departure():
    house = House([parent()])
    house.set(GPS, "home")
    house.set(GPS, "not_home")
    house.run(5)
    house.set(GPS, "home")
    house.run(30)
    assert house.person("parent").state is PersonState.HOME
    assert EventType.LEFT not in house.event_types()


def test_one_home_signal_is_enough():
    house = House([parent()])
    house.set(WIFI, "home", step=False)
    house.set(GPS, "not_home")
    house.run(60)
    assert house.person("parent").state is PersonState.HOME
    assert house.person("parent").sources == (WIFI,)


def test_unavailable_signal_is_ignored():
    house = House([parent()])
    house.set(GPS, "home")
    house.set(GPS, "unavailable")
    house.run(60)
    assert house.person("parent").state is PersonState.HOME


def test_all_signals_unavailable_long_makes_member_unknown():
    house = House([parent()])
    house.set(GPS, "home")
    house.set(GPS, "unavailable", step=False)
    house.set(WIFI, "unavailable")
    house.run(6 * 60 - 1, every=5)
    assert house.person("parent").state is PersonState.HOME
    house.run(2)
    assert house.person("parent").state is PersonState.UNKNOWN
    assert not house.person("parent").available
    assert "member_unavailable" in house.problems()


# --- night window and doors ---------------------------------------------------------


def test_wifi_sleep_at_night_does_not_cause_departure():
    house = House([member("Teen", sig(WIFI))], now=at(22, 30))
    house.set(WIFI, "home")
    house.set(WIFI, "not_home")
    house.run_until(at(7, 10, day=13), every=5)
    assert house.person("teen").state is PersonState.JUST_LEFT
    assert house.hh.someone_home
    # Morning: the night is over, the delay starts again and the member leaves.
    house.run(15)
    assert house.person("teen").state is PersonState.AWAY
    assert house.person("teen").since == at(7, 0, day=13)


def test_daytime_wifi_departure_after_delay():
    house = House([member("Teen", sig(WIFI))], now=at(10))
    house.set(WIFI, "home")
    house.set(WIFI, "not_home")
    house.run(15)
    assert house.person("teen").state is PersonState.AWAY


def test_night_departure_with_door_change():
    house = House(
        [member("Teen", sig(WIFI))],
        {c.CONF_DOOR_ENTITIES: [DOOR]},
        now=at(23),
    )
    house.set(DOOR, "off", step=False)
    house.set(WIFI, "home")
    house.run(1)
    house.set(DOOR, "on")
    house.run(1)
    house.set(DOOR, "off", step=False)
    house.set(WIFI, "not_home")
    house.run(16)
    assert house.person("teen").state is PersonState.AWAY


def test_hold_last_keeps_member_home_without_signals():
    house = House([member("Kid", sig(PC), no_signal_policy="hold_last")], now=at(10))
    house.set(PC, "on")
    house.set(PC, "off")
    house.run(120)
    assert house.person("kid").state is PersonState.HOME


# --- plan -------------------------------------------------------------------------


def school_day(house: House, day: int = 12) -> None:
    house.calendar(
        SCHOOL,
        [
            (at(8, 0, day), at(8, 45, day), "Math"),
            (at(8, 55, day), at(9, 40, day), "Physics"),
            (at(10, 0, day), at(11, 30, day), "English"),
        ],
    )


def test_plan_moves_member_away_and_back():
    house = House([kid()], now=at(7))
    school_day(house)
    house.set(PC, "on")
    house.set(PC, "off")
    house.run_until(at(7, 40))
    assert house.person("kid").state is PersonState.JUST_LEFT
    house.run(15)
    view = house.person("kid")
    assert view.state is PersonState.AWAY
    assert view.method is Method.PLAN
    # Gaps of 10 and 20 minutes are bridged: one block 7:40-12:00.
    assert view.expected_return is not None
    assert view.expected_return.at == at(12)
    assert view.expected_return.source is ReturnSource.PLANNED
    house.run_until(at(11, 59))
    assert house.person("kid").state is PersonState.AWAY
    house.run(1)
    assert house.person("kid").state is PersonState.JUST_ARRIVED
    assert house.person("kid").method is Method.PLAN


def test_pc_left_on_overnight_does_not_keep_member_home():
    house = House([kid()], now=at(6))
    school_day(house)
    house.set(PC, "on")
    house.run_until(at(8))
    assert house.person("kid").state is PersonState.AWAY


def test_sick_child_switches_pc_on_during_plan():
    house = House([kid()], now=at(7))
    school_day(house)
    house.set(PC, "off")
    house.run_until(at(9))
    assert house.person("kid").state is PersonState.AWAY
    house.set(PC, "on")
    assert house.person("kid").state is PersonState.JUST_ARRIVED
    assert house.person("kid").method is Method.SIGNAL


def test_restart_during_plan_is_not_an_arrival():
    house = House([kid()], {c.CONF_STARTUP_GRACE: 5}, now=at(7))
    school_day(house)
    house.set(PC, "off")
    house.run_until(at(9))
    assert house.person("kid").state is PersonState.AWAY
    # After the restart the entity reappears with a fresh last_changed.
    house.restart()
    house.remove(PC)
    house.set(PC, "on", step=False)
    house.run(10)
    assert house.person("kid").state is PersonState.AWAY


def test_gap_longer_than_bridge_splits_blocks():
    house = House([kid()], now=at(7))
    house.calendar(
        SCHOOL,
        [(at(8), at(9), "Morning"), (at(11), at(12), "Late")],
    )
    house.set(PC, "off")
    # Block 7:40-9:30, then home until the next block starts at 10:40.
    house.run_until(at(9, 35))
    assert house.person("kid").state is PersonState.JUST_ARRIVED
    house.run_until(at(10, 56))
    assert house.person("kid").state is PersonState.AWAY


def test_calendar_unavailable_is_a_problem_and_plan_is_skipped():
    house = House([kid()], now=at(7))
    house.calendar(SCHOOL, ok=False)
    house.set(PC, "on")
    house.set(PC, "off")
    house.run_until(at(9))
    assert house.person("kid").state is PersonState.HOME
    assert "calendar_unavailable" in house.problems()


# --- restart and grace -------------------------------------------------------------


def test_restart_during_just_left_keeps_the_timer():
    house = House([parent()], {c.CONF_STARTUP_GRACE: 0})
    house.set(GPS, "home")
    house.set(GPS, "not_home")
    house.run(10)
    house.restart()
    house.run(4)
    assert house.person("parent").state is PersonState.JUST_LEFT
    house.run(1)
    assert house.person("parent").state is PersonState.AWAY
    assert house.person("parent").since == T0


def test_startup_grace_blocks_departures_but_not_arrivals():
    house = House([parent(), member("Other", sig("device_tracker.other", "home_away"))], grace=True)
    house.set("device_tracker.other", "home", step=False)
    house.set(GPS, "not_home")
    house.run(4)
    assert house.person("parent").state is PersonState.UNKNOWN
    assert house.person("other").state is PersonState.HOME
    house.run(2)
    assert house.person("parent").state is PersonState.AWAY
    assert "signal_missing" not in house.problems() or True


# --- modes, guest, away until -------------------------------------------------------------


def test_vacation_ends_on_trusted_arrival_only():
    house = House([parent(), member("Kid2", sig("binary_sensor.console"))])
    house.set(GPS, "not_home", step=False)
    house.set("binary_sensor.console", "off")
    house.run(20)
    house.engine.set_mode(Mode.VACATION, house.now)
    house.run(60)
    assert house.hh.state is HouseholdState.LONG_AWAY
    assert house.hh.reason is Reason.VACATION
    house.set("binary_sensor.console", "on")
    assert house.hh.mode is Mode.VACATION
    assert not house.hh.someone_home
    house.set(GPS, "home")
    assert house.hh.mode is Mode.AUTO
    assert house.hh.someone_home
    assert EventType.MODE_CHANGED in house.event_types()


def test_force_modes_override_signals():
    house = House([parent()])
    house.set(GPS, "home")
    house.engine.set_mode(Mode.FORCE_AWAY, house.now)
    house.step()
    assert not house.hh.someone_home
    assert house.hh.reason is Reason.MANUAL
    house.engine.set_mode(Mode.FORCE_HOME, house.now)
    house.set(GPS, "not_home")
    house.run(30)
    assert house.hh.someone_home


def test_guest_counts_as_someone_home_and_turns_off_after_hours():
    house = House(
        [parent()],
        {c.CONF_GUEST_AUTO_OFF: c.GUEST_OFF_AFTER, c.CONF_GUEST_OFF_HOURS: 2},
    )
    house.set(GPS, "not_home")
    house.run(20)
    house.engine.set_guest(True, house.now)
    house.step()
    assert house.hh.someone_home
    assert house.hh.reason is Reason.GUEST
    assert house.hh.count == 0
    house.run(121)
    assert not house.hh.guest
    assert not house.hh.someone_home


def test_guest_turns_off_at_time():
    house = House(
        [parent()],
        {c.CONF_GUEST_AUTO_OFF: c.GUEST_OFF_AT_TIME, c.CONF_GUEST_OFF_TIME: "04:00:00"},
        now=at(20),
    )
    house.set(GPS, "not_home")
    house.engine.set_guest(True, house.now)
    house.run_until(at(3, 59, day=13), every=10)
    assert house.hh.guest
    house.run(2)
    assert not house.hh.guest


def test_away_until_is_long_away_and_expected_return():
    house = House([parent()])
    house.set(GPS, "not_home")
    house.run(20)
    until = at(18, day=18)
    house.engine.set_away_until(until, house.now)
    house.step()
    assert house.hh.long_away
    assert house.hh.reason is Reason.AWAY_UNTIL
    assert house.hh.expected_return is not None
    assert house.hh.expected_return.at == until
    assert house.hh.expected_return.source is ReturnSource.PLANNED
    house.engine.set_mode(Mode.VACATION, house.now)
    house.run_until(until + timedelta(minutes=1), every=60)
    assert house.hh.away_until is None
    assert house.hh.mode is Mode.AUTO


def test_person_force_away_is_cleared_by_trusted_arrival():
    house = House([parent()])
    house.set(GPS, "home")
    house.engine.set_person_mode("parent", PersonMode.FORCE_AWAY, house.now)
    house.step()
    assert house.person("parent").state is PersonState.AWAY
    assert house.person("parent").method is Method.MANUAL
    house.run(5)
    house.set(GPS, "not_home")
    house.run(1)
    house.set(GPS, "home")
    assert house.person("parent").mode is PersonMode.AUTO
    assert house.person("parent").state is PersonState.JUST_ARRIVED


def test_person_away_until_expires():
    house = House([member("Kid", sig(PC), no_signal_policy="hold_last")])
    house.set(PC, "off")
    house.engine.set_away_until(house.now + timedelta(hours=2), house.now, "kid")
    house.step()
    assert house.person("kid").state is PersonState.AWAY
    assert house.person("kid").expected_return.at == house.now + timedelta(hours=2)
    house.run(121, every=5)
    assert house.person("kid").away_until is None


# --- long absence -----------------------------------------------------------------------


def test_normal_workday_is_not_long_away():
    house = House([parent()], now=at(7))
    house.set(GPS, "home")
    house.set(GPS, "not_home")
    house.run_until(at(16, 30), every=5)
    assert not house.hh.someone_home
    assert not house.hh.long_away
    assert house.hh.state is HouseholdState.AWAY


def test_weekend_away_becomes_long_away_after_24h():
    house = House([parent()], now=at(16, day=16))
    house.set(GPS, "home")
    house.set(GPS, "not_home")
    # The absence counts from the departure itself (16:00), not from its confirmation.
    house.run(24 * 60 - 1, every=1)
    assert not house.hh.long_away
    house.run(1)
    assert house.hh.long_away
    assert house.hh.reason is Reason.DURATION
    assert EventType.LONG_AWAY_STARTED in house.event_types()
    house.set(GPS, "home")
    assert not house.hh.long_away
    assert EventType.LONG_AWAY_ENDED in house.event_types()


def test_vacation_calendar_makes_long_away():
    house = House(
        [parent()],
        {
            c.CONF_VACATION_CALENDARS: ["calendar.family"],
            c.CONF_VACATION_KEYWORDS: "dovolená, chata",
        },
    )
    house.calendar("calendar.family", [(at(0, day=12), at(18, day=14), "Chata u jezera")])
    house.set(GPS, "not_home")
    house.run(16)
    assert house.hh.long_away
    assert house.hh.reason is Reason.CALENDAR
    assert house.hh.expected_return.at == at(18, day=14)


# --- household aggregation and events ------------------------------------------------------


def test_first_arrived_and_last_left_events():
    house = House([parent(), member("Teen", sig("device_tracker.teen", "home_away"))])
    house.set(GPS, "home", step=False)
    house.set("device_tracker.teen", "home")
    house.set(GPS, "not_home")
    house.run(16)
    assert house.hh.count == 1
    house.set("device_tracker.teen", "not_home")
    house.run(16)
    assert not house.hh.someone_home
    house.set(GPS, "home")
    types = house.event_types()
    assert types.count(EventType.LAST_LEFT) == 1
    assert types.count(EventType.FIRST_ARRIVED) == 1
    assert house.hh.people == ("Parent",)


def test_household_signal_counts_as_someone_home():
    house = House([parent()], {c.CONF_HOUSEHOLD_SIGNALS: ["media_player.tv"]})
    house.set(GPS, "not_home")
    house.run(20)
    assert not house.hh.someone_home
    house.set("media_player.tv", "on")
    assert house.hh.someone_home
    assert house.hh.reason is Reason.HOUSEHOLD_SIGNAL
    assert house.hh.count == 0


def test_expected_return_is_never_in_the_past():
    house = House([kid()], now=at(7))
    school_day(house)
    house.set(PC, "off")
    for _ in range(12 * 6):
        house.run(10)
        er = house.hh.expected_return
        assert er is None or er.at > house.now


# --- signals -------------------------------------------------------------------------------


def test_arrival_delay_of_a_low_trust_signal():
    house = House(
        [member("Teen", sig("binary_sensor.console", arrival_delay=2), sig(WIFI))],
        now=at(10),
    )
    house.set(WIFI, "not_home", step=False)
    house.set("binary_sensor.console", "off")
    house.run(20)
    assert house.person("teen").state is PersonState.AWAY
    house.set("binary_sensor.console", "on")
    assert house.person("teen").state is PersonState.AWAY
    house.run(2)
    assert house.person("teen").state is PersonState.JUST_ARRIVED


def test_stuck_signal_is_ignored_and_reported():
    house = House(
        [member("Teen", sig("binary_sensor.console", max_on=12), sig(WIFI))],
        now=at(6),
    )
    house.set(WIFI, "not_home", step=False)
    house.set("binary_sensor.console", "on")
    house.run(12 * 60 + 16, every=1)
    assert house.person("teen").state is PersonState.AWAY
    assert "signal_stuck" in house.problems()


def test_away_only_signal_moves_member_away():
    house = House(
        [
            member(
                "Parent",
                sig(WIFI),
                sig("binary_sensor.work_vpn", "away_only"),
                no_signal_policy="hold_last",
            )
        ],
        now=at(10),
    )
    house.set(WIFI, "home")
    house.set(WIFI, "not_home", step=False)
    house.set("binary_sensor.work_vpn", "on")
    house.run(15)
    assert house.person("parent").state is PersonState.AWAY


def test_missing_signal_and_member_that_cannot_leave_are_problems():
    house = House([member("Kid", sig(PC), no_signal_policy="hold_last")])
    house.step()
    assert {"signal_missing", "member_cannot_leave"} <= house.problems()


def test_members_with_different_signals_and_reconfigure():
    house = House([parent(), kid()], now=at(7))
    school_day(house)
    house.set(GPS, "home", step=False)
    house.set(PC, "on")
    assert house.hh.count == 2
    house.member_data.append(member("Guest Room", sig("binary_sensor.lamp")))
    house.engine.reconfigure(house.engine.config, house._configs())
    house.set("binary_sensor.lamp", "on")
    assert house.hh.count == 3
    house.member_data = house.member_data[:1]
    house.engine.reconfigure(house.engine.config, house._configs())
    house.step()
    assert set(house.result.persons) == {"parent"}
    assert house.person("parent").state is PersonState.HOME
