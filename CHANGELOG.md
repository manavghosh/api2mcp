# Changelog

All notable changes to API2MCP are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Added
- Per-endpoint request timeout configuration
- Wheel export format (`api2mcp export --format wheel`)
- MCP Resource generator for GET endpoints
- MCP Prompt generator for all endpoints
- VS Code `tasks.json` with test/lint/serve tasks
- Cron-based scheduling in `ScheduleTrigger`
- Plugin hooks: `PRE_PARSE`, `PRE_GENERATE`, `POST_GENERATE`, `PRE_SERVE`
- Orchestration classes exported from top-level `api2mcp` package
- Diff now compares parameter types and required status, not just names
- Exception `code` attribute on all `API2MCPError` subclasses
- Orchestration section in CLI config and JSON schema
- Postman collection version validation (v2.1 only; v1 rejected with clear error)
- Redis URL and OTel endpoint configurable via environment variables
- TLS certificate validation for remote `$ref` fetches

### Fixed
- Conversational graph test isolation — empty registry now correctly shows "(none registered)"

## [0.1.0] — 2026-03-07

### Added
- OpenAPI 3.0/3.1 parser with `$ref` resolution and cycle detection
- MCP tool generator with JSON Schema input schemas
- Runtime server — stdio and Streamable HTTP transports
- CLI commands: `generate`, `serve`, `validate`, `dev`, `orchestrate`, `export`, `diff`, `wizard`, `template`
- Authentication framework — API key, bearer, basic, OAuth2 + PKCE
- Secret management — env, Vault, AWS Secrets Manager, keychain, encrypted file
- Input validation pipeline with SQL/command/XSS injection detection
- Rate limiting — token bucket per tool with retry and backoff
- GraphQL parser
- Swagger 2.0 migration converter
- Postman Collection v2.1 parser
- API spec auto-discovery
- Response caching — memory, Redis, disk backends with TTL and Cache-Control support
- HTTP connection pooling with per-host health checks
- Async concurrency limiting — semaphore-based per-tool cap
- Circuit breaker — CLOSED/OPEN/HALF_OPEN state machine
- MCP Tool Adapter using `StructuredTool` factory pattern
- `MCPToolRegistry` with colon-namespaced tool discovery (`github:list_issues`)
- LangGraph workflow state using `TypedDict`
- `ReactiveGraph` — ReAct agent pattern
- `PlannerGraph` — plan-and-execute with sequential/parallel/mixed modes
- Checkpointing — MemorySaver, SQLite, PostgreSQL via official LangGraph packages
- `ConversationalGraph` — multi-turn with human-in-the-loop and memory strategies
- Orchestration error handling — classification, retry policies, partial completion
- End-to-end streaming for workflow progress
- Interactive CLI wizard
- Hot reload dev server
- Testing framework for generated MCP servers
- VS Code integration — settings, launch configurations, JSON schema validation
- Template registry
- Plugin system — hooks, sandbox, dependency resolution
- Documentation site (MkDocs)
- GitHub Actions CI/CD — test, lint/typecheck, security scan
- Docker: `Dockerfile` and `docker-compose.yml`
- Config JSON schema (14+ keys) for `.api2mcp.yaml`

---

[Unreleased]: https://github.com/manavghosh/api2mcp/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/manavghosh/api2mcp/releases/tag/v0.1.0
