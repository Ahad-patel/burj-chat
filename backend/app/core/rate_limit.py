"""Sliding-window rate limiting, per IP and per conversation.

**Why this is ~70 lines instead of `slowapi`.** The requirement is two limits
on different keys with different windows, applied to one route. slowapi is
built around one decorator per limit with a single `key_func`, so expressing
that means two decorators, two key functions, and a dependency whose failure
mode is a library-shaped `RateLimitExceeded` we would translate anyway. The
dependency was dropped rather than carried unused — every package in the lock
file is CVE surface that `pip-audit` has to keep clearing.

**What this actually protects.** Not availability — a construction company's
website is not under load. It protects *spend*. Each request injects the whole
knowledge base as input tokens, so an unbounded endpoint is a way for a
stranger to run up the client's LLM bill from a laptop.

**Concurrency.** `check` is synchronous and contains no `await`, so it runs to
completion without the event loop interleaving another request. That is why
there is no lock here, unlike `ConversationStore` whose methods do await.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from time import monotonic
from typing import Final

#: Ceiling on tracked keys. Without it, a stream of unique IPs would grow this
#: map without bound — the rate limiter itself becoming the memory exhaustion
#: it exists to prevent.
_MAX_TRACKED_KEYS: Final = 10_000


@dataclass(frozen=True, slots=True)
class RateLimitVerdict:
    """Whether a request may proceed, and when to try again if not."""

    allowed: bool
    retry_after_seconds: int = 0

    def __bool__(self) -> bool:
        return self.allowed


@dataclass(slots=True)
class SlidingWindowLimiter:
    """Allows `limit` events per `window_seconds`, per key.

    A sliding window rather than a fixed one: fixed windows let a caller send
    `limit` requests at 11:59:59 and `limit` more at 12:00:00, doubling the
    intended rate at every boundary.
    """

    limit: int
    window_seconds: float
    _hits: dict[str, deque[float]] = field(default_factory=dict, init=False)

    def check(self, key: str) -> RateLimitVerdict:
        """Record an attempt and report whether it is allowed."""
        now = monotonic()
        window = self._hits.setdefault(key, deque())

        cutoff = now - self.window_seconds
        while window and window[0] <= cutoff:
            window.popleft()

        if len(window) >= self.limit:
            # Retry when the oldest hit falls out of the window. Rounded up so
            # a client that obeys Retry-After exactly is not rejected again.
            retry_after = max(1, int(window[0] + self.window_seconds - now) + 1)
            return RateLimitVerdict(allowed=False, retry_after_seconds=retry_after)

        window.append(now)
        self._prune(now)
        return RateLimitVerdict(allowed=True)

    def reset(self, key: str | None = None) -> None:
        """Clear one key, or all of them. Used by tests."""
        if key is None:
            self._hits.clear()
        else:
            self._hits.pop(key, None)

    @property
    def tracked_keys(self) -> int:
        return len(self._hits)

    def _prune(self, now: float) -> None:
        """Drop keys whose windows have fully expired.

        Only runs when the map is at its ceiling — pruning on every request
        would make each call O(keys) for no benefit.
        """
        if len(self._hits) < _MAX_TRACKED_KEYS:
            return

        cutoff = now - self.window_seconds
        stale = [key for key, hits in self._hits.items() if not hits or hits[-1] <= cutoff]
        for key in stale:
            del self._hits[key]

        # Every key is still live and we are at the ceiling: shed the oldest
        # rather than grow without bound. Shedding under-counts a few callers;
        # growing without bound takes the service down.
        if len(self._hits) >= _MAX_TRACKED_KEYS:
            oldest = sorted(self._hits, key=lambda k: self._hits[k][0])[: _MAX_TRACKED_KEYS // 10]
            for key in oldest:
                del self._hits[key]
