"""Weekly schedules for automatic playlist refreshes.

The launchd agents on the host cannot be managed from inside the container
(no launchctl, no access to ~/Library/LaunchAgents), so the schedule lives
here instead, next to the recipes it triggers.

Times are local: the container gets TZ from docker-compose, so "Monday 06:17"
in the UI means the same thing as on the host.
"""

from datetime import datetime, timedelta

# Python's Monday=0; the UI and launchd both count Sunday=0, so convert at
# the edges rather than carrying two conventions through the code.
WEEKDAYS = ["Sonntag", "Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag"]


def _as_ui_weekday(moment: datetime) -> int:
    return (moment.weekday() + 1) % 7


def previous_occurrence(weekday: int, hour: int, minute: int, now: datetime) -> datetime:
    """The most recent moment this schedule should have fired, at or before now."""
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    days_back = (_as_ui_weekday(candidate) - weekday) % 7
    candidate -= timedelta(days=days_back)
    if candidate > now:
        candidate -= timedelta(days=7)
    return candidate


def next_occurrence(weekday: int, hour: int, minute: int, now: datetime) -> datetime:
    return previous_occurrence(weekday, hour, minute, now) + timedelta(days=7)


def is_due(schedule: dict, now: datetime) -> bool:
    """Whether this schedule still owes a run.

    Compares against the last occurrence rather than an exact timestamp, so a
    run missed while the container was down is caught up on the next check
    instead of being skipped until the following week.
    """
    if not schedule.get("enabled"):
        return False
    due_at = previous_occurrence(schedule["weekday"], schedule["hour"], schedule["minute"], now)
    last_run = schedule.get("last_run")
    return last_run is None or datetime.fromtimestamp(last_run) < due_at


def describe(schedule: dict) -> str:
    return f"{WEEKDAYS[schedule['weekday']]} {schedule['hour']:02d}:{schedule['minute']:02d}"


def validate(weekday: int, hour: int, minute: int) -> None:
    """Raise ValueError on anything the scheduler could not act on."""
    if not 0 <= weekday <= 6:
        raise ValueError("weekday muss zwischen 0 (Sonntag) und 6 (Samstag) liegen")
    if not 0 <= hour <= 23:
        raise ValueError("hour muss zwischen 0 und 23 liegen")
    if not 0 <= minute <= 59:
        raise ValueError("minute muss zwischen 0 und 59 liegen")
