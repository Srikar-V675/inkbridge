# 0003: Limits on what agents receive

Status: accepted (INK-012); client rendering check pending

- **Image width** is capped at 1024 px by the API (`GET /regions/{id}/image?max_width=1024`),
  downscaled on the fly with Lanczos; the stored crop is never modified, and images already
  narrower than the cap are returned byte-for-byte.
- **Ink** is capped at 5,000 points per response (`GET /regions/{id}/ink?max_points=5000`). Each
  stroke keeps its first and last point and its pressures stay paired with their points; the
  budget is shared proportionally across strokes. If there are so many tiny strokes that one
  point each would not fit, later strokes are dropped. The response reports `decimated` and
  `original_point_count` so an agent knows it is looking at a reduction.
- Uploads are validated by decoding the PNG (Pillow), not just by magic bytes.

## Client rendering (not yet verified)
The ticket asks to record whether Claude Desktop and Claude Code render MCP image content.
This needs a person at those clients and was not checked during unattended development.
The server returns standard MCP `image` content (`image/png`). If a client does not render it,
the planned fallback is a base64 text block; no fallback is implemented yet.
Record the result here once checked: Claude Desktop: ?  Claude Code: ?
