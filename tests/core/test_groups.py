"""Several people home and groups of members (FR-HH-07, FR-GRP)."""

from custom_components.household_presence import const as c
from custom_components.household_presence.core.model import EventType, Mode, ReturnSource

from .helpers import House, member, plan, sig

A = "device_tracker.a"
B = "device_tracker.b"
C = "device_tracker.c"


def three(**kwargs) -> House:
    return House(
        [
            member("Alex", sig(A, "home_away")),
            member("Blake", sig(B, "home_away")),
            member("Casey", sig(C, "home_away")),
        ],
        **kwargs,
    )


def test_multiple_home_needs_two_members_guest_does_not_count():
    house = three()
    house.set(A, "not_home", step=False)
    house.set(B, "not_home", step=False)
    house.set(C, "not_home")
    assert not house.hh.multiple_home
    house.engine.set_guest(True, house.now)
    house.set(A, "home")
    assert house.hh.count == 1
    assert not house.hh.multiple_home
    house.set(B, "home")
    assert house.hh.multiple_home
    assert EventType.MULTIPLE_HOME in house.event_types()
    house.set(B, "not_home")
    house.run(14)
    assert house.hh.multiple_home
    house.run(1)
    assert not house.hh.multiple_home
    assert EventType.MULTIPLE_ENDED in house.event_types()


def test_multiple_threshold_is_configurable():
    house = three(options={c.CONF_MULTIPLE_MIN: 3})
    house.set(A, "home", step=False)
    house.set(B, "home", step=False)
    house.set(C, "not_home")
    assert house.hh.count == 2
    assert not house.hh.multiple_home
    assert house.hh.multiple_min == 3


def test_group_at_least_one_member():
    house = three(groups=[{c.CONF_NAME: "Parents", c.CONF_MEMBERS: ["alex", "blake"]}])
    house.set(A, "home", step=False)
    house.set(B, "home", step=False)
    house.set(C, "home")
    assert house.group("parents").home
    assert house.group("parents").count == 2
    house.set(A, "not_home")
    house.run(20)
    assert house.group("parents").home
    assert house.group("parents").people == ("Blake",)
    house.set(B, "not_home")
    house.run(14)
    assert house.group("parents").home
    house.run(1)
    group = house.group("parents")
    assert not group.home
    assert group.since == house.now
    assert house.hh.someone_home  # Casey is still home
    types = [e.type for e in house.events if e.name == "Parents"]
    assert types == [EventType.GROUP_AWAY]


def test_group_with_minimum_count_and_expected_return():
    house = House(
        [
            member("Alex", sig(A, "home_away")),
            member("Kid", sig(C), no_signal_policy="hold_last", plan=plan("calendar.school")),
        ],
        groups=[{c.CONF_NAME: "Both", c.CONF_MEMBERS: ["alex", "kid"], c.CONF_MIN_COUNT: 2}],
    )
    start = house.now
    house.calendar("calendar.school", [(start, start.replace(hour=12), "School")])
    house.set(A, "home", step=False)
    house.set(C, "home")
    house.set(C, "not_home")
    assert house.group("both").home
    house.run(16)
    group = house.group("both")
    assert not group.home
    assert group.count == 1
    assert group.expected_return is not None
    assert group.expected_return.source is ReturnSource.PLANNED
    assert group.expected_return.at == start.replace(hour=12, minute=30)


def test_household_mode_overrides_groups_and_multiple():
    house = three(groups=[{c.CONF_NAME: "Parents", c.CONF_MEMBERS: ["alex", "blake"]}])
    house.set(A, "home", step=False)
    house.set(B, "home", step=False)
    house.set(C, "not_home")
    house.engine.set_mode(Mode.FORCE_AWAY, house.now)
    house.step()
    assert not house.group("parents").home
    assert not house.hh.multiple_home
    house.engine.set_mode(Mode.FORCE_HOME, house.now)
    house.set(A, "not_home", step=False)
    house.set(B, "not_home")
    house.run(20)
    assert house.group("parents").home
    assert house.hh.multiple_home


def test_group_state_survives_restart_and_unknown_member_is_ignored():
    house = three(
        groups=[{c.CONF_NAME: "Parents", c.CONF_MEMBERS: ["alex", "removed"]}],
    )
    house.set(A, "home", step=False)
    house.set(B, "home", step=False)
    house.set(C, "home")
    since = house.group("parents").since
    house.run(5)
    house.restart()
    house.step()
    assert house.group("parents").home
    assert house.group("parents").since == since
    assert not [e for e in house.events if e.name == "Parents"]
