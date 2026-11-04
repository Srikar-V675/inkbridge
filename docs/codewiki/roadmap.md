# Roadmap (from `docs/tickets/`, local)

State as of `main`. Ticket statuses live in the local, untracked `docs/tickets/README.md`; check `git log` for what has merged.

## Built since the last refresh

| Ticket | What |
|---|---|
| INK-045 | Accept, Reject, Accept all (`resolve.ts`, `DraftBar.tsx`, decision 0026) |
| INK-047 | Questions API, `list_questions`, `answer_question` (decision 0035). INK-046 waived |
| INK-050, 051 | Eval harness and E1 input-representation arms, synthetic data only (decisions 0033, 0034) |
| INK-062 | Pen-feel patch (decision 0031); tablet tuning pending |
| INK-065 | Tap a chunk label to select it for merge/split (decision 0037) |
| INK-066 | `write_text` / `draw_diagram` sized from handwriting, `size` hint (decision 0032) |
| INK-067 | Timing logs, save-latency verdict (decision 0030) |
| INK-072 | Code health: orphan retention, containment flag, successor guard (decisions 0027..0029) |
| INK-075 | Delta scene saves (decision 0036) |

## Open feature work

| Ticket | What | Notes |
|---|---|---|
| INK-048 | `AgentRunner` and Claude Code adapter | `INKBRIDGE_RUNNER`; never strands a question |
| INK-049 | Ask AI panel and Keep on canvas | Needs the questions API (built) |
| INK-052, 053, 061 | E4 on scripted edits, E2/E3, E5 vs hand-boxed chunks | Real page set still to be provided |
| INK-054, 055, 056 | README and architecture diagram, 2-minute demo, final pass | Never cut |
| INK-063 | Live scene sync across tabs | Backlog |
| INK-060 | Stretch: networkx `get_subgraph` | Read-only |
| INK-076 | Pan to a new agent draft | todo |
| INK-095, 096 | Real-scale canvas fixture; crop/recognition budget for large chunks | todo |

## Post-deadline restructuring (tag `restructure`)

INK-068 (split `db/__init__.py` into a package), INK-069 (other large modules), INK-070 (SQLAlchemy vs raw sqlite3), INK-071 (Alembic vs hand-rolled runner). All backlog; `db/__init__.py` is still one module on `main`.

## Known issues (open)

Bug tickets INK-074..INK-096, all open except INK-075 (done). Grouped:

| Area | Problem | Tickets |
|---|---|---|
| Tablet / LAN lag, slow load | Pen, pan and zoom lag on the LAN/tablet (INK-074); opening a canvas is slow, especially on the tablet (INK-080). Saves were the big cost and are fixed by delta saves (INK-075), load is not | 074, 080 |
| Mega-chunks and id churn | On a real canvas chunks grow too big and ids change often, so notes see `replaced`/`removed` (INK-081). Chunk overlay and merge/split lose active chunks once orphans pile up (INK-089). Orphan chunks and their crops are never deleted (INK-087). Large chunks need a crop and recognition budget (INK-096) | 081, 087, 089, 096 |
| Agent font and placement | Agent text is far smaller than handwriting because the clamp is 64 (INK-082). Drafts land far apart (INK-077). No pan to a new draft (INK-076). Sketch reading treats letter loops as nodes at tablet zoom (INK-085). `read_canvas` overview is unreadable on a large canvas (INK-086) | 076, 077, 082, 085, 086 |
| Orphaned anchors | Agents can anchor to, or read, orphaned chunks (INK-084). Undelivered `write_text` ops never expire and can block the canvas (INK-088) | 084, 088 |
| Conflict notice and merge | Conflict notice shows without another tab (INK-083). Conflict merge drops a local edit when both tabs bump an element to the same version (INK-090) | 083, 090 |
| Drafts and chunks | Accepted drafts get no chunk (INK-078). Chunk overlay misses new chunks until reload (INK-079). An accept whose save fails leaves the op `applied` with no way to finish (INK-091) | 078, 079, 091 |

Also open from earlier: vault loop on real handwritten pages (decision 0022), re-check chunker `k` on real pages, MCP behaviour in the Claude Desktop/Code GUIs is unverified (decision 0003), vault location defaults to a temp folder until `INKBRIDGE_VAULT` is set.

## Cut order if short on time

INK-060, E2/E3, stroke arm of E1, source previews, Keep on canvas, Accept/Reject (keep Accept all), manual merge/split, then Ask panel and runner (keep the pull path). Never cut: canvas-to-note path, stale check, README, demo video.
