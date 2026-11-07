"""Follow `claude -p --output-format stream-json` and surface the growing `answer_md` (INK-176).

The answer lives in the arguments of the `answer_question` tool call, so the text deltas are the
agent's reasoning; the answer is read from the `input_json_delta` pieces of that tool_use block."""

import json
import re
import time

_ESC = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", '"': '"', "\\": "\\", "/": "/"}


def partial_string(buf: str, key: str) -> str | None:
    """Value of string field `key` in a possibly unfinished JSON object; stable as buf grows."""
    m = re.search(rf'"{re.escape(key)}"\s*:\s*"', buf)
    if not m:
        return None
    out, i, n = [], m.end(), len(buf)
    while i < n:
        c = buf[i]
        if c == '"':
            break
        if c != "\\":
            out.append(c)
            i += 1
            continue
        if i + 1 >= n:
            break  # lone backslash at the end: wait for the next piece
        e = buf[i + 1]
        if e == "u":
            if i + 6 > n:
                break
            try:
                out.append(chr(int(buf[i + 2 : i + 6], 16)))
            except ValueError:
                break
            i += 6
        else:
            out.append(_ESC.get(e, e))
            i += 2
    # shortcut: a surrogate pair is two escapes; join halves, replace a lone half until complete
    return "".join(out).encode("utf-16", "surrogatepass").decode("utf-16", "replace")


class AnswerStream:
    """Feeds stream-json lines; calls sink(new_text) as the answer_question answer_md grows."""

    def __init__(self, sink, tool="answer_question", interval=0.15, clock=time.monotonic):
        self.sink, self.tool, self.interval, self.clock = sink, tool, interval, clock
        self._idx = None
        self._buf = ""
        self._sent = 0
        self._last = float("-inf")

    def feed(self, line: str) -> None:
        try:
            ev = json.loads(line)
        except ValueError:
            return
        if not isinstance(ev, dict) or ev.get("type") != "stream_event":
            return
        e = ev.get("event") or {}
        kind = e.get("type")
        if kind == "content_block_start":
            b = e.get("content_block") or {}
            is_ours = b.get("type") == "tool_use" and str(b.get("name", "")).endswith(self.tool)
            self._idx = e.get("index") if is_ours else None
            self._buf, self._sent = "", 0
        elif (
            kind == "content_block_delta" and self._idx is not None and e.get("index") == self._idx
        ):
            d = e.get("delta") or {}
            if d.get("type") != "input_json_delta":
                return
            self._buf += d.get("partial_json", "")
            text = partial_string(self._buf, "answer_md")
            now = self.clock()
            if text and len(text) > self._sent and now - self._last >= self.interval:
                self.sink(text[self._sent :])
                self._sent, self._last = len(text), now
