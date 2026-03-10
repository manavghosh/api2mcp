# API2MCP Project Context

## Project Overview

API2MCP is an open-source Python framework that automatically converts REST/GraphQL APIs into MCP (Model Context Protocol) servers, with an integrated LangGraph orchestration layer for intelligent multi-API workflows.

## Project Status

- PRD v3.0 and setup-spec-kit.sh v3.0 are finalized
- **Next:** Run `setup-spec-kit.sh` → `/prd-to-spec` → `/generate-tasks` → Begin Phase 1 (F1.1)
- Timeline: 24 weeks (optimized from 30), 4 parallel teams

## Key Documentation

| Document | Description |
|----------|-------------|
| `api2mcp-langgraph-setup/PRD.md` | Product Requirements Document v3.0 (source of truth) |
| `api2mcp-langgraph-setup/setup-spec-kit.sh` | Bootstrap script that scaffolds full project structure |
| `api2mcp-langgraph-setup/plan.md` | Design review & agent teams implementation plan |
| `.spec/` | Spec-Kit specifications directory (created by setup script) |
| `.spec/orchestration/` | LangGraph integration specs |
| `docs/` | User documentation |

## Architecture Summary

```
Client → LangGraph Orchestration → MCP Tool Registry → MCP Servers → APIs
```

### Core Components

1. **Parser Engine**: OpenAPI/GraphQL → Intermediate Representation
2. **Generator Engine**: IR → MCP Server code
3. **Orchestration Engine** (NEW): LangGraph workflows for multi-API coordination
4. **Runtime**: MCP protocol implementation (Streamable HTTP transport, not SSE — SSE deprecated in MCP spec 2025-03-26)

### Orchestration Components (LangGraph 1.0+)

- **MCPToolAdapter**: Bridges MCP tools to LangChain StructuredTool (via factory, not BaseTool subclass)
- **MCPToolRegistry**: Central tool discovery with colon namespacing (github:list_issues)
- **Graph Patterns**: Reactive (wraps create_react_agent), Planner (sequential/parallel/mixed), Conversational (human-in-loop)
- **Checkpointing**: Official langgraph-checkpoint-* packages (Memory, SQLite, PostgreSQL)
- **Error Handling**: Classification, retry policies, partial completion, fallbacks
- **Streaming**: End-to-end streaming for tool responses and workflow progress

## Development Workflow

This project uses Specification-Driven Development (SDD) with Spec-Kit:

1. **Specifications** define WHAT to build (`.spec/features/`)
2. **Plans** define HOW to build it (`.spec/phases/`)
3. **Tasks** break down the work (`.spec/tasks/`)
4. **Implementation** follows the specs

## Custom Slash Commands

| Command | Purpose |
|---------|---------|
| `/prd-to-spec` | Convert PRD.md to spec files |
| `/generate-tasks` | Create task breakdown from specs |
| `/implement-feature` | Implement a specific feature |
| `/orchestration-design` | Design orchestration workflow |

## Testing Requirements

- Every feature must have a Testing Strategy section
- Test categories: Unit, Integration, E2E, Performance
- Minimum coverage: 80% overall, 100% for critical paths
- Orchestration requires graph execution tests

## Research & Dependency Verification

- **Always use Ref and Exa MCP servers** for research when implementing features
- Before adding or updating dependencies, use `mcp__exa__get_code_context_exa` and `mcp__Ref__ref_search_documentation` to verify the latest stable versions on PyPI
- Check official documentation via Ref before using any library API to ensure correctness
- This applies to: MCP SDK, LangGraph, Starlette, uvicorn, httpx, Pydantic, anyio, and all other dependencies

## Code Style

- Python 3.11+
- Type hints required everywhere
- Async/await for all I/O operations
- Follow PEP 8
- Use Pydantic for data validation

## Key Dependencies

### Core
- `pyyaml`, `pydantic`, `httpx`, `click`, `rich`, `jinja2`, `graphql-core`, `watchfiles`

### Orchestration (LangGraph 1.0+)
- `langgraph>=1.0.0`
- `langgraph-prebuilt>=1.0.0` (create_react_agent)
- `langgraph-checkpoint>=2.0.0` (MemorySaver)
- `langgraph-checkpoint-sqlite>=2.0.0`
- `langchain-core>=1.0.0`
- `langchain-anthropic>=1.0.0`
- `tenacity>=8.0` (retry logic)

### MCP
- `mcp>=1.0,<2` (pinned below v2 until compatibility verified)

## Phase Structure (4 Parallel Teams)

| Weeks | Team 1 (Core) | Team 2 (Security/Infra) | Team 3 (Orchestration) | Team 4 (Parsing/DX) |
|-------|---------------|------------------------|----------------------|---------------------|
| 1-4 | F1.1-F1.4 | — | — | — |
| 5-8 | — | F2.1-F2.2 | F5.1-F5.2 | F3.1-F3.2 |
| 9-12 | — | F2.3-F2.4 | F5.3-F5.4 | F3.3-F3.4 |
| 13-16 | — | F4.1-F4.4 | F5.5-F5.6 | F6.1-F6.3 |
| 17-20 | DX (F6.x) | — | — | — |
| 21-24 | Ecosystem (F7.x) | — | — | — |

**Critical Path:** F1.1 → F1.2 → F1.3 → F5.1 → F5.2 → F5.4 → F5.5

## Important Patterns

### Intermediate Representation (IR)
The IR is the critical data structure bridging ALL parsers to ALL generators. Every parser outputs IR; every generator consumes IR. Changes to the IR schema affect the entire pipeline.

### LangGraph State (TypedDict)
All graph state definitions use `TypedDict` (correct per LangGraph 1.0 docs), not Pydantic models.

### MCP Tool Adapter Pattern
```python
# Uses StructuredTool factory (not BaseTool subclass)
tool = await MCPToolAdapter.from_mcp_tool(session, tool, "github")
result = await tool.ainvoke({"owner": "user", "repo": "project"})
```

### Tool Registry Pattern (colon namespacing)
```python
registry = MCPToolRegistry()
await registry.register_server("github", github_session)
tools = registry.get_tools(category="read")  # Returns github:list_issues, etc.
```

### LangGraph Workflow Pattern (with official checkpointer)
```python
from langgraph.checkpoint.sqlite import SqliteSaver
checkpointer = SqliteSaver.from_conn_string("workflows.db")
graph = PlannerGraph(model, registry, ["github", "jira"], checkpointer=checkpointer)
result = await graph.run("Sync issues to Jira")
```

## File Locations

| Component | Location |
|-----------|----------|
| Orchestration | `src/api2mcp/orchestration/` |
| Graph Patterns | `src/api2mcp/orchestration/graphs/` |
| State Definitions | `src/api2mcp/orchestration/state/` |
| Checkpointing | `src/api2mcp/orchestration/checkpointing/` |
| CLI Commands | `src/api2mcp/cli/commands/orchestrate.py` |
