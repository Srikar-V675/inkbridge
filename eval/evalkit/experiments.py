"""Experiments. Each is a pure function of a dataset (and a reader) returning a table."""

from dataclasses import dataclass, field
from typing import Any

from inkbridge.chunker import chunk_scene
from inkbridge.regions import bbox_of, content_hash, text_hash

from . import scoring
from .dataset import Dataset, Page
from .edits import apply_edit
from .readers import Reader


@dataclass
class Result:
    headers: list[str]
    rows: list[list[Any]]
    summary: dict[str, Any] = field(default_factory=dict)


def _need_reader(reader: Reader | None) -> Reader:
    if reader is None:
        raise ValueError("this experiment needs a reader")
    return reader


def run_transcribe(dataset: Dataset, reader: Reader | None = None, **_: Any) -> Result:
    """E1 base: read every hand-boxed chunk. CER for text kinds, exact match for equations."""
    reader = _need_reader(reader)
    by_kind: dict[str, list] = {}
    for page in dataset.pages:
        for chunk in page.chunks:
            by_kind.setdefault(chunk.kind, []).append((chunk, reader.read(page, chunk)))
    headers = ["kind", "n", "CER", "exact match", "mean tokens", "total cost usd", "mean latency s"]

    def row(label: str, items: list) -> list[Any]:
        text_items = [(c.text, r.text) for c, r in items if c.kind != "equation"]
        eq_items = [(c, r) for c, r in items if c.kind == "equation"]
        n = len(items)
        cer_v: Any = scoring.mean_cer(text_items) if text_items else "-"
        exact: Any = (
            sum(scoring.exact_match(c.latex or c.text, r.latex or r.text) for c, r in eq_items)
            / len(eq_items)
            if eq_items
            else "-"
        )
        return [
            label,
            n,
            cer_v,
            exact,
            sum(r.tokens for _, r in items) / n,
            sum(r.cost_usd for _, r in items),
            sum(r.latency_s for _, r in items) / n,
        ]

    rows = [row(kind, items) for kind, items in sorted(by_kind.items())]
    everything = [i for items in by_kind.values() for i in items]
    rows.append(row("all", everything))
    text_all = [(c.text, r.text) for c, r in everything if c.kind != "equation"]
    eq = [(c, r) for c, r in everything if c.kind == "equation"]
    summary = {
        "cer": scoring.mean_cer(text_all) if text_all else 0.0,
        "equation_exact": (
            sum(scoring.exact_match(c.latex or c.text, r.latex or r.text) for c, r in eq) / len(eq)
            if eq
            else 0.0
        ),
    }
    return Result(headers, rows, summary)


def _auto_boxes(page: Page) -> list[dict[str, float]]:
    by_id = {e["id"]: e for e in page.elements}
    chunking = chunk_scene(page.elements)
    return [bbox_of([by_id[i] for i in members]) for members in chunking.chunks]


def run_chunks(dataset: Dataset, reader: Reader | None = None, **_: Any) -> Result:
    """E5: automatic chunks against hand-boxed ones. Offline and real (no model involved)."""
    headers = [
        "page",
        "truth chunks",
        "auto chunks",
        "matched (IoU>=0.5)",
        "merge errors",
        "split errors",
        "needs manual fix",
    ]
    rows: list[list[Any]] = []
    totals = [0, 0, 0, 0, 0, 0]  # truth, auto, matched, merge, split, unmatched truth
    for page in dataset.pages:
        pred = _auto_boxes(page)
        truth = [c.box for c in page.chunks]
        m = scoring.match_boxes(pred, truth)
        err = scoring.chunk_errors(pred, truth)
        n = len(truth)
        unmatched = len(m["unmatched_truth"])
        fix = (unmatched + err["merge_errors"] + err["split_errors"]) / n if n else 0.0
        rows.append(
            [page.id, n, len(pred), len(m["pairs"]) / n if n else 0.0]
            + [err["merge_errors"], err["split_errors"], min(fix, 1.0)]
        )
        for i, v in enumerate(
            [n, len(pred), len(m["pairs"]), err["merge_errors"], err["split_errors"], unmatched]
        ):
            totals[i] += v
    n = totals[0]
    fix_all = min((totals[5] + totals[3] + totals[4]) / n, 1.0) if n else 0.0
    rows.append(["all", n, totals[1], totals[2] / n if n else 0.0, totals[3], totals[4], fix_all])
    return Result(
        headers,
        rows,
        {"matched_share": totals[2] / n if n else 0.0, "needs_manual_fix": fix_all},
    )


def _chunk_hashes(elements: list[dict[str, Any]], tracked: set[str], box: dict | None):
    """content_hash set of the auto chunks that hold a tracked id or intersect box."""
    by_id = {e["id"]: e for e in elements}
    hashes = set()
    for members in chunk_scene(elements).chunks:
        els = [by_id[i] for i in members]
        hit = bool(tracked & set(members))
        if not hit and box is not None:
            hit = _intersects(bbox_of(els), box)
        if hit:
            hashes.add(content_hash(els))
    return hashes


def run_stale(dataset: Dataset, reader: Reader | None = None, **_: Any) -> Result:
    """E4 base: a pure model of check_sync. Hash-only flags any content_hash change; early cutoff
    also needs the reading (text_hash) to change. INK-052 reconciles this with db/sync.py."""
    headers = ["page", "edit", "type", "real edit", "hash-only flagged", "early-cutoff flagged"]
    rows: list[list[Any]] = []
    hash_rows: list[tuple[bool, bool]] = []
    cutoff_rows: list[tuple[bool, bool]] = []
    for page in dataset.pages:
        by_chunk = {c.id: c for c in page.chunks}
        for edit in page.edits:
            chunk = by_chunk[edit.chunk]
            before_ids = {
                i
                for members in chunk_scene(page.elements).chunks
                for i in members
                if _intersects(bbox_of([e for e in page.elements if e["id"] in members]), chunk.box)
            }
            tracked = set(before_ids)
            for op in edit.ops:
                if op["op"] == "add":
                    tracked |= {e["id"] for e in op["elements"]}
                elif op["op"] == "redraw":
                    tracked |= {i + op["id_suffix"] for i in op["ids"] if i in before_ids}
            before = _chunk_hashes(page.elements, before_ids, chunk.box)
            after = _chunk_hashes(apply_edit(page.elements, edit), tracked, None)
            hash_flag = before != after
            text_changed = text_hash(chunk.text, None) != text_hash(edit.text_after, None)
            cutoff_flag = hash_flag and text_changed
            hash_rows.append((edit.meaning_changed, hash_flag))
            cutoff_rows.append((edit.meaning_changed, cutoff_flag))
            rows.append([page.id, edit.id, edit.type, edit.meaning_changed, hash_flag, cutoff_flag])
    return Result(
        headers,
        rows,
        {
            "hash_only": scoring.detection_rates(hash_rows),
            "early_cutoff": scoring.detection_rates(cutoff_rows),
        },
    )


def _intersects(b: dict, box: dict) -> bool:
    return (
        b["x"] < box["x"] + box["width"]
        and box["x"] < b["x"] + b["width"]
        and b["y"] < box["y"] + box["height"]
        and box["y"] < b["y"] + b["height"]
    )


def run_diagram(dataset: Dataset, reader: Reader | None = None, **_: Any) -> Result:
    """F1 of diagram nodes and edges. The reader needs an optional read_diagram(page)."""
    headers = ["page", "node P", "node R", "node F1", "edge P", "edge R", "edge F1"]
    read = getattr(reader, "read_diagram", None)
    if read is None:
        return Result(headers, [], {"skipped": "reader has no read_diagram(page); nothing scored"})
    rows: list[list[Any]] = []
    for page in dataset.pages:
        if not page.diagram:
            continue
        nodes, edges = read(page)
        s = scoring.diagram_f1(nodes, edges, page.diagram["nodes"], page.diagram["edges"])
        rows.append(
            [
                page.id,
                *(s[k] for k in ("node_p", "node_r", "node_f1", "edge_p", "edge_r", "edge_f1")),
            ]
        )
    return Result(headers, rows, {})


EXPERIMENTS = {
    "transcribe": run_transcribe,
    "chunks": run_chunks,
    "stale": run_stale,
    "diagram": run_diagram,
}
