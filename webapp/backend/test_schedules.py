import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import schedules

# Saturday 2026-10-10, 10:00 local.
NOW = datetime(2026, 10, 10, 10, 0)


def _sched(weekday, hour, minute, last_run=None, enabled=True):
    return {"weekday": weekday, "hour": hour, "minute": minute,
            "last_run": last_run, "enabled": enabled}


def test_previous_occurrence_walks_back_to_the_right_weekday():
    # Monday 06:17 before Saturday 2026-10-10 is 2026-10-05.
    assert schedules.previous_occurrence(1, 6, 17, NOW) == datetime(2026, 10, 5, 6, 17)
    # Thursday 17:43 is 2026-10-08.
    assert schedules.previous_occurrence(4, 17, 43, NOW) == datetime(2026, 10, 8, 17, 43)


def test_same_day_but_later_belongs_to_the_previous_week():
    # Saturday 23:00, asked on Saturday at 10:00: today's slot has not arrived.
    assert schedules.previous_occurrence(6, 23, 0, NOW) == datetime(2026, 10, 3, 23, 0)
    # Saturday 09:00 already passed today.
    assert schedules.previous_occurrence(6, 9, 0, NOW) == datetime(2026, 10, 10, 9, 0)


def test_next_occurrence_is_a_week_after_the_previous():
    assert schedules.next_occurrence(1, 6, 17, NOW) == datetime(2026, 10, 12, 6, 17)


def test_never_run_schedule_is_due():
    assert schedules.is_due(_sched(1, 6, 17), NOW) is True


def test_a_run_after_the_last_slot_clears_it():
    already = datetime(2026, 10, 5, 6, 18).timestamp()
    assert schedules.is_due(_sched(1, 6, 17, last_run=already), NOW) is False


def test_a_missed_week_is_caught_up_not_skipped():
    """Container down over Monday: the run is owed, not lost until next week."""
    stale = datetime(2026, 9, 28, 6, 17).timestamp()
    assert schedules.is_due(_sched(1, 6, 17, last_run=stale), NOW) is True


def test_disabled_schedules_never_fire():
    assert schedules.is_due(_sched(1, 6, 17, enabled=False), NOW) is False


def test_describe_reads_back_in_german():
    assert schedules.describe(_sched(1, 6, 17)) == "Montag 06:17"
    assert schedules.describe(_sched(4, 17, 43)) == "Donnerstag 17:43"


def test_validate_rejects_impossible_times():
    schedules.validate(0, 0, 0)
    schedules.validate(6, 23, 59)
    for bad in [(7, 0, 0), (-2, 0, 0), (0, 24, 0), (0, 0, 60)]:
        try:
            schedules.validate(*bad)
            assert False, f"expected ValueError for {bad}"
        except ValueError:
            pass


def test_daily_schedule_fires_once_a_day_at_its_time():
    d = schedules.DAILY
    # Saturday 10:00: today's 06:17 has passed, tomorrow's has not.
    assert schedules.previous_occurrence(d, 6, 17, NOW) == datetime(2026, 10, 10, 6, 17)
    assert schedules.next_occurrence(d, 6, 17, NOW) == datetime(2026, 10, 11, 6, 17)
    # Before today's time it still owes yesterday's.
    assert schedules.previous_occurrence(d, 23, 0, NOW) == datetime(2026, 10, 9, 23, 0)


def test_daily_schedule_is_due_until_it_has_run_since_the_last_slot():
    d = schedules.DAILY
    ran_this_morning = datetime(2026, 10, 10, 6, 30).timestamp()
    ran_yesterday = datetime(2026, 10, 9, 6, 30).timestamp()
    assert not schedules.is_due(_sched(d, 6, 17, ran_this_morning), NOW)
    assert schedules.is_due(_sched(d, 6, 17, ran_yesterday), NOW)  # a missed day is caught up


def test_daily_validates_and_describes():
    schedules.validate(schedules.DAILY, 6, 17)
    assert schedules.describe(_sched(schedules.DAILY, 6, 17)) == "Täglich 06:17"
    try:
        schedules.validate(-2, 6, 17)
    except ValueError:
        pass
    else:
        raise AssertionError("-2 is no weekday")


if __name__ == "__main__":
    test_daily_schedule_fires_once_a_day_at_its_time()
    test_daily_schedule_is_due_until_it_has_run_since_the_last_slot()
    test_daily_validates_and_describes()
    test_previous_occurrence_walks_back_to_the_right_weekday()
    test_same_day_but_later_belongs_to_the_previous_week()
    test_next_occurrence_is_a_week_after_the_previous()
    test_never_run_schedule_is_due()
    test_a_run_after_the_last_slot_clears_it()
    test_a_missed_week_is_caught_up_not_skipped()
    test_disabled_schedules_never_fire()
    test_describe_reads_back_in_german()
    test_validate_rejects_impossible_times()
    print("All schedules tests passed.")
