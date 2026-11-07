"""INK-132: POST /watch stores chunk ids and reading hashes only."""

import pytest

from inkbridge import db

URL = "/documents/default/watch"
H = "a" * 64


def chunk(i="abc123def456", h=H):
    return {"id": i, "reading_hash": h}


def stored():
    conn = db.connect()
    try:
        return db.list_watches(conn, "default")
    finally:
        conn.close()


def test_watch_stores_ids_and_hashes(client):
    r = client.post(URL, json={"note": "n1", "chunks": [chunk()]})
    assert r.status_code == 200 and r.json() == {"note": "n1", "chunks": 1}
    assert stored() == [{"note_id": "n1", "chunk_id": "abc123def456", "reading_hash": H}]
    client.post(URL, json={"note": "n1", "chunks": [chunk("c1"), chunk("c2")]})
    assert len(stored()) == 2
    client.post(URL, json={"note": "n1", "chunks": [chunk("c1")]})
    assert len(stored()) == 1  # a second post replaces the note's rows


@pytest.mark.parametrize(
    "body",
    [
        {"note": "n", "chunks": [], "text": "hello"},
        {"note": "n", "chunks": [{**chunk(), "reading": "x"}]},
        {"note": "n", "chunks": [chunk(h="not hex")]},
        {"note": "n", "chunks": [chunk(h="hello world, my note text")]},
        {"note": "my note", "chunks": []},
        {"note": "a/b.md", "chunks": []},
        {"note": "n", "chunks": [chunk(f"c{i}") for i in range(501)]},
    ],
)
def test_watch_refuses_any_other_field(client, body):
    assert client.post(URL, json=body).status_code == 422
    assert stored() == []


def test_watch_unknown_document(client):
    assert client.post("/documents/nope/watch", json={"note": "n", "chunks": []}).status_code == 404
