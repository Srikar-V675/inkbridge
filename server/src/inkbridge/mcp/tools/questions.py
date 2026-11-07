"""Ask AI pull path: list_questions and answer_question."""

from typing import Annotated, Literal

from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field

from inkbridge.mcp.app import _dump, get_client, mcp
from inkbridge.mcp.client import ApiError, Conflict, NotFound


class Source(BaseModel):
    """A local copy of the API's shape; the API stays the one place that enforces it."""

    type: Literal["chunk", "note"]
    id: str | None = Field(default=None, description="Chunk id (type chunk)")
    path: str | None = Field(default=None, description="Vault note path (type note)")


_NEXT_STEP = "Call list_questions to see the pending question ids."


@mcp.tool()
def list_questions(
    status: Annotated[
        Literal["pending", "answered", "cancelled"],
        Field(description="Which questions to list"),
    ] = "pending",
    document_id: Annotated[
        str | None, Field(description="Defaults to the configured document")
    ] = None,
    limit: Annotated[int, Field(ge=1, le=100)] = 20,
) -> str:
    """Questions the user asked on the canvas, oldest first (default: the pending ones).

    Each has focus_chunk_ids (read them with get_region or read_canvas), parent_id and history
    (earlier question/answer pairs of the thread, oldest first). Reply with answer_question.
    """
    client = get_client()
    try:
        questions = client.list_questions(document_id, status, limit)
    except ApiError as e:
        raise ToolError(str(e)) from e
    return _dump({"questions": questions})


@mcp.tool()
def answer_question(
    question_id: str,
    answer_md: Annotated[str, Field(min_length=1, max_length=20_000, description="Markdown")],
    sources: Annotated[
        list[Source],
        Field(description="What the answer rests on: {type:'chunk', id} or {type:'note', path}"),
    ] = [],  # noqa: B006 - never mutated
    canvas_text: Annotated[
        str | None,
        Field(
            max_length=600,
            description="A 1 to 3 sentence summary (about 300 characters) drawn beside the ink; "
            "the full answer stays in the thread",
        ),
    ] = None,
) -> str:
    """Answer a pending question. Stores the text only; it changes no ink and writes no note.

    canvas_text is the answer for the canvas card; omit and the first paragraph is used.
    Fails if the question is already answered or cancelled.
    """
    try:
        q = get_client().answer_question(
            question_id, answer_md, [s.model_dump(exclude_none=True) for s in sources], canvas_text
        )
    except (NotFound, Conflict) as e:
        raise ToolError(f"{e} {_NEXT_STEP}") from e
    except ApiError as e:
        raise ToolError(str(e)) from e
    return _dump({"id": q["id"], "status": q["status"]})
