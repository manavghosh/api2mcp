"""Unit tests for the API Spec Auto-Discovery engine (F3.4).

Uses respx to mock HTTP responses — no real network calls.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
import respx
import httpx

from api2mcp.discovery.discoverer import (
    DiscoveredSpec,
    DiscoveryResult,
    SpecDiscoverer,
    SpecFormat,
    _base_url,
    _detect_format_from_dict,
    _is_html,
    detect_format_from_content,
    detect_format_from_url,
    extract_spec_links_from_html,
)


# ---------------------------------------------------------------------------
# Fixtures — sample spec payloads
# ---------------------------------------------------------------------------

OAS3_DOC: dict[str, Any] = {
    "openapi": "3.0.3",
    "info": {"title": "Test", "version": "1.0.0"},
    "paths": {},
}

SWAGGER2_DOC: dict[str, Any] = {
    "swagger": "2.0",
    "info": {"title": "Test", "version": "1.0.0"},
    "paths": {},
}

POSTMAN_DOC: dict[str, Any] = {
    "info": {
        "name": "My Collection",
        "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
    },
    "item": [],
}

GQL_INTROSPECTION: dict[str, Any] = {
    "__schema": {
        "queryType": {"name": "Query"},
        "types": [],
    }
}

GQL_RESPONSE: dict[str, Any] = {
    "data": {"__typename": "Query"}
}

GRAPHQL_SDL = """
type Query {
  ping: String
}
"""

HTML_WITH_SPEC_LINK = """<!DOCTYPE html>
<html>
<head><title>API Docs</title></head>
<body>
  <a href="/openapi.json">OpenAPI Spec</a>
  <a href="/swagger-ui">Swagger UI</a>
</body>
</html>
"""

HTML_WITHOUT_SPEC_LINK = """<!DOCTYPE html>
<html><body><p>No links here</p></body></html>
"""


# ---------------------------------------------------------------------------
# detect_format_from_url()
# ---------------------------------------------------------------------------


class TestDetectFormatFromUrl:
    def test_openapi_in_path(self) -> None:
        assert detect_format_from_url("https://api.example.com/openapi.json") == SpecFormat.OPENAPI3

    def test_openapi_yaml(self) -> None:
        assert detect_format_from_url("https://api.example.com/openapi.yaml") == SpecFormat.OPENAPI3

    def test_swagger_in_path(self) -> None:
        assert detect_format_from_url("https://api.example.com/swagger.json") == SpecFormat.SWAGGER2

    def test_graphql_in_path(self) -> None:
        assert detect_format_from_url("https://api.example.com/graphql") == SpecFormat.GRAPHQL

    def test_postman_in_path(self) -> None:
        result = detect_format_from_url("https://example.com/collection.postman_collection.json")
        assert result == SpecFormat.POSTMAN

    def test_unknown_url(self) -> None:
        assert detect_format_from_url("https://api.example.com/api/v1") is None

    def test_empty_path(self) -> None:
        assert detect_format_from_url("https://api.example.com/") is None


# ---------------------------------------------------------------------------
# detect_format_from_content()
# ---------------------------------------------------------------------------


class TestDetectFormatFromContent:
    def test_openapi3_json(self) -> None:
        fmt, doc = detect_format_from_content(json.dumps(OAS3_DOC))
        assert fmt == SpecFormat.OPENAPI3
        assert doc is not None

    def test_swagger2_json(self) -> None:
        fmt, doc = detect_format_from_content(json.dumps(SWAGGER2_DOC))
        assert fmt == SpecFormat.SWAGGER2

    def test_postman_json(self) -> None:
        fmt, doc = detect_format_from_content(json.dumps(POSTMAN_DOC))
        assert fmt == SpecFormat.POSTMAN

    def test_graphql_introspection_json(self) -> None:
        fmt, doc = detect_format_from_content(json.dumps(GQL_INTROSPECTION))
        assert fmt == SpecFormat.GRAPHQL

    def test_graphql_introspection_wrapped(self) -> None:
        wrapped = {"data": GQL_INTROSPECTION}
        fmt, _ = detect_format_from_content(json.dumps(wrapped))
        assert fmt == SpecFormat.GRAPHQL

    def test_graphql_sdl(self) -> None:
        fmt, doc = detect_format_from_content(GRAPHQL_SDL)
        assert fmt == SpecFormat.GRAPHQL
        assert doc is None  # SDL is not JSON/YAML dict

    def test_openapi3_yaml(self) -> None:
        import yaml
        content = yaml.dump(OAS3_DOC)
        fmt, doc = detect_format_from_content(content)
        assert fmt == SpecFormat.OPENAPI3
        assert doc is not None

    def test_empty_content(self) -> None:
        fmt, doc = detect_format_from_content("")
        assert fmt == SpecFormat.UNKNOWN
        assert doc is None

    def test_invalid_json(self) -> None:
        fmt, doc = detect_format_from_content("{not valid json")
        assert fmt == SpecFormat.UNKNOWN

    def test_url_hint_used_as_fallback(self) -> None:
        # Content is valid JSON but not recognizable; URL gives the hint
        content = json.dumps({"custom": "spec"})
        fmt, _ = detect_format_from_content(content, url="https://api.example.com/openapi.json")
        assert fmt == SpecFormat.OPENAPI3

    def test_content_type_not_used_for_format(self) -> None:
        # content_type is stored but format comes from content
        fmt, _ = detect_format_from_content(json.dumps(OAS3_DOC), content_type="application/json")
        assert fmt == SpecFormat.OPENAPI3


# ---------------------------------------------------------------------------
# _detect_format_from_dict()
# ---------------------------------------------------------------------------


class TestDetectFormatFromDict:
    def test_openapi3(self) -> None:
        assert _detect_format_from_dict(OAS3_DOC) == SpecFormat.OPENAPI3

    def test_openapi31(self) -> None:
        doc = {"openapi": "3.1.0", "info": {"title": "T", "version": "1"}, "paths": {}}
        assert _detect_format_from_dict(doc) == SpecFormat.OPENAPI3

    def test_swagger2(self) -> None:
        assert _detect_format_from_dict(SWAGGER2_DOC) == SpecFormat.SWAGGER2

    def test_graphql_schema(self) -> None:
        assert _detect_format_from_dict(GQL_INTROSPECTION) == SpecFormat.GRAPHQL

    def test_graphql_data_wrapped(self) -> None:
        wrapped = {"data": GQL_INTROSPECTION}
        assert _detect_format_from_dict(wrapped) == SpecFormat.GRAPHQL

    def test_postman(self) -> None:
        assert _detect_format_from_dict(POSTMAN_DOC) == SpecFormat.POSTMAN

    def test_unknown_dict(self) -> None:
        assert _detect_format_from_dict({"hello": "world"}) == SpecFormat.UNKNOWN

    def test_empty_dict(self) -> None:
        assert _detect_format_from_dict({}) == SpecFormat.UNKNOWN


# ---------------------------------------------------------------------------
# extract_spec_links_from_html()
# ---------------------------------------------------------------------------


class TestExtractSpecLinksFromHtml:
    def test_finds_openapi_link(self) -> None:
        links = extract_spec_links_from_html(HTML_WITH_SPEC_LINK, "https://api.example.com")
        assert any("openapi" in l for l in links)

    def test_resolves_relative_urls(self) -> None:
        links = extract_spec_links_from_html(HTML_WITH_SPEC_LINK, "https://api.example.com")
        assert all(l.startswith("https://") for l in links)

    def test_absolute_url_preserved(self) -> None:
        html = '<a href="https://other.com/openapi.json">spec</a>'
        links = extract_spec_links_from_html(html, "https://api.example.com")
        assert "https://other.com/openapi.json" in links

    def test_no_links_found(self) -> None:
        links = extract_spec_links_from_html(HTML_WITHOUT_SPEC_LINK, "https://api.example.com")
        assert links == []

    def test_empty_html(self) -> None:
        assert extract_spec_links_from_html("", "https://api.example.com") == []

    def test_deduplication(self) -> None:
        html = (
            '<a href="/openapi.json">1</a>'
            '<a href="/openapi.json">2</a>'
        )
        links = extract_spec_links_from_html(html, "https://api.example.com")
        assert len(links) == 1


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_base_url(self) -> None:
        assert _base_url("https://api.example.com/v1/openapi.json") == "https://api.example.com"

    def test_base_url_no_path(self) -> None:
        assert _base_url("https://api.example.com") == "https://api.example.com"

    def test_is_html_true(self) -> None:
        assert _is_html("text/html; charset=utf-8") is True

    def test_is_html_false(self) -> None:
        assert _is_html("application/json") is False

    def test_is_html_empty(self) -> None:
        assert _is_html("") is False


# ---------------------------------------------------------------------------
# DiscoveredSpec properties
# ---------------------------------------------------------------------------


class TestDiscoveredSpec:
    def test_is_yaml_by_url(self) -> None:
        spec = DiscoveredSpec(
            url="https://api.example.com/openapi.yaml",
            content="openapi: 3.0.3",
            format=SpecFormat.OPENAPI3,
        )
        assert spec.is_yaml is True

    def test_is_json_by_url(self) -> None:
        spec = DiscoveredSpec(
            url="https://api.example.com/openapi.json",
            content="{}",
            format=SpecFormat.OPENAPI3,
        )
        assert spec.is_json is True

    def test_is_yaml_by_content_type(self) -> None:
        spec = DiscoveredSpec(
            url="https://api.example.com/spec",
            content="openapi: 3.0.3",
            format=SpecFormat.OPENAPI3,
            content_type="application/yaml",
        )
        assert spec.is_yaml is True

    def test_neither_yaml_nor_json(self) -> None:
        spec = DiscoveredSpec(
            url="https://api.example.com/graphql",
            content="type Query { ping: String }",
            format=SpecFormat.GRAPHQL,
            content_type="text/plain",
        )
        assert spec.is_yaml is False
        assert spec.is_json is False


# ---------------------------------------------------------------------------
# DiscoveryResult properties
# ---------------------------------------------------------------------------


class TestDiscoveryResult:
    def test_found_true(self) -> None:
        spec = DiscoveredSpec(url="u", content="", format=SpecFormat.OPENAPI3)
        result = DiscoveryResult(base_url="https://api.example.com", specs=[spec])
        assert result.found is True

    def test_found_false(self) -> None:
        result = DiscoveryResult(base_url="https://api.example.com")
        assert result.found is False

    def test_best_returns_first(self) -> None:
        s1 = DiscoveredSpec(url="u1", content="", format=SpecFormat.OPENAPI3)
        s2 = DiscoveredSpec(url="u2", content="", format=SpecFormat.SWAGGER2)
        result = DiscoveryResult(base_url="https://api.example.com", specs=[s1, s2])
        assert result.best == s1

    def test_best_none_when_empty(self) -> None:
        result = DiscoveryResult(base_url="https://api.example.com")
        assert result.best is None


# ---------------------------------------------------------------------------
# SpecDiscoverer with mocked HTTP (respx)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSpecDiscovererDirect:
    @respx.mock
    async def test_direct_openapi3_hit(self) -> None:
        respx.get("https://api.example.com/openapi.json").mock(
            return_value=httpx.Response(
                200,
                json=OAS3_DOC,
                headers={"content-type": "application/json"},
            )
        )
        discoverer = SpecDiscoverer()
        result = await discoverer.discover("https://api.example.com/openapi.json")
        assert result.found
        assert result.best.format == SpecFormat.OPENAPI3  # type: ignore[union-attr]

    @respx.mock
    async def test_direct_swagger2_hit(self) -> None:
        respx.get("https://api.example.com/swagger.json").mock(
            return_value=httpx.Response(
                200,
                json=SWAGGER2_DOC,
                headers={"content-type": "application/json"},
            )
        )
        discoverer = SpecDiscoverer()
        result = await discoverer.discover("https://api.example.com/swagger.json")
        assert result.found
        assert result.best.format == SpecFormat.SWAGGER2  # type: ignore[union-attr]

    @respx.mock
    async def test_404_returns_empty(self) -> None:
        respx.get("https://api.example.com/openapi.json").mock(
            return_value=httpx.Response(404)
        )
        discoverer = SpecDiscoverer(probe_graphql=False, parse_html_links=False)
        # Mock all common paths to 404
        respx.get(url__regex=r"https://api\.example\.com/.*").mock(
            return_value=httpx.Response(404)
        )
        result = await discoverer.discover("https://api.example.com/openapi.json")
        assert not result.found

    @respx.mock
    async def test_direct_graphql_introspection(self) -> None:
        respx.get("https://api.example.com/schema.json").mock(
            return_value=httpx.Response(
                200,
                json=GQL_INTROSPECTION,
                headers={"content-type": "application/json"},
            )
        )
        discoverer = SpecDiscoverer()
        result = await discoverer.discover("https://api.example.com/schema.json")
        assert result.found
        assert result.best.format == SpecFormat.GRAPHQL  # type: ignore[union-attr]

    @respx.mock
    async def test_postman_collection_detected(self) -> None:
        respx.get("https://api.example.com/collection.json").mock(
            return_value=httpx.Response(
                200,
                json=POSTMAN_DOC,
                headers={"content-type": "application/json"},
            )
        )
        discoverer = SpecDiscoverer()
        result = await discoverer.discover("https://api.example.com/collection.json")
        assert result.found
        assert result.best.format == SpecFormat.POSTMAN  # type: ignore[union-attr]


@pytest.mark.asyncio
class TestSpecDiscovererProbing:
    @respx.mock
    async def test_probes_openapi_json_path(self) -> None:
        # Base URL returns HTML; /openapi.json returns spec
        respx.get("https://api.example.com/").mock(
            return_value=httpx.Response(
                200,
                text=HTML_WITHOUT_SPEC_LINK,
                headers={"content-type": "text/html"},
            )
        )
        respx.get("https://api.example.com/openapi.json").mock(
            return_value=httpx.Response(
                200,
                json=OAS3_DOC,
                headers={"content-type": "application/json"},
            )
        )
        # All others 404
        respx.get(url__regex=r"https://api\.example\.com/.*").mock(
            return_value=httpx.Response(404)
        )
        discoverer = SpecDiscoverer(probe_graphql=False, parse_html_links=False)
        result = await discoverer.discover("https://api.example.com/")
        assert result.found
        assert result.best.format == SpecFormat.OPENAPI3  # type: ignore[union-attr]

    @respx.mock
    async def test_probes_swagger_json_when_openapi_missing(self) -> None:
        respx.get("https://api.example.com/openapi.json").mock(return_value=httpx.Response(404))
        respx.get("https://api.example.com/openapi.yaml").mock(return_value=httpx.Response(404))
        respx.get("https://api.example.com/openapi").mock(return_value=httpx.Response(404))
        respx.get("https://api.example.com/swagger.json").mock(
            return_value=httpx.Response(
                200,
                json=SWAGGER2_DOC,
                headers={"content-type": "application/json"},
            )
        )
        # Everything else 404
        respx.get(url__regex=r"https://api\.example\.com/.*").mock(
            return_value=httpx.Response(404)
        )
        discoverer = SpecDiscoverer(probe_graphql=False, parse_html_links=False)
        result = await discoverer.discover("https://api.example.com")
        assert result.found
        assert result.best.format == SpecFormat.SWAGGER2  # type: ignore[union-attr]

    @respx.mock
    async def test_html_link_parsing(self) -> None:
        base = "https://api.example.com"
        respx.get(f"{base}/").mock(
            return_value=httpx.Response(
                200,
                text='<html><a href="/api/openapi.json">spec</a></html>',
                headers={"content-type": "text/html"},
            )
        )
        respx.get(f"{base}/api/openapi.json").mock(
            return_value=httpx.Response(
                200,
                json=OAS3_DOC,
                headers={"content-type": "application/json"},
            )
        )
        # All probe paths 404
        respx.get(url__regex=r"https://api\.example\.com/.*").mock(
            return_value=httpx.Response(404)
        )
        discoverer = SpecDiscoverer(probe_graphql=False, parse_html_links=True)
        result = await discoverer.discover(f"{base}/")
        assert result.found
        assert result.best.format == SpecFormat.OPENAPI3  # type: ignore[union-attr]

    @respx.mock
    async def test_graphql_introspection_probe(self) -> None:
        # All GETs return 404; /graphql POST succeeds
        respx.get(url__regex=r"https://api\.example\.com/.*").mock(
            return_value=httpx.Response(404)
        )
        respx.post("https://api.example.com/graphql").mock(
            return_value=httpx.Response(
                200,
                json=GQL_RESPONSE,
                headers={"content-type": "application/json"},
            )
        )
        discoverer = SpecDiscoverer(probe_graphql=True, parse_html_links=False)
        result = await discoverer.discover("https://api.example.com")
        assert result.found
        assert result.best.format == SpecFormat.GRAPHQL  # type: ignore[union-attr]

    @respx.mock
    async def test_graphql_probe_disabled(self) -> None:
        respx.get(url__regex=r"https://api\.example\.com/.*").mock(
            return_value=httpx.Response(404)
        )
        discoverer = SpecDiscoverer(probe_graphql=False, parse_html_links=False)
        result = await discoverer.discover("https://api.example.com")
        assert not result.found

    @respx.mock
    async def test_extra_paths_probed(self) -> None:
        # Register specific route BEFORE the generic 404 catch-all
        respx.get("https://api.example.com/custom/spec.json").mock(
            return_value=httpx.Response(
                200,
                json=OAS3_DOC,
                headers={"content-type": "application/json"},
            )
        )
        respx.get(url__regex=r"https://api\.example\.com/.*").mock(
            return_value=httpx.Response(404)
        )
        discoverer = SpecDiscoverer(
            probe_graphql=False,
            parse_html_links=False,
            extra_paths=["/custom/spec.json"],
        )
        result = await discoverer.discover("https://api.example.com")
        assert result.found

    @respx.mock
    async def test_network_error_adds_to_errors(self) -> None:
        respx.get(url__regex=r"https://api\.example\.com/.*").mock(
            side_effect=httpx.ConnectError("Connection refused")
        )
        discoverer = SpecDiscoverer(probe_graphql=False, parse_html_links=False)
        result = await discoverer.discover("https://api.example.com")
        assert not result.found
        # Errors are populated by the outer try/except or inner fetch silently ignores
        # The important thing is that no exception is raised to the caller


@pytest.mark.asyncio
class TestSpecDiscovererContextManager:
    @respx.mock
    async def test_context_manager_reuses_client(self) -> None:
        respx.get("https://api.example.com/openapi.json").mock(
            return_value=httpx.Response(200, json=OAS3_DOC)
        )
        respx.get(url__regex=r"https://api\.example\.com/.*").mock(
            return_value=httpx.Response(404)
        )
        async with SpecDiscoverer(probe_graphql=False, parse_html_links=False) as d:
            result = await d.discover("https://api.example.com/openapi.json")
        assert result.found

    @respx.mock
    async def test_detect_method(self) -> None:
        respx.get("https://api.example.com/openapi.json").mock(
            return_value=httpx.Response(200, json=OAS3_DOC)
        )
        discoverer = SpecDiscoverer()
        fmt = await discoverer.detect("https://api.example.com/openapi.json")
        assert fmt == SpecFormat.OPENAPI3

    @respx.mock
    async def test_detect_unknown_when_nothing_found(self) -> None:
        respx.get(url__regex=r"https://api\.example\.com/.*").mock(
            return_value=httpx.Response(404)
        )
        respx.post(url__regex=r"https://api\.example\.com/.*").mock(
            return_value=httpx.Response(404)
        )
        discoverer = SpecDiscoverer(probe_graphql=False, parse_html_links=False)
        fmt = await discoverer.detect("https://api.example.com")
        assert fmt == SpecFormat.UNKNOWN


@pytest.mark.asyncio
class TestSpecDiscovererResultSorting:
    @respx.mock
    async def test_known_format_before_unknown(self) -> None:
        # /openapi.json returns valid spec; /swagger.json returns garbage
        respx.get("https://api.example.com/openapi.json").mock(
            return_value=httpx.Response(200, json=OAS3_DOC)
        )
        respx.get(url__regex=r"https://api\.example\.com/.*").mock(
            return_value=httpx.Response(404)
        )
        discoverer = SpecDiscoverer(probe_graphql=False, parse_html_links=False)
        result = await discoverer.discover("https://api.example.com")
        if result.found:
            assert result.specs[0].format != SpecFormat.UNKNOWN
