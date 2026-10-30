# Deep Dive: sketch to diagram (`sketch.py`, `sketch_image.py`, `sketch_prompts.py`)

Two-pass reading (INK-058, decision 0025). **Pass 1** is pure geometry on the server: guess nodes and arrows from the ink and number them. **Pass 2** is the agent: it checks the guess against two images and writes Mermaid that cites the markers, then calls `draw_diagram`. No model call happens in pass 1.

## Pass 1: `read_sketch` (`sketch.py:114-271`)

Constants (`:27-32`): `MIN_NODE_SIZE = 20` px diagonal (smaller loops are letters), `CLOSURE = 0.25` (a loop's ends within 25% of its box diagonal), `LOOP_LENGTH = 1.8` (path at least 1.8 diagonals), `HEAD_SIZE = 0.4` (a separate head stroke at most 40% of the shaft), `HOOK = 0.05`.

1. **Usable elements** (`usable`, `:94`): malformed elements are skipped, not fatal (the scene is stored as sent): finite `x, y, width, height`, shapes with positive size, string text, point lists of finite pairs.
2. **Nodes**: native `rectangle`, `ellipse`, `diamond` (confidence 1.0) or a freedraw loop (`_loop_confidence`, `:68`: needs 4+ points, diagonal at least 20, closure gap and path length within bounds; confidence `1 - 0.5 x gap/(0.25 x diag)`). Nodes are sorted top to bottom in rows of the smallest node height, then left to right, and named `N1..`.
3. **Labels**: any non-connector element whose centre lies inside a node (and is smaller) belongs to the smallest such node as a label; text contributes `label_text`. Free text outside nodes is skipped (shown on the image, not guessed).
4. **Candidate arrows**: native `arrow`/`line` or open freedraw strokes with points. Tolerance `tol = max(15, 0.15 x median node diagonal)`.
   - Native arrowheads give the head directly (`end`, `start`, `both`, evidence 1.0).
   - For a freedraw, `_tip` finds the point farthest from the start; if the stroke continues past it by more than 5% of its length it is a **hook**, so the tip is that point (head `end`, evidence 0.8).
   - Each end maps to the nearest node (`_distance`); native bindings name the node exactly.
   - A stroke is a **shaft** only if both ends are within `tol` of two *different* nodes; others go to a `pool`.
5. **Heads**: shafts are processed longest first. With no head yet, a small pool stroke near one end (bounding diagonal at most 40% of the shaft, within `tol / 2` of the end) becomes the arrowhead (evidence 0.9) and is consumed. This is why a short arrow is never mistaken for a long one's head: shafts are classified before heads are looked for.
6. **Direction and confidence**: a `start` head swaps the ends so arrows always point from -> to. `attach = 1 - 0.5 x (excess gap at both ends beyond tol/3) / (2 tol)`; confidence = `(evidence if head else 0.5) x attach`, rounded to 3 places. With no head the drawing order is kept and the confidence is lower.
7. **Unattached**: pool strokes that did not become heads are listed in `unattached`. The agent must decide if they are arrows with a missing source or target.
8. Arrows are sorted by `(from, to)` and named `A1..`. Rotation is ignored, as in `bbox_of`.

Return shape: `nodes[{id, box, element_ids, label_element_ids, label_text, confidence}]`, `arrows[{id, from, to, head, tip, tail, element_ids, confidence}]`, `unattached[ids]`.

## Marker image (`sketch_image.py`)

The server redraws the ink itself (not on the browser crop) so markers land exactly on the geometry pass 1 used; the crop's padding and scale belong to the browser.
- `_layout`: scale = min(2.0, fit to 1024 wide, fit to 2048 tall) with a 30 px pad.
- `_markers`: red `N#` on node centres, blue `A#` on arrow tips, grey `U#` at the middle point of each unattached stroke.
- `render_markers` draws lines for strokes, shapes for rectangles/ellipses/diamonds, text truncated to 200 characters, then 12 px circles with white labels; `marker_positions` computes positions without drawing (used by `GET /regions/{id}/sketch`).

## Linked chunks

A flowchart with long arrows is split into one chunk per node joined by `links`. `db.get_sketch_elements` (`db/__init__.py:740`) therefore includes the elements of chunks linked one hop away (limit 50 links so a hub does not pull in the canvas), skipping deleted and draft elements. API limit: 2,000 elements.

## Prompts (`sketch_prompts.py`)

`MODES = ("one_shot", "two_pass")`. `ONE_SHOT`: look at the crop, identify boxes and arrows. `TWO_PASS`: get region with `include_image` and `include_sketch`, verify the guess against both images, write Mermaid with node ids equal to markers (`N1[Label]`), add `%% A2: uncertain direction` for confidence below 0.6 or no head, retry once on arrows with a missing end, else leave them out and say so. Both end with: return a flowchart, call `draw_diagram` anchored to the region, use the handwritten labels, do not invent. The MCP prompt `sketch_to_diagram(region_id, mode)` serves these. INK-053's E2 compares the two arms.

## Testing

`test_sketch.py` (10K), `test_sketch_api.py`, `test_mcp_sketch.py`.

## Potential improvements

Heuristics are thresholds on pixels; real handwriting has not been tuned (decision 0025). Free text such as edge labels is not attached to arrows.
