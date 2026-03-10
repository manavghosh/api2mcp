"""
Notes API — Demo backend for API2MCP LangGraph Demo

A simple in-memory Notes CRUD REST API that ships a full OpenAPI spec.
Run it, then point api2mcp at it to generate an MCP server.

Endpoints:
  GET    /health            — health check
  GET    /notes             — list notes (filter by tag / search query)
  POST   /notes             — create a note
  GET    /notes/{id}        — get a single note
  PUT    /notes/{id}        — update a note (partial update)
  DELETE /notes/{id}        — delete a note
  GET    /stats             — notes statistics summary

Start:  python notes_api.py
Swagger UI: http://localhost:8081/docs
OpenAPI JSON: http://localhost:8081/openapi.json
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# App definition
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Notes API",
    description=(
        "A simple Notes REST API — built to demonstrate multi-API orchestration with API2MCP.\n\n"
        "This API manages notes with full CRUD operations and serves an OpenAPI "
        "spec that api2mcp can consume to generate an MCP server automatically.\n\n"
        "Pre-seeded with 5 sample notes about software development topics."
    ),
    version="1.0.0",
    servers=[{"url": "http://localhost:8081"}],
    contact={"name": "API2MCP Demo", "url": "https://github.com/yourusername/api2mcp"},
    license_info={"name": "MIT"},
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------

_notes: dict[int, dict] = {}
_counter: int = 0


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _seed() -> None:
    """Pre-populate with realistic sample notes about software development."""
    global _counter
    samples = [
        (
            "LangGraph Architecture Notes",
            (
                "LangGraph uses a graph-based architecture for AI workflows. "
                "Nodes represent processing steps, edges define transitions. "
                "State is passed between nodes using TypedDict. "
                "Supports conditional routing, parallel execution, and human-in-the-loop patterns."
            ),
            ["langgraph", "architecture", "ai"],
        ),
        (
            "MCP Protocol Overview",
            (
                "Model Context Protocol (MCP) standardizes how AI models interact with tools. "
                "Servers expose tools via JSON-RPC. Clients discover and call tools dynamically. "
                "Streamable HTTP transport replaced SSE in the 2025-03-26 spec update. "
                "Tool names should be descriptive and follow snake_case convention."
            ),
            ["mcp", "protocol", "ai"],
        ),
        (
            "API2MCP Design Decisions",
            (
                "Key design decisions for API2MCP: "
                "1. Use Intermediate Representation (IR) as the bridge between parsers and generators. "
                "2. StructuredTool factory pattern for LangChain tool adapters. "
                "3. Colon namespacing for tools: github:list_issues, tasks:create_task. "
                "4. TypedDict for LangGraph state (not Pydantic models). "
                "5. Async/await everywhere for non-blocking I/O."
            ),
            ["api2mcp", "design", "architecture"],
        ),
        (
            "Python Async Best Practices",
            (
                "Best practices for async Python: "
                "Use asyncio.run() as the single entry point. "
                "Prefer async context managers for resource cleanup. "
                "Use anyio for backend-agnostic async code. "
                "Avoid mixing sync and async code — use run_in_executor for blocking calls. "
                "Use asyncio.gather() for parallel tasks, asyncio.Queue for producer-consumer patterns."
            ),
            ["python", "async", "best-practices"],
        ),
        (
            "REST API Design Guidelines",
            (
                "REST API design principles: "
                "Use nouns for resources (/tasks, /notes), not verbs. "
                "HTTP methods: GET (read), POST (create), PUT (full update), PATCH (partial), DELETE. "
                "Status codes: 200 OK, 201 Created, 204 No Content, 400 Bad Request, 404 Not Found. "
                "Include operationId in OpenAPI specs for better code generation. "
                "Version your API with /v1/ prefix or Accept header."
            ),
            ["rest", "api", "design"],
        ),
    ]
    for title, content, tags in samples:
        _counter += 1
        _notes[_counter] = {
            "id": _counter,
            "title": title,
            "content": content,
            "tags": tags,
            "created_at": _now(),
            "updated_at": _now(),
        }


_seed()

# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class NoteCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200, description="Note title")
    content: str = Field(..., min_length=1, description="Note content (markdown supported)")
    tags: list[str] = Field(default_factory=list, description="List of tags for categorization")


class NoteUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=200, description="New title")
    content: Optional[str] = Field(None, min_length=1, description="New content")
    tags: Optional[list[str]] = Field(None, description="New tags list (replaces existing)")


class Note(BaseModel):
    id: int = Field(..., description="Unique note ID")
    title: str = Field(..., description="Note title")
    content: str = Field(..., description="Note content")
    tags: list[str] = Field(..., description="Tags for categorization")
    created_at: str = Field(..., description="ISO-8601 creation timestamp (UTC)")
    updated_at: str = Field(..., description="ISO-8601 last-update timestamp (UTC)")


class NoteStats(BaseModel):
    total: int = Field(..., description="Total number of notes")
    tags: dict[str, int] = Field(..., description="Tag usage counts")


class HealthResponse(BaseModel):
    status: str
    note_count: int
    version: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["system"],
    operation_id="health_check",
    summary="Health check",
)
def health_check() -> HealthResponse:
    """Health check — returns OK when the server is ready to accept requests."""
    return HealthResponse(status="ok", note_count=len(_notes), version="1.0.0")


@app.get(
    "/notes",
    response_model=list[Note],
    tags=["notes"],
    operation_id="list_notes",
    summary="List all notes",
)
def list_notes(
    tag: Optional[str] = Query(None, description="Filter notes by tag (exact match)"),
    q: Optional[str] = Query(None, description="Search notes by title or content (case-insensitive)"),
) -> list[dict]:
    """
    List all notes.

    Optionally filter by **tag** (exact match) and/or search with **q** (searches
    title and content, case-insensitive). Multiple filters are combined with AND.
    """
    result = list(_notes.values())
    if tag:
        result = [n for n in result if tag in n["tags"]]
    if q:
        q_lower = q.lower()
        result = [
            n for n in result
            if q_lower in n["title"].lower() or q_lower in n["content"].lower()
        ]
    return result


@app.post(
    "/notes",
    response_model=Note,
    status_code=201,
    tags=["notes"],
    operation_id="create_note",
    summary="Create a new note",
)
def create_note(note: NoteCreate) -> dict:
    """
    Create a new note.

    Returns the newly created note including its assigned **id**.
    Tags are optional — provide an empty list or omit them entirely.
    """
    global _counter
    _counter += 1
    entry: dict = {
        "id": _counter,
        "title": note.title,
        "content": note.content,
        "tags": note.tags,
        "created_at": _now(),
        "updated_at": _now(),
    }
    _notes[_counter] = entry
    return entry


@app.get(
    "/notes/{note_id}",
    response_model=Note,
    tags=["notes"],
    operation_id="get_note",
    summary="Get a note by ID",
)
def get_note(note_id: int) -> dict:
    """
    Get a specific note by its numeric ID.

    Returns **404** if the note does not exist.
    """
    if note_id not in _notes:
        raise HTTPException(status_code=404, detail=f"Note {note_id} not found")
    return _notes[note_id]


@app.put(
    "/notes/{note_id}",
    response_model=Note,
    tags=["notes"],
    operation_id="update_note",
    summary="Update a note",
)
def update_note(note_id: int, update: NoteUpdate) -> dict:
    """
    Update an existing note.

    Only the fields you provide are changed — omitted fields keep their
    current values (partial update / PATCH semantics via PUT).
    """
    if note_id not in _notes:
        raise HTTPException(status_code=404, detail=f"Note {note_id} not found")

    note = _notes[note_id]
    if update.title is not None:
        note["title"] = update.title
    if update.content is not None:
        note["content"] = update.content
    if update.tags is not None:
        note["tags"] = update.tags
    note["updated_at"] = _now()
    return note


@app.delete(
    "/notes/{note_id}",
    status_code=204,
    tags=["notes"],
    operation_id="delete_note",
    summary="Delete a note",
)
def delete_note(note_id: int) -> None:
    """
    Delete a note by its ID.

    Returns **204 No Content** on success, **404** if the note does not exist.
    """
    if note_id not in _notes:
        raise HTTPException(status_code=404, detail=f"Note {note_id} not found")
    del _notes[note_id]


@app.get(
    "/stats",
    response_model=NoteStats,
    tags=["notes"],
    operation_id="get_stats",
    summary="Get notes statistics",
)
def get_stats() -> NoteStats:
    """
    Return summary statistics for the notes collection.

    Returns total note count and a breakdown of tag usage counts.
    Useful for a dashboard overview or "what topics do I have notes on?" queries.
    """
    tag_counts: dict[str, int] = {}
    for note in _notes.values():
        for tag in note["tags"]:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1

    return NoteStats(total=len(_notes), tags=tag_counts)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 55)
    print("  Notes API — Demo for API2MCP LangGraph")
    print("=" * 55)
    print(f"  Swagger UI   → http://localhost:8081/docs")
    print(f"  OpenAPI JSON → http://localhost:8081/openapi.json")
    print(f"  Health check → http://localhost:8081/health")
    print("=" * 55)
    uvicorn.run(app, host="0.0.0.0", port=8081, log_level="info")
