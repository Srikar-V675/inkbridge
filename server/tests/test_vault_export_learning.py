"""INK-142: the export skill learns from the user's edits (decision 0103)."""

import json
import re
import subprocess

import pytest

from tests.test_vault_export import export, inknote, page  # noqa: F401  (page is a fixture)

PROFILE = "meta/Inkbridge Export Profile.md"
NAMES = ("gradient descent", "learning rate", "momentum")


def git(vault, *args):
    subprocess.run(
        ["git", "-C", str(vault), "-c", "user.email=t@t", "-c", "user.name=t", *args],
        check=True,
        capture_output=True,
    )


@pytest.fixture
def vault(tmp_path, client, page):  # noqa: F811
    """A vault under git with the exported note committed, then edits are made uncommitted."""
    _canvas, text = export(client, page, tmp_path)
    note = tmp_path / "content" / "library" / "Optimisation.md"
    note.parent.mkdir(parents=True)
    note.write_text(text)
    git(tmp_path, "init")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "export")
    return tmp_path, note


def edit_headings(note, n, start=0):
    text = note.read_text()
    for name in NAMES[start : start + n]:
        text = text.replace(f"## {name}\n", f"## What is {name}?\n", 1)
    note.write_text(text)


def profile_text(v):
    return (v / PROFILE).read_text()


def test_detects_edited_blocks_and_recovers_old_text_from_git(vault):
    _v, note = vault
    edit_headings(note, 3)
    edits = inknote.find_edits(note)
    assert len(edits) == 3
    assert all(set(e) == {"chunk", "old", "new"} for e in edits)
    by_old = {e["old"].splitlines()[0]: e for e in edits}
    assert set(by_old) == {f"## {n}" for n in NAMES}
    assert by_old["## gradient descent"]["new"].startswith("## What is gradient descent?")
    edit_headings(note, 0)
    note.write_text(note.read_text().replace("## What is momentum?", "## momentum"))
    assert len(inknote.find_edits(note)) == 2


def test_classifiers():
    old = "## gradient descent\n\n- x\n"
    got = inknote.classify(old, "## What is gradient descent?\n\n- x\n")
    assert got == [
        {
            "kind": "heading_question",
            "before": "## gradient descent",
            "after": "## What is gradient descent?",
        }
    ]
    lvl = inknote.classify(old, "### gradient descent\n\n- x\n")
    assert [c["kind"] for c in lvl] == ["heading_level"]
    assert (lvl[0]["before"], lvl[0]["after"]) == ("## gradient descent", "### gradient descent")
    with_crop = old + "> [!ink]- Source ink\n> ![[a.png]]\n"
    gone = inknote.classify(with_crop, old)
    assert [c["kind"] for c in gone] == ["crop_removed"]
    assert inknote.classify(old, old) == []


def test_no_git_history_is_skipped_not_an_error(tmp_path, client, page):  # noqa: F811
    _c, text = export(client, page, tmp_path)
    plain = tmp_path / "plain"
    plain.mkdir()
    note = plain / "N.md"
    note.write_text(text.replace("## gradient descent\n", "## What is gradient descent?\n", 1))
    assert inknote.find_edits(note) == []
    edits, missing = inknote.find_edits(note, with_missing=True)
    assert edits == [] and len(missing) == 1


def test_three_similar_edits_make_one_proposal(vault):
    v, note = vault
    edit_headings(note, 3)
    r = inknote.learn(note, v, today="2026-11-08")
    assert r["observed"] == 3 and r["proposed"] == ["heading_question"]
    text = profile_text(v)
    assert len(re.findall(r"^### 2026-11-08 heading_question$", text, re.MULTILINE)) == 1
    tail = text.split("### 2026-11-08 heading_question")[1]
    for key in ("Status: proposed", "Before:", "After:", "Evidence:", "Confidence: low"):
        assert len(re.findall(rf"^- {key}", tail, re.MULTILINE)) == 1


def test_two_edits_propose_nothing_and_evidence_persists(vault):
    v, note = vault
    edit_headings(note, 2)
    r = inknote.learn(note, v, today="2026-11-08")
    assert r["proposed"] == []
    assert "###" not in profile_text(v).split("## Proposals")[1]
    edit_headings(note, 1, start=2)
    r = inknote.learn(note, v, today="2026-11-08")
    assert r["proposed"] == ["heading_question"]


def test_learning_is_idempotent_and_never_reproposes(vault):
    v, note = vault
    edit_headings(note, 3)
    inknote.learn(note, v, today="2026-11-08")
    again = inknote.learn(note, v, today="2026-11-08")
    assert again["proposed"] == []
    text = profile_text(v)
    assert text.count("\n### ") == 1
    assert len(re.findall(r"^- 2026-11-08 heading_question ", text, re.MULTILINE)) == 3
    (v / PROFILE).write_text(text.replace("Status: proposed", "Status: rejected"))
    note.write_text(note.read_text() + "\n")
    inknote.learn(note, v, today="2026-11-09")
    assert profile_text(v).count("\n### ") == 1


def test_the_profile_keeps_the_users_text(vault):
    v, note = vault
    edit_headings(note, 3)
    (v / "meta").mkdir()
    top = "# My export style\n\nI like short headings.\n\n"
    mid = "\n## Observed edits\n\nMy own note about edits.\n\n## Mine\n\nUser paragraph.\n\n"
    (v / PROFILE).write_text(top + mid.lstrip("\n").replace("My own", "My own", 1))
    before = profile_text(v)
    inknote.learn(note, v, today="2026-11-08")
    after = profile_text(v)
    for piece in (
        "# My export style\n\nI like short headings.\n\n",
        "My own note about edits.\n",
        "## Mine\n\nUser paragraph.\n\n",
    ):
        assert piece in after
    assert after.startswith(before.split("My own")[0])
    assert after.index("## Mine") < after.index("## Proposals")


def test_rules_returns_only_approved_known_kinds(vault, tmp_path):
    v, _note = vault
    assert inknote.rules(v) == []

    def prop(kind, status):
        return (
            f"### 2026-11-08 {kind}\n- Status: {status}\n- Before: ## a\n- After: ## b?\n"
            "- Evidence: 3 edits (x#1)\n- Confidence: low\n\n"
        )

    (v / "meta").mkdir()
    (v / PROFILE).write_text(
        "## Proposals\n\n"
        + prop("heading_question", "approved")
        + prop("crop_removed", "proposed")
        + prop("bogus_kind", "approved")
    )
    assert inknote.rules(v) == [{"kind": "heading_question", "before": "## a", "after": "## b?"}]


def test_learning_never_changes_the_note(vault):
    v, note = vault
    edit_headings(note, 3)
    before = note.read_bytes()
    inknote.learn(note, v, today="2026-11-08")
    assert note.read_bytes() == before


def test_cli_learn_then_rules(vault, capsys):
    v, note = vault
    edit_headings(note, 3)
    assert inknote.main(["learn", str(note), "--vault", str(v)]) == 0
    assert "heading_question" in json.loads(capsys.readouterr().out)["proposed"]
    p = v / PROFILE
    p.write_text(p.read_text().replace("Status: proposed", "Status: approved"))
    assert inknote.main(["rules", "--vault", str(v)]) == 0
    got = json.loads(capsys.readouterr().out)
    assert [r["kind"] for r in got] == ["heading_question"]
    assert inknote.main(["validate", str(note)]) == 0
    assert json.loads(capsys.readouterr().out)["valid"] is True


def test_a_title_with_spaces_is_counted_once(vault):
    v, note = vault
    spaced = note.with_name("Gradient Descent.md")
    git(v, "mv", str(note), str(spaced))
    git(v, "commit", "-m", "rename")
    edit_headings(spaced, 3)
    r = inknote.learn(spaced, v, today="2026-11-08")
    assert r["observed"] == 3 and r["proposed"] == ["heading_question"]
    again = inknote.learn(spaced, v, today="2026-11-09")
    assert again["observed"] == 3 and again["new"] == 0 and again["proposed"] == []
    assert len(re.findall(r"^- .* Gradient Descent#", profile_text(v), re.M)) == 3
