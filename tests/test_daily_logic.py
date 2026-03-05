from gethes.daily_logic import is_consecutive_day, next_daily_streak, normalize_date_key


def test_normalize_date_key_valid() -> None:
    assert normalize_date_key("20260305") == 20260305


def test_normalize_date_key_invalid() -> None:
    assert normalize_date_key("2026-03-05") == 0
    assert normalize_date_key("invalid") == 0


def test_is_consecutive_day_handles_boundaries() -> None:
    assert is_consecutive_day(20260228, 20260301) is True
    assert is_consecutive_day(20251231, 20260101) is True
    assert is_consecutive_day(20260301, 20260303) is False


def test_next_daily_streak_progression() -> None:
    assert next_daily_streak(0, 20260305, 0) == 1
    assert next_daily_streak(20260305, 20260305, 1) == 1
    assert next_daily_streak(20260305, 20260306, 1) == 2
    assert next_daily_streak(20260305, 20260310, 4) == 1
