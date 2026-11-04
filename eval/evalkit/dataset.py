"""Dataset loader and validator (format: eval/data/FORMAT.md)."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BOX_KEYS = ("x", "y", "width", "height")
EDIT_OPS = ("add", "delete", "translate", "redraw")
_OP_FIELDS = {
    "add": ("elements",),
    "delete": ("ids",),
    "translate": ("ids", "dx", "dy"),
    "redraw": ("ids", "id_suffix"),
}


class DatasetError(ValueError):
    pass


@dataclass(frozen=True)
class Chunk:
    id: str
    box: dict[str, float]
    kind: str
    text: str
    latex: str | None = None


@dataclass(frozen=True)
class Edit:
    id: str
    type: str
    chunk: str
    meaning_changed: bool
    ops: list[dict[str, Any]]
    text_after: str


@dataclass(frozen=True)
class Page:
    id: str
    kind: str
    synthetic: bool
    elements: list[dict[str, Any]]
    chunks: list[Chunk]
    diagram: dict[str, Any] | None
    edits: list[Edit]
    png: bytes | None = None


@dataclass(frozen=True)
class Dataset:
    name: str
    synthetic: bool
    test_pages_only: bool
    pages: list[Page]


def _need(obj: dict, key: str, where: str) -> Any:
    if not isinstance(obj, dict) or key not in obj:
        raise DatasetError(f"{where}: missing '{key}'")
    return obj[key]


def _load_json(path: Path, where: str) -> Any:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        raise DatasetError(f"{where}: missing file {path.name}") from None


def _load_chunk(raw: dict, where: str) -> Chunk:
    cid = _need(raw, "id", where)
    box = _need(raw, "box", f"{where} chunk {cid}")
    for key in BOX_KEYS:
        if not isinstance(_need(box, key, f"{where} chunk {cid} box"), int | float):
            raise DatasetError(f"{where} chunk {cid} box: '{key}' is not a number")
    return Chunk(
        id=cid,
        box={k: box[k] for k in BOX_KEYS},
        kind=_need(raw, "kind", f"{where} chunk {cid}"),
        text=_need(raw, "text", f"{where} chunk {cid}"),
        latex=raw.get("latex"),
    )


def _load_edit(raw: dict, chunk_ids: set[str], where: str) -> Edit:
    eid = _need(raw, "id", where)
    here = f"{where} edit {eid}"
    chunk = _need(raw, "chunk", here)
    if chunk not in chunk_ids:
        raise DatasetError(f"{here}: chunk '{chunk}' does not exist")
    ops = _need(raw, "ops", here)
    for op in ops:
        name = _need(op, "op", here)
        if name not in EDIT_OPS:
            raise DatasetError(f"{here}: unknown op '{name}'")
        for key in _OP_FIELDS[name]:
            _need(op, key, f"{here} op {name}")
    return Edit(
        id=eid,
        type=_need(raw, "type", here),
        chunk=chunk,
        meaning_changed=bool(_need(raw, "meaning_changed", here)),
        ops=ops,
        text_after=_need(raw, "text_after", here),
    )


def _load_page(root: Path, page_id: str, set_synthetic: bool) -> Page:
    where = f"page {page_id}"
    folder = root / page_id
    truth = _load_json(folder / "truth.json", where)
    synthetic = bool(_need(truth, "synthetic", where))
    if synthetic != set_synthetic:
        raise DatasetError(f"{where}: field 'synthetic' disagrees with the manifest")
    scene = _load_json(folder / "scene.json", where)
    chunks = [_load_chunk(c, where) for c in _need(truth, "chunks", where)]
    ids = [c.id for c in chunks]
    if len(set(ids)) != len(ids):
        raise DatasetError(f"{where}: duplicate chunk ids")
    edits = [_load_edit(e, set(ids), where) for e in truth.get("edits", [])]
    png_path = folder / "page.png"
    return Page(
        id=page_id,
        kind=_need(truth, "kind", where),
        synthetic=synthetic,
        elements=_need(scene, "elements", where),
        chunks=chunks,
        diagram=truth.get("diagram"),
        edits=edits,
        png=png_path.read_bytes() if png_path.exists() else None,
    )


def load_dataset(root: Path) -> Dataset:
    root = Path(root)
    manifest = _load_json(root / "manifest.json", "manifest")
    synthetic = bool(_need(manifest, "synthetic", "manifest"))
    pages = []
    for page_id in _need(manifest, "pages", "manifest"):
        if not (root / page_id).is_dir():
            raise DatasetError(f"manifest: page '{page_id}' has no folder")
        pages.append(_load_page(root, page_id, synthetic))
    return Dataset(
        name=manifest.get("set", root.name),
        synthetic=synthetic,
        test_pages_only=bool(manifest.get("test_pages_only", False)),
        pages=pages,
    )
