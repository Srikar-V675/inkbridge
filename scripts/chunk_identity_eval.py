"""INK-072 item 4: does containment matching keep chunk ids where it should? (decision 0029)

    cd server && uv run python ../scripts/chunk_identity_eval.py

Pure `match_chunks` over synthetic edits of a chunk of n strokes, for three variants (off,
containment 0.6, 0.75). "kept" = the cluster that should continue the chunk keeps its id. For the
rewrite and unrelated cases keeping an id is WRONG, so those count as "wrongly kept".
Synthetic; confirm on real pages (INK-061) before turning the flag on.
"""

from inkbridge.canvas.chunker import match_chunks

SIZES = (2, 3, 4, 6, 10, 20)
VARIANTS = {"off": None, "c0.6": 0.6, "c0.75": 0.75}


def ids(prefix, n, start=0):
    return [f"{prefix}{i}" for i in range(start, start + n)]


def cases(n):
    """(name, old chunks, new clusters, index of the cluster that should keep 'c', expected)."""
    old = {"c": ids("a", n)}
    out = []
    for k in range(1, 6):
        out.append((f"grow+{k}", old, [ids("a", n) + ids("n", k)], 0, "keep"))
    for k in range(1, n):
        if k <= 5:
            out.append((f"shrink-{k}", old, [ids("a", n - k)], 0, "keep"))
    half = n // 2
    out.append(("split 50/50", old, [ids("a", half), ids("a", n - half, half)], 0, "keep"))
    cut = max(1, round(n * 0.7))
    out.append(("split 70/30", old, [ids("a", cut), ids("a", n - cut, cut)], 0, "keep"))
    two = {"c": ids("a", n), "d": ids("b", n)}
    out.append(("merge equal", two, [ids("a", n) + ids("b", n)], 0, "either"))
    big = {"c": ids("a", n), "d": ids("b", max(1, n // 4))}
    out.append(("merge big+small", big, [ids("a", n) + ids("b", max(1, n // 4))], 0, "keep"))
    keep_n = n - n // 2
    out.append(("rewrite 50%", old, [ids("a", keep_n) + ids("n", n - keep_n)], 0, "lose"))
    out.append(("unrelated", old, [ids("z", n)], 0, "lose"))
    return out


def main() -> None:
    totals = {v: {"kept": 0, "should": 0, "wrong": 0, "cases": 0} for v in VARIANTS}
    rows = {}
    for n in SIZES:
        for name, old, clusters, idx, expect in cases(n):
            for v, cont in VARIANTS.items():
                m = match_chunks(old, clusters, tops=list(range(len(clusters))), containment=cont)
                got = m.assigned[idx] == "c" or (expect == "either" and m.assigned[idx] is not None)
                t = totals[v]
                t["cases"] += 1
                if expect in ("keep", "either"):
                    t["should"] += 1
                    t["kept"] += got
                else:
                    t["wrong"] += got
                rows.setdefault((name, n), {})[v] = got
    print(
        f"{'case':<16}"
        + "".join(f"{'n=' + str(n):>6}" for n in SIZES)
        + "   (off / 0.6 / 0.75; K=kept, .=new id)"
    )
    for name in dict.fromkeys(k[0] for k in rows):
        cells = ""
        for n in SIZES:
            r = rows.get((name, n))
            cells += f"{'-' if r is None else ''.join('K' if r[v] else '.' for v in VARIANTS):>6}"
        print(f"{name:<16}{cells}")
    print()
    print(
        f"{'variant':<8}{'should keep':>12}{'kept':>6}{'wrongly kept':>14}  (of {totals['off']['cases']} cases)"
    )
    for v, t in totals.items():
        print(f"{v:<8}{t['should']:>12}{t['kept']:>6}{t['wrong']:>14}")


if __name__ == "__main__":
    main()
