import pytest

from inkbridge.mermaid import diagram_type, is_flowchart


@pytest.mark.parametrize(
    "src",
    [
        "flowchart TD\nA-->B",
        "graph LR\nA-->B",
        "  \n%% a comment\nflowchart\nA-->B",
        "%%{init: {'theme': 'dark'}}%%\nflowchart TD\nA-->B",
        "---\ntitle: Backprop\n---\nflowchart LR\nA-->B",
        "graph",
    ],
)
def test_flowcharts_are_accepted(src):
    assert is_flowchart(src)


@pytest.mark.parametrize(
    ("src", "kind"),
    [
        ("sequenceDiagram\nAlice->>Bob: hi", "sequenceDiagram"),
        ("classDiagram\nA <|-- B", "classDiagram"),
        ("erDiagram\nA ||--o{ B : has", "erDiagram"),
        ("%% graph in a comment\nsequenceDiagram\nA->>B: x", "sequenceDiagram"),
        ("flowchartish TD\nA-->B", "flowchartish"),
        ("graph-beta\nA", "graph-beta"),
        ("A-->B", "A"),
    ],
)
def test_other_diagrams_are_refused(src, kind):
    assert diagram_type(src) == kind
    assert not is_flowchart(src)


def test_empty_source_has_no_type():
    assert diagram_type("\n  \n%% only a comment") is None
