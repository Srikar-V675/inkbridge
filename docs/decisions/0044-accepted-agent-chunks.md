# 0044: Accepted agent ink is its own chunk, read from its own text

Status: accepted (INK-078)

## Problem
After Accept, an agent's text or diagram looked like it had no chunk. Diagnosis (headless
Chromium plus server tests): the chunk existed, and the delta save, `flushNow` and the chunker all
worked. But it had `text: null` and `source: null`, so it read as missing, and the recognition
worker would have sent it to Gemini. Agent ink near handwriting could also merge into a user chunk.

## Decision
1. Accepted agent ink: `customData.author == "agent"`, `customData.op_id` a string, id starting
   `<op_id>:`, not `draft` (`chunker.agent_op`). The id prefix is the trust rule, since customData
   is client-writable. A forged tag only makes user ink skip Gemini, which is safe.
2. Each op's accepted ink is one forced group in `chunk_scene` (`agent_groups`), outside proximity
   merge, like a pin. It is not marked `pinned`: that flag means a manual merge/split and is read
   back as pins on the next save. A manual pin wins on overlap; arrows link to agent groups
   rather than merging them.
3. A chunk made only of accepted agent ink gets an `agent` reading in `_sync_chunks`: the `text`
   of its text elements in (y, x) order, `""` for a shape-only diagram. No model call: the worker's
   `recognition_candidates` skips any region with a reading for the current content hash.
   Precedence stays user > agent > gemini. Rewritten only when the text changes.
4. Drafts stay excluded and `customData` stays out of every hash.

## Consequences
First save after deploy re-chunks accepted agent ink out of any merged user chunk; that chunk is
orphaned (successor_of set) and its export block goes stale once. Reject (isDeleted on `<op>:*`)
removes only the agent chunk.

## Known limit
A chunk is read as agent ink only if every element is accepted agent ink. A user arrow that starts
at an accepted agent shape, or a manual merge or pin of agent and user ink, makes a mixed chunk: it
gets no agent reading and stays a Gemini candidate. This is deliberate, not changed here: Gemini
only reads canvases listed in `INKBRIDGE_RECOGNIZE_DOCUMENTS`, which are test pages by rule, and a
mixed chunk does hold user ink. Tests pin both cases (`test_mixed_chunks_get_no_agent_reading`).
