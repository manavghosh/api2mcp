"""Unit tests for the token bucket algorithm."""

from __future__ import annotations

import asyncio

import pytest

from api2mcp.ratelimit.bucket import TokenBucket


class TestTokenBucketInit:
    def test_defaults_to_full_bucket(self) -> None:
        bucket = TokenBucket(capacity=10, refill_rate=2)
        assert bucket.capacity == 10
        assert bucket.refill_rate == 2

    def test_custom_initial_tokens(self) -> None:
        bucket = TokenBucket(capacity=10, refill_rate=1, initial_tokens=0)
        # peek_tokens is async — run in event loop
        tokens = asyncio.run(bucket.peek_tokens())
        assert tokens == pytest.approx(0.0, abs=0.1)

    def test_rejects_zero_capacity(self) -> None:
        with pytest.raises(ValueError, match="capacity"):
            TokenBucket(capacity=0, refill_rate=1)

    def test_rejects_negative_refill_rate(self) -> None:
        with pytest.raises(ValueError, match="refill_rate"):
            TokenBucket(capacity=10, refill_rate=-1)


class TestTokenBucketConsume:
    @pytest.mark.asyncio
    async def test_consume_succeeds_when_tokens_available(self) -> None:
        bucket = TokenBucket(capacity=5, refill_rate=1)
        assert await bucket.consume() is True

    @pytest.mark.asyncio
    async def test_consume_reduces_tokens(self) -> None:
        bucket = TokenBucket(capacity=5, refill_rate=1)
        await bucket.consume()
        tokens = await bucket.peek_tokens()
        assert tokens == pytest.approx(4.0, abs=0.1)

    @pytest.mark.asyncio
    async def test_consume_fails_when_empty(self) -> None:
        bucket = TokenBucket(capacity=1, refill_rate=0.001, initial_tokens=0)
        assert await bucket.consume() is False

    @pytest.mark.asyncio
    async def test_burst_drains_bucket(self) -> None:
        bucket = TokenBucket(capacity=3, refill_rate=0.001)
        results = [await bucket.consume() for _ in range(4)]
        assert results[:3] == [True, True, True]
        assert results[3] is False

    @pytest.mark.asyncio
    async def test_tokens_refill_over_time(self) -> None:
        bucket = TokenBucket(capacity=2, refill_rate=10, initial_tokens=0)
        # After 0.1s at 10 tokens/s we should have ~1 token
        await asyncio.sleep(0.12)
        assert await bucket.consume() is True


class TestTokenBucketWaitTime:
    @pytest.mark.asyncio
    async def test_zero_wait_when_tokens_available(self) -> None:
        bucket = TokenBucket(capacity=5, refill_rate=1)
        assert await bucket.wait_time() == pytest.approx(0.0, abs=0.01)

    @pytest.mark.asyncio
    async def test_positive_wait_when_empty(self) -> None:
        bucket = TokenBucket(capacity=1, refill_rate=2, initial_tokens=0)
        wait = await bucket.wait_time()
        # 1 token / 2 tokens/s = 0.5s
        assert wait == pytest.approx(0.5, abs=0.05)


class TestTokenBucketDrain:
    def test_drain_reduces_tokens_synchronously(self) -> None:
        bucket = TokenBucket(capacity=10, refill_rate=1)
        bucket.drain(5)
        tokens = asyncio.run(bucket.peek_tokens())
        assert tokens == pytest.approx(5.0, abs=0.1)

    def test_drain_clamps_to_zero(self) -> None:
        bucket = TokenBucket(capacity=10, refill_rate=1)
        bucket.drain(100)
        tokens = asyncio.run(bucket.peek_tokens())
        assert tokens == pytest.approx(0.0, abs=0.01)


class TestTokenBucketConcurrency:
    @pytest.mark.asyncio
    async def test_concurrent_consumes_do_not_overshoot(self) -> None:
        capacity = 5
        bucket = TokenBucket(capacity=capacity, refill_rate=0.001)

        results = await asyncio.gather(*[bucket.consume() for _ in range(10)])
        successful = sum(1 for r in results if r)
        assert successful == capacity
