#!/usr/bin/env python3
"""Mechanics of an Inkbridge vault note (INK-037, docs/vault-note-format.md, decision 0021).

Standard library only, so the skill runs anywhere Python 3.11+ does. The agent writes the words
of each block; this script builds, checks and updates the note around them so that text outside
the markers, and every block that did not change, stays byte-identical.

    inknote.py canvas   [--api URL] [--document ID]            # GET /documents/{id}/chunks
    inknote.py crops    --vault DIR CANVAS_JSON [--api URL] [--ids ID ...]
    inknote.py new      --title T CANVAS_JSON BODIES_JSON [--vault DIR] [--out NOTE]
                        [--index "[[X.base]]"] [--relates "[[A]]" ...]   # refuses an existing NOTE
    inknote.py validate NOTE [--strict]                      # --strict: the vault frontmatter too
    inknote.py sync     NOTE [--api URL] [--wait S]             # POST check_sync, prints result
    inknote.py plan     NOTE SYNC_JSON                          # which blocks need new words
    inknote.py apply    NOTE SYNC_JSON CANVAS_JSON BODIES_JSON [--vault DIR] [--recreate] [--out NOTE]
    inknote.py learn    NOTE --vault DIR     # record the user's edits, propose style rules (INK-142)
    inknote.py rules    --vault DIR          # approved style rules as JSON (INK-142)

BODIES_JSON maps chunk id -> markdown for the block (no markers). The API is never asked to
write anything except check_sync's recognition cache; the note is written by this script, i.e.
by the agent's own file access.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_API = "http://127.0.0.1:8000"
ATTACHMENTS = "content/raw/attachments/inkbridge"
CLOSE = "<!-- /ink -->"
OPEN_RE = re.compile(r"^<!-- ink:(?P<id>[A-Za-z0-9_-]{1,64}) hash:(?P<hash>[0-9a-f]{64}) -->$")
ANY_MARKER_RE = re.compile(r"^<!-- (?:ink:|/ink)")
HEADING_RE = re.compile(r"^#{1,6}\s+(?P<title>.+?)\s*#*\s*$")
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
ENTRY_KEYS = {"id", "hash", "reading", "section", "status", "successor", "body"}
STATUSES = {"removed", "merged"}
REMOVED_FLAG = "> [!warning] Inkbridge: this ink is no longer on the canvas."
MERGED_FLAG = "> [!warning] Inkbridge: this ink was merged into another block of this note ({id})."
MANAGED_RE = re.compile(r"> \[!(?:warning|conflict)\] Inkbridge")
BANNED_RE = re.compile("[–—·←-⇿☀-➿\U0001f300-\U0001faff]")
INDEX_RE = re.compile(r'\[\[[^\]\n"]+\]\]')
FUTURE_AGENT = (
    "> [!info]- For future agent\n"
    "> Provenance note for an Inkbridge canvas. Text between ink markers is managed by the\n"
    "> inkbridge-export skill and synced with check_sync. Text outside the markers is the\n"
    "> user's and is never changed.\n"
)
FORMATS = {"course", "book", "video", "reference"}


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


def _vault_errors(text: str) -> list[str]:
    """The vault frontmatter and callout that `new` writes (flat YAML, as written, before
    Obsidian reformats properties)."""
    head, sep, after = text[4:].partition("\n---\n")
    if not sep:
        return ["the frontmatter is not closed with '---'"]
    lines = head.splitlines()
    errors = [
        f"frontmatter needs the line {want!r}"
        for want in ("tags: [library]", "type: library", "ai-first: true")
        if want not in lines
    ]
    if not {"publish: false", "publish: true"} & set(lines):
        errors.append("frontmatter needs 'publish: false' or 'publish: true'")
    if not any(ln.startswith("format: ") and ln[8:] in FORMATS for ln in lines):
        errors.append(f"frontmatter needs 'format: ' one of {sorted(FORMATS)}")
    if not any(re.fullmatch(r"date: \d{4}-\d{2}-\d{2}", ln) for ln in lines):
        errors.append("frontmatter needs a 'date: YYYY-MM-DD' line")
    for ln in lines:
        if ln.startswith("index:") and not re.fullmatch(r'index: "\[\[[^\]\n"]+\]\]"', ln):
            errors.append(f'index must look like index: "[[Name.base]]", got {ln!r}')
    if not after.startswith("> [!info]- For future agent"):
        errors.append("the '> [!info]- For future agent' callout must follow the frontmatter")
    return errors


def validate(text: str, strict: bool = False) -> list[str]:
    """Every way the note breaks docs/vault-note-format.md; an empty list means it is valid.
    `strict` also checks the vault frontmatter `new` writes; plain validation stays lenient so
    notes exported before INK-106 can still be re-exported."""
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
        if "body" in e and not (isinstance(e["body"], str) and HASH_RE.match(e["body"])):
            errors.append(f"{where}.body must be a 64-hex hash")
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
    if strict:
        errors += _vault_errors(text)
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


def _check_words(label: str, words: str) -> None:
    """Notes follow the vault's writing style (_CLAUDE.md): no em/en dashes, arrows or emoji."""
    for line in words.splitlines():
        if BANNED_RE.search(line):
            raise NoteError(
                f"{label}: use '-', '->' and commas, not dashes, arrows or emoji: {line!r}"
            )


def _check_markers(cid: str, words: str) -> None:
    for line in words.splitlines():
        if ANY_MARKER_RE.match(line.strip()) or "<!-- ink:" in line or "<!-- /ink" in line:
            raise NoteError(f"the words for chunk {cid} contain an ink marker: {line!r}")


def _managed_prefix_len(interior: str) -> int:
    """Length of the leading Inkbridge-managed callouts (flags, conflict) of a block, each ending
    at its own blank line. Flags are one line; only a conflict callout has `>` continuation lines
    (the quoted new words), so a quote glued under a flag is the user's."""
    lines = interior.splitlines(keepends=True)
    i = 0
    while i < len(lines) and MANAGED_RE.match(lines[i]):
        conflict = lines[i].startswith("> [!conflict]")
        i += 1
        while conflict and i < len(lines) and lines[i].startswith(">"):
            i += 1
        if i < len(lines) and not lines[i].strip():
            i += 1
    return sum(len(x) for x in lines[:i])


def _body_hash(interior: str) -> str:
    """Hash of a block's words as the skill wrote them, ignoring its own callouts on top."""
    return hashlib.sha256(interior[_managed_prefix_len(interior) :].encode()).hexdigest()


def _interior(rendered: str) -> str:
    """The text between the markers of a block from render_block (same as the note's slice)."""
    return rendered.split("\n", 1)[1].removesuffix(CLOSE + "\n")


def render_block(chunk: dict, body: str, vault: Path | None = None) -> str:
    """One marker-bounded block: the agent's words, a deep link, a folded crop preview."""
    cid, h = chunk["id"], chunk["content_hash"]
    _check_chunk_fields(chunk)
    _check_markers(cid, body)
    _check_words(f"chunk {cid}", body)
    parts = [f"<!-- ink:{cid} hash:{h} -->", body.strip("\n"), ""]
    if chunk.get("deep_link"):
        parts.append(f"[Open in Inkbridge]({chunk['deep_link']})")
    crop = crop_path(cid, h)
    if vault is None or (vault / crop).is_file():
        parts += ["> [!ink]- Source ink", f"> ![[{crop}]]"]
    parts.append(CLOSE)
    return "\n".join(parts) + "\n"


CONFLICT_HEAD = (
    "> [!conflict] Inkbridge: the ink changed, but you edited this block, so it was not rewritten."
)


def _edited(text: str, note: Note, cid: str) -> bool:
    """The user may have changed this block since the skill wrote it. Without a stored body hash
    (a note from before INK-106) we cannot tell, so we assume yes: user text is never overwritten."""
    e, b = note.entry(cid), note.block(cid)
    if not (e and b):
        return False
    return "body" not in e or _body_hash(text[b.body_start : b.body_end]) != e["body"]


def _conflict_callout(cid: str, words: str) -> str:
    _check_words(f"chunk {cid}", words)
    _check_markers(cid, words)
    head = [
        CONFLICT_HEAD,
        "> The new reading is below. Merge it by hand, then delete this callout.",
        ">",
    ]
    quoted = [("> " + ln).rstrip() for ln in words.strip("\n").splitlines()]
    return "\n".join(head + quoted) + "\n\n"


def _conflict_edits(text: str, b: Block, new_id: str, new_hash: str, words: str) -> list:
    """New marker line plus the callout on top (replacing an older conflict callout there)."""
    inner = text[b.body_start : b.body_end]
    old = _managed_prefix_len(inner) if inner.startswith(CONFLICT_HEAD) else 0
    return [
        (b.start, b.body_start - 1, f"<!-- ink:{new_id} hash:{new_hash} -->"),
        (b.body_start, b.body_start + old, _conflict_callout(new_id, words)),
    ]


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


def _entry(chunk: dict, section: str | None, rendered: str | None = None) -> dict:
    e = {
        "id": chunk["id"],
        "hash": chunk["content_hash"],
        "reading": chunk.get("text_hash"),
        "section": section,
    }
    if rendered is not None:
        e["body"] = _body_hash(_interior(rendered))
    return e


def _checked(text: str, strict: bool = False) -> str:
    """Never hand back a note that breaks the format."""
    errors = validate(text, strict)
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


def new_note(
    canvas: dict,
    title: str,
    bodies: dict[str, str],
    vault: Path | None = None,
    index: str | None = None,
    relates: tuple | list = (),
    date: str | None = None,
) -> str:
    """A fresh note with one block per chunk that has a body, in the canvas's reading order."""
    chunks = [c for c in canvas["chunks"] if c["id"] in bodies and c.get("status") == "active"]
    missing = set(bodies) - {c["id"] for c in chunks}
    if missing:
        raise NoteError(f"bodies for chunks that are not active on the canvas: {sorted(missing)}")
    if "\n" in title or "\r" in title:
        raise NoteError("the title must be one line")
    _check_words("title", title)
    for v in ([index] if index else []) + list(relates):
        if not INDEX_RE.fullmatch(v):
            raise NoteError(f"{v!r} must be a wikilink like [[Name]]")
    rendered = {c["id"]: render_block(c, bodies[c["id"]], vault) for c in chunks}
    meta = {"canvas": canvas["document"], "exported": _now()}
    meta["chunks"] = [_entry(c, None, rendered[c["id"]]) for c in chunks]
    fm = ["tags: [library]", "type: library", "format: reference"]
    if index:
        fm.append(f"index: {json.dumps(index)}")
    if relates:
        fm.append(f"relates: {json.dumps(list(relates))}")
    today = date or datetime.now().astimezone().date().isoformat()
    fm += ["publish: false", f"date: {today}", "ai-first: true", _meta_line(meta)]
    head = "---\n" + "\n".join(fm) + f"\n---\n{FUTURE_AGENT}\n# {title}\n\n"
    text = head + "\n".join(rendered[c["id"]] for c in chunks)
    return _checked(_refresh_sections(text), strict=True)


# -- re-export ---------------------------------------------------------------------------------


def plan(text: str, sync: dict) -> dict:
    """What a re-export will do, and which chunk ids need new words from the agent."""
    note = parse(text)
    has_block = {b.id for b in note.blocks}
    out: dict[str, list] = {
        "unchanged": list(sync.get("fresh", [])),
        "refresh_hash": [i["id"] for i in sync.get("fresh_after_reread", [])],
        "rewrite": [],
        "conflict": [],
        "merged": [],
        "flag_removed": [],
        "append": [],
        "user_deleted": [],
        "needs_body": [],
    }
    for item in sync.get("changed", []):
        if item["id"] in has_block:
            out["conflict" if _edited(text, note, item["id"]) else "rewrite"].append(item["id"])
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
            out["conflict" if _edited(text, note, item["id"]) else "rewrite"].append(item["id"])
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
    conflicts = set(todo["conflict"])  # edited by the user: new words go in a callout, not over it
    # a rewrite or conflict wins over a hash refresh or a flag on that block
    touched = set(todo["rewrite"]) | conflicts
    for item in sync.get("changed", []):
        if item["id"] in conflicts:
            b, e = blocks[item["id"]], note.entry(item["id"])
            edits += _conflict_edits(text, b, item["id"], item["hash"], bodies[item["id"]])
            e.setdefault("body", _body_hash(text[b.body_start : b.body_end]))  # legacy: protect now
            e.update(hash=item["hash"], reading=item["reading"])
            changed_meta = True
        elif item["id"] in todo["rewrite"]:
            b, e = blocks[item["id"]], note.entry(item["id"])
            c = chunk(item["id"], item)
            rendered = render_block(c, bodies[item["id"]], vault)
            edits.append((b.start, b.end, rendered))
            e.update(
                hash=item["hash"], reading=item["reading"], body=_entry(c, None, rendered)["body"]
            )
            changed_meta = True
    for item in sync.get("replaced", []):
        b, e = blocks.get(item["id"]), note.entry(item["id"])
        if item["id"] in conflicts:
            succ = item["successor"]
            edits += _conflict_edits(text, b, succ, item["hash"], bodies[succ])
            e.setdefault("body", _body_hash(text[b.body_start : b.body_end]))
            e.update(id=succ, hash=item["hash"], reading=item["reading"])
            changed_meta = True
        elif item["id"] in todo["rewrite"]:
            s = {"hash": item["hash"], "reading": item["reading"]}
            c = chunk(item["successor"], s)
            rendered = render_block(c, bodies[item["successor"]], vault)
            edits.append((b.start, b.end, rendered))
            e.clear()
            e.update(id=item["successor"], hash=item["hash"], reading=item["reading"])
            e["body"] = _entry(c, None, rendered)["body"]
            changed_meta = True
        elif item["id"] in todo["merged"] and item["id"] not in touched:
            flag = MERGED_FLAG.format(id=item["successor"])
            edits.append((b.body_start, b.body_start, flag + "\n\n"))
            e.update(status="merged", successor=item["successor"])
            changed_meta = True
    for item in sync.get("fresh_after_reread", []):
        e, b = note.entry(item["id"]), blocks.get(item["id"])
        if e is None or item["id"] in touched:
            continue
        e["hash"], e["reading"] = item["hash"], item["reading"]
        changed_meta = True
        if b is not None:  # only the marker line changes; the words stay
            line_end = b.body_start - 1 if text[b.body_start - 1] == "\n" else b.body_start
            edits.append((b.start, line_end, f"<!-- ink:{b.id} hash:{item['hash']} -->"))
    for cid in todo["flag_removed"]:
        if cid in touched:
            continue
        b = blocks[cid]
        edits.append((b.body_start, b.body_start, REMOVED_FLAG + "\n\n"))
        note.entry(cid)["status"] = "removed"
        changed_meta = True
    appended = []
    for item in sync.get("new", []):
        c = chunk(item["id"], item)
        rendered = render_block(c, bodies[item["id"]], vault)
        appended.append(rendered)
        note.meta["chunks"].append(_entry(c, None, rendered))
        changed_meta = True
    if recreate:
        for cid in todo["user_deleted"]:
            src = next(
                (i for k in ("changed", "replaced") for i in sync.get(k, []) if i["id"] == cid),
                None,
            )
            target = src.get("successor", cid) if src else cid
            c = chunk(target, src or {"hash": note.entry(cid)["hash"]})
            rendered = render_block(c, bodies[cid], vault)
            appended.append(rendered)
            e = note.entry(cid)
            e.clear()
            e.update(_entry(c, None, rendered))
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


# -- learning from edits (INK-142, decision 0103) ----------------------------------------------
# Rules only ever affect the words the agent writes. Nothing here touches markers, `body`,
# hashes or apply/validate, and the note itself is never written by `learn`.

RULE_KINDS = ("heading_question", "heading_level", "crop_removed")
PROPOSE_AT = 3
PROFILE = "meta/Inkbridge Export Profile.md"
OBSERVED = "## Observed edits"
PROPOSALS = "## Proposals"
SOURCE_INK = "> [!ink]- Source ink"
OBSERVED_RE = re.compile(
    r"^- (\d{4}-\d{2}-\d{2}) (\w+) (\S+)#([A-Za-z0-9_-]+) ([0-9a-f]{8})$", re.MULTILINE
)
PROPOSAL_RE = re.compile(r"^### (\d{4}-\d{2}-\d{2}) (\w+)[ \t]*$", re.MULTILINE)


def _run_git(note: Path, *args: str) -> str | None:
    try:
        r = subprocess.run(
            ["git", "-C", str(note.parent), *args],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.returncode == 0 else None


def _git_revisions(note: Path) -> list[str]:
    out = _run_git(note, "log", "--format=%H", "--", note.name)
    return out.split() if out else []


def _git_show(note: Path, rev: str) -> str | None:
    prefix = _run_git(note, "rev-parse", "--show-prefix")
    if prefix is None:
        return None
    return _run_git(note, "show", f"{rev}:{prefix.strip()}{note.name}")


def _old_interior(note: Path, cid: str, body_hash: str) -> str | None:
    for rev in _git_revisions(note):
        text = _git_show(note, rev)
        if text is None:
            continue
        try:
            n = parse(text)
        except NoteError:
            continue
        b = n.block(cid)
        if b and _body_hash(text[b.body_start : b.body_end]) == body_hash:
            interior = text[b.body_start : b.body_end]
            return interior[_managed_prefix_len(interior) :]
    return None


def _first_heading(text: str) -> str | None:
    return next((ln.rstrip() for ln in text.splitlines() if HEADING_RE.match(ln)), None)


def classify(old: str, new: str) -> list[dict]:
    """Which known patterns the edit from `old` to `new` shows (closed set RULE_KINDS)."""
    found = []
    oh, nh = _first_heading(old), _first_heading(new)
    if oh and nh and oh != nh:
        o_title, n_title = HEADING_RE.match(oh)["title"], HEADING_RE.match(nh)["title"]
        if not o_title.endswith("?") and n_title.endswith("?"):
            found.append({"kind": "heading_question", "before": oh, "after": nh})
        if len(oh) - len(oh.lstrip("#")) != len(nh) - len(nh.lstrip("#")):
            found.append({"kind": "heading_level", "before": oh, "after": nh})
    if SOURCE_INK in old.splitlines() and SOURCE_INK not in new.splitlines():
        found.append({"kind": "crop_removed", "before": SOURCE_INK, "after": ""})
    return found


def find_edits(note: Path, with_missing: bool = False):
    """Blocks the user edited since the skill wrote them: [{chunk, old, new}], old from vault git.
    Blocks with no stored body hash or no matching git revision are skipped (and listed in
    `missing` when asked for)."""
    text = note.read_text(encoding="utf-8")
    n = parse(text)
    edits, missing = [], []
    for e in n.meta["chunks"]:
        b = n.block(e["id"])
        if not (b and "body" in e):
            continue
        interior = text[b.body_start : b.body_end]
        if _body_hash(interior) == e["body"]:
            continue
        old = _old_interior(note, e["id"], e["body"])
        if old is None:
            missing.append(e["id"])
            continue
        edits.append(
            {"chunk": e["id"], "old": old, "new": interior[_managed_prefix_len(interior) :]}
        )
    return (edits, missing) if with_missing else edits


def _append_to_section(text: str, heading: str, block: str) -> str:
    """Insert `block` after the last non-blank line of the section, or add the section at the end.
    Nothing else in `text` moves."""
    lines = text.splitlines(keepends=True)
    start = next((i for i, ln in enumerate(lines) if ln.rstrip() == heading), None)
    if start is None:
        sep = "" if not text else ("\n" if text.endswith("\n") else "\n\n")
        return f"{text}{sep}{heading}\n\n{block}"
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    last = end
    while last > start + 1 and not lines[last - 1].strip():
        last -= 1
    if last == start + 1:  # empty section
        return "".join(lines[: start + 1]) + "\n" + block + "".join(lines[start + 1 :])
    prefix = "".join(lines[:last])
    if not prefix.endswith("\n"):
        prefix += "\n"
    return prefix + block + "".join(lines[last:])


def _profile_section(text: str, heading: str) -> str:
    lines = text.splitlines(keepends=True)
    start = next((i for i, ln in enumerate(lines) if ln.rstrip() == heading), None)
    if start is None:
        return ""
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    return "".join(lines[start + 1 : end])


def _proposals(text: str) -> list[dict]:
    body = _profile_section(text, PROPOSALS)
    marks = list(PROPOSAL_RE.finditer(body))
    out = []
    for i, m in enumerate(marks):
        chunk = body[m.end() : marks[i + 1].start() if i + 1 < len(marks) else len(body)]
        field = {
            k: (re.search(rf"^- {k}:[ \t]*(.*?)[ \t]*$", chunk, re.MULTILINE) or [None, ""])[1]
            for k in ("Status", "Before", "After")
        }
        out.append({"kind": m[2], "status": field["Status"].lower(), **field})
    return out


def _confidence(n: int) -> str:
    return "low" if n < 4 else "medium" if n < 6 else "high"


def learn(note: Path, vault: Path, today: str | None = None) -> dict:
    """Record the user's edits of this note in the profile and propose a rule once PROPOSE_AT
    distinct blocks show the same pattern. Writes only the profile."""
    today = today or datetime.now(UTC).date().isoformat()
    note = Path(note)
    profile = Path(vault) / PROFILE
    text = profile.read_text(encoding="utf-8") if profile.is_file() else ""
    edits, missing = find_edits(note, with_missing=True)
    seen = {(m[2], m[4], m[5]) for m in OBSERVED_RE.finditer(text)}
    lines, snippets = [], {}
    for e in edits:
        sha = hashlib.sha256(e["new"].encode()).hexdigest()[:8]
        for c in classify(e["old"], e["new"]):
            snippets.setdefault(c["kind"], c)
            if (c["kind"], e["chunk"], sha) not in seen:
                seen.add((c["kind"], e["chunk"], sha))
                lines.append(f"- {today} {c['kind']} {note.stem}#{e['chunk']} {sha}\n")
    if lines:
        text = _append_to_section(text, OBSERVED, "".join(lines))
    proposed, block = [], ""
    known = {p["kind"] for p in _proposals(text)}
    for kind in RULE_KINDS:
        labels = {}
        for m in OBSERVED_RE.finditer(text):
            if m[2] == kind:
                labels.setdefault(m[4], f"{m[3]}#{m[4]}")
        if len(labels) < PROPOSE_AT or kind in known:
            continue
        snip = snippets.get(kind, {"before": "see the note", "after": "see the note"})
        block += (
            f"### {today} {kind}\n- Status: proposed\n- Before: {snip['before']}\n"
            f"- After: {snip['after']}\n- Evidence: {len(labels)} edits ({', '.join(labels.values())})\n"
            f"- Confidence: {_confidence(len(labels))}\n\n"
        )
        proposed.append(kind)
    for heading in (OBSERVED, PROPOSALS):  # both sections exist once the profile does
        if not any(ln.rstrip() == heading for ln in text.splitlines()) and (edits or text):
            text = _append_to_section(text, heading, "")
    if block:
        text = _append_to_section(text, PROPOSALS, block)
    if not text.endswith("\n") and text:
        text += "\n"
    if (text or proposed or lines) and (
        not profile.is_file() or text != profile.read_text(encoding="utf-8")
    ):
        _atomic(profile, text.encode("utf-8"))
    observed = len(OBSERVED_RE.findall(text))
    return {"observed": observed, "new": len(lines), "proposed": proposed, "no_history": missing}


def rules(vault: Path) -> list[dict]:
    """Approved proposals of a known kind, for the agent to follow when writing words."""
    profile = Path(vault) / PROFILE
    if not profile.is_file():
        return []
    return [
        {"kind": p["kind"], "before": p["Before"], "after": p["After"]}
        for p in _proposals(profile.read_text(encoding="utf-8"))
        if p["status"] == "approved" and p["kind"] in RULE_KINDS
    ]


def _read(path: str) -> str:
    with open(path, encoding="utf-8", newline="") as f:  # no newline translation
        return f.read()


def _atomic(path: Path, data: bytes) -> None:
    """Write via a temp file and rename, so an interruption never leaves a truncated file."""
    path.parent.mkdir(parents=True, exist_ok=True)
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
    s.add_argument("--index")
    s.add_argument("--relates", nargs="*", default=[])
    s = sub.add_parser("validate")
    s.add_argument("note")
    s.add_argument("--strict", action="store_true")
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
    s = sub.add_parser("learn")
    s.add_argument("note")
    s.add_argument("--vault", required=True)
    s = sub.add_parser("rules")
    s.add_argument("--vault", required=True)
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
            if a.out and Path(a.out).exists():
                raise NoteError(
                    f"{a.out} exists; use plan/apply to re-export it, or pick another title"
                )
            note = new_note(_load(a.canvas), a.title, _load(a.bodies), vault, a.index, a.relates)
            _write(note, a.out)
        elif a.cmd == "validate":
            errors = validate(_read(a.note), a.strict)
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
        elif a.cmd == "learn":
            print(json.dumps(learn(Path(a.note), Path(a.vault)), indent=2))
        elif a.cmd == "rules":
            print(json.dumps(rules(Path(a.vault)), indent=2))
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
