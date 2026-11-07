"""Partial JSON string reader and stream-json follower (INK-176)."""

import json

from inkbridge.agent.answer_stream import AnswerStream, partial_string


def test_partial_string_cases():
    assert partial_string('{"answer_md":"ab\\nc', "answer_md") == "ab\nc"
    assert partial_string('{"answer_md":"ab\\', "answer_md") == "ab"
    assert partial_string('{"answer_md":"ab\\u00', "answer_md") == "ab"
    assert partial_string('{"answer_md":"a\\u00e9b"}', "answer_md") == "aéb"
    assert partial_string('{"answer_md":"done","x":"y', "answer_md") == "done"
    assert partial_string('{"sources":[]', "answer_md") is None
    assert partial_string('{"sources":[],"answer_md":"x', "answer_md") == "x"
    assert partial_string('{"answer_md":"a\\uzzzzb', "answer_md") == "a"


def ev(e):
    return json.dumps({"type": "stream_event", "event": e})


def start(i, name):
    return ev({"type": "content_block_start", "index": i,
               "content_block": {"type": "tool_use", "name": name}})  # fmt: skip


def delta(i, piece):
    return ev({"type": "content_block_delta", "index": i,
               "delta": {"type": "input_json_delta", "partial_json": piece}})  # fmt: skip


def test_answer_stream_follows_only_our_tool_and_throttles():
    t, got = [0.0], []
    s = AnswerStream(got.append, clock=lambda: t[0])
    for line in ("not json", "[]", ev({"type": "ping"}), start(0, "text")):
        s.feed(line)
    s.feed(ev({"type": "content_block_delta", "index": 0,
               "delta": {"type": "text_delta", "text": "thinking"}}))  # fmt: skip
    s.feed(start(1, "mcp__inkbridge__answer_question"))
    s.feed(delta(1, '{"answer_md":"He'))
    assert got == ["He"]
    t[0] = 0.05
    s.feed(delta(1, "llo "))  # inside the window: held
    assert got == ["He"]
    s.feed(delta(2, '{"answer_md":"other'))  # other block: ignored
    t[0] = 0.3
    s.feed(delta(1, "wor"))
    assert got == ["He", "llo wor"]
    t[0] = 0.5
    s.feed(delta(1, 'ld"}'))
    assert "".join(got) == "Hello world"
    s.feed(start(2, "mcp__inkbridge__read_canvas"))
    s.feed(delta(2, '{"answer_md":"nope'))
    assert "".join(got) == "Hello world"
