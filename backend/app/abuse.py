"""Abuse protection: per-IP hourly limits and a global daily stop.

The limits keep real visitor traffic under the free provider caps (spec: 5
Questions/hour/IP, ~40/day global stop) so a stranger cannot exhaust the day's
quota before a recruiter visits (ADR-0001). Counters are in-memory: the
backend runs a single free-tier worker, so process-local state suffices — a
restart resets the counters, which errs generous and never locks real
visitors out.
"""
from __future__ import annotations

import threading
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
        # The endpoint runs in FastAPI's threadpool, so the check-and-count
        # step is guarded — concurrent requests cannot all slip through.
        self._lock = threading.Lock()
        self._hits_by_ip: dict[str, deque[datetime]] = defaultdict(deque)
        self._day: date | None = None
        self._asked_today = 0

    def reserve(self, ip: str) -> Rejection | None:
        """Check this Question against both limits and, when allowed, count it.

        One lock-protected step — check and record together — so concurrent
        requests from one IP cannot all pass a check-then-record gap. Returns
        the rejection reason, or None once the slot is reserved. A rejected
        Question consumes nothing: it never reached a provider, so spending
        the counters on it would shrink real visitors' headroom.
        """
        with self._lock:
            now = self._now()
            self._roll_day(now)
            if self._asked_today >= self._daily_limit:
                return "daily_limit"

            cutoff = now - timedelta(hours=1)
            self._prune_stale_ips(cutoff)
            hits = self._hits_by_ip[ip]
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= self._per_ip_per_hour:
                return "rate_limit"
            self._asked_today += 1
            hits.append(now)
            return None

    def _roll_day(self, now: datetime) -> None:
        """A new UTC day starts with a fresh global counter."""
        if now.date() != self._day:
            self._day = now.date()
            self._asked_today = 0

    def _prune_stale_ips(self, cutoff: datetime) -> None:
        """Drop IPs whose newest hit is outside the hourly window, so the map
        stays bounded to the visitors of the last hour — not one entry per IP
        the process has ever seen."""
        stale = [
            ip
            for ip, hits in self._hits_by_ip.items()
            if not hits or hits[-1] <= cutoff
        ]
        for ip in stale:
            del self._hits_by_ip[ip]