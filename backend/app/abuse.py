"""Abuse protection: per-IP hourly limits and a global daily stop.

The limits keep real visitor traffic under the free provider caps (spec: 5
Questions/hour/IP, ~40/day global stop) so a stranger cannot exhaust the day's
quota before a recruiter visits (ADR-0001). Counters are in-memory: the
backend runs a single free-tier worker, so process-local state suffices — a
restart resets the counters, which errs generous and never locks real
visitors out.
"""
from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from typing import Literal

# The two rejection reasons, kept distinct so responses say which limit bit.
Rejection = Literal["rate_limit", "daily_limit"]


class AbuseLimiter:
    """Sliding one-hour windows per IP plus a UTC-daily global counter."""

    def __init__(
        self,
        *,
        per_ip_per_hour: int,
        daily_limit: int,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._per_ip_per_hour = per_ip_per_hour
        self._daily_limit = daily_limit
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._hits_by_ip: dict[str, deque[datetime]] = defaultdict(deque)
        self._day: date | None = None
        self._asked_today = 0

    def check(self, ip: str) -> Rejection | None:
        """The rejection reason if this Question must not run, else None.

        The daily stop is checked first: when the global quota is spent, even a
        first-time visitor gets the honest "come back tomorrow" rather than a
        misleading per-IP message.
        """
        now = self._now()
        self._roll_day(now)
        if self._asked_today >= self._daily_limit:
            return "daily_limit"

        hits = self._hits_by_ip[ip]
        cutoff = now - timedelta(hours=1)
        while hits and hits[0] <= cutoff:
            hits.popleft()
        if len(hits) >= self._per_ip_per_hour:
            return "rate_limit"
        return None

    def record(self, ip: str) -> None:
        """Count one accepted Question against the IP's window and the daily stop.

        Called only for questions that passed ``check`` — a rejected ask never
        reached a provider, so it must not consume quota.
        """
        now = self._now()
        self._roll_day(now)
        self._asked_today += 1
        self._hits_by_ip[ip].append(now)

    def _roll_day(self, now: datetime) -> None:
        if now.date() != self._day:
            self._day = now.date()
            self._asked_today = 0