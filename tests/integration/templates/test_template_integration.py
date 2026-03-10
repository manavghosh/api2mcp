"""Integration tests for F7.1 — template install/update cycle and registry search."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

from api2mcp.templates.installer import InstalledTemplate, TemplateInstaller
from api2mcp.templates.manifest import TemplateManifest
from api2mcp.templates.registry import TemplateRegistry

# ---------------------------------------------------------------------------
# Shared fixture data
# ---------------------------------------------------------------------------

_REGISTRY_INDEX = {
    "templates": [
        {
            "id": "github-issues",
            "name": "GitHub Issues MCP Server",
            "description": "MCP server for the GitHub Issues API",
            "author": "api2mcp",
            "version": "1.1.0",
            "tags": ["github", "issues", "rest"],
            "repository": "https://github.com/api2mcp/template-github-issues",
            "rating": 4.5,
            "downloads": 1200,
        },
        {
            "id": "stripe-payments",
            "name": "Stripe Payments MCP Server",
            "description": "MCP server for the Stripe API",
            "author": "api2mcp",
            "version": "2.0.0",
            "tags": ["stripe", "payments", "rest"],
            "repository": "https://github.com/api2mcp/template-stripe",
            "rating": 4.8,
            "downloads": 3400,
        },
    ]
}

_GITHUB_FULL_MANIFEST = {
    "id": "github-issues",
    "name": "GitHub Issues MCP Server",
    "description": "MCP server for the GitHub Issues API",
    "author": "api2mcp",
    "version": "1.1.0",
    "tags": ["github", "issues"],
    "spec_file": "openapi.yaml",
    "repository": "https://github.com/api2mcp/template-github-issues",
    "versions": [
        {"tag": "v1.1.0", "description": "Add label filtering", "released": "2025-03-10"},
        {"tag": "v1.0.0", "description": "Initial release", "released": "2025-01-15"},
    ],
    "rating": 4.5,
    "downloads": 1200,
}


def _build_registry(tmp_path: Path) -> TemplateRegistry:
    """Build a TemplateRegistry backed by a mock HTTP client."""
    index_response = MagicMock()
    index_response.text = yaml.dump(_REGISTRY_INDEX)
    index_response.raise_for_status = MagicMock()

    manifest_response = MagicMock()
    manifest_response.text = yaml.dump(_GITHUB_FULL_MANIFEST)
    manifest_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get.side_effect = [index_response, manifest_response]

    return TemplateRegistry(
        index_url="https://example.com/registry.yaml",
        cache_dir=tmp_path / "cache",
        http_client=mock_client,
    )


def _build_installer(registry: TemplateRegistry, git_dest_files: dict | None = None) -> TemplateInstaller:
    files = git_dest_files or {
        "openapi.yaml": "openapi: '3.0.3'\ninfo:\n  title: GitHub Issues\n  version: 1.0\npaths: {}\n",
        "README.md": "# GitHub Issues MCP Server\n",
    }

    def fake_git(args: list[str]) -> None:
        dest = Path(args[-1])
        dest.mkdir(parents=True, exist_ok=True)
        for name, content in files.items():
            (dest / name).write_text(content, encoding="utf-8")

    return TemplateInstaller(registry=registry, git_runner=fake_git)


# ---------------------------------------------------------------------------
# Integration: registry search
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_registry_search_finds_template(tmp_path: Path) -> None:
    registry = _build_registry(tmp_path)
    await registry.refresh(force=True)
    results = registry.search("github")
    assert len(results) == 1
    assert results[0].id == "github-issues"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_registry_search_all_templates(tmp_path: Path) -> None:
    registry = _build_registry(tmp_path)
    await registry.refresh(force=True)
    all_templates = registry.search("")
    assert len(all_templates) == 2


@pytest.mark.integration
@pytest.mark.asyncio
async def test_registry_search_by_tag(tmp_path: Path) -> None:
    registry = _build_registry(tmp_path)
    await registry.refresh(force=True)
    results = registry.search("stripe")
    assert len(results) == 1
    assert results[0].id == "stripe-payments"


# ---------------------------------------------------------------------------
# Integration: full install cycle
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_full_install_cycle(tmp_path: Path) -> None:
    """Full flow: refresh registry → fetch manifest → install → verify."""
    registry = _build_registry(tmp_path)
    await registry.refresh(force=True)

    installer = _build_installer(registry)
    dest = tmp_path / "github-issues"
    installed = await installer.install("github-issues", dest=dest)

    # Installed template should have correct metadata
    assert isinstance(installed, InstalledTemplate)
    assert installed.manifest.id == "github-issues"
    assert installed.version == "v1.1.0"  # latest

    # Files should exist
    assert (dest / "openapi.yaml").is_file()
    assert (dest / "installed.yaml").is_file()

    # Receipt should be correct
    receipt = TemplateInstaller.read_receipt(dest)
    assert receipt is not None
    assert receipt["id"] == "github-issues"
    assert receipt["version"] == "v1.1.0"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_install_specific_version(tmp_path: Path) -> None:
    registry = _build_registry(tmp_path)
    await registry.refresh(force=True)

    installer = _build_installer(registry)
    dest = tmp_path / "server"
    installed = await installer.install("github-issues", dest=dest, version="v1.0.0")
    assert installed.version == "v1.0.0"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_install_then_update(tmp_path: Path) -> None:
    """Install v1.0.0, then update to latest."""
    # First install
    registry = _build_registry(tmp_path)
    await registry.refresh(force=True)
    installer = _build_installer(registry)
    dest = tmp_path / "server"
    installed_v1 = await installer.install("github-issues", dest=dest, version="v1.0.0")
    assert installed_v1.version == "v1.0.0"

    # Rebuild registry (new mock to serve index + manifest again)
    registry2 = _build_registry(tmp_path)
    await registry2.refresh(force=True)
    installer2 = _build_installer(registry2)

    # Update to latest
    installed_v2 = await installer2.update("github-issues", dest=dest)
    assert installed_v2.version == "v1.1.0"
    assert (dest / "openapi.yaml").is_file()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_install_missing_template_raises(tmp_path: Path) -> None:
    registry = _build_registry(tmp_path)
    await registry.refresh(force=True)

    # Re-use same mock but fetch_manifest will raise KeyError
    installer = _build_installer(registry)
    with pytest.raises(KeyError, match="no-such-template"):
        await installer.install("no-such-template", dest=tmp_path / "s")


# ---------------------------------------------------------------------------
# Integration: manifest version resolution
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_version_resolution_latest() -> None:
    m = TemplateManifest.from_dict(_GITHUB_FULL_MANIFEST)
    assert m.resolve_version(None) == "v1.1.0"
    assert m.resolve_version("latest") == "v1.1.0"


@pytest.mark.integration
def test_version_resolution_pinned() -> None:
    m = TemplateManifest.from_dict(_GITHUB_FULL_MANIFEST)
    assert m.resolve_version("v1.0.0") == "v1.0.0"


@pytest.mark.integration
def test_version_resolution_unknown_raises() -> None:
    m = TemplateManifest.from_dict(_GITHUB_FULL_MANIFEST)
    with pytest.raises(ValueError):
        m.resolve_version("v99.0.0")
