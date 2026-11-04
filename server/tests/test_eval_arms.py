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


# ---- Task 2: arm readers and the input_repr experiment ----

from evalkit.experiments import run_input_repr
from evalkit.readers import OracleReader, load_reader


def test_input_repr_three_rows(ds):
    res = run_input_repr(ds, reader=OracleReader())
    assert [r[0] for r in res.rows] == list(ARMS)
    assert res.headers == [
        "arm",
        "n",
        "CER",
        "exact match",
        "mean tokens",
        "total cost usd",
        "mean latency s",
        "fell back",
        "no input",
    ]
    by_arm = {r[0]: r for r in res.rows}
    # the strokes arm has no input for the diagram chunk, which is a miss and is reported
    for arm in ("image", "image+strokes"):
        assert by_arm[arm][2] == 0.0 and by_arm[arm][3] == 1.0
    assert by_arm["strokes"][8] == 1 and by_arm["strokes"][2] > 0.0
    assert by_arm["image"][7] == 0 and by_arm["image"][8] == 0


def test_tokens_come_from_payload(ds):
    res = run_input_repr(ds, reader=OracleReader())
    chunks = [(p, c) for p in ds.pages for c in p.chunks]
    expected = sum(build_payload(p, c, "image").tokens for p, c in chunks) / len(chunks)
    image_row = next(r for r in res.rows if r[0] == "image")
    assert image_row[4] > 0
    assert image_row[4] == pytest.approx(expected)


def test_noisy_arm_rates_ordering(ds):
    reader = load_reader("arms-noisy:image=0.05,image+strokes=0.02,strokes=0.2", ds)
    cer = run_input_repr(ds, reader=reader).summary
    assert cer["image+strokes"]["cer"] < cer["image"]["cer"] < cer["strokes"]["cer"]


def test_cost_uses_price_table(ds, monkeypatch):
    from evalkit.readers import Reading

    monkeypatch.setattr(arms, "PRICE_PER_MTOK_IN", 1.0)
    p = page(ds, "p01-text")
    c = chunk(p, "c1")
    payload = build_payload(p, c, "image+strokes")

    class Plain:
        name = "plain"

        def read(self, page, chunk):
            return Reading(text=chunk.text)

    got = arms.arm_read(Plain(), p, c, payload)
    assert got.tokens == payload.tokens
    assert got.cost_usd == pytest.approx(payload.tokens / 1e6)


def test_no_model_reach(ds, monkeypatch):
    from inkbridge.recognizer import gemini

    def boom():
        raise AssertionError("the oracle run must never reach a model")

    monkeypatch.setattr(gemini, "default_recognizer", boom)
    res = run_input_repr(ds, reader=OracleReader())
    assert len(res.rows) == 3


def test_input_repr_needs_arm_reader_or_simulated(ds):
    class RealLooking:
        name = "real"

        def read(self, page, chunk):
            raise AssertionError("must not be called as if it could see strokes")

    with pytest.raises(ValueError, match="read_arm"):
        run_input_repr(ds, reader=RealLooking())


def test_parse_arm_rates_rejects_unknown_arm():
    with pytest.raises(ValueError):
        load_reader("arms-noisy:video=0.1", load_dataset(SYNTHETIC))


# ---- Task 3: CLI wiring and the section ----

import run as eval_run

ARMS_SPEC = "arms-noisy:image=0.05,image+strokes=0.02,strokes=0.2"


def _body_rows(text: str, section: str) -> list[str]:
    block = text.split(f"<!-- eval:{section} -->", 1)[1].split("<!-- /eval -->", 1)[0]
    return [
        ln
        for ln in block.splitlines()
        if ln.startswith("| ") and not ln.startswith("| arm") and not ln.startswith("| ---")
    ]


def test_cli_input_repr_writes_section(tmp_path):
    out = tmp_path / "r.md"
    code = eval_run.main(
        ["input_repr", "--reader", ARMS_SPEC, "--out", str(out), "--label", "input_repr"],
        today="2026-11-02",
    )
    assert code == 0
    text = out.read_text()
    assert "<!-- eval:input_repr -->" in text
    assert "SYNTHETIC FIXTURES" in text
    assert "image scale 1.0, stroke width 2, stroke budget 1500 tokens" in text
    rows = _body_rows(text, "input_repr")
    assert [r.split("|")[1].strip() for r in rows] == ["image", "image+strokes", "strokes"]


def test_cli_input_repr_gate(tmp_path):
    out = tmp_path / "r.md"
    assert eval_run.main(["input_repr", "--reader", "gemini", "--out", str(out)]) == 2


def test_cli_default_reader_is_oracle(tmp_path):
    out = tmp_path / "r.md"
    assert eval_run.main(["input_repr", "--out", str(out)], today="2026-11-02") == 0
    text = out.read_text()
    assert "reader: oracle" in text
    assert "| image | 5 | 0.000" in text
