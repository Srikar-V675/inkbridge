"""INK-072 item 1: responses are described in OpenAPI, and their JSON shape is pinned."""

import pytest

from tests.test_chunk_persistence import Canvas, row
from tests.test_regions_api import PNG, post
from tests.test_search import recognise

CHUNK_KEYS = {
    "id", "order", "kind", "bounds", "element_ids", "text", "latex", "source", "status",
    "successor_of", "png_stale", "content_hash", "text_hash", "links", "group_id", "deep_link",
    "read_status", "read_note",
}  # fmt: skip
REGION_KEYS = {
    "id", "document_id", "element_ids", "bounds", "stroke_count", "kind", "created_by",
    "stroke_hash", "content_hash", "status", "successor_of", "png_stale", "pinned", "updated_at",
    "text", "latex", "source", "text_hash", "live_successor",
}  # fmt: skip
OP_KEYS = {"id", "document_id", "type", "status", "payload", "result", "error", "created_at",
           "elements", "box", "resolved_at", "question_id", "diagram_id", "revises"}
SYNC_KEYS = {"fresh", "fresh_after_reread", "changed", "replaced", "removed", "new"}
DOC_KEYS = {
    "id", "title", "updated_at", "version", "url", "pinned", "archived", "element_count",
    "chunk_count", "open_offers", "last_opened_at", "chunker",
}  # fmt: skip

REFS = [  # (path, method, status)
    ("/documents", "post", "201"),
    ("/documents", "get", "200"),
    ("/documents/{document_id}/chunks", "get", "200"),
    ("/documents/{document_id}/regions", "get", "200"),
    ("/documents/{document_id}/regions", "post", "201"),
    ("/regions/{region_id}", "get", "200"),
    ("/regions/{region_id}/image", "put", "200"),
    ("/documents/{document_id}/ops", "post", "201"),
    ("/documents/{document_id}/ops", "get", "200"),
    ("/ops", "post", "201"),
    ("/ops/{op_id}", "get", "200"),
    ("/ops/{op_id}", "patch", "200"),
    ("/documents/{document_id}/check_sync", "post", "200"),
]


def _has_ref(schema):
    return (
        "$ref" in schema
        or any("$ref" in s for s in schema.get("anyOf", []))
        or "$ref" in schema.get("items", {})
    )


@pytest.mark.parametrize(("path", "method", "status"), REFS)
def test_route_declares_a_response_model(client, path, method, status):
    spec = client.get("/openapi.json").json()
    schema = spec["paths"][path][method]["responses"][status]["content"]["application/json"][
        "schema"
    ]
    assert _has_ref(schema), f"{method.upper()} {path} returns an undescribed object"


@pytest.fixture
def canvas(client):
    c = Canvas(client, row("a", 3))
    recognise(c.chunk_of("a0"), "hello")
    return c


def test_chunk_shape(client, canvas):
    body = client.get("/documents/default/chunks").json()
    assert set(body) == {"document", "version", "chunk_count", "chunks", "groups", "isolated"}
    (chunk,) = body["chunks"]
    assert set(chunk) == CHUNK_KEYS
    assert chunk["text"] == "hello" and chunk["links"] == []


def test_chunk_link_shape(client):
    c = Canvas(client, row("a", 3) + row("b", 3, y=500))
    arrow = {
        "id": "arr", "type": "arrow", "x": 40, "y": 10, "width": 0, "height": 490,
        "points": [[0, 0], [0, 490]], "version": 1,
        "startBinding": {"elementId": "a2"}, "endBinding": {"elementId": "b0"},
    }  # fmt: skip
    c.elements.append(arrow)
    c.put()
    links = [
        x for ch in client.get("/documents/default/chunks").json()["chunks"] for x in ch["links"]
    ]
    for link in links:
        assert set(link) == {"to", "kind", "label", "confidence"}


def test_region_shapes(client, canvas):
    chunk_id = canvas.chunk_of("a0")["id"]
    assert set(client.get(f"/regions/{chunk_id}").json()) == REGION_KEYS
    (listed,) = client.get("/documents/default/regions", params={"chunks": True}).json()
    assert set(listed) == REGION_KEYS
    made = post(client, ["a0"])
    assert made.status_code == 201 and set(made.json()) == REGION_KEYS
    assert set(client.get(f"/regions/{made.json()['id']}").json()) == REGION_KEYS
    assert [set(r) for r in client.get("/documents/default/regions").json()] == [REGION_KEYS]
    up = client.put(f"/regions/{chunk_id}/image", files={"image": ("c.png", PNG, "image/png")})
    assert up.status_code == 200 and set(up.json()) == REGION_KEYS


def test_document_shapes(client):
    made = client.post("/documents", json={"title": "x"})
    assert made.status_code == 201 and set(made.json()) == DOC_KEYS
    assert all(set(d) == DOC_KEYS for d in client.get("/documents").json())


def test_op_shapes_and_retry_stays_200(client, canvas):
    body = {"type": "write_text", "payload": {"text": "hi"}, "op_id": "op-one"}
    first = client.post("/documents/default/ops", json=body)
    assert first.status_code == 201 and set(first.json()) == OP_KEYS
    again = client.post("/documents/default/ops", json=body)
    assert again.status_code == 200 and set(again.json()) == OP_KEYS
    assert set(client.get("/ops/op-one").json()) == OP_KEYS
    listed = client.get("/documents/default/ops").json()
    assert set(listed) == {"ops"} and [set(o) for o in listed["ops"]] == [OP_KEYS]
    patched = client.patch("/ops/op-one", json={"status": "expired"})
    assert patched.status_code == 200 and set(patched.json()) == OP_KEYS
    default = client.post("/ops", json={**body, "op_id": "op-two"})
    assert default.status_code == 201 and set(default.json()) == OP_KEYS


def test_check_sync_shape(client, canvas):
    chunk = canvas.chunk_of("a0")
    note = {"id": chunk["id"], "hash": chunk["content_hash"], "reading": chunk["text_hash"]}
    ghost = {"id": "gone", "hash": "h"}
    r = client.post("/documents/default/check_sync", json={"chunks": [note, ghost]})
    assert r.status_code == 200 and set(r.json()) == SYNC_KEYS
    assert r.json()["removed"] == ["gone"]
    fresh = client.post("/documents/default/check_sync", json={"chunks": []}).json()
    (new,) = fresh["new"]
    assert set(new) == {"id", "hash", "reading", "preview"}
    changed = client.post(
        "/documents/default/check_sync",
        json={"chunks": [{**note, "hash": "old", "reading": "zz"}], "wait_s": 0},
    ).json()
    assert [set(c) for c in changed["changed"]] == [{"id", "hash", "reading"}]
