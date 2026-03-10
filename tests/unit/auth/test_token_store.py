"""Unit tests for TokenStore and TokenEntry."""

from __future__ import annotations

import time

import pytest

from api2mcp.auth.token_store import TokenEntry, TokenStore

# ---------------------------------------------------------------------------
# TokenEntry
# ---------------------------------------------------------------------------


def test_token_entry_not_expired_when_no_expiry() -> None:
    entry = TokenEntry(access_token="tok")
    assert not entry.is_expired


def test_token_entry_not_expired_before_buffer() -> None:
    entry = TokenEntry(access_token="tok", expires_at=time.time() + 120)
    assert not entry.is_expired


def test_token_entry_expired_within_buffer() -> None:
    # expires_at within the 30-second buffer → considered expired
    entry = TokenEntry(access_token="tok", expires_at=time.time() + 10)
    assert entry.is_expired


def test_token_entry_expired_in_past() -> None:
    entry = TokenEntry(access_token="tok", expires_at=time.time() - 60)
    assert entry.is_expired


def test_from_oauth_response_basic() -> None:
    data = {"access_token": "abc", "token_type": "Bearer", "expires_in": 3600}
    entry = TokenEntry.from_oauth_response(data)
    assert entry.access_token == "abc"
    assert entry.token_type == "Bearer"
    assert entry.expires_at is not None
    assert entry.expires_at > time.time()


def test_from_oauth_response_with_refresh_token() -> None:
    data = {
        "access_token": "abc",
        "token_type": "Bearer",
        "expires_in": 3600,
        "refresh_token": "rfsh",
        "scope": "read write",
    }
    entry = TokenEntry.from_oauth_response(data)
    assert entry.refresh_token == "rfsh"
    assert entry.scope == "read write"


def test_from_oauth_response_no_expiry() -> None:
    data = {"access_token": "abc"}
    entry = TokenEntry.from_oauth_response(data)
    assert entry.expires_at is None
    assert not entry.is_expired


# ---------------------------------------------------------------------------
# TokenStore
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_store_set_and_get() -> None:
    store = TokenStore()
    entry = TokenEntry(access_token="tok123")
    await store.set("myapi", entry)
    result = await store.get("myapi")
    assert result is not None
    assert result.access_token == "tok123"


@pytest.mark.asyncio
async def test_store_get_missing_returns_none() -> None:
    store = TokenStore()
    result = await store.get("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_store_delete() -> None:
    store = TokenStore()
    await store.set("myapi", TokenEntry(access_token="tok"))
    await store.delete("myapi")
    assert await store.get("myapi") is None


@pytest.mark.asyncio
async def test_store_delete_nonexistent_noop() -> None:
    store = TokenStore()
    await store.delete("nonexistent")  # should not raise


@pytest.mark.asyncio
async def test_store_clear() -> None:
    store = TokenStore()
    await store.set("a", TokenEntry(access_token="t1"))
    await store.set("b", TokenEntry(access_token="t2"))
    await store.clear()
    assert await store.get("a") is None
    assert await store.get("b") is None


@pytest.mark.asyncio
async def test_store_overwrite() -> None:
    store = TokenStore()
    await store.set("k", TokenEntry(access_token="old"))
    await store.set("k", TokenEntry(access_token="new"))
    result = await store.get("k")
    assert result is not None
    assert result.access_token == "new"


@pytest.mark.asyncio
async def test_store_concurrent_access() -> None:
    """Multiple coroutines can access the store concurrently without corruption."""
    import asyncio

    store = TokenStore()
    keys = [f"key{i}" for i in range(20)]

    async def write(k: str) -> None:
        await store.set(k, TokenEntry(access_token=f"tok_{k}"))

    async def read(k: str) -> str | None:
        entry = await store.get(k)
        return entry.access_token if entry else None

    await asyncio.gather(*[write(k) for k in keys])
    results = await asyncio.gather(*[read(k) for k in keys])
    for k, val in zip(keys, results, strict=False):
        assert val == f"tok_{k}"
