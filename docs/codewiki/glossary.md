# Glossary

| Term | Meaning |
|---|---|
| Canvas / document | One Excalidraw board, selected with `?canvas=`; default id `default` |
| Scene | Versioned snapshot of a canvas's Excalidraw elements |
| Chunk | Automatically grouped cluster of ink (one idea); a region with `created_by='auto'` |
| Region | A set of element ids with server-computed bbox, hashes and crop; manual regions are `created_by='user'` |
| Pinned chunk | A chunk fixed by a manual merge/split so the chunker leaves it alone |
| Successor | The chunk that replaced an orphaned one after a split/merge (`successor_of`) |
| Link | Row in `links`; arrows link chunks (`arrow`), plus `answer`, `relates`, `derived`; source `stroke`, `agent` or `user` |
| Reading order | Server ordering of chunks for `read_canvas` and export |
| `stroke_hash` / `content_hash` / `text_hash` | Exact ink / shape of ink / normalised reading; see [data-models.md](data-models.md) |
| Recognition | A cached reading of a chunk, keyed by content hash and source |
| Early cutoff | A cosmetic redraw changes `content_hash` but not `text_hash`, so the note is not stale |
| Crop | PNG of a chunk rendered by the browser; `png_stale` means ink changed since |
| Overview | Downscaled whole-canvas image returned by `read_canvas` |
| Op | Row in `agent_ops`: a queued agent write (`write_text`, `draw_diagram`); carries a server-computed `font_size` and, until Accept, the draft's elements |
| Draft | Dashed agent-drawn elements awaiting Accept/Reject; they live in the op row, not in the scene |
| Marker block | `<!-- ink:ID hash:H -->` ... `<!-- /ink -->` region of a vault note owned by the export skill |
| Deep link | `?canvas=<id>&chunk=<id>` URL that opens a chunk on the canvas |
| Pull path | Ask AI via `list_questions`/`answer_question` (or the task tools) from any MCP client |
| Delta save | Sending only changed elements; since v4 saves merge per element (`POST /elements`, no 409) |
| Accept / Reject | Resolving a draft op from its pills or the tray; accept writes its elements into the scene in one transaction, reject drops the draft; Unaccept reverses an accept |
| Timing log | One-line `name ms= counts` records from server and browser; never content |
| Eval harness | `eval/`: offline scoring of reading, chunking, staleness on a page set |
| Runner | Optional `AgentRunner` adapter (`INKBRIDGE_RUNNER=claude`) that starts `claude -p` for each agent task |
| Two-pass reading | Sketch to diagram: find nodes/arrow ends and draw numbered markers, then ask for Mermaid |
| Stroke kind | Class of a stroke from its shape: writing, container, connector, head, underline, scribble (`canvas/strokes.py`) |
| Chunker v2 | The default chunker: stroke kinds, lines and connectors; a connector with a free end is a `kind: connector` chunk that is never read |
| Oversized split | Cutting a chunk over 3000 units or 600 elements at its widest gaps (`canvas/chunker/split.py`) |
| Reader | The model that transcribes a chunk: Gemini (test pages) or Claude Haiku (`INKBRIDGE_RECOGNIZER`) |
| Structure hint | Plain-words boxes and arrows handed to the reader for a diagram chunk (`canvas/structure.py`) |
| `CANVAS_CONTEXT` | The text every agent gets saying it is inside a handwritten canvas (`canvas_context.py`) |
| Task | Row in `agent_tasks` for a question or tapped offer; worked by `list_tasks` / `claim_task` / `complete_task` or the runner |
| Diagram object | Row in `diagrams` with versions; `edit_diagram` makes a revision whose Accept replaces only untouched shapes |
| Mark-up | The user's new ink over an accepted diagram, read as an instruction (`get_markup`) |
| Offer | A proactive suggestion chip beside the ink; built, off by default (`INKBRIDGE_OFFERS`) |
| Brief | Per-canvas summary an agent writes with `set_canvas_brief`; read back by `read_canvas` |
| Device journal | IndexedDB log of ink on the device, uploaded by an overlapping sender (`sync/journal.ts`) |
| Live delta | `scene.delta` WebSocket push of changed elements to every device but the writer |
| Working dot | Pulsing lime dot while an agent works (`agent.activity`) |
