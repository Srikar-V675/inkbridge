import copy
import math
import sys
from pathlib import Path

import pytest

EVAL = Path(__file__).resolve().parents[2] / "eval"
sys.path.insert(0, str(EVAL))

from evalkit import arms
from evalkit.arms import ARMS, build_payload, image_tokens, strokes_payload
from evalkit.dataset import load_dataset

SYNTHETIC = EVAL / "data" / "synthetic-v1"


@pytest.fixture
def ds():
    return load_dataset(SYNTHETIC)


def page(ds, pid):
    return next(p for p in ds.pages if p.id == pid)


def chunk(p, cid):
    return next(c for c in p.chunks if c.id == cid)


def in_box(el, box):
    return (
        el["x"] < box["x"] + box["width"]
        and box["x"] < el["x"] + el["width"]
        and el["y"] < box["y"] + box["height"]
        and box["y"] < el["y"] + el["height"]
    )


# ---- Task 1: payload builders ----


def test_compact_strokes_keeps_order_and_pressure(ds):
    p = page(ds, "p01-text")
    c = chunk(p, "c1")
    free = [e for e in p.elements if e["type"] == "freedraw" and in_box(e, c.box)]
    text = strokes_payload(p, c, arms.STROKE_TOKEN_BUDGET)
    lines = text.split("\n")
    assert len(lines) == len(free) > 0
    first = free[0]
    digits = [int(tok.split(",")[2]) for tok in lines[0].split(" ")]
    assert digits == [round(pr * 9) for pr in first["pressures"]]
    # offsets are relative to the chunk origin, so the first point is (el.x - box.x, el.y - box.y)
    x, y, _ = lines[0].split(" ")[0].split(",")
    assert (int(x), int(y)) == (
        round(first["x"] + first["points"][0][0] - c.box["x"]),
        round(first["y"] + first["points"][0][1] - c.box["y"]),
    )


def test_budget_fallback(ds):
    p = page(ds, "p01-text")
    c = chunk(p, "c1")
    tiny = build_payload(p, c, "image+strokes", budget=1)
    assert tiny.strokes is None and tiny.fell_back is True
    assert tiny.tokens == tiny.image_tokens
    full = build_payload(p, c, "image+strokes")
    assert isinstance(full.strokes, str) and full.fell_back is False


def test_drafts_and_deleted_skipped(ds):
    p = page(ds, "p01-text")
    c = chunk(p, "c1")
    base = len(strokes_payload(p, c, arms.STROKE_TOKEN_BUDGET).split("\n"))
    els = copy.deepcopy(p.elements)
    inside = [e for e in els if e["type"] == "freedraw" and in_box(e, c.box)]
    inside[0]["isDeleted"] = True
    inside[1]["customData"] = {"draft": True}
    mutated = copy.copy(p)
    object.__setattr__(mutated, "elements", els)
    assert len(strokes_payload(mutated, c, arms.STROKE_TOKEN_BUDGET).split("\n")) == base - 2


def test_arm_tokens_differ(ds):
    p = page(ds, "p01-text")
    c = chunk(p, "c1")
    img = build_payload(p, c, "image").tokens
    both = build_payload(p, c, "image+strokes").tokens
    strokes = build_payload(p, c, "strokes").tokens
    assert img == image_tokens(c)
    assert img != both > strokes


def test_diagram_chunk_has_no_strokes(ds):
    p = page(ds, "p03-diagram")
    c = chunk(p, "c1")  # the diagram's shapes carry no freedraw
    payload = build_payload(p, c, "strokes")
    assert payload.no_input is True and payload.strokes is None and payload.tokens == 0
    assert build_payload(p, c, "image+strokes").fell_back is True


def test_unknown_arm_raises(ds):
    p = page(ds, "p01-text")
    with pytest.raises(ValueError):
        build_payload(p, p.chunks[0], "video")


def test_image_tokens_is_padded_area_estimate(ds):
    c = chunk(page(ds, "p01-text"), "c1")
    w = c.box["width"] + 2 * arms.PAD
    h = c.box["height"] + 2 * arms.PAD
    assert image_tokens(c) == math.ceil(w * h * arms.IMAGE_SCALE**2 / 750)
    assert ARMS == ("image", "image+strokes", "strokes")
