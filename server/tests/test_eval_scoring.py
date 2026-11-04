import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "eval"))

from evalkit import scoring


def box(x, y, w, h):
    return {"x": x, "y": y, "width": w, "height": h}


def test_cer_kitten_sitting():
    assert scoring.cer("kitten", "sitting") == 3 / 6


def test_cer_empty_reference():
    assert scoring.cer("", "") == 0.0
    assert scoring.cer("", "a") == 1.0


def test_normalisation_and_exact_match():
    assert scoring.exact_match("a  b", "a b")
    assert not scoring.exact_match("a  b", "a b", norm=False)
    assert scoring.exact_match("é", "é")


def test_mean_cer_is_corpus_weighted():
    assert scoring.mean_cer([("ab", "ab"), ("c", "d")]) == pytest.approx(1 / 3)


def test_prf():
    p, r, f = scoring.prf(2, 1, 2)
    assert (p, r, f) == pytest.approx((2 / 3, 1 / 2, 4 / 7))
    assert scoring.prf(0, 0, 0) == (0.0, 0.0, 0.0)


def test_diagram_f1_missing_edge_and_spurious_node():
    truth_nodes = ["A", "B", "C"]
    truth_edges = [("A", "B"), ("B", "C")]
    pred_nodes = ["a", "B", "C", "X"]  # case folded match, one spurious
    pred_edges = [("A", "B")]  # one missing
    out = scoring.diagram_f1(pred_nodes, pred_edges, truth_nodes, truth_edges)
    assert out["node_p"] == pytest.approx(3 / 4)
    assert out["node_r"] == pytest.approx(1.0)
    assert out["edge_p"] == pytest.approx(1.0)
    assert out["edge_r"] == pytest.approx(1 / 2)
    assert out["edge_f1"] == pytest.approx(2 / 3)


def test_diagram_f1_directed_flag():
    args = (["A", "B"], [("B", "A")], ["A", "B"], [("A", "B")])
    assert scoring.diagram_f1(*args)["edge_f1"] == 0.0
    assert scoring.diagram_f1(*args, directed=False)["edge_f1"] == 1.0


def test_iou():
    assert scoring.iou(box(0, 0, 10, 10), box(0, 0, 10, 10)) == 1.0
    assert scoring.iou(box(0, 0, 10, 10), box(20, 20, 5, 5)) == 0.0
    assert scoring.iou(box(0, 0, 10, 10), box(5, 0, 10, 10)) == pytest.approx(1 / 3)


def test_match_boxes_one_to_one():
    truth = [box(0, 0, 10, 10), box(1, 0, 10, 10)]
    pred = [box(0, 0, 10, 10)]
    m = scoring.match_boxes(pred, truth)
    assert m["pairs"] == [(0, 0)]
    assert m["unmatched_truth"] == [1]
    assert m["unmatched_pred"] == []


def test_chunk_errors():
    truth = [box(0, 0, 100, 40)]
    assert scoring.chunk_errors(truth, truth) == {"split_errors": 0, "merge_errors": 0}
    cut = [box(0, 0, 40, 40), box(60, 0, 40, 40)]
    assert scoring.chunk_errors(cut, truth) == {"split_errors": 1, "merge_errors": 0}
    two = [box(0, 0, 40, 40), box(60, 0, 40, 40)]
    swallowed = [box(0, 0, 100, 40)]
    assert scoring.chunk_errors(swallowed, two) == {"split_errors": 0, "merge_errors": 1}


def test_detection_rates():
    rows = [(True, True), (True, False), (False, True), (False, False), (False, False)]
    d = scoring.detection_rates(rows)
    assert d["recall"] == pytest.approx(1 / 2)
    assert d["precision"] == pytest.approx(1 / 2)
    assert d["false_alarm_rate"] == pytest.approx(1 / 3)
    assert (d["n_real"], d["n_cosmetic"]) == (2, 3)
    assert scoring.detection_rates([])["recall"] == 0.0
