# 0055 Canvas load: gzip, verbatim JSON, deferred startup (INK-080)

Status: accepted. Tablet numbers pending.

## What dominated
The synthetic real-scale fixture (INK-095, 641 elements) is 536 KB of JSON. The new `load.*` timing marks
(`web/src/loadClock.ts`: `fetch` = time to headers, `parse` = body download + parse, `restore`, `firstChange`,
`total`; each mark is the time since the previous one) show, on a laptop with headless Chromium throttled
to 2.5 Mbit/s, 40 ms latency and 4x CPU, that the body transfer dominates (`load.parse` about 730 ms of a
1100 ms `load.total`). Unthrottled, `load.total` is about 80 ms: restore and first render are not the problem
at this size.

## What changed
- `GZipMiddleware` (level 3, 1 KB minimum): 536 081 bytes become 123 652 (23 %). The Vite proxy passes the
  encoded body through. Crop PNGs go through it too (no size gain, small CPU cost at level 3; accepted).
- `GET /documents/{id}/scene` returns the stored JSON text instead of `json.loads` then re-encoding. Bytes are
  unchanged, so `pressures` and `simulatePressure` are preserved.
- `web/src/startupGate.ts`: the ops socket and crop sync start after the first change event plus an idle
  callback (3 s fallback timer for the socket). The first draft replay can be up to about 1.5 s later.

## Numbers (laptop, headless Chromium, dev server, same fixture; "interactive" = drawing canvas present)
| | before (main) | after |
|---|---|---|
| transfer | 536 081 B | 123 652 B |
| interactive, throttled (2.5 Mbit/s, 4x CPU) | 4.7 s | 2.0 s |
| `load.total`, throttled | n/a (no marks) | 1.1 s |
| interactive / `load.total`, unthrottled | 0.30 s | 0.30 s / 81 ms |

A synthetic pen stroke sent right after the canvas appeared landed on the server (element count +1).

## Budget
Laptop headless `load.total` <= 2000 ms for the fixture (met: 81 ms, 1.1 s throttled). Tablet: 2000 ms to
drawable; numbers pending, to be filled in by the user. `scripts/bench_scene_load.py` records sizes and
server time; `server/tests/test_scene_load_budget.py` guards the gzip ratio (<= 0.35, observed 0.23).

## Not done, on purpose
- IndexedDB stale-while-open cache and a changed-elements GET: needs a new endpoint and conflict reasoning; own ticket.
- Single-origin static serve: waits for INK-074.
- Viewport-first rendering or payload trimming: only if tablet numbers still miss the budget.
