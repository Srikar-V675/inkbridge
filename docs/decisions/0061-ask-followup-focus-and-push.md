# 0061: A follow-up inherits its thread's focus, and Ask updates by push

INK-104. Status: accepted. Builds on INK-103 (decision 0060: `runner_status` and `runner_error`).

## Problem

- The Ask button needed a selection even for a follow-up, and a follow-up stored its own empty focus, so its `focus_chunk_ids` came back empty.
- The Ask panel polled `GET .../questions` every 3 s while a question was pending. The server already pushes `question.update` (INK-047, INK-103), but the browser ignored it.

## Decisions

- **Inherit at create time, stored.** A follow-up sent with empty `focus_element_ids` copies its parent's stored focus. Because each follow-up stores the inherited value, a chain of follow-ups always resolves to the thread root's focus without walking `parent_id`. A follow-up that sends a selection keeps its own. No schema change, no migration. Elements are stored; chunk ids are still computed on read (decision 0035).
- **Push, not poll.** `OpsSocket` takes `onQuestionUpdate`. `App.tsx` forwards it to a small module-level bus in `ask/ask.ts`, which `AskPanel` subscribes to. The panel refetches when it opens and on every socket (re)connect, because a push sent while the socket was down is lost. It never refetches on a timer.
- **Runner line.** A pending question shows `runnerLine`: the red failure reason, `Retrying after: ...` for a retry, or `Answering...`. The reason is server text without paths.

## Rejected

- Walking `parent_id` to the root at read time: an extra query per read for the same result.
- Lifting question state into `App`: it would re-render the whole canvas component on every push.

## Known shortcut

A refetch that resolves after a newer push can briefly show older state. The next push or reconnect corrects it. Sequence numbers are not worth it here.
