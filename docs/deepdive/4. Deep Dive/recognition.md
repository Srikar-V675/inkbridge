# Deep Dive: recognition (`recognizer/` and `recognizer/worker.py`)

> Snapshot written 26 Oct 2026; sections marked Updated 13 Nov 2026 were refreshed.

Recognition turns a chunk's crop PNG into text, LaTeX and a kind. It is a **cache in front of a model**: ink is the truth, a reading is keyed by `(region_id, content_hash, source)` (`recognitions` table). Moved or unchanged ink never triggers a model call because `content_hash` ignores position.

## Files

| File | Role |
|---|---|
| `recognizer/__init__.py` | `Recognition` dataclass (`text`, `latex`, `kind`, `model`), `Recognizer` protocol `(png, hint) -> Recognition`, the error hierarchy, `KINDS` |
| `recognizer/gemini.py` | `GeminiRecognizer`: prompt, spacing, retries, parsing, transport |
| `recognizer/claude.py` | `ClaudeRecognizer`: Claude Haiku through one persistent `claude -p` process (Updated 13 Nov 2026) |
| `recognizer/worker.py` | `RecognitionWorker`: the background thread and its rules |

There is deliberately no module-level `recognize()`. The only caller is the opt-in worker, which owns the privacy gate (decision 0017).

## Error hierarchy (`recognizer/__init__.py:23-49`)

`RecognizerError` is the base; the worker retries these with backoff. `PermanentError` (`MissingApiKey`, `InvalidApiKey`) stops the worker. `RateLimited` (429), `RecognizerTimeout` and `BadResponse` are transient.

## GeminiRecognizer (`gemini.py`)

- **Model**: `GEMINI_MODEL` or `gemini-3.5-flash-lite` (`:23`); key from `GEMINI_API_KEY`. With no key and no injected transport it raises `MissingApiKey` (`:54-55`). `__repr__` never includes the key (`:63`).
- **Prompt** (`:25-30`): transcribe, reply with JSON `{text, latex, kind}` where kind is one of handwriting, equation, diagram, mixed, no commentary. An optional hint is appended as "Context hint".
- **Calls are serialised** by a lock (`:68`) and spaced by `min_interval = 4.0` s (`_space_calls`, `:88`) to stay inside free-tier limits.
- **Retries** (`_send`, `:72-86`): only `RateLimited` retries, up to `max_retries = 3`, sleeping `backoff x 2^attempt` (2, 4, 8 s). Any other `RecognizerError` fails at once. Error messages are redacted (`_redact` replaces the key with `***`) and re-raised outside the `except` block so no chained context keeps the raw message.
- **Parsing** (`_parse`, `:98-119`): strips ```` ```json ```` fences, parses JSON, accepts a list of objects (joined by newlines), requires a string `text` in each; `latex` values are joined; `kind` is lower-cased, aliased (`text` -> handwriting, `math` -> equation) and falls back to `mixed`. Bad JSON or a missing `text` raises `BadResponse`.
- **Transport** (`_google_transport`, `:121-152`): `google-genai` client with `response_mime_type="application/json"`. Mapping: 429 -> `RateLimited`; 401/403 or 400 "api key not valid" -> `InvalidApiKey`; 408/504 or any timeout-looking exception -> `RecognizerTimeout`; anything else -> `RecognizerError` with the code.
- `default_recognizer()` builds one shared instance under a lock.

Tests inject a `transport` callable so nothing goes to the network (`tests/test_recognizer.py`).

## Claude reader and the 13 Nov worker (Updated 13 Nov 2026)

**Choosing the reader.** `make_recognizer()` in `recognizer/__init__.py` reads `INKBRIDGE_RECOGNIZER`: `gemini` (default) or `claude`; anything else warns and means `gemini`. Gemini stays for test and eval pages because its free tier trains on content. The Claude reader runs on the user's subscription and does not train on content (decision 0104), though the opt-in canvas list still gates what is read. A stored reading keeps source `gemini` whichever reader made it; `recognitions.model` says which (`claude-haiku`).

**`ClaudeRecognizer`** (`recognizer/claude.py`, INK-185): one long-lived `claude -p --input-format stream-json --output-format stream-json --model haiku` process with tools off (`--tools ""`), `--strict-mcp-config`, no slash commands, no session persistence and an empty setting-sources list, started in a temp directory (`_spawn_for`, binary from `INKBRIDGE_CLAUDE_BIN`). Each chunk image is one user line and the answer is the next `result` event; a pump thread feeds stdout into a queue (`_Proc`). Calls are serialised by a lock; the process is reset after `max_requests = 25` reads, or on any error or timeout (`timeout = 60` s), to bound context growth. It reuses Gemini's `PROMPT` and `parse_reading`, raises `ClaudeNotFound` (a `PermanentError`) when the binary is missing, and logs usage on `inkbridge.recognizer.usage` (it counts against the 5-hour subscription window). `read_ink(png, prompt)` returns the raw reply and is also used by the latest-ink read (`agent/latest_ink.py`, offers only).

**Structure hint.** For each chunk the worker calls `_structure_hint` and passes the result as the recognizer's `hint` (Gemini appends it as "Context hint"). `canvas/structure.py` `hint(elements, ids)` runs the sketch reader (`canvas/sketch.py`), and when it finds at least `MIN_NODES = 2` boxes it names up to `MAX_LISTED = 12` boxes and arrows in plain words, with an `INSTRUCTION` telling the reader to write the labels first and then one relation per line (`docs -has-> regions`), to trust the picture over the hint, and to ignore the hint when the picture is not a diagram (INK-208, decision 0123). A wrong guess costs nothing. This replaces the old note that the worker always passes `None`.

**Candidates and latency** (INK-196, decision 0111). `db.recognition_candidates` orders by `regions.updated_at DESC, id`, so the line just written is read first, and excludes `kind = 'connector'` chunks. A reading is dropped when the region's content hash changed during the model call (the new hash gets its own read), and a pass ends early if the canvas was saved while it ran. The idle delay defaults to 1.5 s with the Claude reader (5 s otherwise; `INKBRIDGE_RECOGNIZE_IDLE_S` wins). A scene save nudges the worker (`RecognitionWorker.nudge`): a daemon timer wakes the loop `idle_s + 0.1` s later so a pass starts right after the idle delay. The logger `inkbridge.recognizer.latency` writes `region= latency_ms= backlog=` after each saved reading. About 3 s per chunk with the Claude reader.

**Too large to read.** A chunk over `imaging.MAX_READ_UNITS` (4096) or `MAX_CROP_ELEMENTS` (1500) is never sent to a reader; outlines say `read_status: too_large` (decision 0052). Since chunker v2 cuts oversized groups at 3000 units and 600 elements (decision 0124), this is now rare.

**Server crops.** With `INKBRIDGE_CROP_SOURCE=server` the worker renders a stale crop itself with `canvas/raster.py` before reading (decision 0065).

## RecognitionWorker (`recognizer/worker.py`; the sections below are the 26 Oct snapshot)

![diagram 1](../../img/recognition-1.png)

<details><summary>Mermaid source</summary>

```mermaid
flowchart TD
  T[thread loop every poll_s=2s] --> RO[run_once: own db connection]
  RO --> RD[_read_document per opted-in canvas]
  RD --> C[db.recognition_candidates<br/>active, png_stale=0, no reading for content_hash]
  C --> GO{_may_go_on?<br/>not stopped, not paused, canvas idle or urgent}
  GO -->|no| STOP[end this pass]
  GO -->|yes| BO{in backoff?}
  BO -->|yes| SKIP[skip chunk]
  BO -->|no| CROP[db.read_fresh_crop under BEGIN IMMEDIATE]
  CROP --> MODEL[recognizer png]
  MODEL -->|PermanentError| DEAD[stopped = True]
  MODEL -->|other error| BACK[_back_off, 429 or timeout pauses all]
  MODEL -->|ok| SAVE[db.save_model_reading]
  SAVE -->|locked| UNSAVED[keep reading in _unsaved]
  SAVE --> PUB[publish chunks.updated with recognized ids]
```

</details>

### Construction (`from_env`, `:68-91`)

Reads `INKBRIDGE_RECOGNIZE_DOCUMENTS` (comma list; empty returns `None`, so the worker is off), `INKBRIDGE_RECOGNIZE_IDLE_S` (default 5; a bad number logs a warning). A missing key or SDK logs a warning and returns `None`: it never raises, so the API still starts.

### Timing and state

- `idle_s = 5`, `poll_s = 2`, `backoff_s = 30`, `backoff_max_s = 600`.
- `_idle` compares `now - documents.updated_at` to `idle_s`, so a canvas that is being saved is left alone; drawing never waits on this thread.
- `_may_go_on` is checked **before every chunk**: not stopped, not fatal, not paused, and idle (the idle delay is skipped for an urgent chunk).
- State: `_failures[(region, hash)] = (count, retry_at)`, `_unsaved` (readings whose save hit a locked database, kept so no new model call is needed), `_paused_until` (global pause), `_urgent[doc][region] = expiry`.
- Stale entries are dropped each pass when their key no longer appears among candidates (ink changed or chunk gone, `:189-192`).

### Backoff (`_back_off`, `:249-262`)

Delay doubles per failure: `min(30 x 2^(n-1), 600)`. For `RateLimited` and `RecognizerTimeout` the whole worker pauses until the same time, because trying the next chunk would hit the same provider problem.

### Urgent requests (`request`, `:139-162`)

Used by `check_sync`. Returns the region ids it will try: none if the canvas is not opted in, the worker is stopped or not alive, or calls are paused; ids still in backoff are excluded. Accepted ids get an expiry (`ttl_s`, default 60) and are sorted first in the candidate list (`:194`). `_wake` is set so the thread skips the rest of its poll sleep.

### Races handled

- `db.read_fresh_crop` re-checks, under `BEGIN IMMEDIATE` (the same lock crop uploads take), that the region is still active with that content hash and a fresh crop before the bytes are read (`db/__init__.py:909-929`). The candidate list can be seconds old because each model call takes time.
- A locked database on read or save is logged and retried on the next pass (`sqlite3.OperationalError`); the reading is not lost.
- `publish` (wired to the WebSocket hub) sends `chunks.updated` with `recognized` ids, the scene version and the stale-crop ids.

### One process only

Each API process would start its own worker (decision 0017). Run one.

## Privacy

Gemini free tier may train on content; the Claude reader does not (Updated 13 Nov 2026). Nothing is read unless the canvas id is in `INKBRIDGE_RECOGNIZE_DOCUMENTS`; keep personal canvases out. Real notes are read by Claude through `read_canvas` and `get_region`.

## Testing

`tests/test_recognizer.py` (parsing, retries, redaction, spacing with injected clock and sleep) and `tests/test_recognition_worker.py` (about 45 tests: zero calls on a second run or after a move, one call after an edit, source precedence, stale or missing crops skipped, idle wait, only listed canvases, orphans skipped, backoff and a global pause on 429, permanent error stops the worker, locked database keeps the reading, ink edited during a call is not read under its old hash, urgent requests and their TTL, `from_env` never raising, and that the worker never imports the API).

## Potential improvements

- `min_interval` is a per-process pacing; two processes would double the rate.
