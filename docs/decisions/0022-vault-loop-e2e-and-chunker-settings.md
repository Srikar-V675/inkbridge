# 0022: Vault loop end to end, chunker settings, vault location

Status: accepted (INK-038). Evidence: `docs/vault-loop-walkthrough.md`, produced by `scripts/vault_loop_e2e.py`.

- **What was run.** draw -> export -> nudge -> move -> edit one line -> `check_sync` -> re-export, over
  HTTP against a live API on a throwaway database, on a synthetic page (heading, two lines, two
  boxes joined by a long arrow). The script plays the user (scene writes) and the recognition worker
  (readings written into the throwaway DB; nothing goes to Gemini). The skill's helper does the
  note. Result: a nudge refreshes one hash and no words; a move flags nothing; one changed line
  rewrites one block and its crop embed; text outside the markers is untouched.
- **Real pages: pending.** The user's current canvas (read from a copy of the database, never the live
  one) holds two unread test chunks and no study page, so no real run was possible. The hand-off
  checklist is `docs/tickets/plans/INK-038-handoff.md`. E5 reference boxes and the fixture pages for
  INK-050 wait for those pages.
- **Chunker constants: unchanged** (`k` 1.5, `arrow_merge` 6.0, `link_reach` 3.0, `match_threshold` 0.5).
  The synthetic sweep (walkthrough, "Tuning") shows the settings behave as designed: at k 1.5 words
  further than 30 px apart split, and a long arrow between two boxes links two chunks instead of
  merging them. It also shows the one thing real pages must settle: lines whose gap is under 1.5x
  the median stroke size (a 40 px pitch with 20 px strokes) merge into one paragraph chunk. That is
  acceptable for a note (one block per paragraph) but should be re-checked on real handwriting
  before changing `k`, because the right value depends on real stroke sizes.
- **Id matching: keep Jaccard (> 0.5), do not switch to 60% containment yet.** The table shows that
  a chunk of n strokes that gains g >= n strokes between two saves gets a new id (a 1-stroke chunk
  never keeps its id when it grows). The safety net is already in place: the old chunk is orphaned
  with the new one as successor, so `check_sync` reports `replaced` and the skill rewrites the
  block into the successor. Containment would keep more ids but makes merge and split ambiguous.
  Revisit only if the real-page run shows many `replaced` entries for small chunks.
- **Vault location (open question).** Default is a temp folder chosen by `INKBRIDGE_VAULT` (set it
  to the real vault); the e2e script and the tests use one under `/tmp`. The skill asks when it is
  unset. The real vault stays untouched until the user sets the variable.
- **Harness scope.** `scripts/vault_loop_e2e.py` imports `inkbridge.db` to write readings and so is
  a test harness for a throwaway database only; it is not an MCP client and the MCP boundary test
  does not apply to it. `make lint` covers it.
