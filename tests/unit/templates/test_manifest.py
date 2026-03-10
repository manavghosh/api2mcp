"""Unit tests for F7.1 TemplateManifest."""

from __future__ import annotations

import pytest
import yaml

from api2mcp.templates.manifest import ReviewEntry, TemplateManifest, VersionEntry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal_dict(**overrides) -> dict:
    base = {"id": "my-template", "name": "My Template"}
    base.update(overrides)
    return base


def _full_yaml() -> str:
    return yaml.dump(
        {
            "id": "github-issues",
            "name": "GitHub Issues MCP Server",
            "description": "MCP server for GitHub Issues API",
            "author": "api2mcp",
            "version": "1.1.0",
            "tags": ["github", "issues", "rest"],
            "spec_file": "openapi.yaml",
            "repository": "https://github.com/api2mcp/template-github-issues",
            "versions": [
                {"tag": "v1.1.0", "description": "Add label filtering", "released": "2025-03-10"},
                {"tag": "v1.0.0", "description": "Initial release", "released": "2025-01-15"},
            ],
            "rating": 4.5,
            "downloads": 1200,
            "reviews": [
                {"author": "alice", "rating": 5.0, "comment": "Great template!"},
            ],
        }
    )


# ---------------------------------------------------------------------------
# VersionEntry
# ---------------------------------------------------------------------------


def test_version_entry_from_dict() -> None:
    v = VersionEntry.from_dict({"tag": "v1.0.0", "description": "Initial", "released": "2025-01-01"})
    assert v.tag == "v1.0.0"
    assert v.description == "Initial"
    assert v.released == "2025-01-01"


def test_version_entry_defaults() -> None:
    v = VersionEntry.from_dict({"tag": "v2.0.0"})
    assert v.description == ""
    assert v.released == ""


def test_version_entry_to_dict_roundtrip() -> None:
    v = VersionEntry(tag="v1.0.0", description="Init", released="2025-01-01")
    assert VersionEntry.from_dict(v.to_dict()) == v


# ---------------------------------------------------------------------------
# ReviewEntry
# ---------------------------------------------------------------------------


def test_review_entry_from_dict() -> None:
    r = ReviewEntry.from_dict({"author": "bob", "rating": 4.0, "comment": "Good"})
    assert r.author == "bob"
    assert r.rating == 4.0
    assert r.comment == "Good"


def test_review_entry_rating_coerced_to_float() -> None:
    r = ReviewEntry.from_dict({"author": "bob", "rating": "3"})
    assert isinstance(r.rating, float)
    assert r.rating == 3.0


def test_review_entry_to_dict_roundtrip() -> None:
    r = ReviewEntry(author="alice", rating=5.0, comment="Excellent")
    assert ReviewEntry.from_dict(r.to_dict()) == r


# ---------------------------------------------------------------------------
# TemplateManifest.from_dict
# ---------------------------------------------------------------------------


def test_manifest_from_dict_minimal() -> None:
    m = TemplateManifest.from_dict(_minimal_dict())
    assert m.id == "my-template"
    assert m.name == "My Template"
    assert m.description == ""
    assert m.version == "0.1.0"
    assert m.spec_file == "openapi.yaml"
    assert m.tags == []
    assert m.versions == []
    assert m.reviews == []
    assert m.rating == 0.0
    assert m.downloads == 0


def test_manifest_from_dict_full() -> None:
    data = yaml.safe_load(_full_yaml())
    m = TemplateManifest.from_dict(data)
    assert m.id == "github-issues"
    assert m.rating == 4.5
    assert m.downloads == 1200
    assert len(m.versions) == 2
    assert len(m.reviews) == 1
    assert m.reviews[0].author == "alice"


def test_manifest_from_dict_missing_id_raises() -> None:
    with pytest.raises(ValueError, match="'id'"):
        TemplateManifest.from_dict({"name": "No ID"})


def test_manifest_from_dict_missing_name_raises() -> None:
    with pytest.raises(ValueError, match="'name'"):
        TemplateManifest.from_dict({"id": "no-name"})


def test_manifest_from_dict_version_coerced_to_str() -> None:
    m = TemplateManifest.from_dict(_minimal_dict(version=2))
    assert m.version == "2"


# ---------------------------------------------------------------------------
# TemplateManifest.from_yaml
# ---------------------------------------------------------------------------


def test_manifest_from_yaml_full() -> None:
    m = TemplateManifest.from_yaml(_full_yaml())
    assert m.id == "github-issues"
    assert len(m.versions) == 2


def test_manifest_from_yaml_invalid_yaml_raises() -> None:
    with pytest.raises(ValueError, match="Invalid YAML"):
        TemplateManifest.from_yaml("id: [unclosed")


def test_manifest_from_yaml_non_mapping_raises() -> None:
    with pytest.raises(ValueError, match="YAML mapping"):
        TemplateManifest.from_yaml("- item1\n- item2")


# ---------------------------------------------------------------------------
# TemplateManifest.to_dict roundtrip
# ---------------------------------------------------------------------------


def test_manifest_to_dict_roundtrip() -> None:
    m = TemplateManifest.from_yaml(_full_yaml())
    m2 = TemplateManifest.from_dict(m.to_dict())
    assert m.id == m2.id
    assert m.versions == m2.versions
    assert m.reviews == m2.reviews


# ---------------------------------------------------------------------------
# TemplateManifest.latest_version_tag
# ---------------------------------------------------------------------------


def test_latest_version_tag_returns_first() -> None:
    m = TemplateManifest.from_yaml(_full_yaml())
    assert m.latest_version_tag() == "v1.1.0"


def test_latest_version_tag_none_when_empty() -> None:
    m = TemplateManifest.from_dict(_minimal_dict())
    assert m.latest_version_tag() is None


# ---------------------------------------------------------------------------
# TemplateManifest.resolve_version
# ---------------------------------------------------------------------------


def test_resolve_version_none_returns_latest() -> None:
    m = TemplateManifest.from_yaml(_full_yaml())
    assert m.resolve_version(None) == "v1.1.0"


def test_resolve_version_latest_string() -> None:
    m = TemplateManifest.from_yaml(_full_yaml())
    assert m.resolve_version("latest") == "v1.1.0"


def test_resolve_version_exact_match() -> None:
    m = TemplateManifest.from_yaml(_full_yaml())
    assert m.resolve_version("v1.0.0") == "v1.0.0"


def test_resolve_version_unknown_raises() -> None:
    m = TemplateManifest.from_yaml(_full_yaml())
    with pytest.raises(ValueError, match="v9.0.0"):
        m.resolve_version("v9.0.0")


def test_resolve_version_no_versions_falls_back_to_version_field() -> None:
    m = TemplateManifest.from_dict(_minimal_dict(version="0.5.0"))
    assert m.resolve_version(None) == "0.5.0"


# ---------------------------------------------------------------------------
# TemplateManifest.matches_query
# ---------------------------------------------------------------------------


def test_matches_query_by_id() -> None:
    m = TemplateManifest.from_dict(_minimal_dict(id="github-issues"))
    assert m.matches_query("github")


def test_matches_query_by_name() -> None:
    m = TemplateManifest.from_dict(_minimal_dict(name="Stripe Payments Server"))
    assert m.matches_query("stripe")


def test_matches_query_by_tag() -> None:
    m = TemplateManifest.from_dict(_minimal_dict(tags=["rest", "github"]))
    assert m.matches_query("rest")


def test_matches_query_case_insensitive() -> None:
    m = TemplateManifest.from_dict(_minimal_dict(name="GitHub API"))
    assert m.matches_query("GITHUB")


def test_matches_query_no_match() -> None:
    m = TemplateManifest.from_dict(_minimal_dict())
    assert not m.matches_query("definitely-not-in-here")


def test_matches_query_empty_string_always_true() -> None:
    m = TemplateManifest.from_dict(_minimal_dict())
    # Empty query: id/name/description/tags all contain "", which is always True
    assert m.matches_query("")
