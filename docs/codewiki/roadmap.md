# Roadmap (from `docs/tickets/`, local)

Ticket statuses in the index lag the branches: several `todo` tickets (INK-034, 036, 037, 038, 043, 044, 058, 014, 057, 059) have merged into `review/all-latest`. Check `git log`.

## Open feature work

| Ticket | What | Notes |
|---|---|---|
| INK-045 | Accept, Reject, Accept all for drafts | Reject removes only that op's elements; never user ink |
| INK-046 | Spike: pull path with two MCP clients | Writes decision 0007 |
| INK-047 | Questions API, `list_questions`, `answer_question` | WebSocket `question.update` |
| INK-048 | `AgentRunner` and Claude Code adapter | `INKBRIDGE_RUNNER` |
| INK-049 | Ask AI panel and Keep on canvas | Needs 045 and 047 |
| INK-050..053, 061 | Eval harness and E1 to E5 | E1 input representation, E2/E3 diagram F1 and vault grounding, E4 stale detection, E5 chunk quality |
| INK-054, 055, 056 | README and architecture diagram, 2-minute demo, final pass | Never cut: README, demo video |
| INK-062 | Bug: pen pressure too strong, slight ink lag | Excalidraw hardcodes `thinning 0.6`, `smoothing 0.5`, `streamline 0.5`; stored `pressures` must stay raw |
| INK-063 | Backlog: live scene sync across tabs | Server pushes `scene.updated`; clean tabs apply it |
| INK-060 | Stretch: networkx `get_subgraph` | Read-only, built in memory |

## Post-deadline restructuring (tag `restructure`)

INK-068 split `db/__init__.py` into a package, then INK-069 (other large modules) and INK-070 (SQLAlchemy vs raw sqlite3 decision) in parallel, then INK-071 (Alembic vs hand-rolled runner); INK-072 small code-health fixes.

## Cut order if short on time

INK-060, E2/E3, stroke arm of E1, source previews, Keep on canvas, Accept/Reject (keep Accept all), manual merge/split, then Ask panel and runner (keep pull path). Never cut: canvas-to-note path, stale check, README, demo video.

## Open items

- Vault loop on real handwritten pages is still pending (decision 0022); re-check chunker `k` on real pages.
- MCP behaviour in the Claude Desktop and Claude Code GUIs is unverified (decision 0003, `docs/mcp-tools.md`).
- Vault location default is a temp folder until `INKBRIDGE_VAULT` is set.
