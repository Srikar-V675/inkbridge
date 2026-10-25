# 0007: A save conflict merges instead of reloading

Status: accepted (INK-007)

When an autosave `PUT` gets 409, the web client reloads the server scene and merges it with every
local element (`mergeScenes` in `web/src/sceneSync.ts`), then saves the merge against the new
version. A plain reload, as first planned, would throw away whatever the user drew since the last
successful save. The merge uses the element's own `version`: the higher one wins and a tie keeps
the server copy. Two tabs that edit the same element to the same version keep only the server
copy of that element; new elements are never dropped. The local scene at the conflict is also
written to `localStorage` (`inkbridge-conflict-backup-<id>`) as a last resort.

The merge uses the newest scene Excalidraw reported, not the one the failed save sent, because
the canvas stays live while the reload is in flight. Local element objects are passed back to
`updateScene` unchanged so a stroke still being drawn is not replaced by a copy.

The scroll and zoom of each canvas are a per-device convenience and stay in `localStorage`, never
on the server. A canvas with ink and no remembered view is fitted to its content once on open.
