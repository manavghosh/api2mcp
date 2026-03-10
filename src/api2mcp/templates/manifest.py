# SPDX-License-Identifier: MIT
"""Template manifest — parses and validates ``template.yaml`` files (F7.1).

A template manifest lives at the root of every template repository and
describes the template's metadata, version history, and entry point.

Example ``template.yaml``::

    id: github-issues
    name: GitHub Issues MCP Server
    description: MCP server for GitHub Issues API
    author: api2mcp
    version: "1.0.0"
    tags: [github, issues, rest]
    spec_file: openapi.yaml
    repository: https://github.com/api2mcp/template-github-issues
    versions:
      - tag: v1.0.0
        description: "Initial release"
        released: "2025-01-15"
      - tag: v1.1.0
        description: "Add label filtering"
        released: "2025-03-10"
    rating: 4.5
    downloads: 1200
    reviews: []
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import yaml


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class VersionEntry:
    """A single version entry in a template manifest.

    Attributes:
        tag:         Git tag string (e.g. ``"v1.0.0"``).
        description: Short description of what changed in this version.
        released:    Release date string (ISO 8601, e.g. ``"2025-01-15"``).
    """

    tag: str
    description: str = ""
    released: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VersionEntry:
        return cls(
            tag=data["tag"],
            description=data.get("description", ""),
            released=data.get("released", ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"tag": self.tag, "description": self.description, "released": self.released}


@dataclass
class ReviewEntry:
    """A user review for a template.

    Attributes:
        author:  Reviewer handle.
        rating:  Score between 1.0 and 5.0.
        comment: Free-text review body.
    """

    author: str
    rating: float
    comment: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReviewEntry:
        return cls(
            author=data["author"],
            rating=float(data["rating"]),
            comment=data.get("comment", ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"author": self.author, "rating": self.rating, "comment": self.comment}


@dataclass
class TemplateManifest:
    """Parsed contents of a ``template.yaml`` file.

    Attributes:
        id:          Unique slug identifier (e.g. ``"github-issues"``).
        name:        Human-readable template name.
        description: Short description of what the template does.
        author:      Author handle or organisation name.
        version:     Current version string (semver recommended).
        tags:        Searchable keyword tags.
        spec_file:   Relative path to the OpenAPI/Swagger spec inside the template repo.
        repository:  URL of the template's git repository.
        versions:    Ordered list of :class:`VersionEntry` objects (newest first).
        rating:      Average user rating (0.0–5.0).
        downloads:   Total install count.
        reviews:     List of :class:`ReviewEntry` objects.
    """

    id: str
    name: str
    description: str = ""
    author: str = ""
    version: str = "0.1.0"
    tags: list[str] = field(default_factory=list)
    spec_file: str = "openapi.yaml"
    repository: str = ""
    versions: list[VersionEntry] = field(default_factory=list)
    rating: float = 0.0
    downloads: int = 0
    reviews: list[ReviewEntry] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Factories
    # ------------------------------------------------------------------

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TemplateManifest:
        """Build a :class:`TemplateManifest` from a raw parsed dict.

        Args:
            data: Dict loaded from ``template.yaml``.

        Returns:
            A populated :class:`TemplateManifest`.

        Raises:
            ValueError: If required fields (``id``, ``name``) are missing.
        """
        if "id" not in data:
            raise ValueError("template.yaml must contain 'id'")
        if "name" not in data:
            raise ValueError("template.yaml must contain 'name'")

        versions = [VersionEntry.from_dict(v) for v in data.get("versions", [])]
        reviews = [ReviewEntry.from_dict(r) for r in data.get("reviews", [])]

        return cls(
            id=data["id"],
            name=data["name"],
            description=data.get("description", ""),
            author=data.get("author", ""),
            version=str(data.get("version", "0.1.0")),
            tags=list(data.get("tags", [])),
            spec_file=str(data.get("spec_file", "openapi.yaml")),
            repository=str(data.get("repository", "")),
            versions=versions,
            rating=float(data.get("rating", 0.0)),
            downloads=int(data.get("downloads", 0)),
            reviews=reviews,
        )

    @classmethod
    def from_yaml(cls, text: str) -> TemplateManifest:
        """Parse a ``template.yaml`` string.

        Args:
            text: Raw YAML content.

        Returns:
            :class:`TemplateManifest`

        Raises:
            ValueError: If the YAML is invalid or required fields are missing.
        """
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ValueError(f"Invalid YAML in template manifest: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("template.yaml must be a YAML mapping")
        return cls.from_dict(data)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict (round-trippable via :meth:`from_dict`)."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "author": self.author,
            "version": self.version,
            "tags": list(self.tags),
            "spec_file": self.spec_file,
            "repository": self.repository,
            "versions": [v.to_dict() for v in self.versions],
            "rating": self.rating,
            "downloads": self.downloads,
            "reviews": [r.to_dict() for r in self.reviews],
        }

    def latest_version_tag(self) -> str | None:
        """Return the tag of the newest version entry, or ``None`` if empty."""
        return self.versions[0].tag if self.versions else None

    def resolve_version(self, requested: str | None) -> str:
        """Resolve a requested version string to a git tag.

        Args:
            requested: Version tag (e.g. ``"v1.0.0"``) or ``None`` / ``"latest"``.

        Returns:
            The resolved git tag string.

        Raises:
            ValueError: If *requested* does not match any known version.
        """
        if requested is None or requested.lower() in ("latest", ""):
            return self.latest_version_tag() or self.version
        available = {v.tag for v in self.versions}
        if requested in available:
            return requested
        raise ValueError(
            f"Version {requested!r} not found in template {self.id!r}. "
            f"Available: {sorted(available)}"
        )

    def matches_query(self, query: str) -> bool:
        """Return ``True`` if *query* appears in the id, name, description, or tags."""
        q = query.lower()
        return (
            q in self.id.lower()
            or q in self.name.lower()
            or q in self.description.lower()
            or any(q in tag.lower() for tag in self.tags)
        )
