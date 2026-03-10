# SPDX-License-Identifier: MIT
"""ISO-8601 timestamp helpers."""
from __future__ import annotations
from datetime import datetime, timezone


def utcnow_iso() -> str:
    """Return current UTC time as an ISO-8601 string (e.g. '2026-03-07T12:00:00Z')."""
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def utcnow() -> datetime:
    """Return current UTC datetime with timezone info."""
    return datetime.now(tz=timezone.utc)
