# SPDX-License-Identifier: MIT
"""Template registry client for F7.1.

Fetches template listings from a GitHub-based registry index and caches
them locally. The index file is a YAML document listing available templates
with their repository URLs and metadata summaries.

Registry index format (``registry.yaml``)::

    templates:
      - id: github-issues
        name: GitHub Issues MCP Server
        repository: https://github.com/api2mcp/template-github-issues
        description: MCP server for GitHub Issues API
        tags: [github, issues]
        version: "1.0.0"
        rating: 4.5
        downloads: 1200
      - id: stripe-payments
        ...

Usage::

    registry = TemplateRegistry()
    await registry.refresh()                    # fetch remote index
    results = registry.search("github")         # filter by query
    manifest = await registry.fetch_manifest("github-issues")
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from api2mcp.templates.manifest import TemplateManifest


# ---------------------------------------------------------------------------
# Default registry index URL
# ---------------------------------------------------------------------------

_DEFAULT_INDEX_URL = (
    "https://raw.githubusercontent.com/api2mcp/template-registry/main/registry.yaml"
)

_CACHE_TTL_SECONDS = 3600  # 1 hour


# ---------------------------------------------------------------------------
# RegistryIndex
# ---------------------------------------------------------------------------


@dataclass
class RegistryIndex:
    """In-memory representation of a fetched registry index.

    Attributes:
        templates: All templates listed in the remote index (summary manifests).
        fetched_at: Unix timestamp of when this index was loaded.
    """

    templates: list[TemplateManifest]
    fetched_at: float = field(default_factory=time.time)

    def is_stale(self, ttl: float = _CACHE_TTL_SECONDS) -> bool:
        """Return ``True`` if the index is older than *ttl* seconds."""
        return (time.time() - self.fetched_at) > ttl

    @classmethod
    def from_yaml(cls, text: str) -> RegistryIndex:
        """Parse the registry index YAML.

        Args:
            text: Raw YAML content of ``registry.yaml``.

        Returns:
            :class:`RegistryIndex`

        Raises:
            ValueError: If the YAML structure is invalid.
        """
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ValueError(f"Invalid registry index YAML: {exc}") from exc
        if not isinstance(data, dict) or "templates" not in data:
            raise ValueError("Registry index must have a 'templates' list")
        templates = [TemplateManifest.from_dict(t) for t in data["templates"]]
        return cls(templates=templates)


# ---------------------------------------------------------------------------
# TemplateRegistry
# ---------------------------------------------------------------------------


class TemplateRegistry:
    """Client for the remote template registry.

    Args:
        index_url:  URL of the remote ``registry.yaml`` index file.
        cache_dir:  Local directory for caching the index and downloaded manifests.
        http_client: Optional pre-built :class:`httpx.AsyncClient` (injected for tests).
    """

    def __init__(
        self,
        index_url: str = _DEFAULT_INDEX_URL,
        cache_dir: Path | None = None,
        http_client: Any | None = None,
    ) -> None:
        self.index_url = index_url
        self.cache_dir = cache_dir or (Path.home() / ".api2mcp" / "templates")
        self._http_client = http_client
        self._index: RegistryIndex | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def refresh(self, *, force: bool = False) -> RegistryIndex:
        """Fetch (or re-fetch) the registry index.

        Uses local disk cache if the cached file is still fresh,
        unless *force* is ``True``.

        Args:
            force: Bypass cache and always fetch from remote.

        Returns:
            The loaded :class:`RegistryIndex`.
        """
        cache_file = self.cache_dir / "registry.yaml"

        if not force and cache_file.is_file():
            age = time.time() - cache_file.stat().st_mtime
            if age < _CACHE_TTL_SECONDS:
                text = cache_file.read_text(encoding="utf-8")
                self._index = RegistryIndex.from_yaml(text)
                return self._index

        text = await self._fetch_url(self.index_url)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(text, encoding="utf-8")
        self._index = RegistryIndex.from_yaml(text)
        return self._index

    def search(self, query: str = "") -> list[TemplateManifest]:
        """Filter templates by *query* (case-insensitive substring match).

        Searches template id, name, description, and tags.

        Args:
            query: Search string. Empty string returns all templates.

        Returns:
            List of matching :class:`TemplateManifest` objects.

        Raises:
            RuntimeError: If :meth:`refresh` has not been called yet.
        """
        self._ensure_index()
        assert self._index is not None
        if not query:
            return list(self._index.templates)
        return [t for t in self._index.templates if t.matches_query(query)]

    def get(self, template_id: str) -> TemplateManifest | None:
        """Look up a template by exact id.

        Args:
            template_id: Exact template slug.

        Returns:
            :class:`TemplateManifest` or ``None`` if not found.
        """
        self._ensure_index()
        assert self._index is not None
        for t in self._index.templates:
            if t.id == template_id:
                return t
        return None

    async def fetch_manifest(self, template_id: str) -> TemplateManifest:
        """Fetch the full ``template.yaml`` manifest from the template's repository.

        The summary entry in the registry index only contains subset metadata.
        This method fetches the full manifest from the template's own repo.

        Args:
            template_id: Exact template slug.

        Returns:
            Full :class:`TemplateManifest`.

        Raises:
            KeyError:   If *template_id* is not in the registry.
            ValueError: If the remote manifest YAML is malformed.
        """
        summary = self.get(template_id)
        if summary is None:
            available = [t.id for t in (self._index.templates if self._index else [])]
            raise KeyError(
                f"Template {template_id!r} not found in registry. "
                f"Available: {available}"
            )

        manifest_url = _build_raw_url(summary.repository)
        text = await self._fetch_url(manifest_url)
        return TemplateManifest.from_yaml(text)

    @property
    def index(self) -> RegistryIndex | None:
        """The currently loaded :class:`RegistryIndex`, or ``None``."""
        return self._index

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _fetch_url(self, url: str) -> str:
        """Fetch *url* and return the response body as text.

        Uses an injected ``http_client`` if provided, otherwise creates a
        temporary :class:`httpx.AsyncClient`.
        """
        if self._http_client is not None:
            response = await self._http_client.get(url)
            response.raise_for_status()
            return response.text

        import httpx

        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.text

    def _ensure_index(self) -> None:
        if self._index is None:
            raise RuntimeError(
                "Registry index not loaded. Call 'await registry.refresh()' first."
            )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_raw_url(repo_url: str) -> str:
    """Convert a GitHub repo URL to the raw ``template.yaml`` URL.

    Handles HTTPS URLs in the form ``https://github.com/owner/repo``.
    Falls back to appending ``/template.yaml`` for non-GitHub hosts.

    Args:
        repo_url: Repository URL.

    Returns:
        Direct URL to the raw ``template.yaml`` file on the default branch.
    """
    repo_url = repo_url.rstrip("/")
    if "github.com" in repo_url:
        # https://github.com/owner/repo  →  https://raw.githubusercontent.com/owner/repo/main/template.yaml
        parts = repo_url.replace("https://github.com/", "").split("/")
        if len(parts) >= 2:
            owner, repo = parts[0], parts[1]
            return f"https://raw.githubusercontent.com/{owner}/{repo}/main/template.yaml"
    return f"{repo_url}/template.yaml"
