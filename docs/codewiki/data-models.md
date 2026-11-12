# Data models

SQLite file at `INKBRIDGE_DB` (default `data/inkbridge.db`). Forward-only migrations in `server/src/inkbridge/db/migrations/`, 0001 to 0018, run on API start: `0001_init`, `0002_region_png_stale`, `0003_region_fts`, `0004_v2` (hashes, links, questions, op columns), `0005_chunk_pins`, `0006_question_runner_status`, `0007_canvas_home`, `0008_scene_elements` (one-way), `0009_links_v2` (rebuilds `links`, adds `documents.chunker`), `0010_answer_fts`, `0011_drafts_in_ops`, `0012_offers`, `0013_watches`, `0014_canvas_memory`, `0015_question_canvas_text`, `0016_agent_tasks`, `0017_diagrams`, `0018_question_partial`.

| Table | Key columns | Notes |
|---|---|---|
| `documents` | `id`, `title`, `updated_at`, `pinned`, `archived_at`, `last_opened_at`, `chunker` (`v1`/`v2`/null), `focus` | One per canvas; home fields from 0007, per-canvas chunker from 0009, offers Focus toggle from 0012 |
| `scenes` | `document_id` (PK), `version`, `element_count`, `elements_json` | Version counter and count only. `elements_json` is retired (kept one release); elements live in `scene_elements` |
| `scene_elements` | PK `(document_id, id)`; `pos`, `seq`, `version`, `nonce`, `is_deleted`, `json`, `updated_at` | One row per element (0008). Merge: higher `version` wins, tie to the lower nonce. Deleted rows keep their JSON 14 days, then shrink to an id stub. Index `(document_id, seq)` serves `GET /elements?since=N` |
| `regions` | `id`, `document_id`, `element_ids_json`, `bbox`, `kind`, `created_by` (`user`/`auto`), `stroke_hash`, `content_hash`, `png_path`, `png_stale`, `status`, `successor_of`, `pinned` | Chunks are `created_by='auto'`; `status` active/orphaned; `kind` includes `connector` (v2) |
| `recognitions` | PK `(region_id, content_hash, source)`; `model`, `text`, `latex`, `text_hash`, `created_at` | Reading cache; source `user > agent > gemini` (machine readings use source `gemini` whichever reader made them; `model` says which, for example `claude-haiku`) |
| `region_fts` | FTS5 over `text`, `latex` (`region_id`, `document_id` unindexed) | Best reading for current ink |
| `answer_fts` | FTS5 over `question`, `answer` (`question_id`, `document_id` unindexed) | Answered questions, for `retrieve` (0010) |
| `links` | PK `(document_id, from_region, to_region, kind, source, element_id)`; `label`, `confidence` | kind `arrow`/`near`/`answer`/`relates`/`derived`, source `stroke`/`agent`/`user`; rebuilt on every save (0009) |
| `agent_ops` | `id`, `document_id`, `type` (`write_text`/`draw_diagram`), `payload_json`, `status`, `result_json`, `error`, `created_at`, plus from 0011 `elements_json`, `box_json`, `question_id`, `task_id`, `offer_id`, `revises`, `diagram_id`, `resolved_at` | Write queue and draft store: a draft's elements live here until Accept. Payload gains server-set `placement`, `id_prefix`, `font_size`. Status `pending`, `delivered`, `placed`, `accepted`, `rejected`, `failed`, `expired` |
| `questions` | `id`, `document_id`, `parent_id`, `text`, `focus_element_ids`, `answer_md`, `sources_json`, `status` (pending/answered/cancelled), `runner_ref`, `runner_status`, `runner_error`, `canvas_text`, `partial_answer`, `partial_seq`, `created_at` | Ask panel and MCP tools. `focus_chunk_ids` is computed at read time |
| `agent_tasks` | `id`, `document_id`, `kind` (question/offer/revise/brief), `status` (pending/running/done/failed/cancelled), `question_id`, `offer_id`, `input_json`, `claimed_by`, `attempts`, `last_error`, timestamps | One per question or tapped offer (unique indexes); 0016 backfills pending questions |
| `offers` | `id`, `document_id`, `kind`, `anchor_chunk`, `reason`, `payload_json`, `score`, `source`, `status` (open/tapped/dismissed/expired/done), `task_id`, timestamps | Proactive offers (off by default) |
| `watches` | PK `(document_id, note_id, chunk_id)`; `reading_hash` | For the `stale_note` detector; nothing calls `POST /watch` yet |
| `canvas_memory` | `document_id` (PK), `brief_md`, `last_seen_seq`, `updated_at` | Per-canvas brief and the `what_changed` cursor |
| `diagrams` | `id`, `document_id`, `version`, `source_kind` (mermaid/graph), `source`, `node_map_json`, `from_chunks_json`, `current_op` | Diagram objects; `edit_diagram` makes a revision op |

## Hashes

| Hash | Allow-list |
|---|---|
| `stroke_hash` | `id,type,x,y,width,height,angle,points,pressures,isDeleted` |
| `content_hash` | `type,width,height,angle,points,pressures,text,fontSize,fontFamily` plus `x,y` as offsets from the bbox origin rounded to 0.001 px; no `id`; deleted elements dropped |
| `text_hash` | Normalised `text` + `latex` (trimmed, whitespace collapsed) |

## Scene save payload

```text
POST /documents/{id}/elements   {device, batch, elements}   idempotent by (device, batch), strict
PUT  /documents/{id}/scene      {base_version, elements, delta?}   legacy, same merge with strict=False
GET  /documents/{id}/scene      {seq, version, elements}    live ink only (?deleted=true for a reload)
GET  /documents/{id}/elements?since=N                       changed rows
```
The server merges per element (higher `version` wins; nothing is deleted by omission) and answers with the rows that were `newer`. Draft-flagged elements and new `<op_id>:` ids are refused by `POST /elements`.

## Vault note frontmatter

```
inkbridge: {canvas, exported, chunks:[{id, hash, body, reading, section}]}   # one JSON line
```
Block markers: `<!-- ink:ID hash:H -->` ... `<!-- /ink -->`. Text outside markers is never touched. Spec: `docs/vault-note-format.md`.

## Draft elements

Excalidraw elements with `customData {author:"agent", draft:true, op_id}` and dashed style, held in the `agent_ops` row (`elements_json`) and drawn by the client from its draft store. They are not in `scene_elements`. Accept (`POST /ops/{id}/accept`, one transaction) writes them into `scene_elements` without the draft flag, keeping `author` and `op_id`; Unaccept reverses it. Reject drops the op's draft. Ids carry the op's `id_prefix` `<op_id>:`. Once accepted, an op's elements form their own chunk with an `agent` reading.
