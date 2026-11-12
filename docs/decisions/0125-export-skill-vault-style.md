# 0125 The export skill writes like the user's vault

Status: accepted (INK-210). Builds on [0021](0021-vault-export-skill.md), [0063](0063-skill-vault-alignment.md) and [0103](0103-skill-learning-loop.md).

## Problem

Exported notes were correct and traceable but did not read like the user's notes: a generic provenance callout, no dated summary, no `source`, no Related Notes list, and a rewrite-into-study-note instruction that invited padding.

## Decision

- Researched from the vault itself (`_CLAUDE.md`, the library notes such as the MCP, RAG and conceptual-notes notes, the Inkbridge project hub): atomic, heavily structured, bold lead terms, tables and mermaid, a dated "For future agent" callout, a `source` key, a closing `## Related Notes` list, `publish: false` for anything personal, one tag only.
- `inknote.py new` takes `--summary`; the callout carries it, a `Saved <date> from the Inkbridge canvas <id>.` line and then the provenance lines. `source: inkbridge` joins the frontmatter. `relates` also write a closing `## Related Notes` list; blocks added on re-export go above it. Nothing outside the markers is touched on re-export, as before.
- SKILL.md has a "Write like this vault" section: keep the user's words, keep their questions and gaps as theirs, structure rules, link through the vault search tool, atoms in `wiki/concepts/` are proposed and never created unasked, the project hub is never edited.
- Diagram readings now carry relation lines ([0123](0123-reader-gets-diagram-structure.md)); the skill turns them into mermaid edges.

## Limits

The style rules are prose for the agent; only the dash, arrow and emoji ban is checked by `validate`. Tuning against more of the user's notes is expected and is what the learning loop (0103) is for.
