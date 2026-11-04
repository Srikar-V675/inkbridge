# Deep Dive: questions API and MCP tools (`api/questions.py`, `db/questions.py`, `mcp/server.py`)

The pull path of Ask AI (INK-047, decision 0035). The backend stores questions and answers. It starts no process and calls no model, so a question leaves `pending` only through answer or cancel. The Ask panel (INK-049) and runner (INK-048) are not built.

## Lifecycle

```text
        POST question
             |
          pending ----answer----> answered
             |
             +-------cancel-----> cancelled
(any other move: 409 invalid_transition, with the current status)
```

The guard is inside the SQL (`UPDATE ... WHERE status = 'pending'`), so two racing answers cannot both win (`db/questions.py` `answer_question`, `_finish`).

## Routes (`api/questions.py`)

| Route | Notes |
|---|---|
| `POST /documents/{id}/questions` | Body `text` (1..4,000), `focus_element_ids` (max 200, de-duplicated, unknown ids accepted), `parent_id`. 404 unknown canvas; 422 `parent_not_found` if the parent is not a question on this canvas (any status) |
| `GET /documents/{id}/questions` | `status` filter, `limit` 1..100 (default 20); oldest first |
| `GET /questions/{id}` | One question |
| `POST /questions/{id}/answer` | `answer_md` (1..20,000, untrusted markdown stored as is), `sources` (max 50) |
| `POST /questions/{id}/cancel` | |

Models forbid extra fields. A `Source` is `{type:"chunk", id}` or `{type:"note", path}` and the validator rejects mixed shapes. Chunk ids are format-checked only (chunks can disappear).

Every create, answer and cancel calls `hub.publish(document_id, {"type": "question.update", "question": {...}})`. The web client ignores the message type for now.

## Read-time fields (`_full`)

| Field | How it is computed |
|---|---|
| `focus_chunk_ids` | Active auto chunks sharing an element with `focus_element_ids`, computed on every read (chunk ids change on split and merge). `list_questions` builds the chunk map once per call |
| `history` | Ancestors through `parent_id`, oldest first, at most `HISTORY_MAX = 5`, each `{id, text, answer_md, status}`. Cycle-safe (`seen`), built from rows only, so it survives a restart |

## MCP tools

| Tool | Behaviour |
|---|---|
| `list_questions(status="pending", document_id?, limit=20)` | Returns `{questions: [...]}`, oldest first (FIFO for an answering agent) |
| `answer_question(question_id, answer_md, sources=[])` | Returns `{id, status}`. Unknown or already-answered/cancelled becomes a `ToolError` with the next step |

The MCP side uses only HTTP (`ApiClient`), never `inkbridge.db`.

## Testing

`test_questions_api.py` (lifecycle, racing answers, parents, history, sources, limits), `test_mcp_questions.py`, `test_openapi_shapes.py`.

## Potential improvements

Panel and runner (INK-048, 049). No expiry for stale `pending` questions. The markdown must be sanitised by whatever renders it.
