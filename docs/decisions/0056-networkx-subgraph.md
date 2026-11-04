# 0056 networkx subgraph over chunks and arrow links (INK-060)

Status: accepted.

## Decisions
1. The graph is a `networkx.DiGraph`: nodes are active auto chunks, edges are `links` rows (long arrows, decision 0013). Edges touching a non-active chunk are dropped. Drafts need no code: the chunker never makes a chunk from `customData.draft` elements (pinned by a test).
2. Source data is `chunk_outline(conn, doc, status="all")`: one query path, no new SQL, no schema change, no writes.
3. `direction` is `both` (default), `out` or `in`, chosen by using the graph, its reverse view or its undirected view. `both` is the default because arrows are drawn in either direction by hand.
4. Anchors follow decision 0042: unknown or foreign id gives 404 `chunk_not_found`; an orphan with a live successor is followed (`anchor_used`, `note`); an orphan dead end gives 410 `chunk_gone` naming `read_canvas`.
5. Limits (like decision 0018): `depth` 1..5, `max_nodes` 1..100 (40), `max_edges` 1..200 (80); nodes ordered by BFS distance then reading order; cut nodes and edges are counted in `omitted_nodes` / `omitted_edges`. Text previews are 160 chars. Components: at most 30 groups of at most 20 ids, with omitted counts. The caps keep the reply far below the MCP size guard, so there is none.
6. Mermaid is text only: `flowchart TD`, node ids `n1..nN` (never chunk ids), labels stripped of `"[](){}<>|;#&` and newlines, cut at 40 chars. It passes `mermaid.is_flowchart`; no browser is involved.
7. Cheap extras on the same module: shortest path (`to_chunk_id`) and connected components.

## Why per request
Cost per request is O(chunks + elements) through `chunk_outline`, plus the networkx build over chunks and links; there is no cache. That is fine for stretch scope. Canvases hold tens to hundreds of chunks, so building the graph costs microseconds next to the outline query. There is no cache to invalidate and nothing to store. networkx is imported only by the API; the MCP process stays a thin HTTP client (boundary test unchanged).

## MCP error text
`ApiClient._get` now appends the API's own detail to a 404 and turns a 410 into an `ApiError` carrying it, so a tool error says "call read_canvas". No existing assertion changed.

## Known gap
Only arrow links exist. A canvas whose chunks are joined only by proximity merging is a graph of isolated nodes. A real graph database stays future work.
