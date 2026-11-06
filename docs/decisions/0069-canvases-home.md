# 0069: Canvases home and instant switching

Status: accepted (INK-118). Owner checks pending: tablet (switch canvases without a reload, pen in the second canvas, a stroke drawn just before leaving survives), long-press menu with finger-sized targets, visual sign-off with real thumbnails.

## Context

Spec v4 "Canvases home" and the tech reference "Document routes" replace the single `default` canvas with a home screen (Continue, Recent, All canvases, Archived) and a switch between canvases that does not reload the page. The server had `GET /documents` (id, title, updated_at, version) and nothing else. The thumbnail renderer came with INK-120 (`canvas/raster.py`, decision 0065), which left the endpoint and the cache to this ticket.

## Decision

- **"Head seq" is the scene `version` today.** Element rows land with a later ticket; the thumbnail cache key is `(document, version)`: `thumbs/<id>-<version>.png` beside the database. `GET /documents/{id}/thumbnail` answers `ETag: "v<version>"` and `Cache-Control: no-cache`, so a revisit costs a 304. A new version renders once on demand and deletes the older file of that canvas. The route is a plain `def` (threadpool), so rendering never blocks the loop. An id that is not `[A-Za-z0-9_-]{1,64}`, or not a canvas, is a 404 before any path is built.
- **`open_offers`** counts `agent_ops` in `pending|delivered|applied` for the canvas: drafts the user has not decided. INK-114/115 may redefine it.
- **`element_count`** counts elements that are neither deleted nor drafts. `chunk_count` counts active auto chunks (the board says "11 chunks").
- **`last_opened_at`** is stamped by `POST /documents/{id}/open`, called by the web when a canvas view is entered. `GET scene` does not write: a read must not count as "opened" (MCP and other readers use it).
- **Archive, pin, rename** are `PATCH /documents/{id}` (migration `0007`: `pinned`, `archived_at`, `last_opened_at`). Archiving never deletes; `archived:false` restores. Archiving twice keeps the first `archived_at`. PATCH does not bump `updated_at`, which stays "last ink edit". `GET /documents` hides archived canvases; `?archived=true` lists only them, `?archived=all` both. Order stays `updated_at DESC, id`; the web puts pinned first.
- **Duplicate** (`POST /documents/{id}/duplicate`, title "<title> copy") copies the live, non-draft elements through `put_scene`, so chunks, hashes and the search index come from the same path as any save (version 1). Questions, ops and recognitions are not copied. The canvas cap (500) answers 409 `too_many_canvases`.
- **Home search filters titles only**, client side. Search over ink readings across canvases belongs to the retrieval ticket.
- **`/` with no `canvas` parameter is home.** `/?canvas=<id>[&chunk=<id>]` is a canvas. The old `/` opening `default` is gone on purpose (`readRoute` still defaults, for code that calls it inside a canvas).
- **One SPA, `history.pushState`** (`lib/nav.ts`: `navigate`, `subscribe`, `onLinkClick`). Every tile is a real `<a href>`, so new tab and copy link work; a plain left click navigates in place. `Root` shows home or `<App key={canvasKey}>`: the key changes with the canvas and with the chunk, so Excalidraw and sync are torn down and rebuilt and a chunk link inside the open canvas applies its jump.
- **Flush on leave.** `SceneSync.close()` sends what is unsaved, then disposes (`dispose()` alone dropped the last edit inside the 1.5 s debounce). `App`'s cleanup calls it. A final save that ends in a 409 merge may call `onReload` after Excalidraw unmounted; `onReload` swallows that.
- `canvasTitle` asks `?archived=all` so an archived canvas opened by deep link keeps its title.

## Consequences

- `GET /documents` default now hides archived canvases. `element_count` parses each stored scene with `json_each`; fine for tens of canvases, revisit when element rows exist. `fetchTitle` reads the same list on every canvas open.
- `/` is home. A bookmark to `/` no longer opens `default`; vault links carry `?canvas=`.
- Load clock marks are relative to page load, so numbers after an in-app switch are not comparable with a cold load.
- No MCP tool changed, so `docs/mcp-tools.md` is unchanged. MCP has no archive or list-archived tool.
- `vite.config.ts` needs no change: every new route sits under `/documents`, which is already proxied.

## Open items

- `open_offers` versus the drafts-leave-the-scene work in INK-114/115.
- Title-only search.
