# Roadmap and status

State at the feature freeze, 13 Nov 2026. Ticket statuses live in the local, untracked `docs/tickets/README.md`; the story and the future-scope list are in the repo `README.md`; history is in `docs/CHANGELOG.md`.

## Built

| Area | What | Tickets / decisions |
|---|---|---|
| Canvas core | Scenes, chunker with stable ids and arrow links, manual merge/split by tapping a chunk label, chunks API, deep links and overlay, crop sync, FTS search, delta saves | INK-030..035, 059, 065, 075; 0011, 0013, 0014, 0016, 0024, 0036, 0037 |
| Per-element data | `scene_elements` rows, per-element merge (higher `version` wins, no 409), `POST /elements` with `(device, batch)` idempotency, live `scene.delta` push, IndexedDB device journal and sender | INK-110..113; 0077, 0080, 0087, 0088 |
| Chunker v2 (default) | Stroke kinds (writing, container, connector, head, underline, scribble), lines, connectors, arrows by smoothness, slanted writing levelled, scribbles join writing; oversized chunks cut at their widest gap | INK-121, 122, 195, 203, 209; 0078, 0081, 0110, 0118, 0124 |
| Reading | Gemini reader and worker (opt-in per canvas); Claude Haiku persistent reader (`INKBRIDGE_RECOGNIZER=claude`) with newest-touched-first order and latency logs; reader gets a diagram structure hint; `too_large` chunks are never read | INK-013, 014, 096, 185, 196, 208; 0006, 0017, 0052, 0104, 0111, 0123 |
| Vault loop | `read_canvas` (bands, groups, link detail), `retrieve`, `check_sync` with early cutoff, `inkbridge-export` skill (vault style, `--summary`, `source: inkbridge`, Related Notes, learning loop, conflict callouts) | INK-033..038, 086, 105, 106, 123, 136, 142, 210; 0018, 0020, 0021, 0050, 0079, 0092, 0103, 0125 |
| Agent write-back | Ops in `agent_ops`; drafts live in the op row, not the scene; placement search; Accept/Reject/Unaccept; draft tray, tether, per-draft pills; answer placed under its anchor; pan to draft | INK-041..045, 076, 077, 114..116, 200, 201; 0009, 0012, 0026, 0086, 0090, 0094, 0115, 0116 |
| Ask and tasks | Questions API and MCP pull path, `claude` runner, Ask panel with threads, source chips, Draw as diagram, streaming answers; agent tasks with claim/complete, mode-limited tools, daily cap; every agent told it is in a canvas; explicit `document_id` in MCP tools | INK-047..049, 103, 104, 133, 134, 176, 191, 194, 207; 0007, 0035, 0060, 0061, 0095, 0096, 0099, 0108, 0109, 0122 |
| Diagrams | Diagram objects with versions, `edit_diagram` revisions whose Accept replaces only untouched shapes, mark-up as instruction (`get_markup`) | INK-140, 141; 0100, 0102 |
| Memory | Per-canvas brief and `what_changed` (`set_canvas_brief`) | INK-135; 0093 |
| App shell | Design tokens and primitives, top bar, tool rail, props card, canvases home, in-app switching, touch routing (finger pans, pen draws), UI size S/M/L, fast ink layer, working dot, tablet density | INK-117, 118, 160..162, 170..181, 198; 0064..0076, 0083..0085, 0098, 0113 |
| Offers (off by default) | Offers table with budget and mute, detectors, latest-ink read, chips and Focus toggle, one-open-offer rule and expiry | INK-130..132, 183, 184, 197, 199, 202, 204..206; 0089, 0091, 0097, 0112, 0114, 0117, 0119..0121 |
| Eval and tooling | Offline harness (E1, E4, E5) on synthetic fixtures, real-scale fixture, perf harness `npm run perf`, device log | INK-050, 051, 095, 102, 174; 0033, 0034, 0053, 0059, 0073 |
| Graph | Read-only networkx `get_subgraph` and `canvas_components` | INK-060; 0056 |

## Not built / future

- Deleting ink by a cross-out gesture, circle-to-ask, lasso as a first-class selection.
- PWA install, an offline outbox beyond the device journal, an authenticated or hosted mode, multi-user or shared canvases.
- An Obsidian-native view (no plugin by design, decision of 22 Oct).
- Structure-aware reading beyond the hint: per-box readings and a stored `structure` object.
- A fast local reader for the latest ink so offers can return; an embedding ranker for `retrieve` (hook `db.retrieve.RANKERS`); a learned "offer this now?" scorer.
- A warm answer agent (the runner starts a fresh `claude -p` per question).
- Closing the vault loop: concept notes per chunk, a weekly change digest, write-back from vault edits to canvas drafts.
- Restructuring tickets INK-068..071 (SQLAlchemy vs raw sqlite3, Alembic vs the hand-rolled migration runner); `db/` is already a package.

## Known limits

- Tablet and real-page checks are the owner's and are pending for most of the v4 wave (pen feel, lag, the UI on the tablet). The perf harness found the app equal to stock Excalidraw; remaining pen lag is the browser's one point per frame.
- No real-page evals: E1, E4 and E5 run on synthetic fixtures only. Chunker and stroke-kind thresholds are start values fitted to a few pages; a very different hand or zoom may chunk badly (merge/split by hand fixes it).
- Diagrams are the weakest read: relations come from a geometric hint, and arrows that miss their boxes are guessed or dropped.
- Speed depends on the network: saves, reads and answers over weak Wi-Fi are slow (20 to 70 s saves seen on a 2.4 GHz tablet); the runner takes 15 to 40 s per answer.
- Offers are off by default; with `INKBRIDGE_OFFERS=1` their noise and delay did not reach "feels intelligent" on the tablet.
- `stale_note` offers never fire because nothing calls `POST /documents/{id}/watch`.
- Server-rendered crops (`INKBRIDGE_CROP_SOURCE=server`) are outline-only and not pixel-identical to Excalidraw; the default stays `browser`.
- MCP behaviour inside the Claude Desktop and Code GUIs is unverified (decision 0003). The vault location defaults to a temp folder until `INKBRIDGE_VAULT` is set.
- The demo video, README screenshots and the evals are not part of this freeze.

## Cut order if short on time

The networkx stretch, E2/E3, stroke arm of E1, source previews, Keep on canvas, Accept/Reject (keep Accept all), manual merge/split, then the Ask panel and runner (keep the pull path). Never cut: canvas-to-note path, stale check, README, demo video.
