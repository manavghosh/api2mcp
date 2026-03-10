# Changelog

All notable changes to API2MCP are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

Changes that are merged to `main` but not yet released.

---

## [0.1.0] — 2026-03-08

Initial public open source release.

### Added

#### Core Parser Engine
- OpenAPI 3.0 / 3.1 parser with full Intermediate Representation (IR) output
- Swagger 2.0 migration support (auto-upgrades to IR)
- GraphQL schema parser
- Postman Collection v2.1 parser
- API spec auto-discovery (scans directories and URLs for specs)

#### MCP Generator Engine
- IR → MCP Server code generator (Jinja2 templates)
- Streamable HTTP transport (SSE deprecated per MCP spec 2025-03-26)
- Stdio transport for Claude Desktop compatibility
- Hot reload support via `watchfiles`
- Template registry with pluggable generator templates

#### LangGraph Orchestration
- `MCPToolAdapter` — bridges MCP tools to LangChain `StructuredTool`
- `MCPToolRegistry` — central tool discovery with colon namespacing (`github:list_issues`)
- `ReactiveGraph` — wraps `create_react_agent` for single-API ReAct workflows
- `PlannerGraph` — sequential, parallel, and mixed execution modes for multi-API workflows
- `ConversationalGraph` — multi-turn conversation with human-in-loop support
- `LLMFactory` — provider-agnostic factory for Anthropic, OpenAI, and Google models
- Checkpointing via official `langgraph-checkpoint-*` packages (Memory, SQLite)
- End-to-end streaming for tool responses and workflow progress
- Orchestration error handling with retry policies and partial completion

#### Authentication Framework
- API key, Bearer token, Basic auth providers
- Custom auth provider support
- Secret management via `keyring` and environment variables

#### Runtime
- Health check endpoint
- Request logger
- Rate limiting with header-based detection
- Circuit breaker pattern
- Connection pooling
- Response caching (memory and disk)
- Async concurrency primitives

#### CLI
- `api2mcp generate` — generate MCP server from spec
- `api2mcp serve` — start MCP server (HTTP or stdio)
- `api2mcp validate` — validate an OpenAPI/GraphQL spec
- `api2mcp orchestrate` — run a LangGraph workflow from the CLI
- `api2mcp diff` — compare two API specs
- `api2mcp export` — export generated server artifacts
- `api2mcp dev` — development mode with hot reload
- `api2mcp wizard` — interactive setup wizard
- `api2mcp template` — manage generator templates

#### Developer Experience
- Interactive setup wizard
- VS Code extension schema (`schemas/api2mcp-config.schema.json`)
- Testing framework for MCP servers (`src/api2mcp/testing/`)
- Plugin system for extending parsers and generators
- Observability hooks

#### Documentation
- Full MkDocs documentation site
- Getting started guide
- CLI reference
- IR schema reference
- Tutorials: quickstart, multi-API orchestration, authentication
- API reference (auto-generated)

#### CI/CD
- GitHub Actions workflow: test, lint, type-check, security scan
- Dockerfile and docker-compose for containerised deployments
- Docs deployment to GitHub Pages

#### Demos
- `demo-langgraph/` — LangGraph orchestration demo with local FastAPI backends
- `demo-live-api/` — Live API demo with three public internet APIs (Petstore, Open-Meteo, JSONPlaceholder)
- Multi-server tool routing verification scripts (bash + PowerShell)

### Security

- SQL injection check in validation pipeline (before command injection check)
- Catches `TypeError` on malformed schema inputs
- Input validation with configurable limits

---

[Unreleased]: https://github.com/manavghosh/api2mcp/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/manavghosh/api2mcp/releases/tag/v0.1.0
