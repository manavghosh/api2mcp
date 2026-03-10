# SPDX-License-Identifier: MIT
"""API Spec Auto-Discovery engine (F3.4).

Automatically discovers API specifications from a base URL by:

1. Probing common spec paths (openapi.json, swagger.json, /graphql, …)
2. Detecting the spec format from response content
3. Parsing HTML pages for spec links
4. Returning a :class:`DiscoveredSpec` with raw content and format info

Usage::

    discoverer = SpecDiscoverer()
    result = await discoverer.discover("https://api.example.com")
    if result.found:
        spec = result.best
        logger.debug("Discovered spec: %s %s", spec.format, spec.url)
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
import yaml

from api2mcp.core.exceptions import ParseException

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SpecFormat enum
# ---------------------------------------------------------------------------


class SpecFormat(str, Enum):
    """Detected API specification format."""

    OPENAPI3 = "openapi3"      # OpenAPI 3.0 / 3.1
    SWAGGER2 = "swagger2"      # Swagger / OpenAPI 2.0
    GRAPHQL = "graphql"        # GraphQL SDL or introspection
    POSTMAN = "postman"        # Postman Collection v2.x
    UNKNOWN = "unknown"        # Could not determine format


# ---------------------------------------------------------------------------
# DiscoveredSpec dataclass
# ---------------------------------------------------------------------------


@dataclass
class DiscoveredSpec:
    """A single discovered API specification."""

    url: str
    """The URL (or path) where the spec was found."""

    content: str
    """Raw text content of the spec."""

    format: SpecFormat
    """Detected format of the spec."""

    content_type: str = ""
    """HTTP Content-Type header from the response, if available."""

    parsed: dict[str, Any] | None = None
    """Pre-parsed dict if the content is JSON/YAML, else ``None``."""

    @property
    def is_yaml(self) -> bool:
        return (
            "yaml" in self.content_type
            or self.url.endswith((".yaml", ".yml"))
        )

    @property
    def is_json(self) -> bool:
        return (
            "json" in self.content_type
            or self.url.endswith(".json")
        )


@dataclass
class DiscoveryResult:
    """Result of a full auto-discovery run against a base URL."""

    base_url: str
    """The base URL that was probed."""

    specs: list[DiscoveredSpec] = field(default_factory=list)
    """All specs found, ordered by confidence (best first)."""

    errors: list[str] = field(default_factory=list)
    """Non-fatal errors encountered during discovery."""

    @property
    def found(self) -> bool:
        """True if at least one spec was discovered."""
        return bool(self.specs)

    @property
    def best(self) -> DiscoveredSpec | None:
        """The highest-confidence spec found, or ``None``."""
        return self.specs[0] if self.specs else None


# ---------------------------------------------------------------------------
# Common spec paths to probe
# ---------------------------------------------------------------------------

#: Paths tried in priority order.  The first successful response wins.
COMMON_PATHS: list[str] = [
    # OpenAPI 3.x
    "/openapi.json",
    "/openapi.yaml",
    "/openapi",
    # Swagger 2.0
    "/swagger.json",
    "/swagger.yaml",
    "/swagger",
    # Well-known
    "/.well-known/openapi.json",
    "/.well-known/openapi.yaml",
    "/.well-known/openapi",
    # API Docs / developer portals
    "/api-docs",
    "/api-docs.json",
    "/api-docs.yaml",
    "/api/openapi.json",
    "/api/openapi.yaml",
    "/api/swagger.json",
    "/api/swagger.yaml",
    "/api/docs",
    "/v1/openapi.json",
    "/v1/swagger.json",
    "/v2/openapi.json",
    "/v2/swagger.json",
    # GraphQL
    "/graphql",
]

#: Regex patterns that indicate a spec link in HTML
_HTML_SPEC_LINK_RE = re.compile(
    r"""href=["']([^"']*(?:openapi|swagger|api[-_]?docs|graphql)[^"']*)["']""",
    re.IGNORECASE,
)

_GQL_MINIMAL_QUERY = '{"query":"{__typename}"}'


# ---------------------------------------------------------------------------
# Format detection helpers (pure functions — no I/O)
# ---------------------------------------------------------------------------


def detect_format_from_url(url: str) -> SpecFormat | None:
    """Infer format from URL path/extension alone.

    Returns ``None`` if the URL gives no signal.
    """
    path = urlparse(url).path.lower()
    if any(x in path for x in ("openapi",)):
        return SpecFormat.OPENAPI3
    if "swagger" in path:
        return SpecFormat.SWAGGER2
    if "graphql" in path:
        return SpecFormat.GRAPHQL
    if "postman" in path or "collection" in path:
        return SpecFormat.POSTMAN
    return None


def detect_format_from_content(
    content: str,
    content_type: str = "",
    url: str = "",
) -> tuple[SpecFormat, dict[str, Any] | None]:
    """Detect spec format from raw content text.

    Returns ``(format, parsed_doc)`` where *parsed_doc* is the parsed
    dict if the content is valid JSON/YAML, otherwise ``None``.
    """
    stripped = content.strip()
    if not stripped:
        return SpecFormat.UNKNOWN, None

    # --- Try to parse as JSON/YAML ---
    doc: dict[str, Any] | None = None

    if stripped.startswith("{") or stripped.startswith("["):
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, dict):
                doc = parsed
        except (json.JSONDecodeError, ValueError) as exc:
            logger.debug("Ignoring error: %s", exc)
    else:
        try:
            parsed = yaml.safe_load(stripped)
            if isinstance(parsed, dict):
                doc = parsed
        except yaml.YAMLError as exc:
            logger.debug("Ignoring error: %s", exc)

    if doc is not None:
        fmt = _detect_format_from_dict(doc)
        if fmt != SpecFormat.UNKNOWN:
            return fmt, doc

    # --- Fallback: textual heuristics ---

    # GraphQL SDL
    if any(kw in stripped for kw in ("type Query {", "type Mutation {", "schema {", "type Query{")):
        return SpecFormat.GRAPHQL, None

    # URL hint
    url_hint = detect_format_from_url(url)
    if url_hint is not None:
        return url_hint, doc

    return SpecFormat.UNKNOWN, doc


def _detect_format_from_dict(doc: dict[str, Any]) -> SpecFormat:
    """Detect spec format from a parsed dict."""
    # OpenAPI 3.x
    raw = doc.get("openapi", "")
    if isinstance(raw, str) and raw.startswith("3."):
        return SpecFormat.OPENAPI3

    # Swagger 2.0
    if doc.get("swagger") == "2.0":
        return SpecFormat.SWAGGER2

    # GraphQL introspection
    if "__schema" in doc:
        return SpecFormat.GRAPHQL
    if isinstance(doc.get("data"), dict) and "__schema" in doc["data"]:
        return SpecFormat.GRAPHQL

    # Postman Collection
    info = doc.get("info")
    if isinstance(info, dict):
        schema_url = str(info.get("schema", ""))
        if "getpostman.com" in schema_url and "item" in doc:
            return SpecFormat.POSTMAN

    return SpecFormat.UNKNOWN


def extract_spec_links_from_html(html: str, base_url: str) -> list[str]:
    """Parse HTML content and return absolute URLs of any spec links found."""
    links: list[str] = []
    for match in _HTML_SPEC_LINK_RE.finditer(html):
        href = match.group(1)
        abs_url = urljoin(base_url, href)
        if abs_url not in links:
            links.append(abs_url)
    return links


# ---------------------------------------------------------------------------
# SpecDiscoverer
# ---------------------------------------------------------------------------


class SpecDiscoverer:
    """Discover API specifications from a base URL.

    Usage::

        async with SpecDiscoverer() as d:
            result = await d.discover("https://api.example.com")

    Or without context manager (manages its own httpx client internally)::

        discoverer = SpecDiscoverer()
        result = await discoverer.discover("https://api.example.com")
    """

    def __init__(
        self,
        *,
        timeout: float = 10.0,
        max_redirects: int = 5,
        headers: dict[str, str] | None = None,
        probe_graphql: bool = True,
        parse_html_links: bool = True,
        extra_paths: list[str] | None = None,
    ) -> None:
        self._timeout = timeout
        self._max_redirects = max_redirects
        self._base_headers: dict[str, str] = {
            "Accept": "application/json, application/yaml, text/yaml, */*",
            "User-Agent": "api2mcp-autodiscovery/1.0",
            **(headers or {}),
        }
        self._probe_graphql = probe_graphql
        self._parse_html_links = parse_html_links
        self._extra_paths: list[str] = extra_paths or []
        self._client: httpx.AsyncClient | None = None

    # ------------------------------------------------------------------
    # Context manager support
    # ------------------------------------------------------------------

    async def __aenter__(self) -> SpecDiscoverer:
        self._client = httpx.AsyncClient(
            timeout=self._timeout,
            max_redirects=self._max_redirects,
            headers=self._base_headers,
            follow_redirects=True,
        )
        return self

    async def __aexit__(self, *_args: object) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def discover(self, url: str) -> DiscoveryResult:
        """Discover API specs reachable from *url*.

        If *url* points directly to a known spec (returns JSON/YAML with a
        recognisable format) it is returned immediately.  Otherwise the engine:

        1. Probes common spec paths relative to the base URL.
        2. Parses any HTML response for embedded spec links.
        3. Optionally sends a GraphQL introspection query to ``/graphql``.

        Args:
            url: Base URL of the API (e.g. ``https://api.example.com``) or a
                 direct URL to a spec file.

        Returns:
            :class:`DiscoveryResult` with all specs found.
        """
        result = DiscoveryResult(base_url=url)

        # Use an existing shared client (context-manager mode) or create a
        # temporary one that we own and must close.
        owned: httpx.AsyncClient | None = None
        if self._client is not None:
            active: httpx.AsyncClient = self._client
        else:
            owned = httpx.AsyncClient(
                timeout=self._timeout,
                max_redirects=self._max_redirects,
                headers=self._base_headers,
                follow_redirects=True,
            )
            active = owned

        try:
            await self._run_discovery(url, result, active)
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"Discovery failed for {url}: {exc}")
        finally:
            if owned is not None:
                await owned.aclose()

        # Sort: known formats first, then by URL path length (shorter = more likely canonical)
        result.specs.sort(key=lambda s: (s.format == SpecFormat.UNKNOWN, len(s.url)))
        return result

    async def detect(self, url: str) -> SpecFormat:
        """Quick format detection for a single URL without full discovery."""
        result = await self.discover(url)
        if result.best:
            return result.best.format
        return SpecFormat.UNKNOWN

    # ------------------------------------------------------------------
    # Internal discovery pipeline
    # ------------------------------------------------------------------

    async def _run_discovery(
        self, url: str, result: DiscoveryResult, client: httpx.AsyncClient
    ) -> None:
        """Full discovery pipeline."""
        # 1. Try the given URL directly
        direct = await self._fetch_spec(url, client)
        if direct is not None:
            if direct.format != SpecFormat.UNKNOWN:
                result.specs.append(direct)
                return  # Direct hit — no need to probe further

            # HTML page → extract links + probe common paths from base
            if _is_html(direct.content_type):
                if self._parse_html_links:
                    linked = await self._follow_html_links(direct.content, url, client)
                    result.specs.extend(linked)
                    if result.found:
                        return

        # 2. Normalise base URL
        base = _base_url(url)

        # 3. Probe common paths
        probe_paths = [*self._extra_paths, *COMMON_PATHS]
        seen: set[str] = {url, base}
        for path in probe_paths:
            probe_url = base + path
            if probe_url in seen:
                continue
            seen.add(probe_url)

            # GraphQL: special handling with introspection query
            if path == "/graphql" and self._probe_graphql:
                gql_spec = await self._probe_graphql_endpoint(probe_url, client)
                if gql_spec is not None:
                    result.specs.append(gql_spec)
                continue

            spec = await self._fetch_spec(probe_url, client)
            if spec is None:
                continue

            if spec.format != SpecFormat.UNKNOWN:
                result.specs.append(spec)
            elif _is_html(spec.content_type) and self._parse_html_links:
                linked = await self._follow_html_links(spec.content, probe_url, client)
                result.specs.extend(linked)

    async def _fetch_spec(
        self, url: str, client: httpx.AsyncClient
    ) -> DiscoveredSpec | None:
        """Fetch *url* and return a :class:`DiscoveredSpec`, or ``None`` on error."""
        try:
            resp = await client.get(url)
        except (httpx.RequestError, httpx.HTTPStatusError) as exc:
            logger.debug("fetch failed %s: %s", url, exc)
            return None

        if resp.status_code >= 400:
            return None

        content = resp.text
        ct = resp.headers.get("content-type", "")
        final_url = str(resp.url)

        fmt, parsed = detect_format_from_content(content, ct, final_url)

        return DiscoveredSpec(
            url=final_url,
            content=content,
            format=fmt,
            content_type=ct,
            parsed=parsed,
        )

    async def _follow_html_links(
        self, html: str, page_url: str, client: httpx.AsyncClient
    ) -> list[DiscoveredSpec]:
        """Extract and fetch spec links from an HTML page."""
        found: list[DiscoveredSpec] = []
        links = extract_spec_links_from_html(html, page_url)
        for link in links[:5]:  # cap to avoid runaway crawling
            spec = await self._fetch_spec(link, client)
            if spec is not None and spec.format != SpecFormat.UNKNOWN:
                found.append(spec)
        return found

    async def _probe_graphql_endpoint(
        self, url: str, client: httpx.AsyncClient
    ) -> DiscoveredSpec | None:
        """Send a minimal introspection query to a GraphQL endpoint."""
        try:
            resp = await client.post(
                url,
                content=_GQL_MINIMAL_QUERY,
                headers={"Content-Type": "application/json"},
            )
        except (httpx.RequestError, httpx.HTTPStatusError) as exc:
            logger.debug("GraphQL probe failed %s: %s", url, exc)
            return None

        if resp.status_code >= 400:
            return None

        ct = resp.headers.get("content-type", "")
        content = resp.text

        # A GraphQL endpoint returns JSON with a "data" key
        try:
            data = json.loads(content)
            if isinstance(data, dict) and ("data" in data or "errors" in data):
                return DiscoveredSpec(
                    url=str(resp.url),
                    content=content,
                    format=SpecFormat.GRAPHQL,
                    content_type=ct,
                    parsed=data,
                )
        except (json.JSONDecodeError, ValueError) as exc:
            logger.debug("Ignoring error: %s", exc)

        return None

    # ------------------------------------------------------------------
    # Convenience: discover + parse
    # ------------------------------------------------------------------

    async def discover_and_parse(
        self, url: str
    ) -> tuple[DiscoveryResult, Any]:
        """Discover *url* and immediately parse the best spec found.

        Returns ``(result, api_spec)`` where *api_spec* is an
        :class:`~api2mcp.core.ir_schema.APISpec` or ``None`` if nothing
        was found or parsing failed.
        """
        from api2mcp.parsers.graphql import GraphQLParser
        from api2mcp.parsers.openapi import OpenAPIParser
        from api2mcp.parsers.postman import PostmanParser
        from api2mcp.parsers.swagger import SwaggerParser

        result = await self.discover(url)
        if not result.found or result.best is None:
            return result, None

        spec = result.best
        try:
            if spec.format == SpecFormat.OPENAPI3:
                api_spec = await OpenAPIParser().parse(spec.url)
            elif spec.format == SpecFormat.SWAGGER2:
                api_spec = await SwaggerParser().parse(spec.url)
            elif spec.format == SpecFormat.GRAPHQL:
                api_spec = await GraphQLParser().parse(spec.content)
            elif spec.format == SpecFormat.POSTMAN:
                api_spec = await PostmanParser().parse(spec.content)
            else:
                return result, None
        except ParseException as exc:
            result.errors.append(f"Failed to parse {spec.url}: {exc}")
            return result, None

        return result, api_spec


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _base_url(url: str) -> str:
    """Return scheme://host from a URL (no path/query/fragment)."""
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _is_html(content_type: str) -> bool:
    return "html" in content_type.lower()
