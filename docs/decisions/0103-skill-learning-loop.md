# 0103 The export skill learns from the user's edits (INK-142)

Status: accepted. Owner checks pending (real re-export after hand-editing three headings, and
approving a proposal in Obsidian).

## What dominated
Spec v4 "Vault skill" wants the export to adapt to how the user rewrites its words, without ever
changing the safety mechanics. The user's edits are already detectable (INK-106 `body` hash), so the
missing parts were the old text, a pattern test and a way to ask before applying anything.

## What changed
- **An edit** is a block whose entry has `body` and whose current interior hashes differently (the
  `_edited` test). Entries without `body` have no baseline and are skipped.
- **Old text** comes from the vault's git history of the note: the first revision whose block hashes
  to `body`. No repository or no match means the block is skipped and listed under `no_history`,
  never an error.
- **Closed set of kinds** (`heading_question`, `heading_level`, `crop_removed`): simple to test, safe,
  and a rule can only change the words the agent writes, so it cannot reach markers, `body`, hashes
  or `apply`/`validate`. Unknown kinds in a hand-edited profile are ignored.
- **Threshold 3 distinct chunks** of one kind (one block edited three times is one piece of
  evidence). Evidence lives in the profile's `## Observed edits` itself, keyed by kind, chunk id and a
  hash of the new text, so there is no new state and repeated runs add nothing.
- **Proposals are never auto-applied.** Only `Status: approved`, set by the user, makes a rule
  active. A kind with any `###` heading in `## Proposals` (including rejected) is not proposed again.
  The agent never approves one.
- **Profile** `meta/Inkbridge Export Profile.md` is the user's: the helper appends inside its two
  sections and touches no other text.
- **Where it runs.** Learning is in the stdlib helper, so Claude Desktop without a shell does not
  learn. The MCP server and API are unchanged.
