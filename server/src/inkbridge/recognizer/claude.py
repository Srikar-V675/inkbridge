"""Claude Haiku reader on the Claude subscription (INK-185, decision 0104).

One long-lived `claude -p` process speaks stream-json: each chunk image is one user line, the
answer is the next `result` event. The process is reset after `max_requests` reads, or on any
error or timeout, to bound context growth. Claude does not train on subscription content, so
unlike Gemini this reader may be pointed at personal canvases (the canvas list still gates it).
"""

import base64
import json
import logging
import os
import queue
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable
from typing import Any

from inkbridge.recognizer import (
    PermanentError,
    RateLimited,
    Recognition,
    RecognizerError,
    RecognizerTimeout,
    parse_reading,
)
from inkbridge.recognizer.gemini import PROMPT

SYSTEM = "You transcribe handwriting images. Reply with JSON only, no commentary."
MODEL_NAME = "claude-haiku"

usage_log = logging.getLogger("inkbridge.recognizer.usage")
log = logging.getLogger(__name__)


class ClaudeNotFound(PermanentError):
    """The `claude` binary is not installed or not on PATH (INKBRIDGE_CLAUDE_BIN)."""


def _spawn_for(model: str) -> Callable[[], Any]:
    def spawn():
        return subprocess.Popen(
            [
                os.environ.get("INKBRIDGE_CLAUDE_BIN", "claude"),
                "-p",
                "--input-format",
                "stream-json",
                "--output-format",
                "stream-json",
                "--verbose",
                "--model",
                model,
                "--tools",
                "",
                "--strict-mcp-config",
                "--disable-slash-commands",
                "--no-session-persistence",
                "--setting-sources",
                "",
                "--system-prompt",
                SYSTEM,
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            cwd=tempfile.gettempdir(),
        )

    return spawn


class _Proc:
    """A spawned process plus a thread that feeds its stdout lines into a queue (None = EOF)."""

    def __init__(self, proc: Any):
        self.proc = proc
        self.lines: queue.Queue[str | None] = queue.Queue()
        threading.Thread(target=self._pump, name="inkbridge-claude-reader", daemon=True).start()

    def _pump(self) -> None:
        try:
            for line in self.proc.stdout:
                self.lines.put(line)
        except Exception:  # noqa: BLE001 - a closed pipe ends the reader
            pass
        finally:
            self.lines.put(None)

    def kill(self) -> None:
        try:
            self.proc.kill()
        except Exception:  # noqa: BLE001
            pass


class ClaudeRecognizer:
    def __init__(
        self,
        model: str = "haiku",
        *,
        spawn: Callable[[], Any] | None = None,
        timeout: float = 60.0,
        max_requests: int = 25,
    ):
        self.model = MODEL_NAME
        self._spawn = spawn or _spawn_for(model)
        self._timeout, self._max_requests = timeout, max_requests
        self._lock = threading.Lock()
        self._proc: _Proc | None = None
        self._served = 0  # reads answered by the current process
        self._count = 0  # reads answered since start, for the usage log

    def __repr__(self) -> str:
        return f"ClaudeRecognizer(model={self.model!r})"

    def __call__(self, png: bytes, hint: str | None) -> Recognition:
        text = PROMPT if not hint else f"{PROMPT}\nContext hint: {hint}"
        message = {
            "type": "user",
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": base64.b64encode(png).decode(),
                        },
                    },
                    {"type": "text", "text": text},
                ],
            },
        }
        with self._lock:
            try:
                raw = self._ask(json.dumps(message) + "\n")
            except BaseException:
                self._drop()
                raise
            self._served += 1
            if self._served >= self._max_requests:
                self._drop()
        return parse_reading(raw, self.model)

    def _drop(self) -> None:
        if self._proc is not None:
            self._proc.kill()
        self._proc, self._served = None, 0

    def _ask(self, line: str) -> str:
        if self._proc is None:
            try:
                self._proc = _Proc(self._spawn())
            except FileNotFoundError:
                raise ClaudeNotFound("claude binary not found (INKBRIDGE_CLAUDE_BIN)") from None
            except OSError as e:
                raise RecognizerError(f"could not start claude: {type(e).__name__}") from None
        proc = self._proc
        try:
            proc.proc.stdin.write(line)
            proc.proc.stdin.flush()
        except (OSError, ValueError):
            raise RecognizerError("claude process closed its input") from None
        deadline = time.monotonic() + self._timeout
        resets_at: float | None = None
        while True:
            try:
                got = proc.lines.get(timeout=max(deadline - time.monotonic(), 0))
            except queue.Empty:
                raise RecognizerTimeout("claude did not answer in time") from None
            if got is None:
                raise RecognizerError("claude process ended without a result")
            try:
                event = json.loads(got)
            except ValueError:
                continue
            if not isinstance(event, dict):
                continue
            if event.get("type") == "rate_limit_event":
                resets_at = _resets_at(event) or resets_at
                continue
            if event.get("type") != "result":
                continue
            return self._finish(event, resets_at)

    def _finish(self, event: dict, resets_at: float | None) -> str:
        result = event.get("result")
        text = result if isinstance(result, str) else ""
        if event.get("is_error"):
            lowered = text.lower()
            if "usage limit" in lowered or "rate limit" in lowered:
                after = resets_at - time.time() if resets_at else None
                raise RateLimited(text[:200], after if after and after > 0 else None)
            raise RecognizerError(f"claude error: {text[:200]}")
        self._count += 1
        usage = event.get("usage") if isinstance(event.get("usage"), dict) else {}
        usage_log.info(
            "claude read #%d in=%s out=%s cost=%s",
            self._count,
            usage.get("input_tokens"),
            usage.get("output_tokens"),
            event.get("total_cost_usd"),
        )
        return text


def _resets_at(event: dict) -> float | None:
    info = event.get("rate_limit_info")
    value = info.get("resetsAt") if isinstance(info, dict) else event.get("resetsAt")
    return float(value) if isinstance(value, int | float) else None


_default: ClaudeRecognizer | None = None
_default_lock = threading.Lock()


def default_recognizer() -> ClaudeRecognizer:
    global _default
    with _default_lock:
        if _default is None:
            _default = ClaudeRecognizer()
        return _default
