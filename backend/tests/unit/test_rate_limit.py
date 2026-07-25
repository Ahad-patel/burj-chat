"""The sliding-window rate limiter.

What it protects is *spend*, not availability: every request injects the whole
knowledge base as input tokens, so an unbounded endpoint is a way for a
stranger to run up the client's LLM bill.
"""

from __future__ import annotations

import time

import pytest

from app.core.rate_limit import SlidingWindowLimiter


class TestLimiting:
    def test_requests_under_the_limit_pass(self) -> None:
        limiter = SlidingWindowLimiter(limit=3, window_seconds=60)

        assert all(limiter.check("ip").allowed for _ in range(3))

    def test_the_limit_binds(self) -> None:
        limiter = SlidingWindowLimiter(limit=3, window_seconds=60)
        for _ in range(3):
            limiter.check("ip")

        assert not limiter.check("ip").allowed

    def test_keys_are_independent(self) -> None:
        """One noisy visitor must not lock everyone else out."""
        limiter = SlidingWindowLimiter(limit=1, window_seconds=60)
        limiter.check("visitor-a")

        assert limiter.check("visitor-b").allowed

    def test_the_verdict_is_truthy(self) -> None:
        limiter = SlidingWindowLimiter(limit=1, window_seconds=60)

        assert bool(limiter.check("ip"))
        assert not bool(limiter.check("ip"))


class TestSlidingBehaviour:
    def test_capacity_returns_as_the_window_slides(self) -> None:
        limiter = SlidingWindowLimiter(limit=2, window_seconds=0.25)
        limiter.check("ip")
        limiter.check("ip")
        assert not limiter.check("ip").allowed

        time.sleep(0.3)

        assert limiter.check("ip").allowed

    def test_it_slides_rather_than_resetting_on_a_boundary(self) -> None:
        """A fixed window lets a caller send `limit` requests at 11:59:59 and
        `limit` more at 12:00:00 — double the intended rate, every hour."""
        limiter = SlidingWindowLimiter(limit=2, window_seconds=0.4)

        limiter.check("ip")
        time.sleep(0.3)
        limiter.check("ip")

        # The first hit has not yet aged out, so capacity is still spent.
        assert not limiter.check("ip").allowed

        time.sleep(0.15)  # only the first hit expires

        assert limiter.check("ip").allowed
        assert not limiter.check("ip").allowed


class TestRetryAfter:
    def test_a_rejection_says_when_to_come_back(self) -> None:
        limiter = SlidingWindowLimiter(limit=1, window_seconds=60)
        limiter.check("ip")

        verdict = limiter.check("ip")

        assert not verdict.allowed
        assert 0 < verdict.retry_after_seconds <= 61

    def test_retry_after_is_never_zero(self) -> None:
        """A `Retry-After: 0` invites an immediate retry, which is rejected
        again — a hot loop for a well-behaved client."""
        limiter = SlidingWindowLimiter(limit=1, window_seconds=0.1)
        limiter.check("ip")

        assert limiter.check("ip").retry_after_seconds >= 1

    def test_waiting_the_advertised_time_actually_works(self) -> None:
        """Rounded up, so a client that obeys Retry-After exactly is not
        rejected a second time."""
        limiter = SlidingWindowLimiter(limit=1, window_seconds=0.3)
        limiter.check("ip")
        verdict = limiter.check("ip")

        time.sleep(min(verdict.retry_after_seconds, 1))

        assert limiter.check("ip").allowed


class TestMemoryBounds:
    def test_the_limiter_does_not_grow_without_bound(self) -> None:
        """Otherwise the rate limiter becomes the memory exhaustion it exists
        to prevent — a stream of unique IPs is trivial to generate."""
        limiter = SlidingWindowLimiter(limit=5, window_seconds=60)

        for index in range(12_000):
            limiter.check(f"ip-{index}")

        assert limiter.tracked_keys <= 10_000

    def test_pruning_does_not_break_active_limiting(self) -> None:
        limiter = SlidingWindowLimiter(limit=2, window_seconds=60)
        for index in range(11_000):
            limiter.check(f"ip-{index}")

        limiter.check("still-here")

        assert limiter.check("still-here").allowed
        assert not limiter.check("still-here").allowed


class TestReset:
    def test_resetting_one_key(self) -> None:
        limiter = SlidingWindowLimiter(limit=1, window_seconds=60)
        limiter.check("a")
        limiter.check("b")

        limiter.reset("a")

        assert limiter.check("a").allowed
        assert not limiter.check("b").allowed

    def test_resetting_everything(self) -> None:
        limiter = SlidingWindowLimiter(limit=1, window_seconds=60)
        limiter.check("a")

        limiter.reset()

        assert limiter.tracked_keys == 0


class TestClientIdentification:
    @pytest.mark.parametrize("trust", [True, False])
    def test_forwarded_headers_are_only_honoured_when_configured(self, trust: bool) -> None:
        """`X-Forwarded-For` is client-controlled.

        Trusting it without a proxy in front means an attacker sends a fresh
        value per request and the per-IP limit silently stops existing.
        """
        from starlette.datastructures import Headers
        from starlette.requests import Request

        from app.core.security import client_ip

        request = Request(
            {
                "type": "http",
                "headers": Headers({"x-forwarded-for": "1.2.3.4, 10.0.0.1"}).raw,
                "client": ("192.168.1.1", 1234),
            }
        )

        resolved = client_ip(request, trust_proxy_headers=trust)

        assert resolved == ("1.2.3.4" if trust else "192.168.1.1")

    def test_a_missing_client_does_not_crash(self) -> None:
        from starlette.requests import Request

        from app.core.security import client_ip

        request = Request({"type": "http", "headers": [], "client": None})

        assert client_ip(request, trust_proxy_headers=False) == "unknown"
