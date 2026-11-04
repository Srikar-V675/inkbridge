"""Markdown tables and named, replaceable sections in eval/results.md."""

import datetime as dt
import re
from collections.abc import Sequence
from pathlib import Path

TITLE = "# Eval results\n"
BANNER = (
    "\nEach section below is written by `eval/run.py` and replaced in place on re-run. Text outside"
    " the `<!-- eval:NAME -->` blocks is hand-written and never touched.\n"
)
SYNTHETIC_LINE = (
    "**SYNTHETIC FIXTURES: these numbers only prove the harness and say nothing about "
    "handwriting.**"
)


def fmt(x: object, digits: int = 3) -> str:
    if isinstance(x, bool):
        return "yes" if x else "no"
    if isinstance(x, float):
        return f"{x:.{digits}f}"
    return str(x)


def render_table(headers: Sequence[str], rows: Sequence[Sequence[object]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines += ["| " + " | ".join(fmt(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


def section_header(dataset: str, synthetic: bool, reader: str, today: str | None = None) -> str:
    day = today or dt.datetime.now(dt.UTC).date().isoformat()
    head = f"_dataset: {dataset}, synthetic: {'yes' if synthetic else 'no'}, reader: {reader}, run: {day}_"
    return head + ("\n\n" + SYNTHETIC_LINE if synthetic else "")


def write_section(path: Path, name: str, body: str) -> None:
    path = Path(path)
    block = f"<!-- eval:{name} -->\n## {name}\n\n{body.strip()}\n<!-- /eval -->"
    text = path.read_text() if path.exists() else TITLE + BANNER
    pattern = re.compile(rf"<!-- eval:{re.escape(name)} -->.*?<!-- /eval -->", re.DOTALL)
    if pattern.search(text):
        text = pattern.sub(lambda _: block, text, count=1)
    else:
        text = text.rstrip("\n") + "\n\n" + block + "\n"
    path.write_text(text)
