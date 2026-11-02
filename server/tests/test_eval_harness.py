import copy
import json
import shutil
import sys
from pathlib import Path

import pytest

EVAL = Path(__file__).resolve().parents[2] / "eval"
sys.path.insert(0, str(EVAL))

import make_synthetic
from evalkit.dataset import DatasetError, load_dataset
from evalkit.edits import apply_edit

SYNTHETIC = EVAL / "data" / "synthetic-v1"


@pytest.fixture
def ds():
    return load_dataset(SYNTHETIC)


def page(ds, pid):
    return next(p for p in ds.pages if p.id == pid)


def edit(p, eid):
    return next(e for e in p.edits if e.id == eid)


# ---- Task 2: dataset and edits ----


def test_loads_committed_set(ds):
    assert [p.id for p in ds.pages] == ["p01-text", "p02-equation", "p03-diagram"]
    assert ds.synthetic and ds.test_pages_only
    assert all(p.synthetic for p in ds.pages)
    assert all(p.png is None for p in ds.pages)


def copy_set(tmp_path):
    dst = tmp_path / "set"
    shutil.copytree(SYNTHETIC, dst)
    return dst


def test_synthetic_flag_must_match_manifest(tmp_path):
    root = copy_set(tmp_path)
    path = root / "p02-equation" / "truth.json"
    truth = json.loads(path.read_text())
    truth["synthetic"] = False
    path.write_text(json.dumps(truth))
    with pytest.raises(DatasetError, match="p02-equation"):
        load_dataset(root)


def test_edit_must_reference_a_chunk(tmp_path):
    root = copy_set(tmp_path)
    path = root / "p01-text" / "truth.json"
    truth = json.loads(path.read_text())
    truth["edits"][0]["chunk"] = "nope"
    path.write_text(json.dumps(truth))
    with pytest.raises(DatasetError, match="nope"):
        load_dataset(root)


def test_unknown_op_and_missing_field_raise(tmp_path):
    root = copy_set(tmp_path)
    path = root / "p01-text" / "truth.json"
    truth = json.loads(path.read_text())
    truth["edits"][0]["ops"][0]["op"] = "explode"
    path.write_text(json.dumps(truth))
    with pytest.raises(DatasetError, match="explode"):
        load_dataset(root)
    del truth["chunks"][0]["text"]
    truth["edits"][0]["ops"][0]["op"] = "translate"
    path.write_text(json.dumps(truth))
    with pytest.raises(DatasetError, match="text"):
        load_dataset(root)


def test_apply_edit_does_not_mutate_and_translate_is_scoped(ds):
    p = page(ds, "p01-text")
    before = copy.deepcopy(p.elements)
    out = apply_edit(p.elements, edit(p, "e2"))
    assert p.elements == before
    moved = [(a["id"], b["x"] - a["x"]) for a, b in zip(p.elements, out, strict=True)]
    assert [m for m in moved if m[1]] == [("c1-s2", 2)]


def test_redraw_keeps_geometry_with_new_ids(ds):
    p = page(ds, "p01-text")
    out = apply_edit(p.elements, edit(p, "e3"))
    originals = {e["id"]: e for e in p.elements if e["id"].startswith("c1")}
    copies = [e for e in out if e["id"].endswith("-r")]
    assert len(copies) == len(originals)
    for c in copies:
        o = originals[c["id"][: -len("-r")]]
        assert {k: v for k, v in c.items() if k != "id"} == {
            k: v for k, v in o.items() if k not in ("id", "isDeleted")
        } | {"isDeleted": False}
    assert all(e["isDeleted"] for e in out if e["id"] in originals)


def test_unknown_id_raises(ds):
    p = page(ds, "p01-text")
    bad = copy.deepcopy(edit(p, "e2"))
    object.__setattr__(bad, "ops", [{"op": "delete", "ids": ["ghost"]}])
    with pytest.raises(KeyError):
        apply_edit(p.elements, bad)


def test_generator_reproduces_committed_files(tmp_path):
    make_synthetic.generate(tmp_path)
    for f in sorted(SYNTHETIC.rglob("*")):
        if f.is_file():
            assert (tmp_path / f.relative_to(SYNTHETIC)).read_bytes() == f.read_bytes()


# ---- Task 3: readers and the Gemini gate ----

import dataclasses

from evalkit.readers import (
    GateError,
    NoisyReader,
    OracleReader,
    load_reader,
)


def test_oracle_returns_truth(ds):
    p = page(ds, "p02-equation")
    r = OracleReader().read(p, p.chunks[0])
    assert (r.text, r.latex) == (p.chunks[0].text, p.chunks[0].latex)


def test_noisy_reader(ds):
    p = page(ds, "p01-text")
    c = p.chunks[0]
    assert NoisyReader(0.0).read(p, c).text == c.text
    a = NoisyReader(0.5).read(p, c).text
    assert a == NoisyReader(0.5).read(p, c).text
    assert a != c.text
    assert a != NoisyReader(0.5, seed=1).read(p, c).text


def gemini_ready(ds, monkeypatch, **overrides):
    """A dataset that passes every gate condition, then break one via overrides."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real")
    pages = [dataclasses.replace(p, png=b"png", synthetic=False) for p in ds.pages]
    base = dataclasses.replace(ds, synthetic=False, test_pages_only=True, pages=pages)
    return dataclasses.replace(base, **overrides)


@pytest.mark.parametrize("case", ["no_flag", "not_test_pages", "synthetic", "no_key", "no_png"])
def test_gemini_gate_refuses(ds, monkeypatch, case):
    from inkbridge.recognizer import gemini

    def boom():
        raise AssertionError("gate must refuse before reaching the recognizer")

    monkeypatch.setattr(gemini, "default_recognizer", boom)
    d = gemini_ready(ds, monkeypatch)
    allow = True
    if case == "no_flag":
        allow = False
    elif case == "not_test_pages":
        d = dataclasses.replace(d, test_pages_only=False)
    elif case == "synthetic":
        d = dataclasses.replace(d, synthetic=True)
    elif case == "no_key":
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    elif case == "no_png":
        d = dataclasses.replace(d, pages=[dataclasses.replace(d.pages[0], png=None), *d.pages[1:]])
    with pytest.raises(GateError):
        load_reader("gemini", d, allow_model=allow)


def test_gemini_gate_passes_to_recognizer_when_all_conditions_hold(ds, monkeypatch):
    from inkbridge.recognizer import gemini

    sentinel = object()
    monkeypatch.setattr(gemini, "default_recognizer", lambda: sentinel)
    reader = load_reader("gemini", gemini_ready(ds, monkeypatch), allow_model=True)
    assert reader.name == "gemini"


def test_load_reader_from_module(tmp_path, monkeypatch, ds):
    (tmp_path / "myreader_mod.py").write_text(
        "from evalkit.readers import Reading\n"
        "class R:\n    name = 'mine'\n"
        "    def read(self, page, chunk):\n        return Reading(text='x')\n"
        "reader = R()\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    r = load_reader("myreader_mod:reader", ds)
    assert r.read(ds.pages[0], ds.pages[0].chunks[0]).text == "x"
    assert load_reader("oracle", ds).name == "oracle"
    assert load_reader("noisy:0.25", ds).name == "noisy:0.25"


# ---- Task 4: report, experiments, CLI ----

import run as eval_run
from evalkit import report
from evalkit.experiments import run_chunks, run_stale, run_transcribe


def test_transcribe_oracle_and_noisy(ds):
    res = run_transcribe(ds, OracleReader())
    assert res.summary["cer"] == 0.0 and res.summary["equation_exact"] == 1.0
    noisy = run_transcribe(ds, NoisyReader(0.3))
    kinds = {c.kind for p in ds.pages for c in p.chunks}
    assert noisy.summary["cer"] > 0
    assert len(noisy.rows) == len(kinds) + 1  # one row per kind plus "all"


def test_chunks_experiment(ds):
    res = run_chunks(ds)
    total = res.rows[-1]
    assert total[0] == "all" and total[1] == sum(len(p.chunks) for p in ds.pages)
    for row in res.rows:
        assert 0.0 <= row[3] <= 1.0 and 0.0 <= row[6] <= 1.0
    assert res.summary["matched_share"] == 1.0  # fixtures are laid out to chunk cleanly


def test_stale_experiment_is_designed_by_construction(ds):
    res = run_stale(ds)
    flags = {(r[0], r[1]): (r[3], r[4], r[5]) for r in res.rows}  # real, hash-only, early-cutoff
    assert flags[("p01-text", "e1")] == (False, False, False)  # move keeps content_hash
    assert flags[("p01-text", "e2")] == (False, True, False)  # nudge: hash moves, reading does not
    assert flags[("p01-text", "e3")] == (False, False, False)  # redraw identical keeps it
    assert flags[("p01-text", "e4")] == (True, True, True)  # change_word: both change
    assert flags[("p03-diagram", "e1")] == (True, True, True)
    assert flags[("p03-diagram", "e2")] == (True, True, True)
    assert (
        res.summary["hash_only"]["false_alarm_rate"]
        > res.summary["early_cutoff"]["false_alarm_rate"]
    )
    assert res.summary["early_cutoff"]["recall"] == 1.0


def test_write_section(tmp_path):
    path = tmp_path / "results.md"
    report.write_section(path, "a", "one")
    path.write_text(path.read_text().replace("# Eval results", "# Eval results\n\nhand note"))
    report.write_section(path, "b", "two")
    text = path.read_text()
    path.write_text(text + "\ntrailing hand text\n")
    before = path.read_text()
    report.write_section(path, "a", "ONE")
    after = path.read_text()
    assert "ONE" in after and "one" not in after
    assert "hand note" in after and "trailing hand text" in after
    assert after.count("<!-- eval:b -->") == 1
    assert after.split("<!-- eval:a -->")[0] == before.split("<!-- eval:a -->")[0]
    assert after.split("<!-- /eval -->", 1)[1] == before.split("<!-- /eval -->", 1)[1]
    report.write_section(path, "a", "ONE")
    assert path.read_text() == after


def test_section_header_marks_synthetic():
    head = report.section_header("d", True, "oracle", today="2026-01-01")
    assert head.startswith("_dataset: d, synthetic: yes, reader: oracle, run: 2026-01-01_")
    assert "SYNTHETIC FIXTURES" in head
    assert "SYNTHETIC" not in report.section_header("d", False, "oracle", today="2026-01-01")


def test_cli(tmp_path, capsys):
    out = tmp_path / "r.md"
    assert eval_run.main(["chunks", "--out", str(out)], today="2026-01-01") == 0
    assert "<!-- eval:chunks -->" in out.read_text()
    assert "SYNTHETIC FIXTURES" in out.read_text()
    assert eval_run.main(["transcribe", "--reader", "gemini", "--out", str(out)]) == 2
    assert eval_run.main(["transcribe", "--out", str(out), "--label", "e1-oracle"]) == 0
    assert "<!-- eval:e1-oracle -->" in out.read_text()
