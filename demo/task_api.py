"""
Task Manager API — Demo backend for API2MCP

A simple in-memory REST API that ships a full OpenAPI spec.
Run it, then point api2mcp at it to generate an MCP server.

Endpoints:
  GET    /health            — health check
  GET    /tasks             — list tasks (filter by status / priority)
  POST   /tasks             — create a task
  GET    /tasks/{id}        — get a single task
  PUT    /tasks/{id}        — update a task
  DELETE /tasks/{id}        — delete a task
  GET    /stats             — task statistics summary

Start:  python task_api.py
Swagger UI: http://localhost:8080/docs
OpenAPI JSON: http://localhost:8080/openapi.json
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# App definition
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Task Manager API",
    description=(
        "A simple Task Manager REST API — built to demonstrate API2MCP.\n\n"
        "This API manages tasks with full CRUD operations and serves an OpenAPI "
        "spec that api2mcp can consume to generate an MCP server automatically.\n\n"
        "Pre-seeded with 5 sample tasks so there is something to explore "
        "immediately after start."
    ),
    version="1.0.0",
    servers=[{"url": "http://localhost:8080", "description": "Local demo server"}],
    contact={"name": "API2MCP Demo", "url": "https://github.com/yourusername/api2mcp"},
    license_info={"name": "MIT"},
)

# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------

_tasks: dict[int, dict] = {}
_counter: int = 0


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _seed() -> None:
    """Pre-populate with realistic sample tasks so there is data to explore."""
    global _counter
    samples = [
        (
            "Set up development environment",
            "Install Python 3.12, VS Code, configure git, and clone the repo.",
            "done",
            "high",
        ),
        (
            "Write unit tests for auth module",
            "Cover all edge cases for JWT token validation and refresh logic.",
            "in_progress",
            "high",
        ),
        (
            "Review open pull requests",
            "Three PRs waiting for review: #42 (auth), #44 (caching), #47 (docs).",
            "pending",
            "high",
        ),
        (
            "Update API documentation",
            "Sync the OpenAPI spec with the latest endpoint changes in v1.2.0.",
            "pending",
            "medium",
        ),
        (
            "Deploy to staging environment",
            "Run smoke tests after deploying v1.2.0 to staging.example.com.",
            "pending",
            "medium",
        ),
    ]
    for title, description, status, priority in samples:
        _counter += 1
        _tasks[_counter] = {
            "id": _counter,
            "title": title,
            "description": description,
            "status": status,
            "priority": priority,
            "created_at": _now(),
            "updated_at": _now(),
        }


_seed()

# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

STATUS_VALUES = ["pending", "in_progress", "done"]
PRIORITY_VALUES = ["low", "medium", "high"]


class TaskCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200, description="Task title")
    description: Optional[str] = Field(None, description="Optional detailed description")
    status: str = Field("pending", description="Task status: pending | in_progress | done")
    priority: str = Field("medium", description="Task priority: low | medium | high")


class TaskUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=200, description="New title")
    description: Optional[str] = Field(None, description="New description")
    status: Optional[str] = Field(None, description="New status: pending | in_progress | done")
    priority: Optional[str] = Field(None, description="New priority: low | medium | high")


class Task(BaseModel):
    id: int = Field(..., description="Unique task ID")
    title: str = Field(..., description="Task title")
    description: Optional[str] = Field(None, description="Detailed description")
    status: str = Field(..., description="Current status")
    priority: str = Field(..., description="Priority level")
    created_at: str = Field(..., description="ISO-8601 creation timestamp (UTC)")
    updated_at: str = Field(..., description="ISO-8601 last-update timestamp (UTC)")


class Stats(BaseModel):
    total: int
    by_status: dict[str, int]
    by_priority: dict[str, int]


class HealthResponse(BaseModel):
    status: str
    task_count: int
    version: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/health", response_model=HealthResponse, tags=["system"])
def health_check() -> HealthResponse:
    """Health check — returns OK when the server is ready to accept requests."""
    return HealthResponse(status="ok", task_count=len(_tasks), version="1.0.0")


@app.get("/tasks", response_model=list[Task], tags=["tasks"])
def list_tasks(
    status: Optional[str] = Query(None, description="Filter by status: pending | in_progress | done"),
    priority: Optional[str] = Query(None, description="Filter by priority: low | medium | high"),
) -> list[dict]:
    """
    List all tasks.

    Optionally filter by **status** (pending, in_progress, done) and/or
    **priority** (low, medium, high). Multiple filters are combined with AND.
    """
    result = list(_tasks.values())
    if status:
        result = [t for t in result if t["status"] == status]
    if priority:
        result = [t for t in result if t["priority"] == priority]
    return result


@app.post("/tasks", response_model=Task, status_code=201, tags=["tasks"])
def create_task(task: TaskCreate) -> dict:
    """
    Create a new task.

    Returns the newly created task including its assigned **id**.
    Default status is *pending*, default priority is *medium*.
    """
    global _counter

    if task.status not in STATUS_VALUES:
        raise HTTPException(
            status_code=422,
            detail=f"status must be one of: {STATUS_VALUES}",
        )
    if task.priority not in PRIORITY_VALUES:
        raise HTTPException(
            status_code=422,
            detail=f"priority must be one of: {PRIORITY_VALUES}",
        )

    _counter += 1
    entry: dict = {
        "id": _counter,
        "title": task.title,
        "description": task.description,
        "status": task.status,
        "priority": task.priority,
        "created_at": _now(),
        "updated_at": _now(),
    }
    _tasks[_counter] = entry
    return entry


@app.get("/tasks/{task_id}", response_model=Task, tags=["tasks"])
def get_task(task_id: int) -> dict:
    """
    Get a specific task by its numeric ID.

    Returns **404** if the task does not exist.
    """
    if task_id not in _tasks:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return _tasks[task_id]


@app.put("/tasks/{task_id}", response_model=Task, tags=["tasks"])
def update_task(task_id: int, update: TaskUpdate) -> dict:
    """
    Update an existing task.

    Only the fields you provide are changed — omitted fields keep their
    current values (partial update / PATCH semantics via PUT).
    """
    if task_id not in _tasks:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    if update.status and update.status not in STATUS_VALUES:
        raise HTTPException(status_code=422, detail=f"status must be one of: {STATUS_VALUES}")
    if update.priority and update.priority not in PRIORITY_VALUES:
        raise HTTPException(status_code=422, detail=f"priority must be one of: {PRIORITY_VALUES}")

    task = _tasks[task_id]
    if update.title is not None:
        task["title"] = update.title
    if update.description is not None:
        task["description"] = update.description
    if update.status is not None:
        task["status"] = update.status
    if update.priority is not None:
        task["priority"] = update.priority
    task["updated_at"] = _now()
    return task


@app.delete("/tasks/{task_id}", status_code=204, tags=["tasks"])
def delete_task(task_id: int) -> None:
    """
    Delete a task by its ID.

    Returns **204 No Content** on success, **404** if the task does not exist.
    """
    if task_id not in _tasks:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    del _tasks[task_id]


@app.get("/stats", response_model=Stats, tags=["tasks"])
def get_stats() -> Stats:
    """
    Return summary statistics for the task list.

    Returns counts grouped by status and by priority — useful for a
    dashboard overview prompt like "give me a summary of all tasks".
    """
    by_status: dict[str, int] = {s: 0 for s in STATUS_VALUES}
    by_priority: dict[str, int] = {p: 0 for p in PRIORITY_VALUES}

    for task in _tasks.values():
        by_status[task["status"]] = by_status.get(task["status"], 0) + 1
        by_priority[task["priority"]] = by_priority.get(task["priority"], 0) + 1

    return Stats(total=len(_tasks), by_status=by_status, by_priority=by_priority)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 55)
    print("  Task Manager API — Demo for API2MCP")
    print("=" * 55)
    print(f"  Swagger UI  → http://localhost:8080/docs")
    print(f"  OpenAPI JSON → http://localhost:8080/openapi.json")
    print(f"  Health check → http://localhost:8080/health")
    print("=" * 55)
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")
