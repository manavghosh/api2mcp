# SPDX-License-Identifier: MIT
"""Template installer for F7.1.

Downloads a template from its git repository (or local cache) into a
target directory, replacing ``template.yaml`` with a resolved
``openapi.yaml`` spec ready for ``api2mcp generate``.

Usage::

    installer = TemplateInstaller()
    path = await installer.install("github-issues", dest=Path("./my-server"))
    path = await installer.install("github-issues", dest=Path("./my-server"),
                                   version="v1.0.0")
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any

from api2mcp.templates.manifest import TemplateManifest
from api2mcp.templates.registry import TemplateRegistry


# ---------------------------------------------------------------------------
# InstalledTemplate
# ---------------------------------------------------------------------------


class InstalledTemplate:
    """Record of a successfully installed template.

    Attributes:
        manifest:  The full :class:`TemplateManifest` that was installed.
        version:   The resolved git tag that was installed.
        dest:      Absolute path to the installation directory.
    """

    def __init__(self, manifest: TemplateManifest, version: str, dest: Path) -> None:
        self.manifest = manifest
        self.version = version
        self.dest = dest.resolve()

    def __repr__(self) -> str:
        return (
            f"InstalledTemplate(id={self.manifest.id!r}, "
            f"version={self.version!r}, dest={self.dest})"
        )


# ---------------------------------------------------------------------------
# TemplateInstaller
# ---------------------------------------------------------------------------


class TemplateInstaller:
    """Downloads and installs MCP server templates.

    Args:
        registry:     :class:`TemplateRegistry` to look up templates.
        git_runner:   Callable ``(args: list[str]) -> None`` that executes git
                      commands.  Injected for testing; defaults to a real
                      ``subprocess.run`` wrapper.
    """

    def __init__(
        self,
        registry: TemplateRegistry | None = None,
        git_runner: Any | None = None,
    ) -> None:
        self._registry = registry or TemplateRegistry()
        self._git_runner = git_runner or _default_git_runner

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def install(
        self,
        template_id: str,
        *,
        dest: Path,
        version: str | None = None,
    ) -> InstalledTemplate:
        """Install a template into *dest*.

        Fetches the full manifest, resolves the version, clones the
        repository at the requested tag into *dest*, and writes a
        ``installed.yaml`` receipt.

        Args:
            template_id: Template slug from the registry.
            dest:        Directory to install into (created if missing).
            version:     Git tag to install.  ``None`` / ``"latest"`` use the
                         newest version listed in the manifest.

        Returns:
            :class:`InstalledTemplate`

        Raises:
            KeyError:    If *template_id* is not in the registry.
            ValueError:  If *version* is unknown.
            RuntimeError: If git clone fails.
        """
        manifest = await self._registry.fetch_manifest(template_id)
        resolved_version = manifest.resolve_version(version)

        dest = Path(dest)
        dest.mkdir(parents=True, exist_ok=True)

        self._clone(manifest.repository, resolved_version, dest)
        self._write_receipt(dest, manifest, resolved_version)

        return InstalledTemplate(manifest=manifest, version=resolved_version, dest=dest)

    async def update(
        self,
        template_id: str,
        *,
        dest: Path,
        version: str | None = None,
    ) -> InstalledTemplate:
        """Update an existing installation to a newer version.

        Equivalent to a fresh install that overwrites *dest*.

        Args:
            template_id: Template slug.
            dest:        Directory of the existing installation.
            version:     Target version tag.  ``None`` installs the latest.

        Returns:
            :class:`InstalledTemplate`
        """
        if dest.exists():
            shutil.rmtree(dest)
        return await self.install(template_id, dest=dest, version=version)

    @staticmethod
    def read_receipt(dest: Path) -> dict[str, str] | None:
        """Read the ``installed.yaml`` receipt from *dest*.

        Returns:
            Dict with ``id``, ``version``, ``repository`` keys, or ``None``
            if no receipt exists.
        """
        import yaml

        receipt_file = dest / "installed.yaml"
        if not receipt_file.is_file():
            return None
        data = yaml.safe_load(receipt_file.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data  # type: ignore[return-value]
        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _clone(self, repo_url: str, version: str, dest: Path) -> None:
        """Shallow-clone *repo_url* at *version* into *dest*."""
        # Clone into a temp dir then move contents to avoid nested .git
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp) / "repo"
            self._git_runner(
                [
                    "git",
                    "clone",
                    "--depth", "1",
                    "--branch", version,
                    repo_url,
                    str(tmp_path),
                ]
            )
            # Move all contents (including hidden files) into dest
            for item in tmp_path.iterdir():
                target = dest / item.name
                if target.exists():
                    if target.is_dir():
                        shutil.rmtree(target)
                    else:
                        target.unlink()
                shutil.move(str(item), str(dest))

    def _write_receipt(
        self, dest: Path, manifest: TemplateManifest, version: str
    ) -> None:
        """Write an ``installed.yaml`` receipt to *dest*."""
        import yaml

        receipt = {
            "id": manifest.id,
            "name": manifest.name,
            "version": version,
            "repository": manifest.repository,
        }
        (dest / "installed.yaml").write_text(
            yaml.dump(receipt, default_flow_style=False), encoding="utf-8"
        )


# ---------------------------------------------------------------------------
# Default git runner
# ---------------------------------------------------------------------------


def _default_git_runner(args: list[str]) -> None:
    """Run a git command via :func:`subprocess.run`, raising on failure."""
    import subprocess

    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"git command failed: {' '.join(args)}\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )
