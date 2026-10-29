# 0025: Two-pass sketch reading: heuristics, server-drawn markers, an MCP prompt

Status: accepted (INK-058)

- **Pass 1 is pure geometry** (`server/src/inkbridge/sketch.py`), with no model call. A node is
  either a native rectangle, ellipse or diamond, or a freedraw loop. A loop's ends meet within
  25 % of its box diagonal, its path is at least 1.8 diagonals long, and its diagonal is at least
  20 px, so letters like "o" are left out.
- **Labels.** Strokes and text whose centre lies inside a node are that node's label.
- **Arrows.** An arrow is an open stroke, or a native arrow or line, whose two ends are each within
  a tolerance of a different node. The tolerance is the larger of 15 px and 15 % of the median node
  size. A native arrow bound to a shape uses that binding.
- **Arrow heads** are found in this order:
  1. a native arrowhead;
  2. a separate small stroke (at most 40 % of the shaft) near one end;
  3. a hook in the stroke itself, where the path goes on after the point farthest from its start.
     That farthest point is the tip.

  Arrows always point from `from` to `to`. Without a head, the drawing order is kept and the
  confidence is at most 0.5.
- **Unattached strokes.** Strokes touching fewer than two nodes are listed as `unattached`, so the
  agent can name an arrow with a missing end.
- **Not handled.** Boxes drawn in several strokes, and rotation, are not handled. The cost of a
  wrong guess is low: the result is a draft the user rejects.
- **Links one hop.** A sketched flowchart with long arrows becomes one chunk per node joined by
  `links` (INK-032). The sketch read therefore takes the region plus every active region an arrow
  link joins it to. Draft elements are left out.
- **Markers on a server-drawn image, not on the crop.** The crop's padding and scale come from
  the browser's export, so marker positions could drift. The server draws the ink itself
  (`sketch_image.py`, Pillow, up to 2x and at most 1024 px wide) and puts every badge exactly on
  the geometry pass 1 used: red N on node centres, blue A on arrow tips, grey U on the middle
  of each unattached stroke. The agent still gets the real crop alongside.
- **Prompt guidance is an MCP prompt** (`sketch_to_diagram(region_id, mode)`, text in
  `sketch_prompts.py`), not a client-specific skill, so any MCP client gets the same
  instructions. `mode` switches between `one_shot` and `two_pass` for the E2 experiment
  (INK-053). There is no draw skill yet; the export skill (INK-037) can point to this prompt.
