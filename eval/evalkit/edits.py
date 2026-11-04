"""Apply a scripted edit (four low-level ops) to a list of Excalidraw elements."""

import copy
from typing import Any

from .dataset import Edit


def _by_id(elements: list[dict[str, Any]], ids: list[str]) -> list[dict[str, Any]]:
    index = {e["id"]: e for e in elements}
    missing = [i for i in ids if i not in index]
    if missing:
        raise KeyError(f"unknown element ids: {missing}")
    return [index[i] for i in ids]


def apply_edit(elements: list[dict[str, Any]], edit: Edit) -> list[dict[str, Any]]:
    """Return a new list; the input is never mutated."""
    out = copy.deepcopy(elements)
    for op in edit.ops:
        name = op["op"]
        if name == "add":
            out.extend(copy.deepcopy(op["elements"]))
        elif name == "delete":
            for e in _by_id(out, op["ids"]):
                e["isDeleted"] = True
        elif name == "translate":
            for e in _by_id(out, op["ids"]):
                e["x"] += op["dx"]
                e["y"] += op["dy"]
        elif name == "redraw":
            originals = _by_id(out, op["ids"])
            copies = []
            for e in originals:
                clone = copy.deepcopy(e)
                clone["id"] = e["id"] + op["id_suffix"]
                e["isDeleted"] = True
                copies.append(clone)
            out.extend(copies)
        else:
            raise ValueError(f"unknown op {name}")
    return out
