"""edit_diagram: a new draft version of an accepted diagram (INK-140, decision 0100)."""

from typing import Annotated, Literal

from pydantic import Field

from inkbridge.mcp.app import get_client, mcp
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
