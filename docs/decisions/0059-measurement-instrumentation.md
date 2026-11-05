# 0059 Measurement instrumentation: save phases, device log, echo probe (INK-102)

Status: accepted, 2026-11-06. INK-102 only collects numbers; the verdict is the later measurement session on the tablet.

## Decisions
1. **`timing` shape.** The PUT scene response is `{"version": N, "timing": {recv, queue, lock, work, commit, total}}`, ms rounded to 0.1. `recv` = ASGI app entry to last body byte (measured in `BodySizeLimit`). `queue` = last body byte to the first line of the sync handler, so it includes FastAPI body parse, pydantic validation and the wait for a threadpool thread. `lock` = `BEGIN IMMEDIATE` wait. `work` = lock acquired to just before `commit`. `commit` = `conn.commit()`. `total` = before `BEGIN IMMEDIATE` to after commit. A replayed save (same `X-Inkbridge-Save`) carries only `recv`, `queue`, `lock`. A 409 carries no timing.
2. **`db.put_scene` still returns the int version.** It takes an optional `timings` dict as an out-parameter, so existing callers and tests are untouched. The `inkbridge.scene` log line is built from that dict.
3. **Debug routes exist only with `INKBRIDGE_DEVICE_LOG=1`**, mounted at import time. Without the flag they are 404 and absent from OpenAPI. `/__log` is untouched.
4. **The client is opt-in by URL.** `?devicelog=1` turns it on and remembers it in localStorage (`inkbridge.deviceLog`), `?devicelog=0` clears it, `?probe=1` implies it. Off means no heartbeat, no frame loop, no beacons. The client cannot know the server flag; a 404 on the beacon is ignored (shortcut: add a status check if it confuses the session).
5. **Privacy by construction.** `debug.clean()` copies only `device`, `name`, `ms`, `t` and `counts`. Strings are allowed only in `device` and `name` and only matching `[a-z0-9_.]`; every `counts` value must be a finite number. A record that fails is dropped whole; extra keys are never copied.
6. **Not built:** the pen-down-to-first-paint probe from tech ref section 12, and `PerformanceLongTaskTiming` (the tech ref says not to rely on it). An event-loop lag sampler (`inkbridge.loop`, warns over 200 ms) is built instead on the server.
7. **`total=` in the `inkbridge.scene` log now includes lock wait**, so it is not comparable with the numbers in decision 0030. `scripts/bench_scene_save.py` still parses it (it reads any `key=NNms`).

## How to read it
`data/logs/device.jsonl`, one JSON line per record: `device` (random id kept in the tablet's localStorage), `name`, `ms`, `t` (client epoch ms), `ts` (server receive time) and `counts`.

- `scene.save`: `elements`, `sent`, `bytes`, server parts `s_recv s_queue s_lock s_work s_commit s_total`, and browser parts `n_pre n_conn n_wait n_recv`. `n_conn > 0` means a new TCP connection; `n_wait` includes upload plus server time.
- `main.gap`: a main-thread heartbeat (100 ms timer) that arrived more than 200 ms late; `ms` is the gap.
- `frames.pointer` / `frames.wheel`: frame-time buckets (`le20 le34 le50 le100 gt100 frames`) during a pen stroke or a wheel/pan.
- `probe.main.<state>` / `probe.worker.<state>`: a 4 KB `PUT /debug/echo` once a second from the main thread and from a worker; `counts` are `seq`, `bytes`, `ok`.

Probe truth table: main slow + worker fast = main-thread contention; both slow = network or browser; both fast = the app's request path (body parse, scene work).

## How to run
Server: `INKBRIDGE_DEVICE_LOG=1`. Page: `?devicelog=1`, or `?probe=1&state=idle|writing|panning` (300 requests, about 5 min).
