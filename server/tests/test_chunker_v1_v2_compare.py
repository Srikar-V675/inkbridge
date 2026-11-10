"""INK-186: v1 against v2 on the synthetic real-scale scene. Records numbers, does not bless them."""

import sys
from pathlib import Path

from inkbridge import config
from inkbridge.canvas.chunker import ChunkerConfig, chunk_scene

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "eval" / "fixtures"))

import make_real_scale

SCENE = [e for e in make_real_scale.build() if not e["isDeleted"]]


def subset(prefix):
    return [e for e in SCENE if e["id"].startswith(prefix)]


def test_diagram_chunk_counts_are_recorded_not_blessed():
    els = subset("dg")
    v1 = chunk_scene(els, ChunkerConfig()).chunks
    v2 = chunk_scene(els, ChunkerConfig.v2()).chunks
    # The fixture arrows (200) are shorter than its boxes (700), so by the tick rule (techref 5.x)
    # they merge their boxes in both versions. The shape rule is pinned in test_chunker_v2.py
    # (flowchart tests); here the numbers are only recorded: measured 1 and 1.
    assert len(v1) == 1
    assert len(v2) >= 1


def test_handwriting_chunk_counts_are_recorded_not_blessed():
    els = subset("t10")
    assert len(chunk_scene(els, ChunkerConfig()).chunks) <= 6
    # Measured 329 on placeholder stroke sizes (decision 0106); retune with E5, do not pin.
    assert len(chunk_scene(els, ChunkerConfig.v2()).chunks) >= 1


def test_default_chunker_is_v1(monkeypatch):
    monkeypatch.delenv("INKBRIDGE_CHUNKER", raising=False)
    assert config.chunker() == "v1"  # flipping the default is a decision (0106)
