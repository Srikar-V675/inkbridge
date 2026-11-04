"""Pure scoring helpers: text error rates, set precision/recall, box matching."""

import unicodedata
from collections.abc import Iterable, Sequence


def normalise(s: str) -> str:
    return " ".join(unicodedata.normalize("NFC", s).split())


def edit_distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _prep(ref: str, hyp: str, norm: bool) -> tuple[str, str]:
    return (normalise(ref), normalise(hyp)) if norm else (ref, hyp)


def cer(ref: str, hyp: str, norm: bool = True) -> float:
    ref, hyp = _prep(ref, hyp, norm)
    if not ref:
        return 0.0 if not hyp else 1.0
    return edit_distance(ref, hyp) / len(ref)


def exact_match(ref: str, hyp: str, norm: bool = True) -> bool:
    ref, hyp = _prep(ref, hyp, norm)
    return ref == hyp


def mean_cer(pairs: Sequence[tuple[str, str]]) -> float:
    """Corpus CER: total distance over total reference length."""
    prepared = [_prep(r, h, True) for r, h in pairs]
    total = sum(len(r) for r, _ in prepared)
    if not total:
        return 0.0
    return sum(edit_distance(r, h) for r, h in prepared) / total


def prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f


def set_prf(pred: Iterable, truth: Iterable) -> tuple[float, float, float]:
    ps, ts = set(pred), set(truth)
    return prf(len(ps & ts), len(ps - ts), len(ts - ps))


def _label(s: str) -> str:
    return normalise(s).casefold()


def diagram_f1(pred_nodes, pred_edges, truth_nodes, truth_edges, directed: bool = True):
    def edge(e):
        a, b = _label(e[0]), _label(e[1])
        return (a, b) if directed else tuple(sorted((a, b)))

    np_, nr, nf = set_prf({_label(n) for n in pred_nodes}, {_label(n) for n in truth_nodes})
    ep, er, ef = set_prf({edge(e) for e in pred_edges}, {edge(e) for e in truth_edges})
    return {
        "node_p": np_,
        "node_r": nr,
        "node_f1": nf,
        "edge_p": ep,
        "edge_r": er,
        "edge_f1": ef,
    }


def _overlap(a: dict, b: dict) -> float:
    w = min(a["x"] + a["width"], b["x"] + b["width"]) - max(a["x"], b["x"])
    h = min(a["y"] + a["height"], b["y"] + b["height"]) - max(a["y"], b["y"])
    return max(w, 0.0) * max(h, 0.0)


def _area(a: dict) -> float:
    return a["width"] * a["height"]


def iou(a: dict, b: dict) -> float:
    inter = _overlap(a, b)
    union = _area(a) + _area(b) - inter
    return inter / union if union > 0 else 0.0


def match_boxes(pred: list[dict], truth: list[dict], thr: float = 0.5) -> dict:
    scored = sorted(
        ((iou(p, t), pi, ti) for pi, p in enumerate(pred) for ti, t in enumerate(truth)),
        key=lambda s: (-s[0], s[1], s[2]),
    )
    used_p: set[int] = set()
    used_t: set[int] = set()
    pairs: list[tuple[int, int]] = []
    for score, pi, ti in scored:
        if score < thr:
            break
        if pi in used_p or ti in used_t:
            continue
        used_p.add(pi)
        used_t.add(ti)
        pairs.append((pi, ti))
    return {
        "pairs": pairs,
        "unmatched_pred": [i for i in range(len(pred)) if i not in used_p],
        "unmatched_truth": [i for i in range(len(truth)) if i not in used_t],
    }


def _covered(inner: dict, outer: dict, cover: float) -> bool:
    """True if at least `cover` of inner's area lies inside outer."""
    area = _area(inner)
    return area > 0 and _overlap(inner, outer) / area >= cover


def chunk_errors(pred: list[dict], truth: list[dict], cover: float = 0.5) -> dict:
    split = sum(1 for t in truth if sum(_covered(p, t, cover) for p in pred) >= 2)
    merge = sum(1 for p in pred if sum(_covered(t, p, cover) for t in truth) >= 2)
    return {"split_errors": split, "merge_errors": merge}


def detection_rates(rows: Sequence[tuple[bool, bool]]) -> dict[str, float]:
    real = [f for r, f in rows if r]
    cosmetic = [f for r, f in rows if not r]
    flagged = [r for r, f in rows if f]
    tp = sum(real)
    return {
        "recall": tp / len(real) if real else 0.0,
        "precision": sum(flagged) / len(flagged) if flagged else 0.0,
        "false_alarm_rate": sum(cosmetic) / len(cosmetic) if cosmetic else 0.0,
        "n_real": len(real),
        "n_cosmetic": len(cosmetic),
    }
