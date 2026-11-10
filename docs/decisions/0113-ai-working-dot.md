# 0113: The working dot shows when the agent is busy on a canvas

Status: accepted (INK-198). Dev mode: one in-memory tracker, one WebSocket event, one top-bar dot. Owner check pending (see the last section).

## Context

The agent reads handwriting in the background (INK-014), runs offer tasks and answers questions (INK-133, INK-048). None of that showed on the canvas, so the owner could not tell a silent agent from a stuck one. The dot is the smallest signal: it says the agent is busy here, and nothing more.

## Decision

- **One tracker, in memory.** `server/src/inkbridge/agent/activity.py` keeps, per canvas, the items in flight under a string key: `read:<region_id>` while the recognition worker makes a model call, and `task:<task_id>` while a task is `running`. Nothing is stored; a restart clears it, and no migration is needed.
- **One event.** `{"type":"agent.activity","working":bool,"what":"reading"|"task"|"answer","count":int}` on the canvas socket. It is sent only when the triple changes, and once on connect when working, so a late tab shows the dot. When idle it is `{working:false, what:"reading", count:0}`.
- **What is the highest priority in flight.** answer > task > reading. A `question` task is `answer`; every other task kind is `task`. `count` is the number of items in flight.
- **Where the keys begin and end.** The task hook runs wherever a task status is announced (`api/tasks.py` on claim and complete; `agent/ask_runner.py` `_announce`, which also covers the runner's release). `running` begins a key and any other status ends it. The Ask runner also ends the task key in a `finally` around `runner.run`, and the recognition worker begins and ends a `read:` key around its one model call.
- **Expiry.** A key older than 600 s is dropped on the next read. A pull client that claims a task and never completes it therefore cannot keep the dot up forever.
- **Pull-path answers.** `answer_question` without `complete_task` finishes the task row silently (`finish_for_question`), so the key ends at `complete` or by the 600 s expiry, not at the answer. This is accepted for dev. The exact fix is one `activity.end` in `api/questions.py`, not done here.
- **Client hide.** `web/src/app/activity.ts` keeps the dot 1 s after `working:false` (`HIDE_MS`), so a burst of reads does not flicker. A `working:true` in that second cancels the hide. A closed socket hides the dot at once.
- **Look.** A 10 px lime dot beside the save status, pulsing between opacity 1 and 0.35 over 1.2 s, static under `prefers-reduced-motion`. It is not interactive, and its tooltip and aria-label say what the agent is doing. Lime is the agent, so the dot is the only new lime use (listed in `web/tests/designRules.test.ts`). DESIGN.md "Components" and the tokens carry it.

## Overlap with other tickets

- INK-196 edits `recognizer/worker.py`. This change touches only the import, the `begin` line before the model call and the `finally` clause after its excepts.
- INK-197 edits `agent/detectors.py`. Not touched here.

## Consequences

- The dot tells the owner the agent is busy; it does not say what it read or wrote. Drafts still arrive as before.
- The tracker is per process. Inkbridge runs one API process (decision 0017), so one tracker is enough. A second process would need the same signal through the database.

## Owner checks

- The tablet look of the dot: size and pulse speed, next to the save status.
- With a real listed canvas, the dot shows during a Gemini read and during an Ask answer, and disappears about 1 s after the agent is idle.
