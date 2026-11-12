"""A plain-words description of the boxes and arrows in a chunk, for the reader (INK-208).

Pure: no I/O, no model. The recognizer sees one crop and used to return only the words in it, so a
diagram came back as a bag of labels with the arrows lost. The server already finds boxes and
arrows by geometry (`canvas.sketch`); this turns that into a short hint the reader checks against
the picture and writes into the reading as relations (`docs -has-> regions`). A wrong guess costs
nothing: the reader is told to trust the picture over the hint.
"""

from typing import Any

from inkbridge.canvas.hashes import bbox_of
from inkbridge.canvas.sketch import read_sketch

MIN_NODES = 2
MAX_LISTED = 12  # boxes and arrows named in the hint; a bigger drawing is not a small diagram

INSTRUCTION = (
    "Write the boxes' labels first, then one relation per line as `label -> label`, adding the "
    "arrow's own word when it has one (`docs -has-> regions`). A box you cannot read is "
    "`(unreadable box)`. If the picture is not a diagram, ignore all of this and just transcribe."
)


def _place(centre: tuple[float, float], area: dict[str, float]) -> str:
    x, y = centre
    if not (
        area["x"] <= x <= area["x"] + area["width"] and area["y"] <= y <= area["y"] + area["height"]
    ):
        return "outside this image (in a linked chunk)"
    col = (x - area["x"]) / max(area["width"], 1e-9)
    row = (y - area["y"]) / max(area["height"], 1e-9)
    v = "top" if row < 1 / 3 else "bottom" if row > 2 / 3 else "middle"
    h = "left" if col < 1 / 3 else "right" if col > 2 / 3 else "centre"
    return "centre" if (v, h) == ("middle", "centre") else f"{v}-{h}".replace("middle-", "")


def describe(elements: list[dict[str, Any]], own_ids: set[str]) -> dict[str, Any] | None:
    """The sketch of `elements` as short lines, or None when it is not a diagram.

    `own_ids` are the element ids of the chunk being read: boxes outside it are named as being in
    a linked chunk, because the reader's picture does not show them.
    """
    own = [e for e in elements if e.get("id") in own_ids and not e.get("isDeleted")]
    if len(own) < 2:
        return None
    sketch = read_sketch(elements)
    nodes, arrows = sketch["nodes"], sketch["arrows"]
    if len(nodes) < MIN_NODES or not arrows or len(nodes) > MAX_LISTED or len(arrows) > MAX_LISTED:
        return None
    area = bbox_of(own)
    box_lines = []
    for n in nodes:
        b = n["box"]
        where = _place((b["x"] + b["width"] / 2, b["y"] + b["height"] / 2), area)
        label = f' labelled "{n["label_text"]}"' if n.get("label_text") else ""
        box_lines.append(f"{n['id']} {where}{label}")
    arrow_lines = []
    for a in arrows:
        end = "arrowhead at " + a["to"] if a["head"] in ("end", "both") else "direction guessed"
        arrow_lines.append(f"{a['from']} -> {a['to']} ({end})")
    return {"boxes": box_lines, "arrows": arrow_lines}


def hint(elements: list[dict[str, Any]], own_ids: set[str]) -> str | None:
    """The `Context hint` text for the reader, or None when the chunk has no diagram in it."""
    d = describe(elements, own_ids)
    if d is None:
        return None
    return (
        "The server found this layout by geometry (a guide, the picture wins): "
        f"boxes: {'; '.join(d['boxes'])}. arrows: {'; '.join(d['arrows'])}. {INSTRUCTION}"
    )
