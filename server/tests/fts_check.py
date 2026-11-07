import sqlite3

from inkbridge import db


def fts_problems(conn: sqlite3.Connection) -> list[str]:
    """Differences between region_fts and what _reindex_region would produce for active regions."""
    problems = []
    fts = {r["region_id"]: r for r in conn.execute("SELECT region_id, text, latex FROM region_fts")}
    for r in conn.execute("SELECT id, content_hash FROM regions WHERE status = 'active'"):
        rec = conn.execute(db._BEST_RECOGNITION, (r["id"], r["content_hash"])).fetchone()
        want = bool(rec and (rec["text"] or rec["latex"]))
        row = fts.get(r["id"])
        if want and row is None:
            problems.append(f"{r['id']}: reading but no fts row")
        elif not want and row is not None:
            problems.append(f"{r['id']}: fts row without a current reading")
        elif want and ((row["text"], row["latex"]) != (rec["text"] or "", rec["latex"] or "")):
            problems.append(f"{r['id']}: fts row is stale")
    dangling = conn.execute(
        "SELECT region_id FROM region_fts WHERE region_id NOT IN (SELECT id FROM regions)"
    ).fetchall()
    problems += [f"{d['region_id']}: fts row for missing region" for d in dangling]
    dupes = conn.execute(
        "SELECT region_id FROM region_fts GROUP BY region_id HAVING COUNT(*) > 1"
    ).fetchall()
    problems += [f"{d['region_id']}: duplicate fts rows" for d in dupes]
    if "answer_fts" in {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}:
        problems += answer_fts_problems(conn)
    return problems


def answer_fts_problems(conn: sqlite3.Connection) -> list[str]:
    """Every answered question has exactly one matching answer_fts row, and nothing else is indexed."""
    problems = []
    rows: dict[str, list] = {}
    for r in conn.execute("SELECT question_id, question, answer FROM answer_fts"):
        rows.setdefault(r["question_id"], []).append(r)
    answered = set()
    for q in conn.execute("SELECT id, text, answer_md FROM questions WHERE status = 'answered'"):
        answered.add(q["id"])
        got = rows.get(q["id"], [])
        if not got:
            problems.append(f"{q['id']}: answered but no answer_fts row")
        elif len(got) > 1:
            problems.append(f"{q['id']}: duplicate answer_fts rows")
        elif (got[0]["question"], got[0]["answer"]) != (q["text"], q["answer_md"] or ""):
            problems.append(f"{q['id']}: answer_fts row is stale")
    problems += [
        f"{qid}: answer_fts row for a missing or unanswered question"
        for qid in rows
        if qid not in answered
    ]
    return problems
