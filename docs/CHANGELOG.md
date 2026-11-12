# Changelog

Versions are design rounds, not releases. Ticket numbers are `INK-xxx`; decisions are in `docs/decisions/`.

## Freeze (13 Nov 2026)

- Proactive offers are off by default (`INKBRIDGE_OFFERS=1` turns them on). INK-206, 0121.
- Every agent is told it is inside a handwritten canvas. INK-207, 0122.
- The reader gets the boxes and arrows the server found and writes relations. INK-208, 0123.
- Chunks over the reading limit are cut at their widest gaps. INK-209, 0124.
- The export skill writes like the user's vault. INK-210, 0125.
- README rewritten with the story, status and future scope; docs refreshed. INK-211.

## Tablet-test fixes (10 to 12 Nov, INK-183 to INK-205)

- MCP tools take and echo `document_id`; runner prompts pass the canvas; `make serve` writes the runner MCP config (INK-191, INK-194).
- Chunker v2 is the default; stroke kinds by length and smoothness; levelled slanted writing; scribbles join writing (INK-195, INK-203).
- Claude Haiku persistent reader, newest-touched-first, with latency logs (INK-185, INK-196).
- Offers: logged reasons, one open offer, 60 s expiry and replacement, latest-ink read of the newest cluster with rate limits (INK-183, 184, 197, 199, 202, 204, 205). Superseded by 0121 for the default.
- Working dot, per-draft Accept and Reject pills, answers placed under their anchor with a flow arrow (INK-198, 200, 201).

## v4 (5 to 9 Nov, INK-100 to INK-181)

- Single-origin serve, HTTPS for the tablet, measurement instrumentation, pen latency fast-ink layer.
- Design system (`DESIGN.md`, tokens, eight primitives), app shell, canvases home, tool rail and property cards, UI size.
- Per-element scene storage, per-element merge, live scene delta, device journal and sender.
- Drafts moved out of the scene into `agent_ops`; draft tray, tether, Undo toasts; placement search and text sizing.
- Offers table, detectors and chips; agent tasks; Ask panel threads; streaming answers; diagram objects and `edit_diagram`; mark-up as instruction.
- Chunker v2, stroke-kind classifier, `retrieve`, canvas brief and `what_changed`, read_canvas groups.
- Export skill learning loop.

## v2 and v3 (21 to 27 Oct, INK-028 to INK-099)

- Chunks replace manual regions; three hashes; recognition cache; Gemini recognizer and worker; chunk persistence, stable ids, arrow links.
- `read_canvas`, `search`, `check_sync` with early cutoff, the export skill, the ops queue, WebSocket drafts, `write_text`, `create_canvas`, `draw_diagram`, sketch to diagram.
- Questions API, Ask runner, Ask panel, Accept and Reject, deep links, crop sync, eval harness.

## v1 (mid Oct)

- Manual regions, MCP read tools, image limits, FTS search. The design doc is `docs/project-doc.html`.
