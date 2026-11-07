"""Test helper: put a canvas's elements straight into scene_elements (INK-110, decision 0077)."""

import json


def set_scene(conn, document_id, elements, version=None):
    """Replace a canvas's stored elements by rows (tests that used to write scenes.elements_json)."""
    conn.execute("DELETE FROM scene_elements WHERE document_id = ?", (document_id,))
    head = (
        version
        if version is not None
        else conn.execute(
            "SELECT version FROM scenes WHERE document_id = ?", (document_id,)
        ).fetchone()[0]
    )
    for pos, e in enumerate(elements):
        conn.execute(
            "INSERT INTO scene_elements (document_id,id,pos,seq,version,nonce,is_deleted,json,updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (
                document_id,
                e["id"],
                pos,
                head,
                int(e.get("version") or 0),
                int(e.get("versionNonce") or 0),
                int(bool(e.get("isDeleted"))),
                json.dumps(e, ensure_ascii=False, separators=(",", ":")),
                "t",
            ),
        )
    conn.execute("UPDATE scenes SET version = ? WHERE document_id = ?", (head, document_id))
    conn.commit()
