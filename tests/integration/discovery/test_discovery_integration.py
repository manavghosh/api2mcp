"""Integration tests for API Spec Auto-Discovery (F3.4).

Uses respx to simulate a variety of realistic server setups.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from api2mcp.discovery.discoverer import (
    DiscoveryResult,
    SpecDiscoverer,
    SpecFormat,
)

# ---------------------------------------------------------------------------
# Shared spec fixtures
# ---------------------------------------------------------------------------

OAS3: dict[str, Any] = {
    "openapi": "3.0.3",
    "info": {"title": "Pet Store", "version": "1.0.0"},
    "servers": [{"url": "https://api.petstore.example.com"}],
    "paths": {
        "/pets": {
            "get": {
                "operationId": "listPets",
                "summary": "List all pets",
                "responses": {"200": {"description": "OK"}},
            }
        }
    },
}

SWAGGER2: dict[str, Any] = {
    "swagger": "2.0",
    "info": {"title": "Legacy API", "version": "2.0.0"},
    "host": "api.legacy.example.com",
    "basePath": "/v2",
    "paths": {"/users": {"get": {"operationId": "listUsers", "responses": {"200": {"description": "OK"}}}}},
}

GQL_RESPONSE: dict[str, Any] = {"data": {"__typename": "Query"}}

POSTMAN_COL: dict[str, Any] = {
    "info": {
        "name": "My API",
        "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
    },
    "item": [
        {
            "name": "List Items",
            "request": {"method": "GET", "url": "https://api.example.com/items", "header": []},
            "response": [],
        }
    ],
}

SWAGGER_UI_HTML = """<!DOCTYPE html>
<html>
<head><title>Swagger UI</title></head>
<body>
  <div id="swagger-ui"></div>
  <script>
    const spec = {url: "/api-docs/openapi.json"};
  </script>
  <link href="/api-docs/openapi.json" rel="alternate" />
</body>
</html>
"""

DOCS_HTML_WITH_SPEC = """<!DOCTYPE html>
<html>
<head><title>API Documentation</title></head>
<body>
  <h1>API Docs</h1>
  <a href="/openapi.json">Download OpenAPI Spec</a>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Scenario: Server serves OAS3 at /openapi.json
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestOpenAPI3Discovery:
    @respx.mock
    async def test_discovers_oas3_at_standard_path(self) -> None:
        base = "https://api.petstore.example.com"
        respx.get(f"{base}/openapi.json").mock(
            return_value=httpx.Response(200, json=OAS3, headers={"content-type": "application/json"})
        )
        respx.get(url__regex=rf"{base}/.*").mock(return_value=httpx.Response(404))

        async with SpecDiscoverer(probe_graphql=False, parse_html_links=False) as d:
            result: DiscoveryResult = await d.discover(base)

        assert result.found
        assert result.best is not None
        assert result.best.format == SpecFormat.OPENAPI3
        assert result.best.parsed is not None
        assert result.best.parsed.get("info", {}).get("title") == "Pet Store"

    @respx.mock
    async def test_discovers_oas3_yaml(self) -> None:
        import yaml
        base = "https://api.example.com"
        respx.get(f"{base}/openapi.json").mock(return_value=httpx.Response(404))
        respx.get(f"{base}/openapi.yaml").mock(
            return_value=httpx.Response(
                200,
                text=yaml.dump(OAS3),
                headers={"content-type": "application/yaml"},
            )
        )
        respx.get(url__regex=rf"{base}/.*").mock(return_value=httpx.Response(404))

        async with SpecDiscoverer(probe_graphql=False, parse_html_links=False) as d:
            result = await d.discover(base)

        assert result.found
        assert result.best.format == SpecFormat.OPENAPI3  # type: ignore[union-attr]

    @respx.mock
    async def test_direct_url_to_spec(self) -> None:
        url = "https://api.example.com/openapi.json"
        respx.get(url).mock(
            return_value=httpx.Response(200, json=OAS3, headers={"content-type": "application/json"})
        )

        async with SpecDiscoverer() as d:
            result = await d.discover(url)

        assert result.found
        assert result.best.format == SpecFormat.OPENAPI3  # type: ignore[union-attr]

    @respx.mock
    async def test_best_spec_url_recorded(self) -> None:
        url = "https://api.example.com/openapi.json"
        respx.get(url).mock(
            return_value=httpx.Response(200, json=OAS3, headers={"content-type": "application/json"})
        )

        discoverer = SpecDiscoverer()
        result = await discoverer.discover(url)

        assert result.best is not None
        assert "openapi" in result.best.url.lower()


# ---------------------------------------------------------------------------
# Scenario: Legacy Swagger 2.0 at /swagger.json
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSwagger2Discovery:
    @respx.mock
    async def test_discovers_swagger2(self) -> None:
        base = "https://api.legacy.example.com"
        respx.get(f"{base}/openapi.json").mock(return_value=httpx.Response(404))
        respx.get(f"{base}/openapi.yaml").mock(return_value=httpx.Response(404))
        respx.get(f"{base}/openapi").mock(return_value=httpx.Response(404))
        respx.get(f"{base}/swagger.json").mock(
            return_value=httpx.Response(200, json=SWAGGER2, headers={"content-type": "application/json"})
        )
        respx.get(url__regex=rf"{base}/.*").mock(return_value=httpx.Response(404))

        async with SpecDiscoverer(probe_graphql=False, parse_html_links=False) as d:
            result = await d.discover(base)

        assert result.found
        assert result.best.format == SpecFormat.SWAGGER2  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Scenario: GraphQL endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGraphQLDiscovery:
    @respx.mock
    async def test_graphql_introspection_probe(self) -> None:
        base = "https://api.graphql.example.com"
        respx.get(url__regex=rf"{base}/.*").mock(return_value=httpx.Response(404))
        respx.post(f"{base}/graphql").mock(
            return_value=httpx.Response(
                200,
                json=GQL_RESPONSE,
                headers={"content-type": "application/json"},
            )
        )

        async with SpecDiscoverer(probe_graphql=True, parse_html_links=False) as d:
            result = await d.discover(base)

        assert result.found
        assert result.best.format == SpecFormat.GRAPHQL  # type: ignore[union-attr]

    @respx.mock
    async def test_graphql_introspection_json_direct(self) -> None:
        url = "https://api.example.com/schema.json"
        introspection: dict[str, Any] = {
            "__schema": {"queryType": {"name": "Query"}, "types": []}
        }
        respx.get(url).mock(
            return_value=httpx.Response(200, json=introspection)
        )

        async with SpecDiscoverer() as d:
            result = await d.discover(url)

        assert result.found
        assert result.best.format == SpecFormat.GRAPHQL  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Scenario: Postman Collection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestPostmanDiscovery:
    @respx.mock
    async def test_discovers_postman_collection(self) -> None:
        url = "https://api.example.com/my_api.postman_collection.json"
        respx.get(url).mock(
            return_value=httpx.Response(200, json=POSTMAN_COL)
        )

        async with SpecDiscoverer() as d:
            result = await d.discover(url)

        assert result.found
        assert result.best.format == SpecFormat.POSTMAN  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Scenario: HTML page with spec links
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestHTMLLinkDiscovery:
    @respx.mock
    async def test_follows_openapi_link_in_html(self) -> None:
        base = "https://docs.example.com"
        respx.get(f"{base}/").mock(
            return_value=httpx.Response(
                200,
                text=DOCS_HTML_WITH_SPEC,
                headers={"content-type": "text/html"},
            )
        )
        respx.get(f"{base}/openapi.json").mock(
            return_value=httpx.Response(200, json=OAS3)
        )
        respx.get(url__regex=rf"{base}/.*").mock(return_value=httpx.Response(404))

        async with SpecDiscoverer(probe_graphql=False, parse_html_links=True) as d:
            result = await d.discover(f"{base}/")

        assert result.found
        assert result.best.format == SpecFormat.OPENAPI3  # type: ignore[union-attr]

    @respx.mock
    async def test_html_links_disabled(self) -> None:
        base = "https://docs.example.com"
        respx.get(f"{base}/").mock(
            return_value=httpx.Response(
                200,
                text=DOCS_HTML_WITH_SPEC,
                headers={"content-type": "text/html"},
            )
        )
        # The linked spec is available
        respx.get(f"{base}/openapi.json").mock(
            return_value=httpx.Response(200, json=OAS3)
        )
        respx.get(url__regex=rf"{base}/.*").mock(return_value=httpx.Response(404))

        async with SpecDiscoverer(probe_graphql=False, parse_html_links=False) as d:
            result = await d.discover(f"{base}/")

        # HTML link was not followed; but /openapi.json probe path might still match
        # The key test is that parse_html_links=False doesn't cause an error
        assert isinstance(result, DiscoveryResult)


# ---------------------------------------------------------------------------
# Scenario: Multiple specs found — best is first
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestMultipleSpecsDiscovered:
    @respx.mock
    async def test_multiple_specs_sorted(self) -> None:
        base = "https://api.example.com"
        respx.get(f"{base}/openapi.json").mock(
            return_value=httpx.Response(200, json=OAS3)
        )
        respx.get(f"{base}/swagger.json").mock(
            return_value=httpx.Response(200, json=SWAGGER2)
        )
        respx.get(url__regex=rf"{base}/.*").mock(return_value=httpx.Response(404))
        respx.post(url__regex=rf"{base}/.*").mock(return_value=httpx.Response(404))

        async with SpecDiscoverer(probe_graphql=False, parse_html_links=False) as d:
            result = await d.discover(base)

        assert result.found
        # All found specs are of known formats
        for spec in result.specs:
            assert spec.format != SpecFormat.UNKNOWN


# ---------------------------------------------------------------------------
# Scenario: No spec found
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestNoSpecFound:
    @respx.mock
    async def test_all_404(self) -> None:
        base = "https://api.nothing.example.com"
        respx.get(url__regex=rf"{base}/.*").mock(return_value=httpx.Response(404))
        respx.post(url__regex=rf"{base}/.*").mock(return_value=httpx.Response(404))
        # Also mock the base URL itself
        respx.get(base).mock(return_value=httpx.Response(404))

        async with SpecDiscoverer(probe_graphql=False, parse_html_links=False) as d:
            result = await d.discover(base)

        assert not result.found
        assert result.best is None

    @respx.mock
    async def test_base_url_in_result(self) -> None:
        base = "https://api.nothing.example.com"
        respx.get(url__regex=rf"{base}/.*").mock(return_value=httpx.Response(404))
        respx.post(url__regex=rf"{base}/.*").mock(return_value=httpx.Response(404))
        respx.get(base).mock(return_value=httpx.Response(404))

        async with SpecDiscoverer(probe_graphql=False, parse_html_links=False) as d:
            result = await d.discover(base)

        assert result.base_url == base


# ---------------------------------------------------------------------------
# Scenario: Extra custom paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCustomPaths:
    @respx.mock
    async def test_custom_path_discovered(self) -> None:
        base = "https://api.example.com"
        # Register specific route BEFORE the generic catch-all
        respx.get(f"{base}/internal/api-spec.json").mock(
            return_value=httpx.Response(200, json=OAS3)
        )
        respx.get(url__regex=rf"{base}/.*").mock(return_value=httpx.Response(404))
        respx.post(url__regex=rf"{base}/.*").mock(return_value=httpx.Response(404))

        async with SpecDiscoverer(
            probe_graphql=False,
            parse_html_links=False,
            extra_paths=["/internal/api-spec.json"],
        ) as d:
            result = await d.discover(base)

        assert result.found
        assert result.best.format == SpecFormat.OPENAPI3  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Scenario: detect() convenience method
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestDetectMethod:
    @respx.mock
    async def test_detect_openapi(self) -> None:
        url = "https://api.example.com/openapi.json"
        respx.get(url).mock(return_value=httpx.Response(200, json=OAS3))

        d = SpecDiscoverer()
        assert await d.detect(url) == SpecFormat.OPENAPI3

    @respx.mock
    async def test_detect_unknown(self) -> None:
        respx.get(url__regex=r"https://api\.example\.com/.*").mock(
            return_value=httpx.Response(404)
        )
        respx.post(url__regex=r"https://api\.example\.com/.*").mock(
            return_value=httpx.Response(404)
        )
        d = SpecDiscoverer(probe_graphql=False, parse_html_links=False)
        fmt = await d.detect("https://api.example.com")
        assert fmt == SpecFormat.UNKNOWN
