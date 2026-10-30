# Deep Dive: web chunks, deep links, overlay and overrides (`chunks.ts`, `ChunkOverlay.tsx`, `overrides.ts`)

Framework-free logic in `chunks.ts` and `overrides.ts`; `ChunkOverlay.tsx` is the React layer (INK-035, INK-059, decisions 0014 and 0024). All fetches use plain `fetch` and DOM-free maths, so they work over LAN HTTP (not a secure context).

## Deep link resolution (`chunks.ts`)

URL contract: `/?canvas=<document id>&chunk=<chunk id>`.

`resolveChunk(id, canvas)` (`:72-106`):
1. `GET /regions/{id}` with an 8 s timeout covering fetch and body read (`AbortController` works in insecure contexts). 404 means `missing`; other failures mean `error`.
2. A chunk of another document, or not `created_by === "auto"` (a manual region), is `missing`.
3. If the chunk is not active, follow `successor_of` for up to `MAX_HOPS = 10`, stopping on a cycle or a different canvas. A gone successor ends the chain at the last orphan; a network failure on a successor reports `error` (not evidence that the chunk is gone).
4. Outcomes: `found` (the linked chunk is active), `successor` (replaced; jump to the active successor), `orphaned` (dead end; open at the last orphan's old bounds), `missing`, `error`.

`jumpNotice(result)` returns the banner text: "Source changed: chunk X was replaced, showing Y.", "...no longer exists, showing where it was", "Chunk X not found on this canvas.", or "Could not load chunk X...". `null` when the link resolved to the chunk it named.

`jumpPlan(jump, scene)`: select-and-fit the chunk's live strokes (`liveIds` filters to elements present and not deleted locally, because the server may be ahead or behind); an orphan, or one with no live local strokes, opens at its bounding box; `null` when there is no chunk. Only view state changes, never elements, so a jump cannot trigger a save.

Viewport maths: `viewForBounds(b, viewport)` centres the bounds with a 10% margin, zoom clamped to `[0.1, 1]` (never above 100%); `toScreen(b, view)` implements Excalidraw's `screen = (scene + scroll) x zoom`.

`listChunks(canvas)` loads `?chunks=true&limit=500` and keeps the active ones; failures give an empty list. Known limit (in the source): the server applies `limit` before the status filter and orders by recency, so a canvas with over 500 chunk rows (orphans included) can miss active ones.

## Overrides (`overrides.ts`)

`planOverride(selected, chunks, connectors)` (`:21-37`) decides what a selection means:
- ids in `connectors` (arrows, lines, and text bound to them; `connectorIds(scene)`) are ignored on both sides, because the server keeps them with the chunk they start from, so only ink decides;
- selection touching no chunk: `none` ("Select ink that belongs to a chunk.");
- touching two or more chunks: `merge` of those chunks (whole);
- touching part of one chunk: `split` of that part; if the selection is that whole chunk's ink: `none` ("already is a whole chunk").

`sendOverride(canvas, plan)` POSTs to `/documents/{id}/chunks/merge|split` with an 8 s timeout and returns `{ok, ids}` (ids from `chunk` or `chunks`) or `{ok: false, message}` using the API's `detail` string, or "Could not reach the server; try again." on network failure. The server owns overrides (pinned chunks; see [database.md](database.md)); nothing here touches the scene.

## Overlay (`ChunkOverlay.tsx`)

Plain DOM over the canvas; UI state only, nothing here touches the Excalidraw scene, so the overlay can never be autosaved (decision 0014). Hooks: `useView` follows scroll/zoom via `api.onScrollChange`; `useSelection` tracks selected ids via `api.onChange`, updating state only when the selection itself changes; `useChunks(canvas, on, session, status)` loads active chunks while the overlay is on and **refetches whenever the save status moves into `saved`** (not on the WebSocket). Requests are numbered so only the latest may set the list, and rows are tagged with a `session` (one per time the overlay is switched on) so turning it on again never shows a list from before. `OverrideActions` computes `planOverride(selected, chunks, connectors)` (connectors read from the scene only when the selection changes), enables "Merge chunks" or "Split selection" accordingly, and calls `sendOverride`; after any result it refreshes the list, since a refusal usually means the list was stale. Boxes use `toScreen`.

Rendering (`ChunkOverlay.tsx:174-242`): a "Show chunks" / "Hide chunks (N)" toggle button at the bottom right (`aria-pressed`; switching on starts a new `session`). When on, a non-interactive layer (`pointerEvents: none`, `zIndex: 4`) draws one blue box per chunk with a monospace id label above it (inside the box when it touches the top edge); a **pinned** chunk gets a thicker 2.5 px border and a "· manual" suffix. A dashed orange "ghost" box shows the old bounds of an orphaned deep-linked chunk until the notice is dismissed (it renders even when the overlay is off). The Merge/Split buttons sit above the toggle (`OverrideActions`, `:89-155`), disabled with a tooltip carrying the plan's reason when nothing applies; the merge tooltip reads "Merges the whole of every chunk the selection touches"; a status line shows "Merged into <id>" or "Split into <id> and <id>" or the refusal message.

## Testing

`web/tests/chunks.test.ts` (11.9K: successor chains, cycles, timeouts, notices, view maths) and `overrides.test.ts`.

## Potential improvements

`listChunks` could use `GET /documents/{id}/chunks` (exists since INK-033) and drop the 500-row caveat.
