# Deep Dive: web scene sync (`web/src/sceneSync.ts`, `status.ts`, `view.ts`, `route.ts`)

Framework-free load and autosave for one canvas. `App.tsx` wires it to Excalidraw's `onChange`. Rules (tech ref 9.1/10.1, decision 0008): never block drawing, `PUT` with `base_version`, a 409 means reload and merge. No dependency beyond `fetch`, so it runs under Node's test runner (`web/tests/sceneSync.test.ts`).

## States (`SaveState`)

`loading`, `saved`, `dirty`, `saving`, `retry`, `conflict`, `error`. `status.ts` is a tiny external store (`get`, `set`, `subscribe`) so a badge change re-renders only the badge and never the Excalidraw canvas (a canvas re-render mid-stroke shows as a hitch).

## `SceneSync` class

| Method | Behaviour |
|---|---|
| `load()` | `GET /documents/{id}/scene`; stores `version`, `lastSig`, `savedIds`; returns the elements, or `null` with state `error` ("Unknown canvas" for 404, "Load failed (n)", "Cannot reach the Inkbridge API") |
| `notify(elements)` | Called from `onChange` with every element including deleted ones. Computes a signature `id:version|...`; returns `false` when it equals the newest known state (the pending one if any, else the last saved), because Excalidraw re-fires `onChange` after every re-render. Otherwise stores `pending`, emits `dirty`, debounces 1500 ms. Comparing with the *pending* signature means undoing back to the last saved scene while a save is pending still counts as a change |
| `settledVersion()` | The stored version the canvas matches exactly, or `null` before load or while edits are unsaved or saving. Crop sync uses this (decision 0015) |
| `flushNow()` | Page hidden: cancel the timer, await any in-flight save, then save with `keepalive` (only if the body is under 60,000 bytes, since browsers cap keepalive at 64 KiB) |
| `hasSaved(ids)` | True once the server holds every listed element; an op is acked only after its drafts are saved |
| `dispose()` | A disposed instance must not touch the shared badge (React StrictMode runs effects twice) |

## Save (`doSave`, `:154-198`)

1. The signature of what is sent is taken **before** the request, because Excalidraw mutates element objects in place: recomputed after the response it would include edits made during the request.
2. `PUT {base_version, elements}` as JSON.
3. `200`: update `version`, set `lastSig`, `savedIds`, reset the failure count; clear `pending` only if its signature equals what was sent, otherwise emit `dirty` and reschedule (the user kept drawing).
4. `409`: `resolveConflict`.
5. Other `4xx`: stop retrying until the next real edit (the same body would be rejected again) but keep the ink in memory; state `error` "Save rejected (n); changes are not saved yet".
6. `5xx` or network failure: `retryLater` with backoff 2, 4, 8, 16, 30 s (state `retry`).

## Conflict (`resolveConflict`, `:208-241`)

Another tab saved first.
1. Back up everything drawn locally (including edits made during the request) to `localStorage` key `inkbridge-conflict-backup-<doc>` so a conflict never silently destroys work (storage failures are tolerated).
2. Emit `conflict`, `load()` the server scene.
3. If the reload failed: keep the newest scene as pending and retry (the retry `PUT` conflicts again and reloads again), nothing discarded.
4. Otherwise `mergeScenes(fresh, newest)` and call `onReload(merged)`; if the merge differs from the saved scene, it becomes pending and is saved after the debounce.

`mergeScenes(server, local)` (`:28-38`): the server scene plus every local element; per id the higher `version` wins and ties go to the server. Deleted elements stay as tombstones with their bumped version, which is how a delete survives a merge.

## Other files

- `route.ts`: `readRoute()` parses `?canvas=` (default `"default"`) and `?chunk=`. This is the URL contract shared with vault notes.
- `view.ts`: per-device memory of scroll/zoom per canvas in `localStorage` (`inkbridge-view-<canvas>`), tolerant of missing or blocked storage and clamped to zoom 0.1 to 30; `keepFittingFirstDrafts(armed, now, elements)` decides whether a canvas opened empty should keep fitting the first agent drafts (true only if the view did not change and nothing but drafts is drawn; decision 0019).

## Testing

`web/tests/sceneSync.test.ts` (16K: debounce, signatures, conflicts, retries, merge), `view.test.ts`.

## Potential improvements

INK-063 (backlog): server push of `scene.updated` so open tabs sync without reloading. INK-062: pen pressure and lag are Excalidraw rendering constants, not this layer.
