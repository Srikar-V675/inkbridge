# 0091 Detectors that create offers without a model (INK-132)

## Context
Offers (decision 0089) need a source that costs no model call. Rules over the stored chunks are
enough to start; triage (a model) comes later.

## Decision
- `agent/detectors.py` holds pure rules over `list_regions(chunks=True, status="active")`: `question`, `open_equation`, `dangling_arrow`, `stale_note`, `to_note`, `sketch`, `related`. A test fails if the module imports a model or network client.
- `question` only creates an offer (`payload.action="answer"`, `prepare=true`). `agent_tasks` does not exist until INK-133, which reads `prepare` to queue the task. No question row, no runner call here.
- `dangling_arrow` is an active chunk with `kind == 'connector'` (chunker v2 makes a connector with a free end a chunk of its own; v1 never does).
- Accepted agent chunks (`source == 'agent'`) are never examined, so an agent's own answer cannot trigger offers.
- Dedupe: a candidate is dropped when an offer with the same `kind`, `anchor_chunk` and `payload.key` exists in any status. Dismissed and expired offers stay away until the ink or reading changes, which changes `key`.
- `stale_note` compares the `text_hash` a note was written from (table `watches`, migration 0013) with the chunk's current `text_hash`. `POST /documents/{id}/watch` accepts only a note id and per-chunk `(id, reading_hash)`, `extra="forbid"` and hex or id patterns, so no note text or path can reach the backend. Nothing sends it yet: the export skill must call it after an export (follow-up).
- `sketch` reads up to 30 chunks with `read_sketch` (3 nodes and 2 arrows) and claims a chunk plus its linked partners, so one sketch gives one offer. `related` runs a bm25 OR query of the 6 longest tokens of each of the 20 most recent chunks against other canvases' chunks and all answers.
- Trigger: a 2 s debounced timer after a scene save moves the head or the worker publishes `chunks.updated`. It runs on its own connection in the timer thread and never in the save path. `scan_now` logs and swallows any error. Budget, mute and unknown-anchor refusals from `create_offer` are swallowed; candidates are tried best score first.

## Hypotheses to tune on logs
`TO_NOTE_MIN_CHUNKS=8`, `RELATED_MIN_SCORE=3.0` (-bm25, scale depends on corpus size), 20 related and 30 sketch chunk caps, the 2 s debounce, the per-kind `SCORE` table. Related is up to 20 queries per scan: move to embeddings with INK-138. Sketch re-reads chunks each scan: cache by `content_hash` if the logs show cost.

## Consequences
Offers show on the tablet only after INK-131. Until the skill posts `/watch`, `stale_note` never fires.
