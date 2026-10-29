# Glossary

| Term | Meaning |
|---|---|
| Canvas / document | One Excalidraw board, selected with `?canvas=`; default id `default` |
| Scene | Versioned snapshot of a canvas's Excalidraw elements |
| Chunk | Automatically grouped cluster of ink (one idea); a region with `created_by='auto'` |
| Region | A set of element ids with server-computed bbox, hashes and crop; manual regions are `created_by='user'` |
| Pinned chunk | A chunk fixed by a manual merge/split so the chunker leaves it alone |
| Successor | The chunk that replaced an orphaned one after a split/merge (`successor_of`) |
| Link | Row in `links`; long arrows link chunks (`arrow`), `near` is reserved |
| Reading order | Server ordering of chunks for `read_canvas` and export |
| `stroke_hash` / `content_hash` / `text_hash` | Exact ink / shape of ink / normalised reading; see [data-models.md](data-models.md) |
| Recognition | A cached reading of a chunk, keyed by content hash and source |
| Early cutoff | A cosmetic redraw changes `content_hash` but not `text_hash`, so the note is not stale |
| Crop | PNG of a chunk rendered by the browser; `png_stale` means ink changed since |
| Overview | Downscaled whole-canvas image returned by `read_canvas` |
| Op | Row in `agent_ops`: a queued agent write (`write_text`, `draw_diagram`) |
| Draft | Dashed agent-drawn element awaiting Accept/Reject |
| Marker block | `<!-- ink:ID hash:H -->` ... `<!-- /ink -->` region of a vault note owned by the export skill |
| Deep link | `?canvas=<id>&chunk=<id>` URL that opens a chunk on the canvas |
| Pull path | Ask AI via `list_questions`/`answer_question` from any MCP client (planned) |
| Runner | Optional `AgentRunner` adapter that starts an agent on a new question (planned) |
| Two-pass reading | Sketch to diagram: find nodes/arrow ends and draw numbered markers, then ask for Mermaid |
