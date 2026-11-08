"""edit_diagram: a new draft version of an accepted diagram (INK-140, decision 0100)."""

from typing import Annotated, Literal

from mcp.server.mcpserver import Image
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from inkbridge.mcp.app import _dump, get_client, mcp
from inkbridge.mcp.client import ApiError
from inkbridge.mcp.tools.write import _draw


@mcp.tool()
def edit_diagram(
    diagram_id: Annotated[str, Field(description="diagram_id returned by draw_diagram")],
    source: Annotated[
        str, Field(min_length=1, max_length=20_000, description="The revised diagram source")
    ],
    source_kind: Annotated[
        Literal["mermaid", "graph"], Field(description="How to read source; prefer graph")
    ] = "mermaid",
    document_id: Annotated[
        str | None, Field(description="Defaults to the configured document")
    ] = None,
    wait_seconds: Annotated[
        float, Field(ge=1, le=60, description="How long to wait for the browser to draw it")
    ] = 20,
    task_id: Annotated[
        str | None,
        Field(description="Task you claimed; the API enforces its mode and draft limit"),
    ] = None,
) -> str:
    """Draw a new version of an accepted diagram as a draft beside the old one.

    On Accept the old version's agent shapes the user has not changed are replaced; anything the
    user moved or edited stays. Only an accepted diagram can be revised (else a tool error). Use
    source_kind="graph" for revisions: a Mermaid revision is redrawn from scratch. Returns
    {op_id, status: "placed", element_count, diagram_id, revises}.
    """
    client = get_client()
    payload = {
        "source": source,
        "source_kind": source_kind,
        "diagram_id": diagram_id,
        **({"task_id": task_id} if task_id else {}),
    }
    return _draw(
        client, document_id or client.default_document, payload, None, wait_seconds, "edit_diagram"
    )


@mcp.tool()
def get_markup(
    diagram_id: Annotated[str, Field(description="diagram_id from the task's details")],
    document_id: Annotated[
        str | None, Field(description="Defaults to the configured document")
    ] = None,
) -> list:
    """The diagram and the ink the user drew over it since it was accepted.

    Returns the diagram source and ids as JSON plus a PNG: the old diagram in its own colours, the
    new ink in red. Read it, then call edit_diagram (source_kind="graph") with the task_id you
    claimed. Never redraw or delete the ink: it is the user's.
    """
    client = get_client()
    doc = document_id or client.default_document
    try:
        info = client.get_markup(doc, diagram_id)
        png = client.get_markup_image(doc, diagram_id)
    except ApiError as e:
        raise ToolError(str(e)) from e
    return [_dump(info), Image(data=png, format="png")]
