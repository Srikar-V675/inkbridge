# 0121 Proactive offers are off by default

Status: accepted (INK-206). Supersedes the "offers on" default implied by [0089](0089-offers-gate-budget-mute.md), [0112](0112-offer-noise.md) and [0119](0119-latest-ink-newest-cluster.md); the code stays.

## Problem

Owner tests on 10 to 12 Nov: offers were noisy or late, and the one place they could be fast (reading the newest ink with a model) depends on the tablet's Wi-Fi and a per-call model cost. The product is stronger without them: the canvas-to-vault loop, staleness checks and the MCP interface do not depend on them.

## Decision

- `INKBRIDGE_OFFERS` (`1`, `true`, `on`, `yes`; default unset = off), read at call time by `config.offers_enabled()`.
- Off means: `scan_now`, `flush` and `schedule_scan` return at once. No detector runs, no latest-ink Haiku read, no chip is pushed, no sweep runs. Rows already in `offers` stay and are never shown.
- `GET /health` reports `offers: bool`; the web hides the Focus toggle when it is false. The chip layer renders nothing without offers.
- Not removed: detectors, `agent/latest_ink.py`, tables, routes (`POST/GET /documents/{id}/offers`), web chips. Ask, drafts, tasks for questions, MCP tools and the export skill are unaffected.
- Tests switch it on with an autouse fixture; `tests/test_offers_off.py` pins the default.

## Turning them back on

Set `INKBRIDGE_OFFERS=1` and restart. Quiet window, TTL, daily cap and recognizer settings are unchanged.
