# 0089 Offers: attention gate, budget and mute (INK-130)

## Context
Offers are small suggestions beside the ink. They must never interrupt writing, never pile up, and
stop coming when the user keeps refusing one kind.

## Decision
- The gate is in memory per document (`agent/attention.py`). It is live browser state: the browser sends `attention {pen, view}` and the state dies with the last socket. After a restart offers simply wait for the next frame. No state means closed.
- A pen-down, and the pen-up that follows it, count as stroke moments. A view tick while the pen stays up does not restart the quiet window (deviation from the plan text, which would make the window never open). The gate opens when the pen is up and `INKBRIDGE_QUIET_S` (default 8) have passed. Scene saves are not a stroke source (known limit).
- Offers are stored whenever they are created; `flush` pushes `offer.created` only through the open gate, so a held offer is never lost. When only the quiet window is missing, one daemon timer per document re-flushes. `offer.updated` goes out only for offers the browser was sent.
- Budget: 3 open per canvas. A fourth with a higher score replaces the lowest (stored as `expired`, one status set, kept as log); otherwise 409 `budget_full`. Open offers older than 24 h expire lazily on create and list.
- Mute: a kind is muted when it has 2 `dismissed` rows resolved since the session start, the time the first socket of the document joined. Computed from the log, no extra table; rows stay as feedback.
- Focus (`documents.focus`, migration 0012) holds pushes and hides open offers; creation still stores them. Questions and ops ignore it.

## Consequences
- Hypothesis: the 8 s, the budget of 3 and the mute count of 2 are tuning values to read off the log.
- A second device joining later gets held offers only through `GET /offers` (web must dedupe by id and fetch on connect).
- Tap sets `tapped` only; `task_id` stays null until the agent task ticket.
