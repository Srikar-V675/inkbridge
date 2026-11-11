# 0120 Open offers expire after 60 s and newer ink replaces them

Status: accepted (INK-205). Narrows the "one open offer at a time" rule of [0112](0112-offer-noise.md) for staleness only.

## Problem

An offer the user never saw stayed `open` for 24 h (INK-088/INK-130 TTL) and, under the one-chip rule, blocked every new offer on the canvas. Owner test 11 Nov: "2+2=" produced a candidate, but `detector run held=open_offer` on every scan.

## Decision

- Open offers of the proactive kinds (`question`, `open_equation`, `dangling_arrow`, `sketch`) expire after `OFFER_OPEN_TTL_S` = 60 s (env `INKBRIDGE_OFFER_OPEN_TTL_S`, read at call time). `markup`, `stale_note`, `to_note` and the rest keep 24 h. A tapped offer is no longer `open`, so it is never swept.
- Expiry is status `expired`, not `dismissed`: it never counts toward the mute rule. The row gets `payload.lapsed = true`; the detectors' seen-set keeps lapsed offers, so the same ink is not offered again every minute (budget-expired offers can still return, as in 0089).
- Sweeps run lazily in `detectors.run` (hence `scan_now`), `flush`, the offers list and `create_offer`, and once at API startup (`sweep_all`). Each sweep publishes `offer.updated`, which the web store already turns into a removed chip.
- A candidate whose anchor chunk changed after the open proactive offer was created replaces it: the old offer is expired (and marked lapsed) in the same transaction as the insert (`create_offer(replace_open=True)`), so the budget holds. If any non-proactive offer is open, the one-chip hold stays.
- No migration.

## Limits

A pushed chip lapses when the next sweep runs (scan, flush, list), not on a timer.
