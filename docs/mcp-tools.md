# MCP tools

Server: `inkbridge-mcp` (stdio). A thin HTTP client of the API; it never imports `inkbridge.db`
(enforced by `server/tests/test_mcp_boundary.py`). stdout carries protocol frames only; logs go to stderr.
Built on the MCP Python SDK 2.x (`MCPServer`, formerly `FastMCP`).

Env: `INKBRIDGE_API_URL` (default `http://127.0.0.1:8000`), `INKBRIDGE_DOCUMENT` (default `default`).

## Client config

Claude Code:

```bash
claude mcp add inkbridge -- uv run --directory /path/to/inkbridge/server inkbridge-mcp
```

Once, at user scope, the tools are available in every project (set `-e INKBRIDGE_API_URL=...` if the API is not on :8000):

```bash
claude mcp add --scope user inkbridge -- uv run --directory /path/to/inkbridge/server inkbridge-mcp
```

Claude Desktop (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "inkbridge": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/inkbridge/server", "inkbridge-mcp"],
      "env": { "INKBRIDGE_API_URL": "http://127.0.0.1:8000" }
    }
  }
}
```

Never run a script from inside `server/src/inkbridge/mcp/` (the directory name shadows the SDK); use the entry point or `python -m inkbridge.mcp`.

## Verifying a client setup

`uv run --directory server inkbridge-mcp-smoke --api http://127.0.0.1:8000` (API running) drives
`inkbridge-mcp` over stdio with the MCP SDK's own client, the way Claude Desktop and Claude Code do:
`initialize`, `tools/list`, then `read_canvas`, `get_region` on the first chunk, `search` and an
unknown canvas. It prints one PASS/FAIL line per check and exits 1 on any failure; it only reads.
`server/tests/test_mcp_smoke.py` runs it against a live API process in CI.

Checked by the script (INK-039): every reply is standard MCP content; `read_canvas` returns text
then an `image/png` block (a real PNG), `get_region` returns text plus the crop or a text note when no
crop exists yet, and an unknown canvas is a tool error (`is_error`). Checked by the test suite on top:
error texts carry a next step, and the raw stdout stream holds protocol frames only during real tool
calls (the server's HTTP log goes to stderr).

Not yet checked: how the real GUI clients render this (decision 0003 still says "?"). Manual steps
for whoever is at the keyboard:
1. Start the API (`make dev-server`) and open a canvas with a few chunks.
2. Claude Code: `claude mcp add inkbridge -- uv run --directory /path/to/inkbridge/server inkbridge-mcp`,
   then ask it to call `read_canvas`. Expect the outline JSON and the overview image.
3. Claude Desktop: add the config above, restart, ask for `read_canvas` and `get_region <id>`.
4. Record per client: text shown, image shown inline (yes/no), anything odd. Write the result into
   decision 0003 and the quirks list below.

Known quirks: the SDK 2.x client exposes `mime_type` / `is_error` (snake case), not the wire names
`mimeType` / `isError`; scripts written against 1.x need the change. The SDK 2.x stdio server diverts `sys.stdout` to stderr while it runs
(SDK issue #1933), so a stray `print` in a tool cannot corrupt the protocol stream; the raw-stdout test
in `test_mcp_smoke.py` still guards the stream end to end.

## Tools (built)

| Tool | Input | Returns | Mutates |
|---|---|---|---|
| `list_regions` | `document_id?`, `kind?`, `limit=50` | Manual (saved) regions only; chunks come from `read_canvas`. JSON `{regions: [{id, kind, bounds, stroke_count, preview, updated_at}]}` | No |
| `get_markup` | `diagram_id`, `document_id?` | JSON text `{diagram_id, version, source, source_kind, ink_ids, box}` plus a PNG of the diagram with the ink the user drew over it since Accept in red. Use it in a `markup` task, then call `edit_diagram` with your task_id; never redraw or delete the ink. Unknown diagram is a tool error (INK-141, decision 0102) | No |
| `get_region` | `region_id` (a chunk id or a saved region id), `include_image=true`, `include_ink=false`, `include_sketch=false` | JSON text `{id, kind, text, latex, source, bounds, status, png_stale, updated_at, read_status, read_note, ink?, sketch?}` plus the region PNG as image content. `read_status: too_large` (a side over 4096 units or over 1500 elements, INK-096) means no image is sent, only a text note: ask the user to split the chunk. An orphaned (replaced or deleted) chunk returns only `{id, status, live_successor, note}`: read `live_successor`, or call `read_canvas` if null (INK-084) | No |
| `read_canvas` | `document_id?`, `include_overview=true`, `offset=0`, `max_width=1568` (256 to 1568) | Compact JSON `{document, version, brief, chunk_count, groups: [{id, chunk_ids, omitted_ids?}], groups_omitted?, chunks: [{id, order, kind, bounds, text, latex, status, png_stale, content_hash, text_hash, links: [{to, kind, label, confidence}], group_id, deep_link, read_status, read_note}], omitted?, note?}` in reading order, then overview PNGs (up to 3 per call, `max_width` px wide; a spread-out canvas is split into reading-order bands so each chunk box stays at least 24 px tall; when more bands remain the reply names the `offset` that continues; orientation only, read a chunk with `get_region`) as image content. `text: null` means not read yet: open the chunk with `get_region`. `read_status: too_large` means the chunk is not readable at a useful scale and is never read by the worker: ask the user to split it, do not guess. Text over 60,000 chars is cut at a chunk boundary with `omitted` and a note naming the `offset` that continues; a reading over 4,000 chars is shortened and flagged `text_truncated` / `latex_truncated`; at most 20 links per chunk, the rest counted in `links_omitted`. A group is a connected component of 2+ active chunks over arrow links; `group_id` is null for a chunk on its own; at most 20 groups of 20 chunk ids; computed from ink alone (no model), and `groups` repeats on every page. With the v2 chunker (INK-122, decision 0081) pen and native connectors are links at any length above a tick and a connector with a free end is a chunk of `kind: connector` (never read; skip it when exporting). | No |
| `get_subgraph` | `chunk_id`, `depth=1` (1..5), `direction=both` (`out`, `in`), `to_chunk_id?`, `max_nodes=40` (1..100), `mermaid=false`, `document_id?` | Chunks within `depth` arrow hops of `chunk_id`: `{document, version, anchor_used, note, center, nodes: [{id, order, kind, text (160 chars), distance, deep_link}], edges: [{from, to, kind}], reachable, omitted_nodes, omitted_edges, mermaid?}`. With `to_chunk_id`: the shortest arrow path `{found, length, nodes, edges, ...}`. Only long-arrow links count; orphaned ids are followed to their live successor (`anchor_used`, `note`), a deleted chunk is refused and points at `read_canvas`. `mermaid` is `flowchart TD` text, nothing is drawn. Built in memory per request (INK-060, decision 0056) | No |
| `set_canvas_brief` | `brief` (max 4000 chars), `document_id?` | `{brief, last_seen_seq, updated_at}`. Replaces the canvas brief (1 to 10 lines: what it is about, who for, what is in progress). Kept in Inkbridge's database, never in the vault; `read_canvas` returns it (INK-135, decision 0093) | No |
| `what_changed` | `document_id?`, `since?` (seq, default the saved cursor), `mark_seen=false` | `{document, since, seq, marked_seen, chunk_count, omitted, chunks: [{id, change: changed\|removed, kind, bounds, text, latex, content_hash, text_hash}]}` for chunks whose ink has a newer seq than `since` (max 100, reading order). Readings that arrive later are not changes. `mark_seen=true` moves the saved cursor to `seq` (INK-135, decision 0093) | No |
| `canvas_components` | `document_id?` | Groups of chunks joined by arrows, largest first: `{chunk_count, component_count, isolated, components: [{size, chunk_ids (max 20), omitted_ids}] (max 30), omitted_components}`. Active chunks only | No |
| `check_sync` | `chunks: [{id, hash, reading}]` (from a note's frontmatter: content hash and reading hash), `document_id?`, `wait_s=15` (0..30) | JSON `{fresh: [id], fresh_after_reread: [{id, hash, reading}], changed: [{id, hash, reading}], replaced: [{id, successor, hash, reading}], removed: [id], new: [{id, hash, reading, preview}]}`; `changed` with `reading: null` means no reading in time (look with `get_region`) | Recognition cache only |
| `answer_question` | `question_id`, `answer_md` (1 to 20,000 chars), `sources=[]` (`{type:"chunk", id}` or `{type:"note", path}`, max 50), `canvas_text?` (max 600; a 1 to 3 sentence summary for the canvas card, omit and the first paragraph is used; INK-134), `final=true` (false appends `answer_md` to a streaming partial the panel shows growing, total 20,000 chars; sources and canvas_text are ignored; INK-176), `document_id?` (the question's canvas; pass it on every call, a mismatch is refused; INK-191) | JSON `{id, status: "answered", document_id}`, or `{id, status: "pending", document_id, seq}` when `final` is false; fails (tool error pointing at `list_questions`) if the question is unknown, already answered or cancelled, or (with `document_id`) is on another canvas (409 `question_other_canvas`, names both canvases) | Answers a question (stores text only) |
| `draw_diagram` | `source` (Mermaid flowchart only, or graph JSON), `source_kind="mermaid"` (`mermaid`\|`graph`; graph is `{nodes:[{id,label,shape?}],edges:[{from,to,label?}]}`, bad input is 422 `bad_graph`), `anchor?` (chunk id), `from_chunks?` (chunk ids the diagram was made from; unknown id or a chunk of another canvas is 422 `chunk_not_found` with `document_id` and `found_on`, INK-191), `document_id?`, `wait_seconds=20` (1 to 60), `question_id?`, `relation?` (`answer`\|`diagram`\|`relates`; needs `question_id`, default `answer`; the question must be on this canvas, else 422 `question_not_found`), `task_id?` (a task you claimed) | JSON `{op_id, status: "placed", document_id, element_count, diagram_id, anchor_used?, note?}` (`anchor_used` is the chunk actually used; `note` when a replaced anchor was followed to its successor; a deleted anchor is refused with `anchor_gone`) once the browser measured the drawn diagram and the server placed the dashed drafts (they live in the op until Accept, INK-114, decision 0086) With `task_id`, the API refuses with 409 `task_not_running`, `task_mode` (op type not allowed in the task's mode) or `task_op_limit` (drafts used up); omitting `task_id` skips the limit (INK-133). | Adds a draft op (never edits ink) |
| `edit_diagram` | `diagram_id`, `source`, `source_kind="mermaid"` (prefer `graph`), `document_id?`, `wait_seconds=20` (1 to 60), `task_id?` (a task you claimed) | JSON `{op_id, status: "placed", document_id, element_count, diagram_id, revises}`: a new draft version beside the old one (a `draw_diagram` op that carries `diagram_id`, so `revises` is the diagram's accepted op). On Accept the server tombstones only the previous version's agent shapes the user has not touched (same version and nonce as at its Accept); anything moved or edited stays. Unaccepting a revision is refused (`window_closed`). A diagram whose current draft is not accepted is refused with 409 `diagram_not_accepted`, an unknown id with 422 `diagram_not_found`. The Ask runner denies it by default, except in a `markup` task, where it is the only draft allowed (INK-141, decision 0102; INK-140, decision 0100). | Adds a draft op; Accept replaces untouched agent shapes of the previous version |
| `create_canvas` | `title` (1 to 200 chars) | JSON `{document_id, url}`; `url` opens the new, empty canvas | Adds a document (never changes an existing one) |
| `write_text` | `text` (1 to 10,000 chars), `anchor?` (chunk id), `size?` (`small`, `normal`, `large`), `question_id?`, `relation?` (as for `draw_diagram`), `document_id?`, `task_id?` (a task you claimed) | JSON `{op_id, status: "pending", document_id, placement: {x, y}, font_size, anchor_used?, note?}` (`anchor_used` and `note` as for `draw_diagram`; a deleted anchor is refused with `anchor_gone`; sized from the line height of the anchor's writing, decision 0094; `wrap_chars` is min(34, view based)); the text appears as a dashed draft in any open browser, now or when the canvas is next opened; the draft lives in the op until Accept, not in the scene (decision 0086). With a `question_id` the text starts with `Answer:` (added if missing); an anchored draft goes below its chunk, else right of it, and carries a dashed `flow-arrow` element from the chunk (decision 0116). With `task_id`, the API refuses with 409 `task_not_running`, `task_mode` (op type not allowed in the task's mode) or `task_op_limit` (drafts used up); omitting `task_id` skips the limit (INK-133). | Adds a draft op (never edits ink); a canvas with 200 open drafts is refused with 409 `too_many_open_ops` (body names the count and the oldest draft, `open` and `since`); drafts expire after 24 h (decision 0049) |
| `list_questions` | `status="pending"` (or `answered`, `cancelled`), `document_id?`, `limit=20` (1..100) | JSON `{document_id, questions: [{id, document_id, parent_id, text, focus_element_ids, focus_chunk_ids, status, answer_md, canvas_text, sources, history: [{id, text, answer_md, status}], runner_status, runner_error, created_at}]}`, oldest first | No |
| `list_tasks` | `status="pending"` (or `running`, `done`, `failed`, `cancelled`), `document_id?`, `limit=20` (1..100) | JSON `{tasks: [{id, kind, status, mode, op_limit, allowed_op_types, input, question?, claimed_by, attempts, last_error, created_at}]}`, oldest first, question tasks before offer tasks (INK-133, decision 0095) | No |
| `claim_task` | `task_id`, `claimed_by="mcp"` | The claimed task (same shape as `list_tasks`). Pass its id as `task_id` to `write_text` / `draw_diagram`: the API refuses an op type the mode does not allow and drafts past `op_limit`. Fails (tool error pointing at `list_tasks`) if already claimed | Marks the task running |
| `complete_task` | `task_id`, `status="done"` (or `failed`), `error?` | JSON `{id, status}`; a question task cannot be `done` until `answer_question` was called (that finishes it itself) | Marks the task finished |
| `retrieve` | `query`, `scope="canvas"` (or `all`), `k=8` (1..50), `document_id?` | JSON `{results: [{kind: "chunk"\|"answer", id, chunk_id, canvas, canvas_title, snippet, deep_link, source, score, matched_by}]}`, best first. Keyword (prefix, AND) match over the best reading of each active chunk and over answered questions, fused by reciprocal rank (`1/(60+rank)` per list); `scope=all` skips archived canvases. `source` is the reading source (`user`/`agent`/`gemini`) or `answer`. Never searches vault notes; creates no links | No |
| `search` | `query`, `limit=10`, `document_id?` | JSON `{results: [{region_id, snippet, score}]}`; snippet marks matches with `[ ]`; score is higher-is-better (negated BM25) | No |

Search is prefix-based, ANDs the words, covers text and LaTeX, and only returns active regions of one canvas (`document_id`, default `INKBRIDGE_DOCUMENT`). The index holds the best reading (user > agent > gemini) for the region's current ink, keyed by its position-independent content hash: changing the ink drops its old text until it is re-recognised, while moving it keeps the reading and the search hit.

Retrieve (INK-136, decision [0079](decisions/0079-retrieve-keyword.md)) indexes the best reading of each active chunk and every answered question's text and answer (`answer_fts`, filled in the answering transaction). It does not index vault text (a note source stays in the question's sources only), orphaned chunks, or pending and cancelled questions. The embedding ranker (INK-138) will join the fusion without changing the tool.

Questions (Ask AI, pull path): the user asks in the browser, the row is `pending`, and any MCP client lists and answers it; no runner is needed. Statuses: `pending`, `answered`, `cancelled`; only `pending` can change, so a second answer is refused. A follow-up has `parent_id`; `history` is the last 5 ancestors (question, answer, status), oldest first. `focus_chunk_ids` are computed when read, from the elements the user pointed at. `runner_status` (`pending|running|failed`) and `runner_error` show the Ask runner state while the question is pending; with no runner they stay `pending`. A follow-up created without `focus_element_ids` inherits its parent's stored focus (so the thread root's). Each create, answer or cancel pushes `{"type": "question.update", "question": {...}}` over the WebSocket. Answers are untrusted markdown and change no ink. With `INKBRIDGE_RUNNER` set the API starts the answering agent itself (decision 0007); the tools are unchanged.

`check_sync` compares content hashes first (a move is `fresh`), then the reading hash (a cosmetic edit is `fresh_after_reread`; only a different reading is `changed`). Chunks that need a new reading are read by the recognition worker while the call waits (bounded by `wait_s`, only for canvases in `INKBRIDGE_RECOGNIZE_DOCUMENTS`). A reading that the note lacks for unchanged ink (exported before recognition, or corrected later) is reported as `changed`. Several `replaced` entries can share one `successor` after a merge: rewrite that block once. See decision 0020.

Errors are returned as tool errors with a next step (for example, "call list_regions to see valid region ids").

**Sketch to diagram** (two-pass reading, INK-058, decision [0025](decisions/0025-sketch-two-pass.md)):
- `get_region(include_sketch=true)` adds a `sketch` field, the server's pass-1 guess from the ink alone with no model call:
  - `nodes`: closed shapes; freehand loops count only when big relative to the sketch (not an absolute size), so zoom does not matter. `[{id: N1.., box, element_ids, label_element_ids, label_text, confidence}]`
  - `arrows`: `[{id: A1.., from, to, head: "end"|"both"|null, tip, tail, element_ids, confidence}]`
  - `unattached`: strokes that touch fewer than two nodes (at most 30, longest first; `unattached_total` and `unattached_note` say when some were left out)
  - `markers`: pixel positions on the marker image

  It also adds a second image: the ink redrawn with red node markers on node centres, blue arrow markers on arrow tips, and grey markers (U1..) on unattached strokes.
- The read follows arrow `links` one hop, so a flowchart split into one chunk per node still resolves its arrows. Drafts are left out.
- The MCP prompt `sketch_to_diagram(region_id, mode)` gives the instructions. With `mode=two_pass` (default), the agent checks the guess, writes Mermaid that uses the marker ids, flags uncertain arrows, then calls `draw_diagram` anchored beside the sketch. With `mode=one_shot`, it uses the crop alone. INK-053's E2 experiment compares the two.

`draw_diagram` needs the canvas open in a browser, because Mermaid is converted there (decision [0023](decisions/0023-draw-diagram-wait.md)). The API refuses anything that is not a flowchart (`flowchart` / `graph`): sequence, class and other diagram types would come back as one uneditable image. The tool polls the op until the browser has measured it (status `placed`), for up to `wait_seconds`. Its errors are:

An accepted diagram is stored as a `diagrams` row (version, source, node map, and the reading hash of each `from_chunks` chunk at Accept). When a source chunk's reading changes, the offer detector raises a `stale_diagram` offer (score 0.7, action `diagram`); moved ink or an unchanged reading raises nothing. A `markup` offer (score 0.85, action `diagram`, payload `markup: true`, reason "Apply mark-up?") is raised when the user draws over an accepted diagram within 30 minutes of its Accept; tapping it makes a `markup` task (`draw_diagram` only, one draft) and the agent reads the ink with `get_markup` (INK-141, decision 0102).
- `Mermaid could not be parsed: <message>`, reported by the browser. No elements are drawn.
- `No browser drew the diagram within N s … Open the canvas at <url>`. The op is set to `expired`, so a browser that connects later never draws it.
- The API's own refusals: `not_flowchart`, `anchor_not_found`, `existing_element_id`.

## Planned tools (spec v3)

Not built yet; each ticket updates this file when it lands. (No tool is currently planned; the table is empty.) All tools take an optional `document_id` (default `INKBRIDGE_DOCUMENT`).

| Tool | Ticket | Purpose | Mutates |
|---|---|---|---|

Outside MCP: `GET /regions/{id}/sketch` (pass-1 JSON) and `GET /regions/{id}/sketch.png` (marker image) back `include_sketch`. `GET /regions/{id}/png` serves a chunk's stored crop at full size (built, INK-033; the `GET /regions/{id}/image` is capped at 1024 px wide by default) so the export skill can save it into the vault. `save_transcription` and `get_neighbors` from the v1 plan are dropped.

## Limits

- Images are downscaled to at most 1024 px wide (API default; the stored crop is untouched).
- `include_ink` returns at most 5,000 points in total; `ink.decimated` and `ink.original_point_count` say whether it was reduced. See `docs/decisions/0003-agent-output-limits.md`.

`png_stale: true` means the ink changed since the crop was saved, so the image may not match the strokes. Ink strokes carry `x`, `y` and `angle`; their `points` are relative to `(x, y)`. If the image cannot be fetched, `get_region` still returns the transcription plus a note: "the crop file is missing" only when the API answers 404, otherwise the actual error (retry those).
