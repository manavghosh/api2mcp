"""Unit tests for F7.1 TemplateInstaller."""

from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from api2mcp.templates.installer import InstalledTemplate, TemplateInstaller
from api2mcp.templates.manifest import TemplateManifest, VersionEntry
from api2mcp.templates.registry import TemplateRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_manifest(
    template_id: str = "my-template",
    version: str = "1.0.0",
    versions: list[dict] | None = None,
    repository: str = "https://github.com/api2mcp/t1",
) -> TemplateManifest:
    versions = versions or [{"tag": "v1.0.0", "description": "Init"}]
    return TemplateManifest.from_dict({
        "id": template_id,
        "name": "My Template",
        "version": version,
        "repository": repository,
        "versions": versions,
        "spec_file": "openapi.yaml",
    })


def _make_installer(
    manifest: TemplateManifest | None = None,
    *,
    git_files: dict[str, str] | None = None,
) -> TemplateInstaller:
    """Build an installer with a mocked registry and git runner."""
    m = manifest or _make_manifest()

    mock_registry = AsyncMock(spec=TemplateRegistry)
    mock_registry.fetch_manifest.return_value = m

    def fake_git_runner(args: list[str]) -> None:
        # Simulate git clone by writing fake files into the dest dir
        dest = Path(args[-1])  # last arg is dest path
        dest.mkdir(parents=True, exist_ok=True)
        files = git_files or {"openapi.yaml": "openapi: '3.0.3'\ninfo:\n  title: Test\n  version: 1.0\npaths: {}\n"}
        for name, content in files.items():
            (dest / name).write_text(content, encoding="utf-8")

    return TemplateInstaller(registry=mock_registry, git_runner=fake_git_runner)


# ---------------------------------------------------------------------------
# InstalledTemplate
# ---------------------------------------------------------------------------


def test_installed_template_repr(tmp_path: Path) -> None:
    m = _make_manifest()
    installed = InstalledTemplate(manifest=m, version="v1.0.0", dest=tmp_path)
    r = repr(installed)
    assert "my-template" in r
    assert "v1.0.0" in r


# ---------------------------------------------------------------------------
# TemplateInstaller.install
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_install_creates_dest_dir(tmp_path: Path) -> None:
    installer = _make_installer()
    dest = tmp_path / "my-server"
    installed = await installer.install("my-template", dest=dest)
    assert dest.is_dir()


@pytest.mark.asyncio
async def test_install_copies_spec_file(tmp_path: Path) -> None:
    installer = _make_installer()
    dest = tmp_path / "my-server"
    await installer.install("my-template", dest=dest)
    assert (dest / "openapi.yaml").is_file()


@pytest.mark.asyncio
async def test_install_writes_receipt(tmp_path: Path) -> None:
    installer = _make_installer()
    dest = tmp_path / "my-server"
    await installer.install("my-template", dest=dest)
    assert (dest / "installed.yaml").is_file()


@pytest.mark.asyncio
async def test_install_receipt_contents(tmp_path: Path) -> None:
    installer = _make_installer()
    dest = tmp_path / "server"
    await installer.install("my-template", dest=dest)
    receipt = TemplateInstaller.read_receipt(dest)
    assert receipt is not None
    assert receipt["id"] == "my-template"
    assert receipt["version"] == "v1.0.0"


@pytest.mark.asyncio
async def test_install_returns_installed_template(tmp_path: Path) -> None:
    installer = _make_installer()
    installed = await installer.install("my-template", dest=tmp_path / "s")
    assert isinstance(installed, InstalledTemplate)
    assert installed.manifest.id == "my-template"


@pytest.mark.asyncio
async def test_install_resolves_version(tmp_path: Path) -> None:
    m = _make_manifest(versions=[
        {"tag": "v2.0.0", "description": "v2"},
        {"tag": "v1.0.0", "description": "v1"},
    ])
    installer = _make_installer(manifest=m)
    installed = await installer.install("my-template", dest=tmp_path / "s", version="v1.0.0")
    assert installed.version == "v1.0.0"


@pytest.mark.asyncio
async def test_install_latest_version_default(tmp_path: Path) -> None:
    m = _make_manifest(versions=[
        {"tag": "v2.0.0", "description": "newest"},
        {"tag": "v1.0.0", "description": "old"},
    ])
    installer = _make_installer(manifest=m)
    installed = await installer.install("my-template", dest=tmp_path / "s")
    assert installed.version == "v2.0.0"


@pytest.mark.asyncio
async def test_install_unknown_version_raises(tmp_path: Path) -> None:
    installer = _make_installer()
    with pytest.raises(ValueError, match="v99.0.0"):
        await installer.install("my-template", dest=tmp_path / "s", version="v99.0.0")


@pytest.mark.asyncio
async def test_install_git_failure_raises(tmp_path: Path) -> None:
    def bad_git(args: list[str]) -> None:
        raise RuntimeError("git failed")

    mock_registry = AsyncMock(spec=TemplateRegistry)
    mock_registry.fetch_manifest.return_value = _make_manifest()
    installer = TemplateInstaller(registry=mock_registry, git_runner=bad_git)

    with pytest.raises(RuntimeError, match="git failed"):
        await installer.install("my-template", dest=tmp_path / "s")


# ---------------------------------------------------------------------------
# TemplateInstaller.update
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_replaces_existing(tmp_path: Path) -> None:
    dest = tmp_path / "server"
    dest.mkdir()
    (dest / "old_file.txt").write_text("old")

    installer = _make_installer()
    await installer.update("my-template", dest=dest)
    # old_file should be gone (rmtree + fresh install)
    assert not (dest / "old_file.txt").exists()
    assert (dest / "openapi.yaml").is_file()


# ---------------------------------------------------------------------------
# TemplateInstaller.read_receipt
# ---------------------------------------------------------------------------


def test_read_receipt_returns_none_for_missing_dir(tmp_path: Path) -> None:
    assert TemplateInstaller.read_receipt(tmp_path / "nonexistent") is None


def test_read_receipt_returns_dict(tmp_path: Path) -> None:
    receipt = {"id": "t1", "version": "v1.0.0", "repository": ""}
    (tmp_path / "installed.yaml").write_text(yaml.dump(receipt), encoding="utf-8")
    result = TemplateInstaller.read_receipt(tmp_path)
    assert result == receipt
