# Data models

SQLite file at `INKBRIDGE_DB` (default `data/inkbridge.db`). Forward-only migrations in `server/src/inkbridge/db/migrations/`: `0001_init`, `0002_region_png_stale`, `0003_region_fts`, `0004_v2`, `0005_chunk_pins`.

| Table | Key columns | Notes |
|---|---|---|
| `documents` | `id`, `title`, `updated_at` | One per canvas |
| `scenes` | `document_id` (PK), `version`, `elements_json` | Optimistic versioning; stored as received |
| `regions` | `id`, `document_id`, `element_ids_json`, `bbox`, `kind`, `created_by` (`user`/`auto`), `stroke_hash`, `content_hash`, `png_path`, `png_stale`, `status`, `successor_of`, `pinned` | Chunks are `created_by='auto'`; `status` active/orphaned |
| `recognitions` | PK `(region_id, content_hash, source)`; `model`, `text`, `latex`, `text_hash`, `created_at` | Reading cache; source `user > agent > gemini` |
| `region_fts` | FTS5 over `text`, `latex` (`region_id`, `document_id` unindexed) | Holds the best reading for current ink |
| `links` | PK `(document_id, from_region, to_region, kind)`; kind `arrow`/`near` | Rebuilt on every save |
| `agent_ops` | `id`, `document_id`, `type`, `payload_json`, `status`, `result_json`, `error`, `created_at` | Write queue. Payload gains server-set `placement`, `id_prefix`, `font_size` (clients cannot send them); ops stored before INK-066 have no `font_size` and count as 20 |
| `questions` | `id`, `document_id`, `parent_id`, `text`, `focus_element_ids`, `answer_md`, `sources_json`, `status` (pending/answered/cancelled), `runner_ref`, `created_at` | Served by the questions API and MCP tools (decision 0035). `focus_chunk_ids` is computed at read time, not stored |

## Hashes

| Hash | Allow-list |
|---|---|
| `stroke_hash` | `id,type,x,y,width,height,angle,points,pressures,isDeleted` |
| `content_hash` | `type,width,height,angle,points,pressures,text,fontSize,fontFamily` plus `x,y` as offsets from the bbox origin rounded to 0.001 px; no `id`; deleted elements dropped |
| `text_hash` | Normalised `text` + `latex` (trimmed, whitespace collapsed) |

## Scene save payload

```text
PUT /documents/{id}/scene
  full : {base_version, elements: [all]}
  delta: {base_version, elements: [changed only], delta: true}
```
Server replaces stored elements by id (in place) and appends new ones; deleted ink stays as `isDeleted`. No new tables or migrations.

## Vault note frontmatter

```
inkbridge: {canvas, exported, chunks:[{id, hash, reading, section}]}   # one JSON line
```
Block markers: `<!-- ink:ID hash:H -->` ... `<!-- /ink -->`. Text outside markers is never touched. Spec: `docs/vault-note-format.md`.

## Draft elements

Excalidraw elements with `customData {author:"agent", draft:true, op_id}` and dashed style. Accept (built, `resolve.ts`) drops the dashed style and the draft flag, keeps `author` and `op_id`, and sets text opacity back to 100. Reject soft-deletes elements whose id starts with `<op_id>:` (never matched by tag alone). Ids carry the op's `id_prefix` `<op_id>:`.
