"""INK-038: run the vault loop end to end on a synthetic study page and print the walkthrough.

draw -> export -> nudge -> move -> edit one line -> check_sync -> re-export, against a live API
and a throwaway database. The script plays the two roles that are not under test: the user (writes
the scene) and the recognition worker / agent (writes readings and the words of each block).

    INKBRIDGE_DB=/tmp/claude-1000/e2e/synth.db uv run uvicorn inkbridge.api:app --port 8300 &
    cd server && INKBRIDGE_DB=/tmp/claude-1000/e2e/synth.db uv run python ../scripts/vault_loop_e2e.py \\
        --api http://127.0.0.1:8300 --vault /tmp/claude-1000/e2e/vault

Readings are written straight into the throwaway database (this is a test harness, not an MCP
client). Nothing is sent to Gemini. Never point it at a database that holds real notes.
"""

import argparse
import base64
import difflib
import importlib.util
import re
import sys
from pathlib import Path

import httpx

from inkbridge import db

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)
_spec = importlib.util.spec_from_file_location(
    "inknote", Path(__file__).parents[1] / "skills" / "inkbridge-export" / "scripts" / "inknote.py"
)
inknote = importlib.util.module_from_spec(_spec)
sys.modules["inknote"] = inknote
_spec.loader.exec_module(inknote)


def stroke(i, x, y, w=10, h=20):
    return {
        "id": i, "type": "freedraw", "x": x, "y": y, "width": w, "height": h, "version": 1,
        "points": [[0, 0], [w, h]], "pressures": [0.5, 0.5], "isDeleted": False,
    }  # fmt: skip


def word(prefix, n, x, y):
    """A word: n strokes 15 px apart (one chunk at k = 1.5)."""
    return [stroke(f"{prefix}{i}", x + 15 * i, y) for i in range(n)]


def page_elements():
    """A study page: a heading, two bullet lines, and a two-box diagram joined by an arrow."""
    box = {"type": "rectangle", "width": 120, "height": 60, "isDeleted": False, "version": 1}
    return [
        *word("h", 6, 0, 0),
        *word("b", 5, 0, 120),
        *word("c", 4, 0, 240),
        {**box, "id": "r1", "x": 0, "y": 420},
        {**box, "id": "r2", "x": 400, "y": 420},
        {
            "id": "ar", "type": "arrow", "x": 120, "y": 450, "width": 280, "height": 0,
            "points": [[0, 0], [280, 0]], "isDeleted": False, "version": 1,
            "startBinding": {"elementId": "r1"}, "endBinding": {"elementId": "r2"},
        },
    ]  # fmt: skip


class Run:
    def __init__(self, api, vault):
        self.http = httpx.Client(base_url=api, timeout=60)
        self.vault = vault
        self.doc = self.http.post("/documents", json={"title": "e2e synthetic"}).json()["id"]
        self.version = self.http.get(f"/documents/{self.doc}/scene").json()["version"]
        self.elements = page_elements()
        self.put()

    def put(self):
        r = self.http.put(
            f"/documents/{self.doc}/scene",
            json={"base_version": self.version, "elements": self.elements},
        )
        r.raise_for_status()
        self.version = r.json()["version"]

    def canvas(self):
        return self.http.get(f"/documents/{self.doc}/chunks").json()

    def chunk(self, element_id):
        regions = self.http.get(
            f"/documents/{self.doc}/regions", params={"chunks": True, "limit": 500}
        ).json()
        return next(
            c for c in regions if element_id in c["element_ids"] and c["status"] == "active"
        )

    def read(self, element_id, text):
        """Stand in for the recognition worker: a reading for the chunk's current ink."""
        c = self.chunk(element_id)
        conn = db.connect()
        try:
            db.save_recognition(conn, c["id"], c["content_hash"], "user", text)
        finally:
            conn.close()

    def upload_crops(self):
        for c in self.canvas()["chunks"]:
            self.http.put(
                f"/regions/{c['id']}/image",
                files={"image": ("c.png", PNG, "image/png")},
                data={"scene_version": str(self.version)},
            ).raise_for_status()

    def sync(self, text):
        note = inknote.parse(text)
        r = self.http.post(
            f"/documents/{self.doc}/check_sync",
            json={"chunks": inknote._sync_chunks(note), "wait_s": 0},
        )
        r.raise_for_status()
        return r.json()


def blocks(text):
    note = inknote.parse(text)
    return {b.id: text[b.start : b.end] for b in note.blocks}


def short(text):
    """64-hex hashes shortened to 8 characters so a walkthrough stays readable."""
    return re.sub(r"\b([0-9a-f]{8})[0-9a-f]{56}\b", r"\1...", text)


def show(title, text):
    print(f"\n### {title}\n")
    print("```diff\n" + short(text).rstrip("\n") + "\n```")


def diff(before, after):
    return "".join(
        difflib.unified_diff(
            before.splitlines(True), after.splitlines(True), "before.md", "after.md", n=1
        )
    )


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://127.0.0.1:8300")
    ap.add_argument("--vault", required=True)
    a = ap.parse_args(argv)
    vault = Path(a.vault)
    vault.mkdir(parents=True, exist_ok=True)
    run = Run(a.api, vault)
    ids = {"h": "h0", "b": "b0", "c": "c0"}
    texts = {"h": "Gradient descent", "b": "step = learning rate x gradient", "c": "momentum"}
    for key, text in texts.items():
        run.read(ids[key], text)
    run.read("r1", "weights")
    run.read("r2", "loss")
    run.upload_crops()
    canvas = run.canvas()
    print(f"# Vault loop walkthrough (synthetic page, canvas `{run.doc}`)\n")
    print(
        f"Chunks found: {canvas['chunk_count']} (expected 5: heading, two lines, two diagram boxes linked by a long arrow)."
    )
    assert canvas["chunk_count"] == 5, canvas["chunk_count"]

    def words(c):
        return f"## {c['text']}\n\n- {c['text']}"

    bodies = {c["id"]: words(c) for c in canvas["chunks"]}
    inknote.fetch_crops(a.api, vault, canvas)
    note = inknote.new_note(canvas, "Optimisation", bodies, vault)
    user_text = "\nMy own remark, typed in Obsidian.\n"
    note = note.replace(
        "\n<!-- ink:", user_text + "\n<!-- ink:", 1
    )  # the user types between blocks
    path = vault / "Optimisation.md"
    path.write_text(note)
    assert inknote.validate(note) == []
    print(f"\nFirst export: `{path.name}`, valid, {len(blocks(note))} blocks.")
    show("First export (frontmatter + first block)", "\n".join(note.splitlines()[:14]))

    # 1. A nudge: one stroke moves 0.4 px. The ink hash changes; the reading does not.
    nudged = next(e for e in run.elements if e["id"] == "b1")
    nudged["x"] += 0.4
    nudged["version"] += 1
    run.put()
    run.read("b0", texts["b"])  # the worker re-reads the nudged ink: same words
    sync = run.sync(note)
    plan = inknote.plan(note, sync)
    print("\n## 1. Nudge one stroke\n")
    print(
        f"check_sync: fresh={len(sync['fresh'])} fresh_after_reread={len(sync['fresh_after_reread'])}"
        f" changed={len(sync['changed'])} replaced={len(sync['replaced'])}"
    )
    assert not sync["changed"] and not sync["replaced"] and plan["needs_body"] == []
    after_nudge = inknote.apply(note, sync, run.canvas(), {}, vault)
    show("Nudge: note diff (hash refresh only, no words touched)", diff(note, after_nudge))
    assert [k for k in blocks(note) if block_words(after_nudge, k) != block_words(note, k)] == []

    # 2. A move: the whole diagram moves 300 px. Offsets from the bbox origin are unchanged.
    for e in run.elements:
        if e["id"] in ("r1", "r2", "ar"):
            e["x"] += 300
            e["version"] = e.get("version", 1) + 1
    run.put()
    sync = run.sync(after_nudge)
    print("\n## 2. Move the diagram\n")
    print(f"check_sync: fresh={len(sync['fresh'])} (all five), nothing else flagged.")
    assert not (sync["changed"] or sync["replaced"] or sync["removed"] or sync["new"])
    assert inknote.apply(after_nudge, sync, run.canvas(), {}, vault) == after_nudge

    # 3. One changed line: a stroke is added to "momentum" and it now reads differently.
    run.elements.append(stroke("c4", 15 * 4, 240))
    run.put()
    run.read("c0", "momentum beta = 0.9")
    run.upload_crops()  # the browser re-renders the stale crop of the changed chunk
    inknote.fetch_crops(a.api, vault, run.canvas())
    sync = run.sync(after_nudge)
    plan = inknote.plan(after_nudge, sync)
    print("\n## 3. Change one line\n")
    print(f"check_sync changed={len(sync['changed'])}; plan rewrite={plan['rewrite']}")
    assert len(sync["changed"]) == 1 and len(plan["rewrite"]) == 1
    target = plan["rewrite"][0]
    final = inknote.apply(
        after_nudge, sync, run.canvas(), {target: "## momentum\n\n- momentum beta = 0.9"}, vault
    )
    show("Edit: note diff (exactly one block)", diff(after_nudge, final))
    changed = [
        k for k in blocks(after_nudge) if block_words(final, k) != block_words(after_nudge, k)
    ]
    assert changed == [target], changed
    assert user_text in final and inknote.validate(final) == []
    path.write_text(final)
    print(
        "\nAll checks passed: nudge flagged nothing, move flagged nothing, one edit rewrote one block,"
        " text outside the markers untouched."
    )
    tune()
    return 0


def tune():
    """Chunker constants on synthetic handwriting: where `k` splits lines, and id retention."""
    from inkbridge.chunker import ChunkerConfig, cluster

    print("\n## Tuning (synthetic handwriting, 10 x 20 px strokes)\n")
    print(
        "Two words of 4 strokes (15 px apart inside a word); the gap between the words varies."
        " `1` = one chunk, `2` = two chunks.\n"
    )
    gaps = [20, 30, 40, 60, 90]
    print("| k | " + " | ".join(f"gap {g}" for g in gaps) + " |")
    print("|---|" + "---|" * len(gaps))
    for k in (1.0, 1.5, 2.0, 3.0):
        cells = []
        for g in gaps:
            els = [stroke(f"a{i}", 15 * i, 0) for i in range(4)]
            els += [stroke(f"b{i}", 45 + g + 15 * i, 0) for i in range(4)]
            cells.append(str(len(cluster(els, ChunkerConfig(k=k)))))
        print(f"| {k} | " + " | ".join(cells) + " |")
    print(
        "\nRows of text 40 px below each other (a normal line pitch) must stay separate chunks:"
        " one chunk would hide the structure of the page.\n"
    )
    print("| k | line pitch 40 | line pitch 60 |")
    print("|---|---|---|")
    for k in (1.0, 1.5, 2.0, 3.0):
        cells = []
        for pitch in (40, 60):
            els = [stroke(f"a{i}", 15 * i, 0) for i in range(4)]
            els += [stroke(f"b{i}", 15 * i, pitch) for i in range(4)]
            cells.append(str(len(cluster(els, ChunkerConfig(k=k)))))
        print(f"| {k} | " + " | ".join(cells) + " |")
    print(
        "\nId retention when a chunk of n strokes gains g strokes between two saves"
        " (J = n / (n + g) must be above the threshold; containment keeps the id whenever the old"
        " set is inside the new one):\n"
    )
    print("| n \\ g | 1 | 2 | 3 | 5 |")
    print("|---|---|---|---|---|")
    for n in (1, 2, 3, 5, 8):
        cells = [
            "keeps" if n / (n + g) > ChunkerConfig.match_threshold else "NEW ID"
            for g in (1, 2, 3, 5)
        ]
        print(f"| {n} | " + " | ".join(cells) + " |")


def block_words(text, chunk_id):
    b = inknote.parse(text).block(chunk_id)
    return text[b.body_start : b.body_end]


if __name__ == "__main__":
    sys.exit(main())
