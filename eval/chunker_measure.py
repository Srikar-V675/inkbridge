"""Chunk counts for private scene dumps (INK-195). Never commit the dumps.

Run: cd server && uv run python ../eval/chunker_measure.py /tmp/claude-1000/scene-*.json
"""

import collections
import json
import sys

from inkbridge.canvas.chunker import ChunkerConfig, chunk_scene
from inkbridge.canvas.strokes import analyse


def measure(path: str) -> str:
    els = [e for e in json.load(open(path))["elements"] if not e.get("isDeleted")]
    k = analyse(els)
    v1 = chunk_scene(els, ChunkerConfig())
    v2 = chunk_scene(els, ChunkerConfig.v2())
    top = sorted((len(c) for c in v2.chunks), reverse=True)[:5]
    return (
        f"{path.rsplit('scene-', 1)[-1]} T={k.scale:.1f} {dict(collections.Counter(k.kinds.values()))} "
        f"v1={len(v1.chunks)} v2={len(v2.chunks)} v2_connector_chunks={sum(v2.connector)} top5={top}"
    )


if __name__ == "__main__":
    for p in sys.argv[1:]:
        print(measure(p))
