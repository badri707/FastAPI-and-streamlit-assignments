"""UTC storage / Asia-Kolkata display helpers. All DB timestamps are naive UTC."""
from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def to_naive_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(UTC).replace(tzinfo=None)


def parse_ts(value: str) -> datetime:
    """Parse ISO-8601; naive input is treated as UTC."""
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return to_naive_utc(dt)


def iso(dt: datetime | None) -> str | None:
    return None if dt is None else dt.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")


def local_date(dt_utc: datetime, tz: ZoneInfo = IST) -> date:
    return dt_utc.replace(tzinfo=UTC).astimezone(tz).date()


def local_day_bounds_utc(d: date, tz: ZoneInfo = IST) -> tuple[datetime, datetime]:
    """Half-open [start, end) UTC range for a local calendar day."""
    start = datetime.combine(d, time.min, tzinfo=tz).astimezone(UTC).replace(tzinfo=None)
    end = datetime.combine(d + timedelta(days=1), time.min, tzinfo=tz).astimezone(UTC).replace(tzinfo=None)
    return start, end


def local_range_utc(start: date, end_inclusive: date, tz: ZoneInfo = IST) -> tuple[datetime, datetime]:
    s, _ = local_day_bounds_utc(start, tz)
    _, e = local_day_bounds_utc(end_inclusive, tz)
    return s, e


def fmt_local(dt_utc: datetime | None, tz: ZoneInfo = IST) -> str | None:
    if dt_utc is None:
        return None
    return dt_utc.replace(tzinfo=UTC).astimezone(tz).strftime("%Y-%m-%d %H:%M IST")
