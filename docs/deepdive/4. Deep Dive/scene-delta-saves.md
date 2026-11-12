# Deep Dive: delta scene saves (`web/src/sync/sceneSync.ts`, `api/__init__.py`, `db/__init__.py`)

> Snapshot written 26 Oct 2026; sections marked Updated 13 Nov 2026 were refreshed.

> Updated 13 Nov 2026: delta saves were superseded by per-element storage. Autosave now journals ink to IndexedDB (`sync/journal.ts`) and `sync/sender.ts` posts changed elements with `POST /documents/{id}/elements`, idempotent by `(device, batch)`; the server merges per element (higher `version` wins, nothing deleted by omission), so there is no `base_version` check or 409 on that path, and other devices get `scene.delta` over the WebSocket (decisions 0077, 0080, 0087, 0088). `PUT /scene` with `delta: true` still works and runs the same merge with `strict=False`. The text below is the 26 Oct design.

INK-075, decision 0036. Autosave used to `PUT` the whole scene. A 496-element canvas (about 1 MB) took 96 s through the Vite proxy from the tablet while the server needed 41 ms, so cost grew with the page, not with the edit. Now only changed elements travel.

## Flow

```text
browser                                         server (put_scene)
-------                                         ------------------
baseline: id -> version (last confirmed)
changed = elements whose version != baseline
PUT {base_version, elements: changed, delta:true}
                                                BEGIN IMMEDIATE (write lock)
                                                version == base_version ? else 409
                                                _apply_delta: replace by id in place,
                                                  append unknown ids
                                                UPDATE scenes ... AND version = base
                                                re-chunk, refresh regions, commit
<-- {version}
baseline = versions of what was sent
```

## Client (`sync/sceneSync.ts`)

- `deltaFor(baseline, els)` returns the changed elements, or `null` (send a full save) when there is no baseline, when an element in the baseline is missing from the list (a delta cannot delete), or when the delta would not be smaller.
- The baseline is set on load and after every successful save, taken from what was sent (before the request, because Excalidraw mutates elements in place). A failed save keeps the old baseline, so the retry carries the whole unconfirmed diff.
- A 409 goes through the normal conflict path (reload, `mergeScenes`, retry); the reload rebuilds the baseline.
- `scene.save` timing record: `elements`, `sent`, `bytes`.

## Server

- `SceneIn.delta: bool = False`. `_elements_valid` runs the same per-element checks on a delta (finite numbers, string ids, geometry).
- `put_scene(..., delta=True, max_elements=50_000)`: `_apply_delta` keeps stored order, swaps changed elements by id, then appends new ones. Deleted ink stays in the scene as `isDeleted`, so nothing is ever removed.
- If the merged scene exceeds the cap, `SceneTooLarge` rolls back and the route answers 422.
- Safety rests on `base_version`: any other writer bumps the version, so a stale client gets 409 and never a bad merge.
- The phases are logged under `inkbridge.scene` (`parse`, `diff`, `refresh`, `chunks`, `total`); warning above 1 s.

## Testing

`server/tests/test_scenes.py` (replace in place and append, deleted flag and untouched ink kept, stale `base_version` is a conflict and changes nothing, cap), `test_scene_timing.py`; `web/tests/sceneSync.test.ts` (`deltaFor`, baseline after failure and conflict).

## Not done

gzip of the body; serving the built web from the API to drop the Vite proxy (INK-074). Opening a canvas is still slow (INK-080).
