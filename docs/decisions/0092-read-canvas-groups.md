# 0092: read_canvas shows link detail and groups of connected chunks

INK-123. Status: accepted.

## Problem

`read_canvas` gave an agent a flat list of chunks. Each chunk named its arrow links as `{to, kind}` only, so the agent had to rebuild the structure of the page (which chunks belong to one diagram, which stand alone) from ids alone.

## Decision

- Groups are connected components of two or more active chunks over arrow links. They are computed by `canvas/graph.groups` (pure, networkx) and attached in `db/outline.chunk_outline`, because the MCP package must not import `inkbridge.db`. The MCP tool only passes them through and caps them.
- A lone chunk has `group_id: null` and is not listed as a group, so a 200-chunk canvas of singletons does not list 200 groups. `isolated` counts them on the API outline.
- `group_id` is the id of the group's first chunk in reading order. It is stable while membership is stable. There is no new table and nothing is hashed.
- Groups are sorted by size, largest first, then by reading order. They are built from active chunks before any status or png filter, so a filtered list keeps its groups.
- Links are deduplicated by `(to, kind)`. `label` and `confidence` take the maximum non-null value across the duplicate rows.
- Caps (decision 0018): top-level `groups` at most `MAX_GROUPS = 20` (the rest in `groups_omitted`), each group's `chunk_ids` at most `MAX_GROUP_IDS = 20` (the rest in `omitted_ids`). Ids are 12 characters, so the head stays far under the 60,000 character cap. `group_id` on every chunk is never capped, so no membership is lost.
- `groups` repeats on every page of a continued read, so a reader that continues at an offset keeps the structure.
- Not done: drawing groups on the debug overlay, and semantic groups from a model (a later ticket).

## Consequences

- Group ids move when links change, because the id is the first member. An agent should re-read the outline rather than keep a group id across edits.
- Groups are derived from ink only and sit outside all three hashes, so no cache or note is invalidated by them.
- The MCP reply does not carry `isolated`; an agent reads the chunks with `group_id: null` instead.
- Link dicts gain `label` and `confidence` keys in every outline response. Clients that compare link dicts exactly must accept the two new keys.
