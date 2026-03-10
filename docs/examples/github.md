# Example: GitHub Issues MCP Server

This example converts the GitHub Issues REST API into an MCP server and
uses it in a LangGraph workflow.

---

## 1. Install the Template

```bash
api2mcp template install github-issues
```

Or generate from the public OpenAPI spec:

```bash
# Download GitHub's OpenAPI spec (subset)
curl -o github.yaml https://raw.githubusercontent.com/github/rest-api-description/main/descriptions/api.github.com/api.github.com.yaml

api2mcp generate github.yaml --output ./github-server
```

---

## 2. Configure Authentication

GitHub uses Bearer token authentication.  Create `.api2mcp.yaml`:

```yaml
auth:
  type: bearer
  token_env: GITHUB_TOKEN

rate_limit:
  strategy: sliding_window
  requests_per_minute: 60    # GitHub's rate limit for authenticated requests
  retry_after: true
```

Set your token:

```bash
export GITHUB_TOKEN="ghp_your_personal_access_token"
```

---

## 3. Start the Server

```bash
api2mcp serve ./github-server --port 8001
```

Tools available:

```
github:list_issues          List repository issues
github:get_issue            Get a single issue by number
github:create_issue         Create a new issue
github:update_issue         Update an existing issue
github:list_issue_comments  List comments on an issue
github:create_issue_comment Add a comment to an issue
github:close_issue          Close an issue
```

---

## 4. Use in a LangGraph Workflow

```python
import asyncio
import os
from langchain_anthropic import ChatAnthropic
from langgraph.checkpoint.memory import MemorySaver
from api2mcp.orchestration.adapters.registry import MCPToolRegistry
from api2mcp.orchestration.graphs.reactive import ReactiveGraph
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    registry = MCPToolRegistry()

    # Connect GitHub MCP server
    params = StdioServerParameters(command="python", args=["github-server/server.py"])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await registry.register_server("github", session)

            model = ChatAnthropic(
                model="claude-sonnet-4-6",
                api_key=os.environ["ANTHROPIC_API_KEY"],
            )
            graph = ReactiveGraph(
                model=model,
                registry=registry,
                api_names=["github"],
                checkpointer=MemorySaver(),
            )

            # Ask the agent to do something
            result = await graph.run(
                "List the 5 most recently opened issues in the "
                "anthropics/claude-code repository and summarise them."
            )
            print(result["output"])


asyncio.run(main())
```

---

## 5. Testing

```python
import asyncio
from api2mcp.testing import MCPTestClient, CoverageReporter

async def test_github_server():
    async with MCPTestClient(server_dir="./github-server", seed=42) as client:
        tools = await client.list_tools()

        # Test list_issues
        result = await client.call_tool("list_issues", {"owner": "api2mcp", "repo": "api2mcp"})
        assert result.status == "success"

        # Test error scenario (404)
        result = await client.call_tool(
            "get_issue",
            {"owner": "api2mcp", "repo": "api2mcp", "issue_number": 999},
            scenario="not_found",
        )
        assert result.status == "error"
        assert result.status_code == 404

        reporter = CoverageReporter.from_client(client)

    report = reporter.report()
    print(report.summary())

asyncio.run(test_github_server())
```

---

## 6. Generated Tool Definition

Example of what the `list_issues` tool looks like after generation:

```json
{
  "name": "list_issues",
  "description": "List issues in a repository",
  "inputSchema": {
    "type": "object",
    "properties": {
      "owner": {"type": "string", "description": "Repository owner (user or org)"},
      "repo":  {"type": "string", "description": "Repository name"},
      "state": {"type": "string", "enum": ["open", "closed", "all"], "default": "open"},
      "labels": {"type": "string", "description": "Comma-separated label names"},
      "per_page": {"type": "integer", "minimum": 1, "maximum": 100, "default": 30},
      "page": {"type": "integer", "minimum": 1, "default": 1}
    },
    "required": ["owner", "repo"]
  }
}
```
