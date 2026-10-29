# Sketch to diagram (two-pass)

**Story:** as a note-taker, I want a hand-drawn flowchart turned into a clean editable diagram.

1. Claude uses the MCP prompt `sketch_to_diagram(region_id, mode)`.
2. `get_region(include_sketch=true)` returns the server's pass-1 guess from the ink alone (`nodes` N1.., `arrows` A1.., `unattached`, `markers`) and a marker image (red node markers, blue arrow tips, grey U1.. for unattached strokes). Arrow `links` are followed one hop.
3. Claude checks the guess against the image, writes Mermaid using the marker ids, flags uncertain arrows.
4. `draw_diagram` anchored beside the sketch creates dashed drafts (see [agent-drafts.md](agent-drafts.md)).

`mode=one_shot` uses the crop alone; INK-053 (planned) compares both. Decision 0025. Files: `sketch.py`, `sketch_image.py`, `sketch_prompts.py`.
