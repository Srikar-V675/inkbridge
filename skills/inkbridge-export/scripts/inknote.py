#!/usr/bin/env python3
"""Mechanics of an Inkbridge vault note (INK-037, docs/vault-note-format.md, decision 0021).

Standard library only, so the skill runs anywhere Python 3.11+ does. The agent writes the words
of each block; this script builds, checks and updates the note around them so that text outside
the markers, and every block that did not change, stays byte-identical.

    inknote.py canvas   [--api URL] [--document ID]            # GET /documents/{id}/chunks
    inknote.py crops    --vault DIR CANVAS_JSON [--api URL] [--ids ID ...]
    inknote.py new      --title T CANVAS_JSON BODIES_JSON [--vault DIR] [--out NOTE]
    inknote.py validate NOTE
    inknote.py sync     NOTE [--api URL] [--wait S]             # POST check_sync, prints result
    inknote.py plan     NOTE SYNC_JSON                          # which blocks need new words
    inknote.py apply    NOTE SYNC_JSON CANVAS_JSON BODIES_JSON [--vault DIR] [--recreate] [--out NOTE]

BODIES_JSON maps chunk id -> markdown for the block (no markers). The API is never asked to
write anything except check_sync's recognition cache; the note is written by this script, i.e.
by the agent's own file access.
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_API = "http://127.0.0.1:8000"
ATTACHMENTS = "attachments/inkbridge"
CLOSE = "<!-- /ink -->"
OPEN_RE = re.compile(r"^<!-- ink:(?P<id>[A-Za-z0-9_-]{1,64}) hash:(?P<hash>[0-9a-f]{64}) -->$")
ANY_MARKER_RE = re.compile(r"^<!-- (?:ink:|/ink)")
HEADING_RE = re.compile(r"^#{1,6}\s+(?P<title>.+?)\s*#*\s*$")
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
ENTRY_KEYS = {"id", "hash", "reading", "section", "status", "successor"}
STATUSES = {"removed", "merged"}
REMOVED_FLAG = "> [!warning] Inkbridge: this ink is no longer on the canvas."
MERGED_FLAG = "> [!warning] Inkbridge: this ink was merged into another block of this note ({id})."


class NoteError(ValueError):
    """The note does not follow docs/vault-note-format.md."""


# -- parsing -----------------------------------------------------------------------------------


@dataclass
class Block:
    id: str
    hash: str
    start: int  # offset of the opening marker
    end: int  # offset just after the closing marker (and its newline, if any)
    body_start: int  # just after the opening marker's newline
    body_end: int  # offset of the closing marker


@dataclass
class Note:
    text: str
    meta: dict
    meta_span: tuple[int, int]  # the `inkbridge: ...` line without its newline
    body_offset: int  # where the body (after the frontmatter) starts
    blocks: list[Block]

    def entry(self, chunk_id: str) -> dict | None:
        return next((e for e in self.meta["chunks"] if e["id"] == chunk_id), None)

    def block(self, chunk_id: str) -> Block | None:
        return next((b for b in self.blocks if b.id == chunk_id), None)


def _lines(text: str, start: int = 0):
    """(offset, line without newline, offset after the line) for each line from start."""
    pos = start
    while pos < len(text):
        nl = text.find("\n", pos)
        end = len(text) if nl < 0 else nl + 1
        yield pos, text[pos : nl if nl >= 0 else len(text)], end
        pos = end


def parse(text: str) -> Note:
    if "\r" in text:
        raise NoteError(
            "the note has CRLF line endings; convert it to LF first (nothing was changed)"
        )
    if not text.startswith("---\n"):
        raise NoteError("the note must start with a '---' frontmatter block")
    meta_span = None
    body_offset = None
    for off, line, end in _lines(text, 4):
        if line == "---":
            body_offset = end
            break
        if line.startswith("inkbridge:"):
            if meta_span is not None:
                raise NoteError("more than one 'inkbridge:' line in the frontmatter")
            meta_span = (off, off + len(line))
    if body_offset is None:
        raise NoteError("the frontmatter is not closed with '---'")
    if meta_span is None:
        raise NoteError("no 'inkbridge:' line in the frontmatter")
    raw = text[meta_span[0] + len("inkbridge:") : meta_span[1]].strip()
    try:
        meta = json.loads(raw)
    except ValueError as e:
        raise NoteError(f"the 'inkbridge:' value is not a JSON object: {e}") from None
    if not isinstance(meta, dict) or not isinstance(meta.get("chunks"), list):
        raise NoteError("'inkbridge' must be an object with a 'chunks' list")
    blocks: list[Block] = []
    open_: tuple[str, str, int, int] | None = None
    for off, line, end in _lines(text, body_offset):
        m = OPEN_RE.match(line)
        if m:
            if open_:
                raise NoteError(f"block {open_[0]} is not closed before block {m['id']} opens")
            open_ = (m["id"], m["hash"], off, end)
        elif line == CLOSE:
            if not open_:
                raise NoteError("a closing '<!-- /ink -->' has no opening marker")
            blocks.append(Block(open_[0], open_[1], open_[2], end, open_[3], off))
            open_ = None
        elif ANY_MARKER_RE.match(line):
            raise NoteError(f"malformed ink marker: {line!r}")
    if open_:
        raise NoteError(f"block {open_[0]} is never closed")
    return Note(text, meta, meta_span, body_offset, blocks)


# -- validation --------------------------------------------------------------------------------


def validate(text: str) -> list[str]:
    """Every way the note breaks docs/vault-note-format.md; an empty list means it is valid."""
    try:
        note = parse(text)
    except NoteError as e:
        return [str(e)]
    errors = []
    meta = note.meta
    extra = set(meta) - {"canvas", "exported", "chunks"}
    if extra:
        errors.append(f"unknown inkbridge keys: {sorted(extra)}")
    if not isinstance(meta.get("canvas"), str) or not meta["canvas"]:
        errors.append("inkbridge.canvas must be a non-empty string")
    try:
        datetime.fromisoformat(meta.get("exported", ""))
    except (TypeError, ValueError):
        errors.append("inkbridge.exported must be an ISO-8601 timestamp")
    seen: set[str] = set()
    for i, e in enumerate(meta["chunks"]):
        where = f"chunks[{i}]"
        if not isinstance(e, dict):
            errors.append(f"{where} must be an object")
            continue
        if set(e) - ENTRY_KEYS:
            errors.append(f"{where}: unknown keys {sorted(set(e) - ENTRY_KEYS)}")
        cid = e.get("id")
        if not isinstance(cid, str) or not cid:
            errors.append(f"{where}.id must be a non-empty string")
        elif cid in seen:
            errors.append(f"{where}.id {cid} is listed twice")
        else:
            seen.add(cid)
        if not isinstance(e.get("hash"), str) or not HASH_RE.match(e["hash"]):
            errors.append(f"{where}.hash must be a 64-hex content hash")
        reading = e.get("reading")
        if reading is not None and not (isinstance(reading, str) and HASH_RE.match(reading)):
            errors.append(f"{where}.reading must be a 64-hex reading hash or null")
        if e.get("section") is not None and not isinstance(e["section"], str):
            errors.append(f"{where}.section must be a string or null")
        if "status" in e and e["status"] not in STATUSES:
            errors.append(f"{where}.status must be one of {sorted(STATUSES)}")
        if e.get("status") == "merged" and not isinstance(e.get("successor"), str):
            errors.append(f"{where}: a merged chunk needs its successor id")
    marked: set[str] = set()
    for b in note.blocks:
        if b.id in marked:
            errors.append(f"block {b.id} appears twice")
        marked.add(b.id)
        e = note.entry(b.id)
        if e is None:
            errors.append(f"block {b.id} has no entry in inkbridge.chunks")
        elif e.get("hash") != b.hash:
            errors.append(f"block {b.id}: marker hash differs from inkbridge.chunks")
    return errors


# -- building blocks ---------------------------------------------------------------------------


def crop_path(chunk_id: str, content_hash: str) -> str:
    """The vault-relative path of a chunk's crop (one file per id and ink version)."""
    return f"{ATTACHMENTS}/{chunk_id}-{content_hash[:12]}.png"


ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _check_chunk_fields(chunk: dict) -> None:
    """Ids and hashes from the canvas end up in file names and marker lines: keep them plain."""
    cid, h = chunk.get("id"), chunk.get("content_hash")
    if not isinstance(cid, str) or not ID_RE.match(cid):
        raise NoteError(f"unsafe chunk id {cid!r}")
    if not isinstance(h, str) or not HASH_RE.match(h):
        raise NoteError(f"chunk {cid}: content_hash is not a 64-hex hash")
    link = chunk.get("deep_link")
    if link is not None and (not isinstance(link, str) or re.search(r"[\s<>()]", link)):
        raise NoteError(f"chunk {cid}: unsafe deep link {link!r}")


def render_block(chunk: dict, body: str, vault: Path | None = None) -> str:
    """One marker-bounded block: the agent's words, a deep link, a folded crop preview."""
    cid, h = chunk["id"], chunk["content_hash"]
    _check_chunk_fields(chunk)
    for line in body.splitlines():
        if ANY_MARKER_RE.match(line.strip()) or "<!-- ink:" in line or "<!-- /ink" in line:
            raise NoteError(f"the words for chunk {cid} contain an ink marker: {line!r}")
    parts = [f"<!-- ink:{cid} hash:{h} -->", body.strip("\n"), ""]
    if chunk.get("deep_link"):
        parts.append(f"[Open in Inkbridge]({chunk['deep_link']})")
    crop = crop_path(cid, h)
    if vault is None or (vault / crop).is_file():
        parts += ["> [!ink]- Source ink", f"> ![[{crop}]]"]
    parts.append(CLOSE)
    return "\n".join(parts) + "\n"


def _section(text: str, body_offset: int, block_start: int, block_end: int) -> str | None:
    """The heading a block sits under: its own first heading, else the nearest one above it."""
    for _, line, _ in _lines(text[block_start:block_end]):
        m = HEADING_RE.match(line)
        if m:
            return m["title"]
    title = None
    for off, line, _ in _lines(text, body_offset):
        if off >= block_start:
            break
        m = HEADING_RE.match(line)
        if m:
            title = m["title"]
    return title


def _meta_line(meta: dict) -> str:
    return "inkbridge: " + json.dumps(meta, ensure_ascii=False, separators=(", ", ": "))


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _entry(chunk: dict, section: str | None) -> dict:
    return {
        "id": chunk["id"],
        "hash": chunk["content_hash"],
        "reading": chunk.get("text_hash"),
        "section": section,
    }


def _checked(text: str) -> str:
    """Never hand back a note that breaks the format."""
    errors = validate(text)
    if errors:
        raise NoteError("the result would not be a valid note: " + "; ".join(errors))
    return text


def _refresh_sections(text: str) -> str:
    """Recompute each entry's section from where its block now sits (frontmatter line only)."""
    note = parse(text)
    for b in note.blocks:
        e = note.entry(b.id)
        if e is not None:
            e["section"] = _section(text, note.body_offset, b.start, b.end)
    return _replace_meta(text, note)


def _replace_meta(text: str, note: Note) -> str:
    a, b = note.meta_span
    return text[:a] + _meta_line(note.meta) + text[b:]


def new_note(canvas: dict, title: str, bodies: dict[str, str], vault: Path | None = None) -> str:
    """A fresh note with one block per chunk that has a body, in the canvas's reading order."""
    chunks = [c for c in canvas["chunks"] if c["id"] in bodies and c.get("status") == "active"]
    missing = set(bodies) - {c["id"] for c in chunks}
    if missing:
        raise NoteError(f"bodies for chunks that are not active on the canvas: {sorted(missing)}")
    meta = {"canvas": canvas["document"], "exported": _now(), "chunks": []}
    meta["chunks"] = [_entry(c, None) for c in chunks]
    if "\n" in title or "\r" in title:
        raise NoteError("the title must be one line")
    head = f"---\n{_meta_line(meta)}\n---\n# {title}\n\n"
    text = head + "\n".join(render_block(c, bodies[c["id"]], vault) for c in chunks)
    return _checked(_refresh_sections(text))


# -- re-export ---------------------------------------------------------------------------------


def plan(text: str, sync: dict) -> dict:
    """What a re-export will do, and which chunk ids need new words from the agent."""
    note = parse(text)
    has_block = {b.id for b in note.blocks}
    out: dict[str, list] = {
        "unchanged": list(sync.get("fresh", [])),
        "refresh_hash": [i["id"] for i in sync.get("fresh_after_reread", [])],
        "rewrite": [],
        "merged": [],
        "flag_removed": [],
        "append": [],
        "user_deleted": [],
        "needs_body": [],
    }
    for item in sync.get("changed", []):
        if item["id"] in has_block:
            out["rewrite"].append(item["id"])
            out["needs_body"].append(item["id"])
        else:
            out["user_deleted"].append(item["id"])
    taken = set(has_block)
    for item in sync.get("replaced", []):
        if item["id"] not in has_block:
            out["user_deleted"].append(item["id"])
        elif item["successor"] in taken:
            out["merged"].append(item["id"])
        else:
            taken.add(item["successor"])
            out["rewrite"].append(item["id"])
            out["needs_body"].append(item["successor"])
    for cid in sync.get("removed", []):
        e = note.entry(cid)
        if cid in has_block and not (e and e.get("status")):
            out["flag_removed"].append(cid)
    for item in sync.get("new", []):
        out["append"].append(item["id"])
        out["needs_body"].append(item["id"])
    return out


def _sync_chunks(note: Note) -> list[dict]:
    """The frontmatter entries check_sync should be asked about (flagged ones are settled)."""
    return [
        {"id": e["id"], "hash": e["hash"], "reading": e.get("reading")}
        for e in note.meta["chunks"]
        if not e.get("status")
    ]


def apply(
    text: str,
    sync: dict,
    canvas: dict,
    bodies: dict[str, str],
    vault: Path | None = None,
    recreate: bool = False,
) -> str:
    """Apply a check_sync result. Fresh blocks and all text outside rewritten blocks are kept
    byte for byte; with nothing to do the note is returned unchanged."""
    note = parse(text)
    by_id = {c["id"]: c for c in canvas["chunks"]}
    todo = plan(text, sync)
    if recreate:
        todo["needs_body"] += todo["user_deleted"]
    missing = [i for i in todo["needs_body"] if i not in bodies]
    if missing:
        raise NoteError(f"no new words given for chunks {missing} (see `plan`)")

    def chunk(cid: str, fallback: dict) -> dict:
        c = dict(by_id.get(cid) or {})
        c.setdefault("id", cid)
        c.setdefault("content_hash", fallback["hash"])
        c.setdefault("text_hash", fallback.get("reading"))
        return c

    edits: list[tuple[int, int, str]] = []  # (start, end, replacement) in the original text
    changed_meta = False
    blocks = {b.id: b for b in note.blocks}
    rewritten = set(todo["rewrite"])  # a rewrite wins over a hash refresh or a flag on that block
    for item in sync.get("changed", []):
        if item["id"] in todo["rewrite"]:
            b, e = blocks[item["id"]], note.entry(item["id"])
            c = chunk(item["id"], item)
            edits.append((b.start, b.end, render_block(c, bodies[item["id"]], vault)))
            e.update(hash=item["hash"], reading=item["reading"])
            changed_meta = True
    for item in sync.get("replaced", []):
        b, e = blocks.get(item["id"]), note.entry(item["id"])
        if item["id"] in todo["rewrite"]:
            s = {"hash": item["hash"], "reading": item["reading"]}
            c = chunk(item["successor"], s)
            edits.append((b.start, b.end, render_block(c, bodies[item["successor"]], vault)))
            e.clear()
            e.update(id=item["successor"], hash=item["hash"], reading=item["reading"])
            changed_meta = True
        elif item["id"] in todo["merged"] and item["id"] not in rewritten:
            flag = MERGED_FLAG.format(id=item["successor"])
            edits.append((b.body_start, b.body_start, flag + "\n\n"))
            e.update(status="merged", successor=item["successor"])
            changed_meta = True
    for item in sync.get("fresh_after_reread", []):
        e, b = note.entry(item["id"]), blocks.get(item["id"])
        if e is None or item["id"] in rewritten:
            continue
        e["hash"], e["reading"] = item["hash"], item["reading"]
        changed_meta = True
        if b is not None:  # only the marker line changes; the words stay
            line_end = b.body_start - 1 if text[b.body_start - 1] == "\n" else b.body_start
            edits.append((b.start, line_end, f"<!-- ink:{b.id} hash:{item['hash']} -->"))
    for cid in todo["flag_removed"]:
        if cid in rewritten:
            continue
        b = blocks[cid]
        edits.append((b.body_start, b.body_start, REMOVED_FLAG + "\n\n"))
        note.entry(cid)["status"] = "removed"
        changed_meta = True
    appended = []
    for item in sync.get("new", []):
        c = chunk(item["id"], item)
        appended.append(render_block(c, bodies[item["id"]], vault))
        note.meta["chunks"].append(_entry(c, None))
        changed_meta = True
    if recreate:
        for cid in todo["user_deleted"]:
            src = next(
                (i for k in ("changed", "replaced") for i in sync.get(k, []) if i["id"] == cid),
                None,
            )
            target = src.get("successor", cid) if src else cid
            c = chunk(target, src or {"hash": note.entry(cid)["hash"]})
            appended.append(render_block(c, bodies[cid], vault))
            e = note.entry(cid)
            e.clear()
            e.update(_entry(c, None))
            changed_meta = True
    if not changed_meta:
        return text

    note.meta["exported"] = _now()
    edits.append((note.meta_span[0], note.meta_span[1], _meta_line(note.meta)))
    ordered = sorted(edits, key=lambda x: x[0])
    for (_, e1, _), (s2, _, _) in itertools.pairwise(ordered):
        if s2 < e1:
            raise NoteError("the sync result touches one block twice; nothing was changed")
    out = text
    for start, end, repl in reversed(ordered):
        out = out[:start] + repl + out[end:]
    if appended:
        if not out.endswith("\n"):
            out += "\n"
        out += "\n" + "\n".join(appended)
    return _checked(_refresh_sections(out))


# -- HTTP (read-only except check_sync's recognition cache) -------------------------------------


def _api(args) -> str:
    return (args.api or os.environ.get("INKBRIDGE_API_URL") or DEFAULT_API).rstrip("/")


def _request(url: str, body: dict | None = None, timeout: float = 60) -> bytes:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def fetch_canvas(api: str, document_id: str) -> dict:
    doc = urllib.parse.quote(document_id, safe="")
    return json.loads(_request(f"{api}/documents/{doc}/chunks"))


def fetch_crops(api: str, vault: Path, canvas: dict, ids: list[str] | None = None) -> dict:
    """Save each chunk's full-size crop into the vault; returns {saved, skipped, failed}."""
    out: dict[str, list] = {"saved": [], "skipped": [], "failed": []}
    for c in canvas["chunks"]:
        if c.get("status") != "active" or (ids and c["id"] not in ids):
            continue
        target = vault / crop_path(c["id"], c["content_hash"])
        if target.is_file():
            out["skipped"].append(c["id"])
            continue
        try:
            png = _request(f"{api}/regions/{urllib.parse.quote(c['id'], safe='')}/png")
        except (urllib.error.URLError, OSError) as e:
            out["failed"].append({"id": c["id"], "error": str(e)})
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        _atomic(target, png)
        out["saved"].append(c["id"])
    return out


def check_sync(api: str, text: str, wait_s: float = 15) -> dict:
    note = parse(text)
    doc = urllib.parse.quote(note.meta["canvas"], safe="")
    body = {"chunks": _sync_chunks(note), "wait_s": wait_s}
    return json.loads(_request(f"{api}/documents/{doc}/check_sync", body, timeout=wait_s + 30))


# -- CLI ---------------------------------------------------------------------------------------


def _load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _read(path: str) -> str:
    with open(path, encoding="utf-8", newline="") as f:  # no newline translation
        return f.read()


def _atomic(path: Path, data: bytes) -> None:
    """Write via a temp file and rename, so an interruption never leaves a truncated file."""
    tmp = path.with_name(f".{path.name}.inknote-tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def _write(text: str, out: str | None, default: str | None = None) -> None:
    target = out or default
    if target:
        path = Path(target)
        if path.is_file() and _read(target) == text:
            return  # nothing changed: leave the file (and its mtime) alone
        _atomic(path, text.encode("utf-8"))
    else:
        sys.stdout.write(text)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="inknote", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("canvas")
    s.add_argument("--api")
    s.add_argument("--document", default=os.environ.get("INKBRIDGE_DOCUMENT", "default"))
    s = sub.add_parser("crops")
    s.add_argument("canvas")
    s.add_argument("--vault", required=True)
    s.add_argument("--api")
    s.add_argument("--ids", nargs="*")
    s = sub.add_parser("new")
    s.add_argument("canvas")
    s.add_argument("bodies")
    s.add_argument("--title", required=True)
    s.add_argument("--vault")
    s.add_argument("--out")
    s = sub.add_parser("validate")
    s.add_argument("note")
    s = sub.add_parser("sync")
    s.add_argument("note")
    s.add_argument("--api")
    s.add_argument("--wait", type=float, default=15, help="seconds, 0..30")
    s = sub.add_parser("plan")
    s.add_argument("note")
    s.add_argument("sync")
    s = sub.add_parser("apply")
    s.add_argument("note")
    s.add_argument("sync")
    s.add_argument("canvas")
    s.add_argument("bodies")
    s.add_argument("--vault")
    s.add_argument("--recreate", action="store_true")
    s.add_argument("--out")
    a = p.parse_args(argv)
    try:
        if a.cmd == "canvas":
            print(json.dumps(fetch_canvas(_api(a), a.document), indent=2, ensure_ascii=False))
        elif a.cmd == "crops":
            result = fetch_crops(_api(a), Path(a.vault), _load(a.canvas), a.ids)
            print(json.dumps(result, indent=2))
            return 1 if result["failed"] else 0
        elif a.cmd == "new":
            vault = Path(a.vault) if a.vault else None
            _write(new_note(_load(a.canvas), a.title, _load(a.bodies), vault), a.out)
        elif a.cmd == "validate":
            errors = validate(_read(a.note))
            print(json.dumps({"valid": not errors, "errors": errors}, indent=2))
            return 1 if errors else 0
        elif a.cmd == "sync":
            text = _read(a.note)
            print(
                json.dumps(
                    check_sync(_api(a), text, min(max(a.wait, 0), 30)), indent=2, ensure_ascii=False
                )
            )
        elif a.cmd == "plan":
            text = _read(a.note)
            print(json.dumps(plan(text, _load(a.sync)), indent=2))
        elif a.cmd == "apply":
            text = _read(a.note)
            vault = Path(a.vault) if a.vault else None
            out = apply(text, _load(a.sync), _load(a.canvas), _load(a.bodies), vault, a.recreate)
            _write(out, a.out, a.note)
    except NoteError as e:
        print(f"inknote: {e}", file=sys.stderr)
        return 2
    except urllib.error.HTTPError as e:
        detail = e.read()[:300].decode("utf-8", "replace")
        print(f"inknote: the API answered {e.code} for {e.url}: {detail}", file=sys.stderr)
        return 3
    except (urllib.error.URLError, OSError) as e:
        print(f"inknote: cannot reach the Inkbridge API or read a file: {e}", file=sys.stderr)
        return 3
    except (ValueError, KeyError, TypeError) as e:
        print(f"inknote: malformed input: {e!r}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
