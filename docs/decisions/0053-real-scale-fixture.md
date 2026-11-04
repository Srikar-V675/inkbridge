# 0053: Real-scale canvas fixture, generated and synthetic (INK-095)

Status: accepted

## Context
Several v2 acceptance criteria (INK-074, 077, 080, 081, 082, 084, INK-061) passed on small
synthetic scenes and would fail on the real page: about 640 elements, about 11k points, a scene
about 17000 x 15000 units, and 10x handwriting (strokes 180-330 units tall). The only copy of that
data is the personal `default` canvas, which must never be committed or sent to a model (CLAUDE.md
privacy invariant).

## Decision
- A generator, `eval/fixtures/make_real_scale.py`, builds the scene from a seed (`SEED = 95`,
  `random.Random`, no clock). It is stdlib only and pure: `build()` returns the element list,
  `boxes()` the intended groups, `main --out PATH` writes `{"elements": [...]}` plus
  `<stem>.boxes.json`. Output is produced on demand and gitignored (`eval/fixtures/*.json`).
- Shape: 4 paragraphs of 10x handwriting (`t10-p{p}l{l}s{s}`, 11 lines of 12 strokes), a 1x block
  of 60 strokes (`t1-l{l}s{s}`, height 15-30, pitch 30), 3 diagrams with 5 boxes, bound text,
  4 arrows (with bindings) and an arrow label each (`dg{d}-box|txt|arr|lbl`), and 8 deleted
  strokes (`del-{n}`). That is 633 live and 641 total elements, 11006 points, 536 KB of JSON.
  Strokes carry `pressures` in 0.1-1.0 with `simulatePressure: false`.
- Consumers import the module (`make_real_scale.build()` and `boxes()`); nobody copies it. The
  replay helper `scripts/replay_fixture.py` feeds it in delta saves and counts new chunk ids per
  save. The loader `scripts/load_fixture.py` seeds a running API on your own port for
  `?canvas=<id>`. The snapshot helper `scripts/snapshot_canvas.py` reads the real canvas
  read-only into `~/.inkbridge-private/`.
- Which later ticket uses what: INK-081 (chunk sizes and replay churn) uses `replay_fixture` and
  `build()`; INK-080 (load time) loads with `load_fixture.py` and times the browser; INK-082 (font
  size at 10x) uses the `t10-` group. Their wiring is theirs; this ticket only provides the helpers.
- Numbers in the generator are PLACEHOLDERS: `STROKE_H_MEDIAN = 250`, `LINE_PITCH = 420`,
  `WORD_GAP = 120`. They were NOT measured in this ticket, because the agent building it was not
  allowed to read the personal canvas. The user should calibrate them with
  `cd server && uv run python ../scripts/snapshot_canvas.py default --stats` (numbers only: median
  stroke height, line pitch, median gap, counts, extent) and edit the three constants. The tests
  only pin the bands (median height 180-330, extent above 15000 in x, 600-700 live elements).
- Privacy: `snapshot_canvas.py` refuses an `--out` inside the repo, writes files 0600 in a 0700
  folder, uses `GET` or a `mode=ro` sqlite copy, and never prints text or ids. `.inkbridge-private/`
  is gitignored; the README has a Privacy section. Nothing is sent to Gemini, and the snapshot must
  never be listed in `INKBRIDGE_RECOGNIZE_DOCUMENTS`. `load_fixture.py` refuses the `default`
  canvas (exit 2) so the real notes cannot be overwritten.
- The API assigns random canvas ids (POST /documents has no id argument), so `load_fixture.py`
  creates a missing canvas and prints its real id instead of a fixed `?canvas=fixture-real`.

## Measured on the fixture (synthetic, one run on the dev machine)
- Replay at batch 20 (`replay_fixture.py`): 33 delta saves, median 23 ms, max 44 ms per save, 14
  new chunk ids in total, 8 active chunks at the end.
- Growing 1x line (`t1-l0`, 10 strokes) at batch 2: new ids per save `[1, 1, 0, 0, 0]`. A save
  that adds half the chunk or more drops the element-id Jaccard to 0.5 or below, so the old id is
  orphaned and a successor is made (INK-031 rule, decision 0011). After that the id is stable.
  The test pins this (`test_replay_counts_new_chunk_ids`); the original plan's "one id" only holds
  for a single save.

## Consequences
- Acceptance for the 4 Nov bugs can run on a page with the real size, shape and pressure data,
  without committing anything personal.
- The fixture is synthetic: it proves the shape and the code paths, not handwriting. Real
  numbers come from the snapshot step above and are the user's to run.
- Until the constants are calibrated, timing and churn numbers from the fixture describe the
  placeholder layout, not the real page.
- No product code changed. The chunker, recognizer, MCP and web are untouched.
