import sqlite3


def successor_problems(conn: sqlite3.Connection) -> list[str]:
    """successor_of that points at a missing region, another document's region, or loops back."""
    rows = {
        r["id"]: (r["document_id"], r["successor_of"])
        for r in conn.execute("SELECT id, document_id, successor_of FROM regions")
    }
    problems = []
    for rid, (doc, nxt) in rows.items():
        if nxt is None:
            continue
        if nxt not in rows:
            problems.append(f"{rid}: successor_of points at missing region {nxt}")
        elif rows[nxt][0] != doc:
            problems.append(f"{rid}: successor_of points at a region of another document")
        else:
            seen, cur = {rid}, nxt
            while cur is not None and cur in rows:
                if cur in seen:
                    problems.append(f"{rid}: successor_of chain loops")
                    break
                seen.add(cur)
                cur = rows[cur][1]
    return problems
