"""INK-037: the export skill's note mechanics (skills/inkbridge-export/scripts/inknote.py)."""

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from tests.test_chunk_persistence import Canvas, row
from tests.test_regions_api import PNG
from tests.test_search import recognise

SCRIPT = Path(__file__).parents[2] / "skills" / "inkbridge-export" / "scripts" / "inknote.py"
_spec = importlib.util.spec_from_file_location("inknote", SCRIPT)
inknote = importlib.util.module_from_spec(_spec)
sys.modules["inknote"] = inknote
_spec.loader.exec_module(inknote)

USER_TEXT = "Notes I typed myself.\n\nThey must survive every re-export exactly.\n"


@pytest.fixture
def api(client, monkeypatch):
    """Route the script's HTTP calls to the in-process API."""

    def request(url, body=None, timeout=60):
        path = url.removeprefix("http://api")
        r = client.post(path, json=body) if body is not None else client.get(path)
        if r.status_code >= 400:
            raise inknote.urllib.error.URLError(f"{r.status_code} {path}")
        return r.content

    monkeypatch.setattr(inknote, "_request", request)
    return "http://api"


def outline(client):
    return client.get("/documents/default/chunks").json()


def bodies_for(canvas_json, **override):
    return {
        c["id"]: override.get(c["id"], f"## {c['text'] or 'Untitled'}\n\n- {c['text']}")
        for c in canvas_json["chunks"]
    }


@pytest.fixture
def page(client):
    """Three lines of ink, each read, as on a study page."""
    c = Canvas(client, row("a", 3) + row("b", 3, y=500) + row("c", 3, y=1000))
    for cid, text in (("a0", "gradient descent"), ("b0", "learning rate"), ("c0", "momentum")):
        recognise(c.chunk_of(cid), text)
    return c


def export(client, page, tmp_path=None):
    canvas = outline(client)
    vault = tmp_path
    text = inknote.new_note(canvas, "Optimisation", bodies_for(canvas), vault)
    return canvas, backdate(text)


def backdate(text):
    """An export from long ago, so a needless re-stamp of `exported` would show."""
    stamp = inknote.parse(text).meta["exported"]
    return text.replace(f'"exported": "{stamp}"', '"exported": "2020-01-01T00:00:00+00:00"', 1)


def with_user_text(text):
    """The user adds text above, between and below the blocks."""
    head, sep, rest = text.partition("<!-- ink:")
    rest = sep + rest
    first_close = rest.index("<!-- /ink -->\n") + len("<!-- /ink -->\n")
    return (
        head
        + USER_TEXT
        + "\n"
        + rest[:first_close]
        + "\n"
        + USER_TEXT
        + rest[first_close:]
        + "\n"
        + USER_TEXT
    )


def check(client, text, wait_s=0):
    note = inknote.parse(text)
    r = client.post(
        f"/documents/{note.meta['canvas']}/check_sync",
        json={"chunks": inknote._sync_chunks(note), "wait_s": wait_s},
    )
    assert r.status_code == 200
    return r.json()


# -- export and schema -----------------------------------------------------------------------------


def test_a_new_note_validates_and_records_provenance(client, page):
    canvas, text = export(client, page)
    assert inknote.validate(text) == []
    note = inknote.parse(text)
    assert note.meta["canvas"] == "default"
    by_id = {c["id"]: c for c in canvas["chunks"]}
    assert [e["id"] for e in note.meta["chunks"]] == [c["id"] for c in canvas["chunks"]]
    for e in note.meta["chunks"]:
        assert e["hash"] == by_id[e["id"]]["content_hash"]
        assert e["reading"] == by_id[e["id"]]["text_hash"] and e["reading"]
        assert e["section"] == by_id[e["id"]]["text"]  # the block's own heading
    assert [b.id for b in note.blocks] == [c["id"] for c in canvas["chunks"]]
    assert text.startswith("---\ntags: [library]\n")


def test_each_block_links_to_its_chunk_and_embeds_its_crop(client, page):
    _canvas, text = export(client, page)
    note = inknote.parse(text)
    for b in note.blocks:
        body = text[b.body_start : b.body_end]
        (link,) = [ln for ln in body.splitlines() if ln.startswith("[Open in Inkbridge](")]
        q = parse_qs(urlparse(link[len("[Open in Inkbridge](") : -1]).query)
        assert q == {"canvas": ["default"], "chunk": [b.id]}
        assert f"![[content/raw/attachments/inkbridge/{b.id}-{b.hash[:12]}.png]]" in body
        assert "> [!ink]- Source ink" in body  # folded callout


@pytest.mark.parametrize(
    ("mutate", "error"),
    [
        (lambda t: t.replace("---\n", "", 1), "frontmatter"),
        (lambda t: t.replace("inkbridge: {", "inkbridge: [", 1), "JSON"),
        (lambda t: t.replace("<!-- /ink -->\n", "", 1), "not closed"),
        (lambda t: t.replace('"canvas": "default"', '"canvas": ""'), "canvas"),
        (lambda t: t.replace('"exported": "', '"exported": "x', 1), "exported"),
        (lambda t: t.replace('"reading": "', '"reading": "zz', 1), "reading"),
        (lambda t: t + "<!-- ink:zzz hash:" + "0" * 64 + " -->\nx\n<!-- /ink -->\n", "no entry"),
        (lambda t: t + "<!-- ink:broken -->\n", "malformed"),
    ],
)
def test_validation_catches_each_schema_break(client, page, mutate, error):
    _, text = export(client, page)
    errors = inknote.validate(mutate(text))
    assert errors and any(error in e for e in errors), errors


def test_a_marker_hash_that_disagrees_with_the_frontmatter_is_invalid(client, page):
    _, text = export(client, page)
    b = inknote.parse(text).blocks[0]
    broken = text.replace(f"hash:{b.hash} -->", f"hash:{'0' * 64} -->", 1)
    assert any("marker hash differs" in e for e in inknote.validate(broken))


# -- vault rules (INK-106) -------------------------------------------------------------------------


def test_new_note_has_the_vault_frontmatter_and_callout(client, page):
    _canvas, text = export(client, page)
    fm, _, after = text[4:].partition("\n---\n")
    lines = fm.splitlines()
    for want in ("tags: [library]", "type: library", "format: reference", "publish: false"):
        assert want in lines
    assert "ai-first: true" in lines
    assert any(re.fullmatch(r"date: \d{4}-\d{2}-\d{2}", ln) for ln in lines)
    assert sum(ln.startswith("inkbridge:") for ln in lines) == 1
    assert after.startswith("> [!info]- For future agent\n")
    assert inknote.validate(text, strict=True) == []
    canvas = outline(client)
    rich = inknote.new_note(
        canvas,
        "T",
        bodies_for(canvas),
        index="[[Machine Learning & AI.base]]",
        relates=["[[Linear Regression]]"],
    )
    assert 'index: "[[Machine Learning & AI.base]]"' in rich
    assert 'relates: ["[[Linear Regression]]"]' in rich
    assert inknote.validate(rich, strict=True) == []
    with pytest.raises(inknote.NoteError):
        inknote.new_note(canvas, "T", bodies_for(canvas), index="Machine")
    with pytest.raises(inknote.NoteError):
        inknote.new_note(canvas, "T", bodies_for(canvas), relates=["Linear"])


def test_every_entry_records_the_body_hash(client, page):
    _canvas, text = export(client, page)
    note = inknote.parse(text)
    for b in note.blocks:
        want = inknote._body_hash(text[b.body_start : b.body_end])
        assert note.entry(b.id)["body"] == want


@pytest.mark.parametrize(
    "mutate",
    [
        lambda t: t.replace("tags: [library]", "tags: [library, ml]"),
        lambda t: t.replace("type: library\n", ""),
        lambda t: t.replace("format: reference", "format: novel"),
        lambda t: t.replace("> [!info]- For future agent", "> note"),
    ],
)
def test_strict_validation_catches_vault_breaks(client, page, mutate):
    _, text = export(client, page)
    broken = mutate(text)
    assert broken != text
    assert inknote.validate(broken) == []
    assert inknote.validate(broken, strict=True)


@pytest.mark.parametrize(
    "bad", ["a \u2014 b", "a \u2013 b", "a \u2192 b", "ok \U0001f600", "a \u00b7 b"]
)
def test_words_with_dashes_arrows_or_emoji_are_refused(client, page, bad):
    canvas = outline(client)
    first = canvas["chunks"][0]["id"]
    with pytest.raises(inknote.NoteError, match="chunk"):
        inknote.new_note(canvas, "T", {first: f"## h\n\n- {bad}"})
    with pytest.raises(inknote.NoteError, match="title"):
        inknote.new_note(canvas, f"T {bad}", bodies_for(canvas))


# -- re-export -------------------------------------------------------------------------------------


def test_reexport_with_nothing_changed_is_byte_identical(client, page):
    canvas, text = export(client, page)
    text = with_user_text(text)
    sync = check(client, text)
    assert inknote.plan(text, sync)["needs_body"] == []
    assert inknote.apply(text, sync, canvas, {}) == text


def test_a_moved_chunk_changes_nothing(client, page):
    _canvas, text = export(client, page)
    text = with_user_text(text)
    for i in range(3):
        page.el(f"b{i}")["x"] += 300
    page.put()
    assert inknote.apply(text, check(client, text), outline(client), {}) == text


def nudge(page):
    page.el("a1")["points"] = [[0, 0], [10, 21]]
    page.put()


def test_a_nudged_stroke_flags_nothing_and_only_refreshes_the_stored_hash(client, page):
    _canvas, text = export(client, page)
    text = with_user_text(text)
    nudge(page)
    recognise(page.chunk_of("a0"), "gradient descent")  # re-read: same words
    sync = check(client, text)
    assert inknote.plan(text, sync)["needs_body"] == []
    out = inknote.apply(text, sync, outline(client), {})
    before, after = inknote.parse(text), inknote.parse(out)
    a = page.chunk_of("a0")
    assert after.entry(a["id"])["hash"] == a["content_hash"] != before.entry(a["id"])["hash"]
    assert after.block(a["id"]).hash == a["content_hash"]
    # Everything except the frontmatter line and that one marker line is byte-identical.
    assert strip_markers_and_meta(out) == strip_markers_and_meta(text)
    for b in before.blocks:
        assert block_body(out, b.id) == block_body(text, b.id)
    assert inknote.validate(out) == []


def strip_markers_and_meta(text):
    return "\n".join(
        ln for ln in text.splitlines() if not ln.startswith(("inkbridge:", "<!-- ink:"))
    )


def block_body(text, cid):
    b = inknote.parse(text).block(cid)
    return text[b.body_start : b.body_end]


def test_one_changed_line_rewrites_exactly_one_block(client, page):
    _canvas, text = export(client, page)
    text = with_user_text(text)
    page.el("b1")["points"] = [[0, 0], [30, -10]]
    page.put()
    recognise(page.chunk_of("b0"), "learning rate schedule")
    sync = check(client, text)
    b = page.chunk_of("b0")
    plan = inknote.plan(text, sync)
    assert plan["rewrite"] == [b["id"]] and plan["needs_body"] == [b["id"]]
    out = inknote.apply(text, sync, outline(client), {b["id"]: "## learning rate schedule\n\nnew"})
    before, after = inknote.parse(text), inknote.parse(out)
    changed = [x.id for x in before.blocks if block_body(out, x.id) != block_body(text, x.id)]
    assert changed == [b["id"]]
    assert "learning rate schedule" in block_body(out, b["id"])
    assert after.entry(b["id"])["reading"] == page.chunk_of("b0")["text_hash"]
    assert after.entry(b["id"])["section"] == "learning rate schedule"
    # Text outside every block is byte-identical.
    assert outside_blocks(out) == outside_blocks(text)
    assert inknote.validate(out) == []


# -- edited blocks are never overwritten (INK-106) ---------------------------------------------------


def edit_first_block_and_change_its_ink(client, page, reading="gradient descent v2"):
    """The user edits block a0 by hand; then a0's ink changes meaning."""
    _canvas, text = export(client, page)
    text = with_user_text(text)
    text = text.replace("- gradient descent", "- gradient descent (my note)", 1)
    page.el("a1")["points"] = [[0, 0], [10, 21]]
    page.put()
    recognise(page.chunk_of("a0"), reading)
    return text


def test_a_changed_block_the_user_edited_is_not_overwritten(client, page):
    text = edit_first_block_and_change_its_ink(client, page)
    sync = check(client, text)
    a = page.chunk_of("a0")
    plan = inknote.plan(text, sync)
    assert plan["conflict"] == [a["id"]] and plan["rewrite"] == []
    assert a["id"] in plan["needs_body"]
    out = inknote.apply(text, sync, outline(client), {a["id"]: "## v2\n\n- brand new words"})
    before, after = inknote.parse(text), inknote.parse(out)
    block = block_body(out, a["id"])
    assert "(my note)" in block
    assert block.startswith("> [!conflict] Inkbridge:") and "> - brand new words" in block
    assert after.block(a["id"]).hash == a["content_hash"]
    e = after.entry(a["id"])
    assert e["hash"] == a["content_hash"] and e["reading"] == a["text_hash"]
    assert e["body"] == before.entry(a["id"])["body"]
    assert inknote.validate(out) == []
    for b in before.blocks[1:]:
        assert block_body(out, b.id) == block_body(text, b.id)
    assert out.count(USER_TEXT) == 3


def test_after_a_conflict_the_next_sync_is_clean_and_a_second_change_replaces_the_callout(
    client, page
):
    text = edit_first_block_and_change_its_ink(client, page)
    a = page.chunk_of("a0")["id"]
    out = inknote.apply(text, check(client, text), outline(client), {a: "first words"})
    again = check(client, out)
    assert a in again["fresh"]
    assert inknote.apply(out, again, outline(client), {}) == out
    page.el("a1")["points"] = [[0, 0], [10, 40]]
    page.put()
    recognise(page.chunk_of("a0"), "gradient descent v3")
    sync = check(client, out)
    assert inknote.plan(out, sync)["conflict"] == [page.chunk_of("a0")["id"]]
    a2 = page.chunk_of("a0")["id"]
    out2 = inknote.apply(out, sync, outline(client), {a2: "second words"})
    block = block_body(out2, a2)
    assert block.count("[!conflict]") == 1
    assert "second words" in block and "first words" not in block and "(my note)" in block
    assert inknote.validate(out2) == []


def test_an_unedited_changed_block_is_rewritten_and_its_body_hash_follows(client, page):
    _canvas, text = export(client, page)
    for n in (2, 3):
        page.el("b1")["points"] = [[0, 0], [30, -10 * n]]
        page.put()
        recognise(page.chunk_of("b0"), f"learning rate {n}")
        b = page.chunk_of("b0")["id"]
        sync = check(client, text)
        assert inknote.plan(text, sync)["conflict"] == []
        text = inknote.apply(text, sync, outline(client), {b: f"## rate {n}\n\nnew"})
        note = inknote.parse(text)
        assert note.entry(b)["body"] == inknote._body_hash(block_body(text, b))
        assert "[!conflict]" not in text


def test_flags_are_not_user_edits(client, page):
    _canvas, text = export(client, page)
    for i in range(3):
        page.el(f"c{i}")["isDeleted"] = True
    page.put()
    c_id = inknote.parse(text).blocks[2].id
    out = inknote.apply(text, check(client, text), outline(client), {})
    assert block_body(out, c_id).startswith(inknote.REMOVED_FLAG)
    assert not inknote._edited(out, inknote.parse(out), c_id)
    assert inknote._edited(out.replace("- momentum", "- momentum!"), inknote.parse(out), c_id)


def test_a_note_without_body_hashes_is_treated_as_edited_and_gets_one(client, page):
    text = edit_first_block_and_change_its_ink(client, page)
    note = inknote.parse(text)
    for e in note.meta["chunks"]:
        del e["body"]
    text = inknote._replace_meta(text, note)
    a = page.chunk_of("a0")["id"]
    sync = check(client, text)
    assert inknote.plan(text, sync)["conflict"] == [a]
    out = inknote.apply(text, sync, outline(client), {a: "legacy words"})
    block = block_body(out, a)
    assert "(my note)" in block and block.startswith("> [!conflict] Inkbridge:")
    assert "> legacy words" in block
    after = inknote.parse(out)
    assert after.entry(a)["body"] == inknote._body_hash(block)
    assert after.entry(a)["hash"] == page.chunk_of("a0")["content_hash"]
    assert not inknote._edited(out, after, a)
    assert "body" not in after.entry(
        after.blocks[1].id
    )  # untouched legacy blocks stay as they were
    assert inknote.validate(out) == []


def test_a_quote_glued_under_a_callout_is_not_part_of_it(client, page):
    flag = inknote.REMOVED_FLAG
    mine = "> my own quote\n"
    assert inknote._managed_prefix_len(f"{flag}\n{mine}words\n") == len(flag) + 1
    assert inknote._body_hash(f"{flag}\n{mine}words\n") != inknote._body_hash("words\n")
    # After a conflict the user keeps a quote under the callout; a second conflict keeps it.
    text = edit_first_block_and_change_its_ink(client, page)
    a = page.chunk_of("a0")["id"]
    out = inknote.apply(text, check(client, text), outline(client), {a: "first"})
    b = inknote.parse(out).block(a)
    top = out[b.body_start :]
    end = top.index("\n\n") + 2  # the callout's own blank line
    out = out[: b.body_start + end] + mine + out[b.body_start + end :]
    page.el("a1")["points"] = [[0, 0], [10, 40]]
    page.put()
    recognise(page.chunk_of("a0"), "gradient descent v3")
    a2 = page.chunk_of("a0")["id"]
    out2 = inknote.apply(out, check(client, out), outline(client), {a2: "second"})
    block = block_body(out2, a2)
    assert mine in block and "(my note)" in block and block.count("[!conflict]") == 1
    assert "second" in block and "first" not in block


def outside_blocks(text):
    note = inknote.parse(text)
    out, pos = [], note.body_offset
    for b in note.blocks:
        out.append(text[pos : b.start])
        pos = b.end
    out.append(text[pos:])
    return out


def test_a_users_edit_inside_a_fresh_block_survives(client, page):
    _canvas, text = export(client, page)
    a = page.chunk_of("a0")
    b = inknote.parse(text).block(a["id"])
    text = text[: b.body_end] + "My own aside.\n" + text[b.body_end :]
    page.el("b1")["points"] = [[0, 0], [30, -10]]
    page.put()
    recognise(page.chunk_of("b0"), "something else")
    out = inknote.apply(
        text, check(client, text), outline(client), {page.chunk_of("b0")["id"]: "x"}
    )
    assert "My own aside.\n" in block_body(out, a["id"])


def test_new_chunks_are_appended_and_removed_ones_flagged_once(client, page):
    _canvas, text = export(client, page)
    text = with_user_text(text)
    for i in range(3):
        page.el(f"c{i}")["isDeleted"] = True
    page.elements += row("d", 3, y=1500)
    page.put()
    recognise(page.chunk_of("d0"), "adam")
    sync = check(client, text)
    d = page.chunk_of("d0")
    c_id = inknote.parse(text).blocks[2].id
    out = inknote.apply(text, sync, outline(client), {d["id"]: "## adam\n\n- adaptive"})
    after = inknote.parse(out)
    assert after.blocks[-1].id == d["id"] and after.entry(d["id"])["section"] == "adam"
    assert block_body(out, c_id).startswith(inknote.REMOVED_FLAG)
    assert after.entry(c_id)["status"] == "removed"
    assert out.count(USER_TEXT) == 3
    assert inknote.validate(out) == []
    again = check(client, out)
    assert c_id not in again["removed"]  # flagged entries are not asked about again
    assert inknote.apply(out, again, outline(client), {}) == out
    # Even a stale result that still lists it does not flag it twice.
    stale = {**sync, "new": []}
    assert inknote.apply(out, stale, outline(client), {}).count(inknote.REMOVED_FLAG) == 1


def test_a_split_rewrites_the_block_from_its_successor_and_appends_the_other_piece(client):
    page = Canvas(client, row("e", 10))
    recognise(page.chunk_of("e0"), "ten strokes")
    canvas = outline(client)
    text = inknote.new_note(canvas, "Split", bodies_for(canvas))
    old = page.chunk_of("e0")["id"]
    for i in range(5, 10):
        page.el(f"e{i}")["y"] += 400
    page.put()
    top, low = page.chunk_of("e0"), page.chunk_of("e9")
    sync = check(client, text)
    plan = inknote.plan(text, sync)
    assert plan["needs_body"] == [top["id"], low["id"]]
    out = inknote.apply(text, sync, outline(client), {top["id"]: "top", low["id"]: "low"})
    after = inknote.parse(out)
    assert [b.id for b in after.blocks] == [top["id"], low["id"]]
    assert after.entry(old) is None and after.entry(top["id"])["hash"] == top["content_hash"]
    assert inknote.validate(out) == []


def test_a_split_of_an_edited_block_keeps_the_edit_and_adds_a_conflict(client):
    page = Canvas(client, row("e", 10))
    recognise(page.chunk_of("e0"), "ten strokes")
    canvas = outline(client)
    text = inknote.new_note(canvas, "Split", bodies_for(canvas))
    text = text.replace("- ten strokes", "- ten strokes (mine)", 1)
    for i in range(5, 10):
        page.el(f"e{i}")["y"] += 400
    page.put()
    top, low = page.chunk_of("e0"), page.chunk_of("e9")
    sync = check(client, text)
    assert inknote.plan(text, sync)["conflict"] != []
    out = inknote.apply(text, sync, outline(client), {top["id"]: "top", low["id"]: "low"})
    after = inknote.parse(out)
    assert "(mine)" in block_body(out, top["id"]) and "[!conflict]" in block_body(out, top["id"])
    assert after.entry(top["id"])["hash"] == top["content_hash"]
    assert after.block(low["id"]) is not None
    assert inknote.validate(out) == []


def test_a_merge_rewrites_the_first_block_and_flags_the_second(client):
    page = Canvas(client, row("p", 6) + row("q", 6, x=1090, start=6))
    canvas = outline(client)
    text = inknote.new_note(canvas, "Merge", bodies_for(canvas))
    p, q = page.chunk_of("p0")["id"], page.chunk_of("q6")["id"]
    for i in range(6, 12):
        page.el(f"q{i}")["x"] -= 1000
    page.put()
    merged = page.chunk_of("p0")
    sync = check(client, text)
    assert inknote.plan(text, sync)["merged"] == [q]
    out = inknote.apply(text, sync, outline(client), {merged["id"]: "both lines"})
    after = inknote.parse(out)
    assert [b.id for b in after.blocks] == [merged["id"], q]
    assert after.entry(q)["status"] == "merged" and after.entry(q)["successor"] == merged["id"]
    assert block_body(out, q).startswith("> [!warning] Inkbridge: this ink was merged")
    assert after.entry(p) is None
    assert inknote.validate(out) == []


def test_a_block_the_user_deleted_is_not_recreated_unless_asked(client, page):
    _canvas, text = export(client, page)
    b_id = page.chunk_of("b0")["id"]
    blk = inknote.parse(text).block(b_id)
    text = text[: blk.start] + text[blk.end :]
    page.el("b1")["points"] = [[0, 0], [30, -10]]
    page.put()
    recognise(page.chunk_of("b0"), "changed words")
    sync = check(client, text)
    plan = inknote.plan(text, sync)
    assert plan["user_deleted"] == [b_id] and plan["needs_body"] == []
    assert inknote.apply(text, sync, outline(client), {}) == text
    out = inknote.apply(text, sync, outline(client), {b_id: "back"}, recreate=True)
    assert inknote.parse(out).block(b_id) is not None
    assert inknote.validate(out) == []


def test_apply_refuses_without_the_words_it_needs(client, page):
    _canvas, text = export(client, page)
    nudge(page)
    recognise(page.chunk_of("a0"), "other words")
    with pytest.raises(inknote.NoteError, match="no new words"):
        inknote.apply(text, check(client, text), outline(client), {})


def test_trailing_text_without_a_newline_is_preserved(client, page):
    canvas, text = export(client, page)
    text = text + "\n\n> a trailing quote with no newline"
    assert inknote.apply(text, check(client, text), canvas, {}) == text


# -- crops and CLI ---------------------------------------------------------------------------------


def upload(client, page, rid):
    r = client.put(
        f"/regions/{rid}/image",
        data={"scene_version": str(page.version)},
        files={"image": ("c.png", PNG, "image/png")},
    )
    assert r.status_code == 200


def test_crops_are_saved_under_the_documented_name_and_embedded(client, page, api, tmp_path):
    a = page.chunk_of("a0")
    upload(client, page, a["id"])  # only a0 has a crop on the server
    canvas = outline(client)
    result = inknote.fetch_crops(api, tmp_path, canvas)
    assert result["saved"] == [a["id"]] and len(result["failed"]) == 2
    saved = tmp_path / f"content/raw/attachments/inkbridge/{a['id']}-{a['content_hash'][:12]}.png"
    assert saved.read_bytes() == PNG
    assert inknote.fetch_crops(api, tmp_path, canvas, [a["id"]])["skipped"] == [a["id"]]
    text = inknote.new_note(canvas, "T", bodies_for(canvas), tmp_path)
    note = inknote.parse(text)
    embeds = [b.id for b in note.blocks if "![[" in text[b.body_start : b.body_end]]
    assert embeds == [a["id"]], "a crop that is not in the vault is not embedded"


def test_cli_round_trip(client, page, api, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("INKBRIDGE_API_URL", api)
    note = tmp_path / "note.md"
    canvas_json, bodies_json = tmp_path / "canvas.json", tmp_path / "bodies.json"
    assert inknote.main(["canvas"]) == 0
    canvas_json.write_text(capsys.readouterr().out)
    bodies_json.write_text(json.dumps(bodies_for(json.loads(canvas_json.read_text()))))
    args = ["new", str(canvas_json), str(bodies_json), "--title", "T", "--out", str(note)]
    assert inknote.main(args) == 0
    assert inknote.main(["validate", str(note)]) == 0
    assert json.loads(capsys.readouterr().out)["valid"] is True
    assert inknote.main(["validate", str(note), "--strict"]) == 0
    assert json.loads(capsys.readouterr().out)["valid"] is True
    before = note.read_bytes()
    assert inknote.main(["sync", str(note)]) == 0
    sync_json = tmp_path / "sync.json"
    sync_json.write_text(capsys.readouterr().out)
    assert inknote.main(["plan", str(note), str(sync_json)]) == 0
    planned = json.loads(capsys.readouterr().out)
    assert planned["needs_body"] == [] and planned["conflict"] == []
    apply_args = ["apply", str(note), str(sync_json), str(canvas_json), str(bodies_json)]
    assert inknote.main(apply_args) == 0
    assert note.read_bytes() == before
    note.write_text("not a note")
    assert inknote.main(["validate", str(note)]) == 1


def test_cli_new_creates_folders_and_refuses_to_overwrite(
    client, page, api, tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("INKBRIDGE_API_URL", api)
    canvas_json, bodies_json = tmp_path / "canvas.json", tmp_path / "bodies.json"
    assert inknote.main(["canvas"]) == 0
    canvas_json.write_text(capsys.readouterr().out)
    bodies_json.write_text(json.dumps(bodies_for(json.loads(canvas_json.read_text()))))
    out = tmp_path / "content/library/T.md"
    args = ["new", str(canvas_json), str(bodies_json), "--title", "T", "--out", str(out)]
    args += ["--index", "[[Machine Learning & AI.base]]"]
    assert inknote.main(args) == 0
    assert 'index: "[[Machine Learning & AI.base]]"' in out.read_text()
    before = out.read_bytes()
    capsys.readouterr()
    assert inknote.main(args) == 2
    assert "apply" in capsys.readouterr().err
    assert out.read_bytes() == before


def test_the_script_only_uses_the_standard_library():
    import ast

    tree = ast.parse(SCRIPT.read_text())
    mods = {
        a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names
    }
    mods |= {
        (n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
    }
    assert mods <= set(sys.stdlib_module_names) | {"__future__"}, mods


# -- hardening (review findings) --------------------------------------------------------------------


def test_one_id_in_two_sync_lists_is_not_applied_twice(client, page):
    _canvas, text = export(client, page)
    b = page.chunk_of("b0")
    hexa = b["content_hash"]
    sync = {
        "fresh": [],
        "fresh_after_reread": [{"id": b["id"], "hash": hexa, "reading": hexa}],
        "changed": [{"id": b["id"], "hash": hexa, "reading": hexa}],
        "replaced": [],
        "removed": [b["id"]],
        "new": [],
    }
    out = inknote.apply(text, sync, outline(client), {b["id"]: "## rewritten"})
    assert inknote.validate(out) == []
    assert "rewritten" in block_body(out, b["id"])
    assert inknote.REMOVED_FLAG not in out  # the rewrite wins over the flag
    assert inknote.parse(out).entry(b["id"])["hash"] == hexa


def test_overlapping_edits_are_refused_not_spliced(client, page):
    _canvas, text = export(client, page)
    b = page.chunk_of("b0")
    h = "b" * 64
    item = {"id": b["id"], "hash": h, "reading": h}
    sync = {"changed": [item, item]}
    with pytest.raises(inknote.NoteError):
        inknote.apply(text, sync, outline(client), {b["id"]: "x"})


def test_words_cannot_forge_markers(client, page):
    canvas = outline(client)
    first = canvas["chunks"][0]["id"]
    evil = "hi\n<!-- /ink -->\n<!-- ink:Z hash:" + "c" * 64 + " -->\nmore"
    with pytest.raises(inknote.NoteError):
        inknote.new_note(canvas, "T", {first: evil})


def test_unsafe_ids_titles_and_links_are_refused(client, page):
    canvas = outline(client)
    c = dict(canvas["chunks"][0])
    for field, value in (
        ("id", "../../x"),
        ("content_hash", "a/b"),
        ("deep_link", "http://x) <!--"),
    ):
        bad = {**canvas, "chunks": [{**c, field: value}]}
        with pytest.raises(inknote.NoteError):
            inknote.new_note(bad, "T", {bad["chunks"][0]["id"]: "x"})
    with pytest.raises(inknote.NoteError):
        inknote.new_note(canvas, "a\n<!-- ink:x -->", bodies_for(canvas))


def test_a_crlf_note_is_refused_and_left_untouched(client, page, tmp_path):
    _canvas, text = export(client, page)
    note = tmp_path / "n.md"
    note.write_bytes(text.replace("\n", "\r\n").encode())
    before = note.read_bytes()
    assert inknote.main(["validate", str(note)]) == 1
    assert inknote.main(["apply", str(note), "s", "c", "b"]) != 0
    assert note.read_bytes() == before


def test_an_unchanged_note_file_is_not_rewritten(client, page, tmp_path):
    _canvas, text = export(client, page)
    note = tmp_path / "n.md"
    note.write_text(text, newline="")
    inknote._write(text, None, str(note))
    import os

    os.utime(note, (1, 1))
    inknote._write(text, None, str(note))
    assert note.stat().st_mtime == 1


SKILL = SCRIPT.parents[1] / "SKILL.md"


def test_skill_does_not_assume_the_repo_as_cwd():
    text = SKILL.read_text()
    assert "H=skills/" not in text and "from the repo or copy it" not in text


def test_skill_follows_the_vault_rules():
    text = SKILL.read_text()
    for want in (
        "content/library/",
        "content/raw/attachments/inkbridge",
        "_CLAUDE.md",
        "For future agent",
        "obsidian_validate_note",
        'validate "$INKBRIDGE_VAULT',
        "--strict",
    ):
        assert want in text, want
    assert "Crops go in `attachments/inkbridge/`" not in text
    fmt = (SCRIPT.parents[3] / "docs" / "vault-note-format.md").read_text()
    assert "body" in fmt and "[!conflict]" in fmt


def test_helper_runs_from_a_symlinked_skill_outside_the_repo(tmp_path):
    link = tmp_path / "inkbridge-export"
    link.symlink_to(SCRIPT.parents[1])
    r = subprocess.run(
        [sys.executable, str(link / "scripts" / "inknote.py"), "--help"],
        check=False,
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0 and "validate" in r.stdout


def test_summary_relates_and_source_follow_the_vault_style(client, page):
    canvas = outline(client)
    text = inknote.new_note(
        canvas,
        "T",
        bodies_for(canvas),
        relates=["[[Linear Regression]]"],
        date="2026-11-13",
        summary="Handwritten notes on how Inkbridge stores ink.\nRead the Strokes section first.",
    )
    assert "source: inkbridge" in text.splitlines()
    assert "> Handwritten notes on how Inkbridge stores ink.\n" in text
    assert "> Saved 2026-11-13 from the Inkbridge canvas" in text
    assert "Provenance note for an Inkbridge canvas" in text
    assert text.rstrip().endswith("## Related Notes\n- [[Linear Regression]]")
    assert inknote.validate(text, strict=True) == []
    with pytest.raises(inknote.NoteError):
        inknote.new_note(canvas, "T", bodies_for(canvas), summary="a — dash")


def test_new_blocks_go_above_the_related_notes_list(client, page):
    canvas = outline(client)
    text = inknote.new_note(canvas, "T", bodies_for(canvas), relates=["[[Linear Regression]]"])
    page.elements += row("d", 3, y=1500)
    page.put()
    recognise(page.chunk_of("d0"), "adam")
    sync = check(client, text)
    d = page.chunk_of("d0")
    out = inknote.apply(text, sync, outline(client), {d["id"]: "## adam\n\n- adaptive"})
    assert out.index(f"<!-- ink:{d['id']}") < out.index("## Related Notes")
    assert out.rstrip().endswith("- [[Linear Regression]]")
    assert inknote.validate(out) == []
