"""
Notes API — Demo backend for API2MCP (Advanced Demo)

A simple in-memory Notes CRUD API that ships a full OpenAPI spec.
Run it, then point api2mcp at it to generate an MCP server.

Endpoints:
  GET    /health              — health check with note count
  GET    /notes               — list notes (filter by tag, title search)
  POST   /notes               — create a note (201)
  GET    /notes/{note_id}     — get a single note (404 if missing)
  PUT    /notes/{note_id}     — partial update (404 if missing)
  DELETE /notes/{note_id}     — delete (204, 404 if missing)
  GET    /stats               — total count + tags breakdown

Start:        python notes_api.py
Swagger UI:   http://localhost:8081/docs
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
        "A simple Notes REST API — built to demonstrate API2MCP multi-API workflows.\n\n"
        "This API manages notes with full CRUD operations, tag-based filtering, and "
        "full-text title search. It serves an OpenAPI spec that api2mcp can consume to "
        "generate an MCP server automatically.\n\n"
        "Pre-seeded with 5 sample notes so there is something to explore immediately "
        "after start."
    ),
    version="1.0.0",
    servers=[{"url": "http://localhost:8081", "description": "Local demo server"}],
    contact={"name": "API2MCP Demo", "url": "https://github.com/yourusername/api2mcp"},
    license_info={"name": "MIT"},
)

# ---------------------------------------------------------------------------
# CORS — allow all origins so the demo works without any browser restrictions
# ---------------------------------------------------------------------------

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
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _seed() -> None:
    """Pre-populate with realistic sample notes so there is data to explore."""
    global _counter
    samples = [
        (
            "Project Setup Notes",
            (
                "Initial project configuration:\n"
                "- Python 3.12 venv created\n"
                "- Pre-commit hooks configured (black, ruff, mypy)\n"
                "- CI/CD pipeline added (GitHub Actions)\n"
                "- Docker Compose for local dev stack"
            ),
            ["setup", "infrastructure", "devops"],
        ),
        (
            "API Design Decisions",
            (
                "Key choices made during API design review:\n"
                "1. REST over GraphQL for simplicity\n"
                "2. Streamable HTTP transport (SSE deprecated in MCP spec 2025-03-26)\n"
                "3. Colon namespacing for MCP tools: github:list_issues\n"
                "4. TypedDict for LangGraph state (not Pydantic models)"
            ),
            ["api", "architecture", "decisions"],
        ),
        (
            "Sprint 1 Retrospective",
            (
                "What went well:\n"
                "- OpenAPI parser shipped on time\n"
                "- 95% unit test coverage on core modules\n\n"
                "What to improve:\n"
                "- Start integration tests earlier\n"
                "- Document edge cases as they are discovered"
            ),
            ["sprint", "retrospective", "process"],
        ),
        (
            "Authentication Strategy",
            (
                "Supported auth methods in order of preference:\n"
                "1. Bearer token (JWT)\n"
                "2. API key (header or query param)\n"
                "3. HTTP Basic\n"
                "4. Custom header\n\n"
                "All secrets loaded from environment variables — never hardcoded."
            ),
            ["api", "security", "auth"],
        ),
        (
            "MCP Tool Naming Conventions",
            (
                "Agreed naming standards for generated MCP tools:\n"
                "- operationId from OpenAPI spec is used as-is if present\n"
                "- Fallback: {method}_{resource} e.g. get_users, create_task\n"
                "- Multi-API: namespace with colon — github:list_issues\n"
                "- Max tool name length: 64 chars (MCP protocol limit)"
            ),
            ["api", "mcp", "conventions"],
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
    """Input model for creating a new note."""

    title: str = Field(..., min_length=1, max_length=300, description="Note title")
    content: str = Field(..., min_length=1, description="Note body content (Markdown supported)")
    tags: list[str] = Field(
        default_factory=list,
        description="List of tags for categorisation (e.g. ['api', 'design'])",
    )


class NoteUpdate(BaseModel):
    """Input model for a partial note update — all fields are optional."""

    title: Optional[str] = Field(None, min_length=1, max_length=300, description="New title")
    content: Optional[str] = Field(None, min_length=1, description="New body content")
    tags: Optional[list[str]] = Field(None, description="Replacement tag list")


class Note(BaseModel):
    """Full note representation returned by the API."""

    id: int = Field(..., description="Unique note ID")
    title: str = Field(..., description="Note title")
    content: str = Field(..., description="Note body content")
    tags: list[str] = Field(..., description="List of tags")
    created_at: str = Field(..., description="ISO-8601 creation timestamp (UTC)")
    updated_at: str = Field(..., description="ISO-8601 last-update timestamp (UTC)")


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = Field(..., description="Always 'ok' when the server is healthy")
    note_count: int = Field(..., description="Number of notes currently stored")
    version: str = Field(..., description="API version")


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
    summary="List notes",
)
def list_notes(
    tag: Optional[str] = Query(
        None,
        description="Filter notes that contain this tag (exact match, case-insensitive)",
    ),
    q: Optional[str] = Query(
        None,
        description="Search notes whose title contains this substring (case-insensitive)",
    ),
) -> list[dict]:
    """
    List all notes.

    Optionally filter by **tag** (exact match, case-insensitive) and/or search
    by **q** (substring match against the title, case-insensitive). Multiple
    filters are combined with AND.
    """
    result = list(_notes.values())
    if tag:
        tag_lower = tag.lower()
        result = [n for n in result if tag_lower in [t.lower() for t in n["tags"]]]
    if q:
        q_lower = q.lower()
        result = [n for n in result if q_lower in n["title"].lower()]
    return result


@app.post(
    "/notes",
    response_model=Note,
    status_code=201,
    tags=["notes"],
    operation_id="create_note",
    summary="Create a note",
)
def create_note(note: NoteCreate) -> dict:
    """
    Create a new note.

    Returns the newly created note including its assigned **id** and timestamps.
    Tags default to an empty list if not provided.
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
    summary="Get a note",
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
    Returns **404** if the note does not exist.
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
    tags=["notes"],
    operation_id="get_stats",
    summary="Get note statistics",
)
def get_stats() -> dict:
    """
    Return summary statistics for the notes store.

    Returns the total note count and a breakdown of how many notes carry
    each tag — useful for a dashboard prompt like "give me a summary of
    all my notes".
    """
    tag_counts: dict[str, int] = {}
    for note in _notes.values():
        for tag in note["tags"]:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1

    return {
        "total": len(_notes),
        "tags": tag_counts,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 55)
    print("  Notes API — Demo for API2MCP (Advanced)")
    print("=" * 55)
    print(f"  Swagger UI   → http://localhost:8081/docs")
    print(f"  OpenAPI JSON → http://localhost:8081/openapi.json")
    print(f"  Health check → http://localhost:8081/health")
    print("=" * 55)
    uvicorn.run(app, host="0.0.0.0", port=8081, log_level="info")
