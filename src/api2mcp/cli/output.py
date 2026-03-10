# SPDX-License-Identifier: MIT
"""Rich output helpers for API2MCP CLI.

Centralises all terminal output so commands stay clean.
"""

from __future__ import annotations

import sys
from collections.abc import Generator
from contextlib import contextmanager

from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table
from rich.theme import Theme

_THEME = Theme(
    {
        "info": "cyan",
        "success": "bold green",
        "warning": "bold yellow",
        "error": "bold red",
        "dim": "dim white",
        "header": "bold blue",
    }
)

# On Windows the default console encoding (cp1252) cannot render Unicode
# symbols such as ✓, ✗, ℹ, ⚠.  Force UTF-8 by wrapping sys.stdout/stderr
# with a reconfigured stream when the encoding is not already unicode-capable.
def _utf8_stream(stream: object) -> object:
    """Return *stream* reconfigured for UTF-8 output on Windows if needed."""
    encoding = getattr(stream, "encoding", "utf-8") or "utf-8"
    if encoding.lower().replace("-", "") not in ("utf8", "utf16", "utf32"):
        try:
            return open(  # intentional reconfigure — not a context manager
                stream.fileno(),  # type: ignore[union-attr]
                mode="w",
                encoding="utf-8",
                errors="replace",
                closefd=False,
                buffering=1,
            )
        except Exception:  # noqa: BLE001
            pass
    return stream

console = Console(
    file=_utf8_stream(sys.stdout),  # type: ignore[arg-type]
    theme=_THEME,
    highlight=False,
)
err_console = Console(
    file=_utf8_stream(sys.stderr),  # type: ignore[arg-type]
    stderr=True,
    theme=_THEME,
    highlight=False,
)


def info(msg: str) -> None:
    console.print(f"[info]ℹ[/info]  {msg}")


def success(msg: str) -> None:
    console.print(f"[success]✓[/success]  {msg}")


def warning(msg: str) -> None:
    err_console.print(f"[warning]⚠[/warning]  {msg}")


def error(msg: str) -> None:
    err_console.print(f"[error]✗[/error]  {msg}")


def header(title: str, subtitle: str = "") -> None:
    content = f"[header]{title}[/header]"
    if subtitle:
        content += f"\n[dim]{subtitle}[/dim]"
    console.print(Panel(content, expand=False))


def print_tool_table(tools: list[dict[str, str]]) -> None:
    """Render a table of generated MCP tools."""
    table = Table(
        title="Generated MCP Tools",
        show_header=True,
        header_style="bold cyan",
        border_style="dim",
    )
    table.add_column("Tool Name", style="green")
    table.add_column("Method", style="yellow", width=8)
    table.add_column("Path")
    table.add_column("Description", no_wrap=False)
    for tool in tools:
        table.add_row(
            tool.get("name", ""),
            tool.get("method", ""),
            tool.get("path", ""),
            tool.get("description", ""),
        )
    console.print(table)


@contextmanager
def spinner(description: str) -> Generator[None, None, None]:
    """Context manager that shows a spinner while work is in progress."""
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        progress.add_task(description, total=None)
        yield


@contextmanager
def progress_bar(description: str, total: int) -> Generator[Progress, None, None]:
    """Context manager that shows a determinate progress bar."""
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    ) as progress:
        progress.add_task(description, total=total)
        yield progress
