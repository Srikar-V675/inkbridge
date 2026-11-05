"""Which kind of Mermaid diagram a source is. Pure. Only flowcharts become editable shapes:
@excalidraw/mermaid-to-excalidraw renders every other kind as one image, so draw_diagram refuses
them up front with a clear message instead of drawing a picture the user cannot edit."""

import re

_FRONTMATTER = re.compile(r"\A\s*---\n.*?\n---[ \t]*(\n|\Z)", re.DOTALL)
_DIRECTIVE = re.compile(r"%%\{[^}]{0,2000}\}%%")  # bounded, so no slow backtracking
_KEYWORD = re.compile(r"[A-Za-z]\w*(?:-[A-Za-z0-9]+)*")
FLOWCHART_KEYWORDS = ("flowchart", "graph")


def diagram_type(source: str) -> str | None:
    """The diagram keyword (e.g. "flowchart", "sequenceDiagram"), or None if there is none."""
    source = source.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    text = _DIRECTIVE.sub("", _FRONTMATTER.sub("", source, count=1))
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("%%"):
            continue
        m = _KEYWORD.match(line)
        return m.group(0) if m else None
    return None


def is_flowchart(source: str) -> bool:
    return diagram_type(source) in FLOWCHART_KEYWORDS
