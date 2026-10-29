# 0023: draw_diagram waits by polling, expires on give-up, and refuses non-flowcharts

Status: accepted (INK-044)

- **Wait.** The MCP tool creates the op, then polls `GET /ops/{id}` every 0.25 s until the
  browser applies or fails it, for at most `wait_seconds` (default 20, 1 to 60). The MCP server is
  a thin HTTP client, so polling is simpler than a long-poll route or a second WebSocket. A
  20 s wait costs about 80 small local requests.
- **Give-up expires the op.** If the wait runs out while the op is still pending or delivered, the
  tool PATCHes it to `expired`. A browser that connects later is never sent an expired op, and a
  browser that already drew it sweeps the drafts on `op.updated` (decision 0012). If the PATCH
  conflicts because the ack landed in that instant, the tool re-reads the op and reports it as
  applied. The timeout message gives the canvas URL from `INKBRIDGE_PUBLIC_URL` (as seen by the
  MCP process).
- **Flowcharts only, enforced by the API.** `@excalidraw/mermaid-to-excalidraw` turns every
  diagram type except flowcharts into a single image, which is no use as editable drafts. The
  API reads the diagram keyword (`inkbridge/mermaid.py`), skipping front matter, `%%{init}%%`
  directives and comments. Anything but `flowchart` or `graph` is
  `422 {code: "not_flowchart", diagram_type, msg}`, and no op is created. The browser keeps its
  own check (an image result fails the op) as a second line.
- **Errors carry the cause.** The MCP client now surfaces the API's `detail` for 404, 409 and 422,
  so the agent sees `not_flowchart`, `anchor_not_found` or `existing_element_id`, not a bare
  status code.
