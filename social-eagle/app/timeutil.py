"""UTC storage, Asia/Kolkata presentation, and a controllable clock for tests."""
from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import overload

from app.config import REPORT_TZ


def to_utc_naive(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(UTC).replace(tzinfo=None)


def parse_ts(value: str | datetime | None) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return to_utc_naive(value)
    s = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        raise ValueError(f"timestamp without timezone is ambiguous: {value!r}")
    return to_utc_naive(dt)


def local_day_bounds_utc(day: date) -> tuple[datetime, datetime]:
    """[start, end) of an Asia/Kolkata calendar day, expressed as naive UTC."""
    start = datetime.combine(day, time(0, 0), tzinfo=REPORT_TZ)
    end = start + timedelta(days=1)
    return to_utc_naive(start), to_utc_naive(end)


def local_range_bounds_utc(first: date, last: date) -> tuple[datetime, datetime]:
    return local_day_bounds_utc(first)[0], local_day_bounds_utc(last)[1]


def as_local(dt: datetime) -> datetime:
    return dt.replace(tzinfo=UTC).astimezone(REPORT_TZ)


def utc_to_local(dt: datetime | None) -> datetime | None:
    return None if dt is None else as_local(dt)


def local_date_of(dt: datetime) -> date:
    return dt.replace(tzinfo=UTC).astimezone(REPORT_TZ).date()


def fmt_local(dt: datetime | None) -> str:
    if dt is None:
        return "unknown"
    return as_local(dt).strftime("%Y-%m-%d %H:%M IST")


@overload
def iso(dt: datetime) -> str: ...
@overload
def iso(dt: None) -> None: ...
@overload
def iso(dt: datetime | None) -> str | None: ...


def iso(dt: datetime | None) -> str | None:
    return None if dt is None else dt.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")


def working_hours_between(start: datetime, end: datetime, start_hour: int, end_hour: int) -> float:
    """Hours between two UTC instants that fall inside Mon–Sat local working hours."""
    if end <= start:
        return 0.0
    total = 0.0
    cur = as_local(start)
    stop = as_local(end)
    while cur < stop:
        day_open = cur.replace(hour=start_hour, minute=0, second=0, microsecond=0)
        day_close = cur.replace(hour=end_hour, minute=0, second=0, microsecond=0)
        if cur.weekday() < 6:
            seg_start = max(cur, day_open)
            seg_end = min(stop, day_close)
            if seg_end > seg_start:
                total += (seg_end - seg_start).total_seconds() / 3600
        cur = (cur + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return total


class Clock:
    def now(self) -> datetime:
        return datetime.now(UTC).replace(tzinfo=None)


class FrozenClock(Clock):
    def __init__(self, at: datetime):
        self.at = to_utc_naive(at)

    def now(self) -> datetime:
        return self.at

    def advance(self, **kw) -> None:
        self.at += timedelta(**kw)


def sql_ts(dt: datetime) -> str:
    """Bind format matching SQLAlchemy's SQLite DateTime storage, for raw SQL comparisons."""
    return to_utc_naive(dt).strftime("%Y-%m-%d %H:%M:%S.%f")
