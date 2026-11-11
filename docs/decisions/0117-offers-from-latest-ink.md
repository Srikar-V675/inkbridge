# 0117: Offers from the latest ink (INK-202)

Status: accepted, 11 Nov 2026. No migration.

## Context

Owner, 11 Nov: offers came late, missed a lone "?" and fired on half-written words. They waited for
the chunk to be cropped, uploaded and read. The Penecho approach reads what was just written.

## Decision

- `agent/latest_ink.py`. An in-memory watermark `_mark[doc]` holds the scene seq already looked at
  (after a restart the first look covers only the last save, `head - 1`).
- Ink is the `freedraw` rows with `seq > mark` that are live, not drafts (`customData.draft`) and
  not agent ink (`customData.author == "agent"`). Drafts live in ops anyway; the filter keeps
  the invariant locally.
- The new strokes alone are cropped with `raster.render_crop`, pad `min(300, max(10, 0.4 * longest side))`,
  so a lone "?" is read without its line. No browser upload.
- Slanted writing: the principal axis of the stroke points gives a dominant angle, used only when the
  ink is elongated (axis ratio >= 2) and the angle is 8 to 60 degrees; the crop is rotated level
  (white fill) before sending. The prompt says nothing about it. Deterministic, no model.
- One Haiku call (the existing persistent process, `ClaudeRecognizer.read_ink`) returns
  `{"text", "intent": question|equation|arrow_leads_nowhere|none}`. Fenced JSON is tolerated, anything
  else counts as `none`. `arrow_leads_nowhere` is ignored; the geometry rule keeps that job.
- Cancel: the scene version is read before and after the call. If it moved, the result is dropped and
  the watermark stays, so the next look covers the union. A reader error advances the mark and the
  chunk detectors take over.
- Offer: `question` -> kind `question`, `equation` -> `open_equation`, anchored on the active user chunk
  sharing most element ids with the ink, else the nearest by box distance. Payload carries `text`,
  `key` (sha1 of normalised text), `src: "latest"`. A tapped offer's task uses the payload text as
  `anchor_reading` while the chunk has no reading (`refresh_anchor`).
- Gate: `scan_now` reads only when attention is `quiet` and `can_push`; if ink is pending and the pen
  is not gone, the scan reschedules. While an offer is open the latest path is skipped without
  advancing the mark (one chip at a time, INK-197).
- Precedence: latest candidates go first. The chunk `question`/`open_equation` fallback is skipped for
  any anchor that already has a non-expired `src == "latest"` offer.
- `INKBRIDGE_QUIET_S` default lowered from 8 to 3 s (owner: 8 s is too slow); no test needed the old
  value.
- Off unless a reader is set or `INKBRIDGE_RECOGNIZER=claude`.

## Shortcuts

- A moved old stroke counts as new ink. The Haiku process cannot be interrupted, so cancel is by
  dropping the result. The watermark is in memory. The call blocks that document's scan lock. Cost is
  one Haiku call per quiet burst; see `inkbridge.offers.latest` logs
  (`doc= ms= strokes= intent= text_len= outcome=offered|none|dropped|error calls=N`) and
  `latest_ink.stats`.

## Hypotheses to tune

Pad 40% and 300 px cap, the intent prompt, slant limits (8 to 60 degrees, ratio 2), quiet window 3 s.
