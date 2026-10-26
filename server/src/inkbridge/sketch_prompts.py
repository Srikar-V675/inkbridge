"""Instructions for turning a hand-drawn sketch into Mermaid (INK-058). Two arms, so the E2
experiment (INK-053) can compare them: `one_shot` reads the crop alone; `two_pass` adds the
server's pass-1 structure and the numbered marker image (get_region include_sketch=true)."""

MODES = ("one_shot", "two_pass")

_COMMON = """Return a Mermaid flowchart only (start with `flowchart TD` or `flowchart LR`), then call
draw_diagram with it and anchor=<region id> so the diagram lands beside the sketch as a draft.
Use the handwritten labels as node text. Do not invent nodes or arrows that are not drawn."""

ONE_SHOT = f"""Sketch to diagram, one shot.
1. Call get_region(region_id, include_image=true) and look at the crop.
2. Identify every box and every arrow (with its direction) in the drawing.
{_COMMON}"""

TWO_PASS = f"""Sketch to diagram, two passes.
1. Call get_region(region_id, include_image=true, include_sketch=true). You get the crop, the
   server's guess (`sketch`: nodes N1.., arrows A1.. with from/to/head and a confidence, and
   `unattached` strokes) and a second image with red node markers (N1..) on node centres and blue
   arrow markers (A1..) on arrow tips; grey markers (U1..) sit on the `unattached` strokes.
2. Check the guess against both images: read each node's label, confirm each arrow's source,
   target and direction, and look at every `unattached` stroke (an arrow whose source or target
   was missed, or not an arrow at all).
3. Write the Mermaid with node ids equal to the markers (`N1[Label]`), one line per arrow, and add
   a `%% A2: uncertain direction` comment for every arrow with confidence below 0.6 or no head.
4. If an arrow still lacks a source or target, look again at the marker image and retry once;
   if it is still unclear, leave it out and say so.
{_COMMON}"""


def sketch_prompt(region_id: str, mode: str = "two_pass") -> str:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    body = TWO_PASS if mode == "two_pass" else ONE_SHOT
    return f"Region: {region_id}\n\n{body}"
