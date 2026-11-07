"""Agent tasks, pull path (INK-133): list_tasks, claim_task, complete_task."""

from typing import Annotated, Literal

from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from inkbridge.mcp.app import _dump, get_client, mcp
from inkbridge.mcp.client import ApiError, Conflict


@mcp.tool()
def list_tasks(
    status: Annotated[
        Literal["pending", "running", "done", "failed", "cancelled"],
        Field(description="Which tasks to list"),
    ] = "pending",
    document_id: Annotated[
        str | None, Field(description="Defaults to the configured document")
    ] = None,
    limit: Annotated[int, Field(ge=1, le=100)] = 20,
) -> str:
    """Tasks waiting on the canvas (questions and offers the user tapped), oldest first.

    Work through them with claim_task, then complete_task. Question tasks finish by themselves
    when you call answer_question. Each has a mode, allowed_op_types and op_limit.
    """
    try:
        tasks = get_client().list_tasks(document_id, status, limit)
    except ApiError as e:
        raise ToolError(str(e)) from e
    return _dump({"tasks": tasks})


@mcp.tool()
def claim_task(
    task_id: str,
    claimed_by: Annotated[str, Field(min_length=1, max_length=64)] = "mcp",
) -> str:
    """Take a pending task so nobody else works on it.

    Returns the task with its mode, allowed_op_types, op_limit, input and (for a question task)
    the question. Pass its id as `task_id` to write_text and draw_diagram: the API refuses ops of a
    type the mode does not allow and drafts past op_limit.
    """
    try:
        task = get_client().claim_task(task_id, claimed_by)
    except Conflict as e:
        raise ToolError(f"{e} The task is already claimed. Call list_tasks.") from e
    except ApiError as e:
        raise ToolError(str(e)) from e
    return _dump(task)


@mcp.tool()
def complete_task(
    task_id: str,
    status: Annotated[Literal["done", "failed"], Field(description="How it ended")] = "done",
    error: Annotated[str | None, Field(max_length=2_000)] = None,
) -> str:
    """Finish a task you claimed. A question task cannot be `done` until answer_question was called."""
    try:
        task = get_client().complete_task(task_id, status, error)
    except ApiError as e:
        raise ToolError(str(e)) from e
    return _dump({"id": task["id"], "status": task["status"]})
