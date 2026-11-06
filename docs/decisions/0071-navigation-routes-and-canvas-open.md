# 0071: Navigation routes and a quicker canvas open

Status: accepted (INK-172). Amends 0069 ("Canvases home and instant switching", the routing part). Owner checks pending: tablet (Home, Archived, system Back lands on home; the Canvases link from a canvas; open a large canvas from home and judge the open time against the numbers below), visual sign-off of the "Canvas not found" state.

## Context

Three things were wrong after 0069. "Archived" and "Back to canvases" only set component state, so the history stack for canvas, Canvases, Archived was `[canvas, home]` while the screen showed Archived: system Back skipped Archived and the home. The top bar "Canvases" link always pushed `/`, so a canvas opened from home grew the stack (`home, canvas, home`). An unknown `?canvas=` id (the server answers 404 and never creates one on read) showed an empty paper with a risk badge and no explanation. Opening a canvas was also slower than it needed to be: the title showed the raw id for about 100 ms, and Excalidraw mounted only after the scene had downloaded.

## Decision

- **Archived is a route.** `/?view=archived` is a real history entry (`parseLocation` gives `{kind: "home", archived: true}`; `archivedHref(on)` builds the link). `Home` takes `archived` as a prop; the "Archived" and "Back to canvases" controls are anchors, so new tab and copy link work. `view` is ignored on a canvas URL. `/` is still home, never a redirect to `default`.
- **`backTo(url)` steps back instead of growing the stack.** Every `navigate` stores the URL it was pushed from in `history.state` (`prev`; a `replace` keeps the old `prev`). `backTo` calls `history.back()` when `prev` is the target, and pushes the target otherwise (a deep link, a new tab, a reload that lost nothing but a stack). Used by "Back to canvases" and the top bar "Canvases" link. Consequence: after home, canvas A, Canvases, canvas B, Back lands on home, and the next Back leaves the app's own entries, because the A entry was popped by the step back. From a canvas opened out of the Archived view the previous entry is Archived, not home, so "Canvases" pushes home (`[home, archived, canvas, home]`); only a canvas opened from home steps back.
- **Search text and list mutations never touch history.** Search is component state; archive, restore, rename, pin and duplicate only reload the list. The list is tagged with the view it was loaded for, and a response that is not the newest load is dropped, so switching views never shows the other view's list.
- **The home passes the canvas title in `history.state`** (`hint {canvas, title}`; tile clicks and a new canvas). `titleHint(canvas)` returns it only for that canvas. The top bar shows it from the first frame. It is refreshed with `GET /documents/{id}` after the first paint (it may be stale after a rename elsewhere); a deep link or reload without state fetches immediately, as before.
- **Unknown canvas shows "Canvas not found".** `SceneSync.notFound` is true after a 404 load only (a network error or a 5xx leaves it false). `CanvasState` fills the canvas area: heading, "No canvas has the id <code>", and a "Back to canvases" button; a failed load reads "Could not open this canvas". Top bar title says "Canvas not found". No empty drawing surface, no rail. Tokens only, no lime, no alarm colour of its own (DESIGN.md "Canvas state").
- **Excalidraw mounts at once, with `initialData` as a promise** (`sceneData`, resolved with the restored elements after `sync.load()`; `null` when the canvas did not open, which then unmounts it). `restoreElements` still runs before the data reaches Excalidraw. A cancelled effect never resolves, so a dead promise never reaches a mounted Excalidraw. **Nothing acts on that early Excalidraw until the scene is open:** a transparent `.ink-shell__loading` layer over the canvas catches pen and touch while `initial` is null (Excalidraw's pointer handlers ignore its loading state, and a stroke drawn then would be replaced by the scene when it lands), and the rail, zoom control and draft bar get no api until the canvas is open. `SceneSync.notify` returns false before `load()` has succeeded, so nothing can be saved or backed up from a canvas that is not the saved scene (`close()` before load sends nothing). Checked with the scene response held for 2.5 s: a stroke attempted in the window did not appear and no save was sent; a stroke right after load saved. Excalidraw's own `LoadingMessage` is hidden in `shell.css` (it would flash over the dotted paper); the existing "Loading…" status in the top bar is the loading state, nothing louder was added.

## Measurements

Method: `docs/tickets/plans/INK-172-measure-open.cjs` (Playwright, system Chromium, fresh context per run, 4x CPU, 40 ms latency, 10 Mbps), canvas of 641 elements from `eval/fixtures/make_real_scale.py`, home tile click. Milliseconds after the click.

| build | topbar | title (not id) | excalidraw canvas | load.fetch | load.parse | load.restore | load.firstChange | load.total |
|---|---|---|---|---|---|---|---|---|
| base commit (median of 3) | 34 | 98 | 490 | 73 | 138 | 33 | 532 | 775 |
| title hint only (median of 3) | 31 | 31 | 461 | 70 | 128 | 48 | 462 | 712 |
| title hint + early mount (median of 5) | 31 | 31 | 197 | 67 | 204 | 25 | 184 | 480 |

Gate for the early mount: median `load.total` and median click to Excalidraw at least 15% better. Result: 38% and 60% better than the base commit, so it is kept. Checked in a browser with the early mount: pen, eraser and zoom controls work, a stroke saves (version and element count rise by one, no save on a plain open), a `?chunk=` deep link still selects and fits the chunk, the chunk overlay and zoom control show, and no Loading message is visible. `GET /documents/{id}` is no longer on the critical path when the home passed a hint.

## Consequences

- `Location` home variant carries `archived`; every `deepEquals` on it needed the field. The `Win` type of `nav.ts` now needs `history.back` and `history.state`.
- `history.state` survives reloads and Back/Forward, so a hint can be stale; it is only trusted for the first frame.
- The rail and zoom control appear only once the scene is open, as before; the gain of the early mount is Excalidraw's startup, not a visible rail.
- A title hint is refreshed only with a real title: `fetchTitle` answers the raw id on failure, and that never replaces a hint.
- Numbers are from throttled desktop Chromium, not the tablet.

## Open items

- Tablet numbers, and pen feel with the early mount (patched freedraw, `penMode`).
- Visual sign-off of the "Canvas not found" state.
