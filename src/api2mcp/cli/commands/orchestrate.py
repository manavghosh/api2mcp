"""``api2mcp orchestrate`` — run a LangGraph workflow from the CLI."""
from __future__ import annotations

import logging
from typing import Optional

import click

from api2mcp.cli import output

logger = logging.getLogger(__name__)


@click.command("orchestrate")
@click.argument("prompt")
@click.option(
    "--server",
    "servers",
    multiple=True,
    metavar="NAME=URL",
    help="MCP server to connect (name=url). Repeatable.",
)
@click.option(
    "--graph",
    type=click.Choice(["reactive", "planner", "conversational"], case_sensitive=False),
    default="reactive",
    show_default=True,
    help="LangGraph workflow type.",
)
@click.option(
    "--mode",
    type=click.Choice(["sequential", "parallel", "mixed"], case_sensitive=False),
    default="sequential",
    show_default=True,
    help="Execution mode (planner graph only).",
)
@click.option(
    "--model",
    default="claude-sonnet-4-6",
    show_default=True,
    help="Claude model ID.",
)
@click.option(
    "--thread-id",
    default=None,
    help="Thread ID for checkpointing / conversation memory.",
)
@click.option("--stream", is_flag=True, help="Stream output tokens in real-time.")
@click.option(
    "--checkpoint",
    default=None,
    help="SQLite DB path for checkpointing (default: in-memory).",
)
@click.option(
    "--output-format",
    "output_format",
    type=click.Choice(["text", "json"], case_sensitive=False),
    default="text",
    show_default=True,
    help="Output format.",
)
@click.option(
    "--api-name",
    "api_names",
    multiple=True,
    metavar="NAME",
    help="API name to expose (from --server). Repeatable. Defaults to all registered servers.",
)
def orchestrate_cmd(
    prompt: str,
    servers: tuple[str, ...],
    graph: str,
    mode: str,
    model: str,
    thread_id: Optional[str],
    stream: bool,
    checkpoint: Optional[str],
    output_format: str,
    api_names: tuple[str, ...],
) -> None:
    """Run a LangGraph orchestration workflow.

    PROMPT is the natural-language task description.

    \b
    Example:
      api2mcp orchestrate "List open issues" \\
        --server github=http://localhost:8001 \\
        --graph reactive --stream
    """
    # Parse server name=url pairs
    server_map: dict[str, str] = {}
    for entry in servers:
        if "=" not in entry:
            raise click.UsageError(f"--server must be NAME=URL, got: {entry!r}")
        name, url = entry.split("=", 1)
        server_map[name.strip()] = url.strip()

    output.info(f"Running [bold]{graph}[/bold] graph with model [bold]{model}[/bold]")
    if server_map:
        for sname, surl in server_map.items():
            output.info(f"  Server: {sname} → {surl}")

    try:
        import asyncio
        asyncio.run(
            _run_workflow(
                prompt=prompt,
                graph_type=graph,
                mode=mode,
                model_id=model,
                servers=server_map,
                api_names=api_names,
                thread_id=thread_id,
                stream=stream,
                checkpoint_db=checkpoint,
                output_format=output_format,
            )
        )
    except KeyboardInterrupt:
        output.info("\nWorkflow interrupted.")


async def _run_workflow(
    *,
    prompt: str,
    graph_type: str,
    mode: str,
    model_id: str,
    servers: dict[str, str],
    api_names: tuple[str, ...],
    thread_id: Optional[str],
    stream: bool,
    checkpoint_db: Optional[str],
    output_format: str,
) -> None:
    """Build and run the requested LangGraph workflow."""
    from api2mcp.cli import output as out

    _ = mode  # used for planner graph selection in future
    _ = stream  # streaming handled by graph run() in future

    try:
        from langchain_anthropic import ChatAnthropic  # type: ignore[import-not-found]
        model = ChatAnthropic(model=model_id)  # type: ignore[call-arg]
    except ImportError:
        raise click.ClickException(
            "langchain-anthropic is required for orchestrate. "
            "Install: pip install langchain-anthropic"
        )

    # Set up checkpointer
    checkpointer = None
    if checkpoint_db:
        try:
            from langgraph.checkpoint.sqlite import SqliteSaver  # type: ignore[import-not-found]
            checkpointer = SqliteSaver.from_conn_string(checkpoint_db)
        except ImportError:
            pass

    if servers:
        out.warning("Live MCP server connections not yet wired — running without tools.")

    # Build a real (empty) registry — live server connections are future work
    from api2mcp.orchestration.adapters.registry import MCPToolRegistry
    registry = MCPToolRegistry()

    # Import the correct graph class
    graph_map = {
        "reactive": "api2mcp.orchestration.graphs.reactive.ReactiveGraph",
        "planner": "api2mcp.orchestration.graphs.planner.PlannerGraph",
        "conversational": "api2mcp.orchestration.graphs.conversational.ConversationalGraph",
    }
    module_path, class_name = graph_map[graph_type].rsplit(".", 1)
    import importlib
    mod = importlib.import_module(module_path)
    graph_cls = getattr(mod, class_name)

    if graph_type == "reactive":
        # ReactiveGraph requires exactly one api_name
        single_api = (
            api_names[0]
            if api_names
            else (list(servers.keys())[0] if servers else "default")
        )
        graph = graph_cls(model, registry, api_name=single_api, checkpointer=checkpointer)
    elif graph_type == "planner":
        # PlannerGraph requires a list of api_names
        names = list(api_names) if api_names else (list(servers.keys()) or ["default"])
        graph = graph_cls(model, registry, api_names=names, checkpointer=checkpointer)
    else:  # conversational
        names_or_none = list(api_names) if api_names else (list(servers.keys()) or None)
        graph = graph_cls(model, registry, api_names=names_or_none, checkpointer=checkpointer)

    config = {"configurable": {"thread_id": thread_id or "default"}}
    result = await graph.run(prompt, config=config)

    if output_format == "json":
        import json
        out.info(json.dumps({"result": str(result)}, indent=2))
    else:
        out.info(str(result))
