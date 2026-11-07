"""Graph IR for draw_diagram `source_kind: "graph"` (INK-140, decision 0100). Laid out in the browser."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class Node(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=64)
    label: str = Field(max_length=200)
    shape: Literal["rect", "ellipse", "diamond"] = "rect"


class Edge(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    from_: str = Field(alias="from")
    to: str
    label: str | None = Field(default=None, max_length=200)


class Graph(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nodes: list[Node] = Field(min_length=1, max_length=200)
    edges: list[Edge] = Field(default_factory=list, max_length=400)

    @model_validator(mode="after")
    def _consistent(self):
        ids = [n.id for n in self.nodes]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate node id")
        for e in self.edges:
            if e.from_ not in ids or e.to not in ids:
                raise ValueError(f"edge {e.from_!r} -> {e.to!r} names an unknown node")
        return self


def parse_graph(source: str) -> Graph:
    try:
        return Graph.model_validate_json(source)
    except ValidationError as e:
        raise ValueError("; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors())) from None
