# API2MCP Roadmap

This document describes the planned direction for API2MCP. It is a living document — priorities may shift based on community feedback, usage patterns, and the evolving MCP ecosystem.

For the full feature backlog and task breakdown see the [GitHub Issues](https://github.com/manavghosh/api2mcp/issues) and [Discussions](https://github.com/manavghosh/api2mcp/discussions).

---

## Current Release — v0.1.0 (March 2026)

The initial public release covers the full core feature set:

### Core Pipeline
- [x] OpenAPI 3.0/3.1 parser → Intermediate Representation (IR)
- [x] Swagger 2.0 migration (auto-upgrade to OpenAPI 3.x)
- [x] GraphQL SDL parser
- [x] Postman Collection v2.0/v2.1 parser
- [x] MCP Tool Generator (IR → MCP tool definitions)
- [x] Streamable HTTP transport (MCP spec 2025-03-26)
- [x] stdio transport (Claude Desktop / development)

### Security & Infrastructure
- [x] Authentication framework: API key, Bearer, Basic, OAuth2 (client credentials + PKCE)
- [x] Secret management: env vars, system keychain, AWS Secrets Manager, HashiCorp Vault
- [x] Input validation pipeline with SQL/command injection protection
- [x] Per-endpoint rate limiting (token bucket)
- [x] Circuit breaker pattern

### Performance
- [x] Response caching (memory + Redis backends)
- [x] Connection pooling with health checks
- [x] Async concurrency limiting
- [x] Async-first throughout

### Orchestration (LangGraph 1.0+)
- [x] MCP Tool Adapter (MCP → LangChain StructuredTool)
- [x] MCP Tool Registry with colon namespacing (`github:list_issues`)
- [x] ReactiveGraph — single-API ReAct agent
- [x] PlannerGraph — multi-API sequential/parallel/mixed planner
- [x] ConversationalGraph — multi-turn with human-in-the-loop
- [x] Checkpointing: MemorySaver, SQLite, PostgreSQL
- [x] End-to-end streaming (LangGraph astream_events v2)
- [x] Orchestration error handling, retry policies, partial completion

### Developer Experience
- [x] Interactive setup wizard (`api2mcp wizard`)
- [x] Hot reload dev server (`api2mcp dev`)
- [x] Testing framework: MCPTestClient, CoverageReporter
- [x] VS Code integration (settings, launch configs, tasks, schema validation)
- [x] Template registry for custom code generation
- [x] Plugin system with lifecycle hooks
- [x] CLI: generate, serve, dev, orchestrate, export, diff, validate

### Documentation & CI
- [x] MkDocs Material documentation site
- [x] Tutorials: basic, auth, orchestration, multi-API
- [x] Runnable examples (GitHub, Stripe, multi-API, conversational)
- [x] CI: test (3.11/3.12/3.13), lint, type-check, security scan
- [x] Release automation via OIDC (no stored secrets)
- [x] Dependabot + dependency review

---

## Near-Term — v0.2.0 (Q2 2026)

**Theme: Ecosystem & Polish**

### Parser Improvements
- [ ] OpenAPI 3.2 support (when spec is finalised)
- [ ] AsyncAPI 3.0 parser (event-driven APIs)
- [ ] HAR file importer (browser network captures → MCP server)
- [ ] Auto-discovery improvements: mDNS, well-known URL patterns

### Orchestration
- [ ] Multi-model support: Gemini 2.0, GPT-4o, Mistral in the same workflow
- [ ] Parallel tool execution within a single graph node
- [ ] Workflow templates library (billing sync, issue triage, data pipeline)
- [ ] Visual workflow editor (web UI, generates PlannerGraph config)

### Transport & Protocol
- [ ] WebSocket transport (real-time bidirectional MCP)
- [ ] MCP v2 compatibility (when v2 is stable — anticipated Q2 2026)
- [ ] gRPC transport adapter

### Developer Experience
- [ ] `api2mcp test` command — run MCPTestClient test suites from CLI
- [ ] Coverage report HTML output (`--cov-report html`)
- [ ] Pre-built Docker images on GitHub Container Registry
- [ ] Helm chart for Kubernetes deployment
- [ ] GitHub Copilot / Cursor integration guide

### Community
- [ ] Curated template marketplace (hosted templates for popular APIs)
- [ ] Plugin registry (community plugins)
- [ ] First "good first issue" batch labelled

---

## Medium-Term — v0.3.0 (Q3 2026)

**Theme: Enterprise Readiness**

- [ ] RBAC (role-based access control) for MCP tool exposure
- [ ] Audit logging (structured, tamper-evident tool call logs)
- [ ] Multi-tenant server mode (namespace isolation per client)
- [ ] OpenTelemetry tracing integration (spans for every tool call)
- [ ] Prometheus metrics endpoint (`/metrics`)
- [ ] SLA-aware retry policies (deadline propagation)
- [ ] Federated MCP registry (discover tools across organisations)

---

## Long-Term — v1.0.0 (Q4 2026)

**Theme: Stability & Production Grade**

- [ ] Stable public API with semantic versioning guarantees
- [ ] Backwards compatibility policy (deprecation notices, 2-version runway)
- [ ] MCP conformance test suite (verify generated servers pass the full MCP spec)
- [ ] Performance benchmarks published and tracked in CI
- [ ] Official integrations: Claude Desktop, Cursor, VS Code Copilot, Open WebUI
- [ ] Hosted SaaS option (api2mcp.io) — optional, community-driven

---

## How to Influence the Roadmap

The roadmap is community-driven. The best ways to influence it:

1. **Vote on existing issues** — thumb up 👍 features you want
2. **Open a discussion** — propose new features in [GitHub Discussions](https://github.com/manavghosh/api2mcp/discussions/categories/ideas)
3. **Submit a PR** — contributions welcome, see [CONTRIBUTING.md](./CONTRIBUTING.md)
4. **Sponsor the project** — sponsor via [GitHub Sponsors](https://github.com/sponsors/manavghosh) to fund prioritised development

Items on this roadmap are not commitments — they represent current intent subject to change. Dates are targets, not guarantees.
