# 0052: Crop and recognition budget for large chunks (INK-096)

Status: accepted

## Context
A very large chunk (INK-081's mega-chunk is 10106 x 5957 units) made the browser export a PNG that
blocks the main thread and, capped at 2048 px, is downscaled past reading. Gemini and the agents
would then receive an unreadable image.

## Decision
- One limit, mirrored on both sides: `MAX_READ_UNITS = 4096` (longest bbox side) and
  `MAX_CROP_ELEMENTS = 1500`. The browser exports at `maxWidthOrHeight: 2048`, so 4096 units
  keeps the scale at 0.5 or better; 1500 elements bounds the main-thread cost of one export.
  Constants live in `server/src/inkbridge/imaging.py` and `web/src/cropSync.ts`; a test on each
  side pins the numbers.
- Nothing is stored. Whether a chunk is too large is a pure function of its bounds and element
  count, so both sides recompute it, and a chunk that is split or shrunk is exported again. A
  skipped chunk stays `png_stale=1` (honest: no crop exists); the browser just never exports it.
- Enforcement points: the browser (no export, no upload; `crop.skipped` mark once per chunk), the
  recognition worker (no model call even for a legacy crop or an urgent `check_sync` request,
  logged once per region and hash), `check_sync` (`needs_reading` does not wait for it), and MCP
  `get_region` (no image, a text note).
- Outlines (`/chunks`, `read_canvas`) carry `read_status: ok | too_large` and `read_note`
  ("too large to read (WxH units, N elements): split the chunk") so an agent asks the user to
  split instead of guessing.
- Cadence: one chunk per idle slot with `slotMs` (250 ms) between chunks, rechecking pointer,
  idle and version before each. Per-chunk failure backoff in the browser: 30 s doubling to 10 min,
  cleared on success. `crop.export` is recorded per export (elements).

## Consequences
- The exportable set is bounded by 1500 elements per export. No timing was measured on tablet
  data here; the `crop.export` mark gives the number for the next run on a real page.
- Crops and readings made before the limit stay as they are; only new reads are blocked.
- 4096 and 1500 are untuned for a real tablet page; each is one constant per side.
- Only model calls are removed; nothing new is sent to Gemini.
