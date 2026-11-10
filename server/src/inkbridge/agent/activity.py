"""What the agent is doing right now, per canvas (INK-198, decision 0113). In memory only."""

import threading
import time
from collections.abc import Callable

Publish = Callable[[str, dict], object]
PRIORITY = {"reading": 0, "task": 1, "answer": 2}
STALE_S = 600.0


class Activity:
    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._publish: Publish | None = None
        self._lock = threading.Lock()
        self._live: dict[str, dict[str, tuple[str, float]]] = {}  # doc -> key -> (what, since)
        self._last: dict[str, tuple] = {}

    def configure(self, publish: Publish | None) -> None:
        self._publish = publish

    def _view(self, document_id: str) -> dict:
        now = self._clock()
        live = self._live.get(document_id, {})
        for k in [k for k, (_, t) in live.items() if now - t > STALE_S]:
            del live[k]
        whats = [w for w, _ in live.values()]
        what = max(whats, key=PRIORITY.__getitem__) if whats else "reading"
        return {"type": "agent.activity", "working": bool(whats), "what": what, "count": len(whats)}

    def snapshot(self, document_id: str) -> dict:
        with self._lock:
            return self._view(document_id)

    def _changed(self, document_id: str) -> None:
        msg = self._view(document_id)
        sig = (msg["working"], msg["what"], msg["count"])
        if self._last.get(document_id, (False, "reading", 0)) == sig:
            return
        self._last[document_id] = sig
        if self._publish is not None:
            self._publish(document_id, msg)

    def begin(self, document_id: str, what: str, key: str) -> None:
        with self._lock:
            self._live.setdefault(document_id, {})[key] = (what, self._clock())
            self._changed(document_id)

    def end(self, document_id: str, key: str) -> None:
        with self._lock:
            self._live.get(document_id, {}).pop(key, None)
            self._changed(document_id)

    def on_task(self, task: dict) -> None:
        """Called wherever a task status is announced: running = in flight, anything else = over."""
        key = f"task:{task['id']}"
        if task["status"] == "running":
            self.begin(task["document_id"], "answer" if task["kind"] == "question" else "task", key)
        else:
            self.end(task["document_id"], key)


activity = Activity()
