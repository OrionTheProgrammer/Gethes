from __future__ import annotations

from datetime import datetime, timedelta


_DATE_FMT = "%Y%m%d"


def normalize_date_key(date_key: str) -> int:
    token = date_key.strip()
    try:
        parsed = datetime.strptime(token, _DATE_FMT).date()
    except ValueError:
        return 0
    return int(parsed.strftime(_DATE_FMT))


def is_consecutive_day(previous_date_key: int, current_date_key: int) -> bool:
    try:
        prev = datetime.strptime(str(int(previous_date_key)), _DATE_FMT).date()
        cur = datetime.strptime(str(int(current_date_key)), _DATE_FMT).date()
    except (ValueError, TypeError):
        return False
    return (cur - prev) == timedelta(days=1)


def next_daily_streak(previous_date_key: int, current_date_key: int, current_streak: int) -> int:
    if current_date_key <= 0:
        return max(0, int(current_streak))

    normalized_current = int(current_date_key)
    normalized_previous = int(previous_date_key) if previous_date_key > 0 else 0
    streak_now = max(0, int(current_streak))

    if normalized_previous == normalized_current:
        return max(1, streak_now)
    if normalized_previous > 0 and is_consecutive_day(normalized_previous, normalized_current):
        return max(1, streak_now) + 1
    return 1
