# 0030: Save latency verdict and timing logs (INK-067)

Status: accepted, 2 Nov 2026.

## Verdict rule (written before measuring)

Warm 100-stroke save `total` under 100 ms: no server work, keep the 1500 ms debounce. 100 to 500 ms:
acceptable, a diff PUT is the first lever. Above 500 ms: follow-up ticket naming the dominant phase.

## Measurement

```
cd server && uv run python ../scripts/bench_scene_save.py --sizes 100 1000 --points 100
```

Machine: x86_64, 12 threads, Linux, SQLite on /tmp. Median ms of the server side of `put_scene`
(phases from the `inkbridge.scene` log, decision 0027); 100 points and pressures per stroke.

| strokes | save | parse | diff | refresh | chunks | total |
|--------:|------|------:|-----:|--------:|-------:|------:|
| 100 | cold | 2 | 0 | 0 | 33 | 35 |
| 100 | warm | 3 | 0 | 0 | 5 | 8 |
| 1000 | cold | 19 | 0 | 0 | 320 | 340 |
| 1000 | warm | 34 | 2 | 0 | 48 | 85 |

**Verdict: warm 100-stroke save is 8 ms, under 100 ms. No server work needed; keep the 1500 ms
debounce.** Even 1000 strokes stay at 85 ms warm. If the chunker ever dominates, the first lever is
chunking off the request path. Network and browser serialisation are not in these numbers: read
them from the `timing scene.save ... ms= elements= bytes=` lines in `web/dev.log` (dev builds only)
and the "Saved: N ms" badge on the tablet. No tablet run was done for this note.

## Logging

- Server: `inkbridge.request` (one line per HTTP request: method, route template, status, ms; WARNING
  above 1 s), `inkbridge.timing` (`timed(name, **int_counts)`: check_sync, ops.create,
  recognition.pass), `inkbridge.scene` (0027). All to stderr via `configure_logging()`; no file
  logging. Counts must be ints (enforced with `TypeError`), and the route template is logged, never
  the raw path, query or body, so no scene content, ids or readings reach a log.
- Web: `timing.ts` (`timed`, `record`, default no-op sink). The only module that names `/__log` is
  `devLog.ts`, loaded by dynamic import under `import.meta.env.DEV` in `main.tsx`; the build drops
  it (`grep -rl '/__log' web/dist` prints nothing) and a test guards the source layout. Records:
  `scene.load`, `scene.save` (elements, bytes), `crop.pass`, `crop.upload`, `chunks.list`,
  `ops.apply`. The save time also shows in the status badge detail.
- Deviation from the plan: `recognition.pass` counts documents, not regions, and `ops.create` counts
  payload fields, because those counts are not known before the work and `timed` takes counts up
  front. The finer phases (hashing, persistence, links, index) stay inside `chunks`; split them only
  if a measurement shows `chunks` dominating.
