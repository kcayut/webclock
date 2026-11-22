# /// script
# requires-python = ">=3.10"
# dependencies = ["mcp>=1.12,<2"]
# ///
"""Local stdio adapter for the scoped WebClock control API."""
import json
from pathlib import Path
import subprocess
import sys
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import Field

server = FastMCP("WebClock")
CLI = Path(__file__).with_name("control_clock.py")
RequestId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{8,128}$", description=(
    "Choose a fresh unique ID for each new creation. Keep the same ID and arguments on retry."))]
Day = Annotated[str, Field(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")]
ClockTime = Annotated[str, Field(pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$")]
Target = Annotated[str, Field(pattern=r"^(group|device):[A-Za-z0-9_-]{1,128}$",
                              description="Exact target value returned by list_targets.")]


def control(resource, action, body=None):
    result = subprocess.run([sys.executable, str(CLI), resource, action],
                            input=json.dumps(body), capture_output=True, text=True, encoding="utf-8")
    if result.returncode:
        try:
            error = json.loads(result.stderr)["error"]
        except (ValueError, KeyError, TypeError):
            error = "control_client_failed"
        raise ToolError(error)
    return json.loads(result.stdout)


@server.tool()
def list_targets() -> dict[str, Any]:
    """List authorized clock/group names and IDs, with the current Taipei date and time.
    Match the user's room or clock to one target. If ambiguous, ask before writing.
    """
    return control("targets", "list")


def create(resource, field, request_id, content, target):
    return control(resource, "create", body={"request_id": request_id, field: content, "assignment_target": target})


@server.tool()
def create_alarm(request_id: RequestId, name: str, date: Day, time: ClockTime, target: Target) -> dict[str, Any]:
    """Create a one-off Taipei alarm on one authorized clock/group. Resolve tomorrow using list_targets.
    Report saved and assigned separately. A missing next_occurrence means no upcoming ring is confirmed.
    On retry use identical arguments. A replay reads current assignment without changing it.
    """
    return create("schedules", "schedule", request_id,
                  {"name": name, "time": time, "rule": {"dates": [date]}}, target)


@server.tool()
def create_calendar_event(request_id: RequestId, title: str, start: str, end: str,
                          timezone: str = "Asia/Taipei", target: Target | None = None) -> dict[str, Any]:
    """Create a timed event in WebClock's local calendar. Supply ISO start/end with UTC offsets.
    Ask if the end is unknown. Supply a target only when the user wants it displayed there.
    Use the saved event ID for an event-linked alarm. Retry with the same ID and arguments.
    """
    return create("events", "event", request_id,
                  {"title": title, "start": start, "end": end, "timezone": timezone}, target)


@server.tool()
def create_event_alarm(request_id: RequestId, name: str, event_id: str,
                       minutes_before: Annotated[int, Field(ge=0, le=1440)], target: Target) -> dict[str, Any]:
    """Set an alarm relative to a saved WebClock event. Use its exact event ID and a fresh request ID.
    The alarm follows changes to the event. Only report assignment if assigned is true.
    """
    link = {"mode": "event", "source_ids": ["webclock"], "offset_minutes": minutes_before,
            "target": {"source_id": "webclock", "uid": event_id, "scope": "occurrence", "recurrence_id": ""}}
    return create("schedules", "schedule", request_id, {"name": name, "time": "00:00", "calendar_link": link}, target)


if __name__ == "__main__":
    server.run(transport="stdio")
