"""Unit tests for F7.1 TemplateRegistry and RegistryIndex."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

from api2mcp.templates.registry import RegistryIndex, TemplateRegistry, _build_raw_url

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_index_yaml(templates: list[dict] | None = None) -> str:
    entries = templates or [
        {"id": "github-issues", "name": "GitHub Issues", "repository": "https://github.com/api2mcp/t1", "version": "1.0.0"},
        {"id": "stripe-payments", "name": "Stripe Payments", "repository": "https://github.com/api2mcp/t2", "version": "2.0.0", "tags": ["stripe", "payments"]},
        {"id": "slack-bot", "name": "Slack Bot", "repository": "https://github.com/api2mcp/t3", "version": "1.0.0", "tags": ["slack"]},
    ]
    return yaml.dump({"templates": entries})


def _make_registry(index_yaml: str = "", *, cache_dir: Path | None = None) -> TemplateRegistry:
    """Build a TemplateRegistry with a mocked HTTP client."""
    mock_client = AsyncMock()
    mock_response = MagicMock()
    mock_response.text = index_yaml or _make_index_yaml()
    mock_response.raise_for_status = MagicMock()
    mock_client.get.return_value = mock_response
    return TemplateRegistry(
        index_url="https://example.com/registry.yaml",
        cache_dir=cache_dir,
        http_client=mock_client,
    )


# ---------------------------------------------------------------------------
# RegistryIndex
# ---------------------------------------------------------------------------


def test_registry_index_from_yaml() -> None:
    idx = RegistryIndex.from_yaml(_make_index_yaml())
    assert len(idx.templates) == 3
    assert idx.templates[0].id == "github-issues"


def test_registry_index_invalid_yaml_raises() -> None:
    with pytest.raises(ValueError, match="Invalid registry index"):
        RegistryIndex.from_yaml("not: valid: yaml: [unclosed")


def test_registry_index_missing_templates_key_raises() -> None:
    with pytest.raises(ValueError, match="'templates' list"):
        RegistryIndex.from_yaml(yaml.dump({"other": []}))


def test_registry_index_is_stale_fresh() -> None:
    idx = RegistryIndex(templates=[], fetched_at=time.time())
    assert not idx.is_stale(ttl=3600)


def test_registry_index_is_stale_old() -> None:
    idx = RegistryIndex(templates=[], fetched_at=time.time() - 7200)
    assert idx.is_stale(ttl=3600)


# ---------------------------------------------------------------------------
# TemplateRegistry.refresh
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_registry_refresh_loads_templates(tmp_path: Path) -> None:
    registry = _make_registry(cache_dir=tmp_path)
    index = await registry.refresh(force=True)
    assert len(index.templates) == 3


@pytest.mark.asyncio
async def test_registry_refresh_writes_cache(tmp_path: Path) -> None:
    registry = _make_registry(cache_dir=tmp_path)
    await registry.refresh(force=True)
    assert (tmp_path / "registry.yaml").is_file()


@pytest.mark.asyncio
async def test_registry_refresh_uses_cache_when_fresh(tmp_path: Path) -> None:
    # Write a cache file with one template
    single = yaml.dump({"templates": [{"id": "cached-one", "name": "Cached One", "repository": ""}]})
    (tmp_path / "registry.yaml").write_text(single, encoding="utf-8")
    # Set mtime to now (fresh)
    registry = _make_registry(cache_dir=tmp_path)
    index = await registry.refresh(force=False)
    # Should get the cached version, not the mock's 3-template list
    assert len(index.templates) == 1
    assert index.templates[0].id == "cached-one"


# ---------------------------------------------------------------------------
# TemplateRegistry.search
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_registry_search_empty_returns_all(tmp_path: Path) -> None:
    registry = _make_registry(cache_dir=tmp_path)
    await registry.refresh(force=True)
    results = registry.search("")
    assert len(results) == 3


@pytest.mark.asyncio
async def test_registry_search_by_id(tmp_path: Path) -> None:
    registry = _make_registry(cache_dir=tmp_path)
    await registry.refresh(force=True)
    results = registry.search("github")
    assert len(results) == 1
    assert results[0].id == "github-issues"


@pytest.mark.asyncio
async def test_registry_search_by_tag(tmp_path: Path) -> None:
    registry = _make_registry(cache_dir=tmp_path)
    await registry.refresh(force=True)
    results = registry.search("slack")
    assert len(results) == 1
    assert results[0].id == "slack-bot"


@pytest.mark.asyncio
async def test_registry_search_no_match_returns_empty(tmp_path: Path) -> None:
    registry = _make_registry(cache_dir=tmp_path)
    await registry.refresh(force=True)
    results = registry.search("xyzzy-no-match")
    assert results == []


def test_registry_search_without_refresh_raises() -> None:
    registry = TemplateRegistry()
    with pytest.raises(RuntimeError, match="refresh"):
        registry.search("anything")


# ---------------------------------------------------------------------------
# TemplateRegistry.get
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_registry_get_existing(tmp_path: Path) -> None:
    registry = _make_registry(cache_dir=tmp_path)
    await registry.refresh(force=True)
    t = registry.get("slack-bot")
    assert t is not None
    assert t.name == "Slack Bot"


@pytest.mark.asyncio
async def test_registry_get_missing_returns_none(tmp_path: Path) -> None:
    registry = _make_registry(cache_dir=tmp_path)
    await registry.refresh(force=True)
    assert registry.get("nonexistent") is None


# ---------------------------------------------------------------------------
# TemplateRegistry.fetch_manifest
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_registry_fetch_manifest(tmp_path: Path) -> None:
    # First call returns the index; second call returns the full manifest
    full_manifest = yaml.dump({
        "id": "github-issues",
        "name": "GitHub Issues MCP Server",
        "version": "1.0.0",
        "versions": [{"tag": "v1.0.0", "description": "Init"}],
    })
    mock_client = AsyncMock()
    index_response = MagicMock()
    index_response.text = _make_index_yaml()
    index_response.raise_for_status = MagicMock()
    manifest_response = MagicMock()
    manifest_response.text = full_manifest
    manifest_response.raise_for_status = MagicMock()
    mock_client.get.side_effect = [index_response, manifest_response]

    registry = TemplateRegistry(
        index_url="https://example.com/registry.yaml",
        cache_dir=tmp_path,
        http_client=mock_client,
    )
    await registry.refresh(force=True)
    manifest = await registry.fetch_manifest("github-issues")
    assert manifest.id == "github-issues"
    assert len(manifest.versions) == 1


@pytest.mark.asyncio
async def test_registry_fetch_manifest_unknown_raises(tmp_path: Path) -> None:
    registry = _make_registry(cache_dir=tmp_path)
    await registry.refresh(force=True)
    with pytest.raises(KeyError, match="no-such-template"):
        await registry.fetch_manifest("no-such-template")


# ---------------------------------------------------------------------------
# _build_raw_url
# ---------------------------------------------------------------------------


def test_build_raw_url_github() -> None:
    url = _build_raw_url("https://github.com/api2mcp/template-github-issues")
    assert url == "https://raw.githubusercontent.com/api2mcp/template-github-issues/main/template.yaml"


def test_build_raw_url_github_trailing_slash() -> None:
    url = _build_raw_url("https://github.com/api2mcp/template-github-issues/")
    assert "raw.githubusercontent.com" in url


def test_build_raw_url_non_github_fallback() -> None:
    url = _build_raw_url("https://example.com/myrepo")
    assert url == "https://example.com/myrepo/template.yaml"
