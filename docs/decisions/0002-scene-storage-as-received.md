# 0002: Scenes are stored as received (value-identical)

Status: accepted (INK-006)

`PUT /documents/{id}/scene` parses the body once and stores `json.dumps(elements)` compactly.
The elements are never filtered or reshaped, so `pressures`, `simulatePressure` and
`customData` come back equal in value. Whitespace and key order of the original request are not
preserved; the client only ever consumes parsed JSON, so "byte-for-byte" is read as
value-identical. Python floats round-trip exactly through `json`.

Versioning is a single `UPDATE ... WHERE version = base_version`, so concurrent writers with the
same base cannot both succeed. A stale write returns 409 with `{"current_version": n}`.
