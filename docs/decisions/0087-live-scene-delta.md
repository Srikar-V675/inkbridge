# 0087 Live scene delta (INK-112)

## Context
After INK-110/111 every write is a merge of element rows with a head `seq`, but other open tabs only
learned of a change through `chunks.updated` and their own next save answer. Two devices on one canvas
(laptop and tablet) did not see each other's strokes. This supersedes INK-063.

## Decision
- The server publishes `scene.delta {seq, origin, elements}` after every merge that wrote rows. `elements` are the winners this merge stored (`MergeResult.written`), with draft-flagged elements left out. A replay or a no-op merge publishes nothing. It goes out before `chunks.updated`, so a tab shows the ink before it hears about stale crops.
- Origin: `POST /elements` body `device`; legacy `PUT /scene` the part of `X-Inkbridge-Save` before `:` (the web `SceneSync.tabId`). The browser opens `/ws?document=ID&device=<tabId>` and `Hub.send` skips sockets whose device equals the message `origin`. The client drops its own origin as well.
- The client applies deltas through `applyNewer` (the same rule as the server; it handles tombstone stubs without a `type`, which `reconcileElements` and `restoreElements` cannot take), via `SceneSync.applyRemote`. The save baseline and signature move with the remote elements, so no echo save fires. This deviates from the ticket wording ("reconcileElements").
- `LiveDelta` keeps `lastSeq` (max seq seen from deltas and catch-ups, starting at the scene load seq). Own save answers do not advance it, so a delta lost from another device is always refetched with `GET /elements?since=lastSeq` on socket connect and when the tab becomes visible. Gaps are normal (own writes), so there is no gap detection.
- Deltas queue by id (winner by `winsOver`) while the pen is down and apply when `onChange` sees it lifted.
- `onReload` updates the scene with `captureUpdate: NEVER`: remote ink never enters local undo (this also covers the existing `newer` answers).
- `SceneSync.load` seeds `latest` once, so a delta before the first change event does not replace the scene with only the remote elements.

## Consequences
- `SceneSync.version` is not advanced by remote deltas, so a legacy PUT `newer` may repeat rows already shown (harmless).
- A save in flight when a delta lands may send the remote elements back once; the server treats it as a no-op.
- INK-114 removing drafts from the scene makes the draft filter dead but harmless.
- Echo suppression relies on Excalidraw keeping element order across `updateScene`.
