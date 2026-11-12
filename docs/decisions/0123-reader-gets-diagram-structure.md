# 0123 The reader gets the boxes and arrows the server found

Status: accepted (INK-208).

## Problem

The recognizer returned only words, so a diagram chunk read as a bag of labels ("docs, questions, was, has") and the arrows, which carry the meaning, were lost to questions, search and export. Owner test 12 Nov on the ER sketch.

## Decision

- `canvas/structure.py` turns the deterministic sketch pass ([INK-058](0051-sketch-relative-thresholds.md), `canvas/sketch.py`) into a short hint: boxes with a coarse position in the chunk's crop (or "outside this image, in a linked chunk"), arrows as `N1 -> N2` with the arrowhead end. No hint unless there are at least two boxes and one arrow, and at most 12 of each.
- The recognition worker passes it as the reader's `Context hint` (the hook existed and was unused). The hint says the picture wins over the guess, and asks the reader to write box labels first and then one relation per line (`docs -has-> regions`). Elements of one-hop linked chunks are included, as `get_sketch_elements` already does.
- The relations live in the reading text: no schema change, and search, `read_canvas`, `check_sync` and the export skill see them with no further code.
- A failing hint is dropped silently; reading never depends on it.

## Limits

The relations are only as good as the reader and the geometry; hand-drawn arrows that miss their boxes are guessed or left out. Not measured on real pages yet.
