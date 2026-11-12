"""The agent knows it is inside a canvas (INK-207, decision 0122)."""

from inkbridge.agent import ask_runner
from inkbridge.canvas_context import CANVAS_CONTEXT
from inkbridge.mcp.app import mcp


def test_context_states_the_essentials():
    for word in ("canvas", "chunk", "handwriting", "side panel", "never edit or delete", "unsure"):
        assert word in CANVAS_CONTEXT.replace("and you only ever ADD to the canvas and ", "")


def test_runner_prompts_carry_it():
    q = {"id": "q1", "document_id": "d", "text": "what?", "focus_chunk_ids": [], "history": []}
    assert CANVAS_CONTEXT in ask_runner.build_prompt(q)
    t = {
        "id": "t1",
        "kind": "question",
        "mode": "answer",
        "document_id": "d",
        "op_limit": 1,
        "input": {"anchor_chunk": "c1", "reason": "r", "payload": {}},
    }
    assert CANVAS_CONTEXT in ask_runner.build_task_prompt(t)


def test_mcp_instructions_carry_it():
    assert mcp.instructions.startswith(CANVAS_CONTEXT)
    assert "read_canvas" in mcp.instructions
