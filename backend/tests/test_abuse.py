"""Abuse protection: per-IP hourly limits and the global daily stop.

The limiter is pure logic against an injected clock, so window expiry and the
UTC-day rollover are tested deterministically — no sleeps, no wall clock.
``reserve`` is the single atomic check-and-count step the /ask endpoint calls.
"""
from datetime import datetime, timedelta, timezone

from app.abuse import AbuseLimiter

T0 = datetime(2026, 9, 30, 12, 0, 0, tzinfo=timezone.utc)


class Clock:
    """A controllable ``now`` for the limiter's windows."""

    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)


def limiter(clock: Clock, *, per_ip: int = 5, daily: int = 40) -> AbuseLimiter:
    return AbuseLimiter(per_ip_per_hour=per_ip, daily_limit=daily, now=clock)


def test_allows_exactly_five_questions_per_ip_then_rejects() -> None:
    """Questions 1-5 reserve a slot; the 6th inside the hour is rejected."""
    clock = Clock()
    guard = limiter(clock)

    for _ in range(5):
        assert guard.reserve("1.2.3.4") is None

    assert guard.reserve("1.2.3.4") == "rate_limit"


def test_hourly_hits_age_out_after_an_hour() -> None:
    """An hour after the burst, the same IP may ask again."""
    clock = Clock()
    guard = limiter(clock)
    for _ in range(5):
        guard.reserve("1.2.3.4")

    clock.advance(minutes=61)

    assert guard.reserve("1.2.3.4") is None


def test_ips_are_limited_independently() -> None:
    """One visitor exhausting their window never blocks another."""
    clock = Clock()
    guard = limiter(clock)
    for _ in range(5):
        guard.reserve("1.2.3.4")

    assert guard.reserve("5.6.7.8") is None


def test_daily_stop_rejects_everyone_regardless_of_ip() -> None:
    """The global daily stop protects the provider's free cap (ADR-0001): once
    the day's questions are spent, even a first-time visitor gets rejected —
    and the reason is the daily stop, not a per-IP message."""
    clock = Clock()
    guard = limiter(clock, daily=3)
    for ip in ("1.2.3.4", "1.2.3.4", "5.6.7.8"):
        assert guard.reserve(ip) is None

    assert guard.reserve("9.9.9.9") == "daily_limit"
    assert guard.reserve("1.2.3.4") == "daily_limit"


def test_daily_counter_resets_at_utc_midnight() -> None:
    """A new UTC day starts with a fresh global counter."""
    clock = Clock()
    guard = limiter(clock, daily=1)
    assert guard.reserve("1.2.3.4") is None
    assert guard.reserve("1.2.3.4") == "daily_limit"

    clock.advance(days=1)

    assert guard.reserve("1.2.3.4") is None


def test_rejected_questions_do_not_consume_quota() -> None:
    """A rejected reserve records nothing: it never reached a provider, so
    spending the daily counter on it would shrink real visitors' headroom."""
    clock = Clock()
    guard = limiter(clock, per_ip=1, daily=3)

    assert guard.reserve("1.2.3.4") is None  # 1 of 3 today
    assert guard.reserve("1.2.3.4") == "rate_limit"  # rejected, not counted
    assert guard.reserve("5.6.7.8") is None  # 2 of 3 today
    assert guard.reserve("9.9.9.9") is None  # 3 of 3 today
    assert guard.reserve("8.8.8.8") == "daily_limit"


def test_stale_ips_are_pruned_so_the_map_stays_bounded() -> None:
    """A visitor who never returns must not leave an entry behind forever:
    once their newest hit leaves the hourly window, the entry is dropped."""
    clock = Clock()
    guard = limiter(clock)
    guard.reserve("1.2.3.4")

    clock.advance(minutes=61)
    guard.reserve("5.6.7.8")

    assert "1.2.3.4" not in guard._hits_by_ip  # internals: pruning is invisible
    assert "5.6.7.8" in guard._hits_by_ip