"""Background recognition of chunks (tech ref 6 and 9.5, decision 0017).

A daemon thread with its own SQLite connection wakes every `poll_s`, and for each opted-in canvas
that has been idle for `idle_s` reads the active regions whose crop is fresh (png_stale = 0) and
whose content_hash has no reading yet. Readings are a cache keyed by (region, content_hash), so
unchanged or merely moved ink never calls the model. Model failures back off per (region, hash),
a 429 or timeout pauses the whole worker, and both are only logged; drawing never waits on this
thread. Run one API process: each process would run its own worker (decision 0017).

Privacy: the Gemini free tier may train on what it receives, so nothing is read unless its canvas
id is listed in INKBRIDGE_RECOGNIZE_DOCUMENTS (test and eval pages only).
"""

import logging
import os
import sqlite3
import threading
import time
from collections.abc import Callable, Iterable
from datetime import datetime

from inkbridge import db
from inkbridge.recognizer import (
    PermanentError,
    RateLimited,
    Recognition,
    Recognizer,
    RecognizerTimeout,
)

log = logging.getLogger(__name__)

Publish = Callable[[str, dict], None]


class RecognitionWorker:
    def __init__(
        self,
        recognizer: Recognizer,
        documents: Iterable[str],
        *,
        idle_s: float = 5.0,
        poll_s: float = 2.0,
        backoff_s: float = 30.0,
        backoff_max_s: float = 600.0,
        clock: Callable[[], float] = time.time,
        publish: Publish | None = None,
    ):
        self.recognizer = recognizer
        self.documents = tuple(documents)
        self.idle_s, self.poll_s = idle_s, poll_s
        self._backoff_s, self._backoff_max_s = backoff_s, backoff_max_s
        self._clock = clock
        self._publish = publish
        Key = tuple[str, str]  # (region id, content hash)
        self._failures: dict[Key, tuple[int, float]] = {}  # -> (count, retry at)
        self._unsaved: dict[Key, Recognition] = {}  # readings whose save hit a locked database
        self._paused_until = 0.0  # after a 429 or timeout no chunk is read, not just that one
        self._stop = threading.Event()
        self._wake = threading.Event()  # set by stop() and request(): skip the rest of poll_s
        self._lock = threading.Lock()
        # Chunks check_sync is waiting on, per canvas, with an expiry time: read them first and
        # without the idle delay (INK-036). The canvas list still gates them.
        self._urgent: dict[str, dict[str, float]] = {}
        self._thread: threading.Thread | None = None
        self.stopped = False  # a PermanentError (missing or rejected key) ends the worker

    @classmethod
    def from_env(cls, recognizer: Recognizer | None = None, **kw) -> "RecognitionWorker | None":
        """The configured worker, or None when no canvas is opted in or the model cannot start.

        Never raises: a bad setting logs a warning and the API starts without the worker.
        """
        raw = os.environ.get("INKBRIDGE_RECOGNIZE_DOCUMENTS", "")
        documents = tuple(d.strip() for d in raw.split(",") if d.strip())
        if not documents:
            return None
        try:
            idle = float(os.environ.get("INKBRIDGE_RECOGNIZE_IDLE_S") or 5)
        except ValueError:
            log.warning("INKBRIDGE_RECOGNIZE_IDLE_S is not a number; using 5 s")
            idle = 5.0
        if recognizer is None:
            from inkbridge.recognizer.gemini import default_recognizer

            try:
                recognizer = default_recognizer()
            except Exception as e:  # noqa: BLE001 - e.g. missing key or SDK: start without it
                log.warning("recognition worker not started: %s", e)
                return None
        return cls(recognizer, documents, idle_s=idle, **kw)

    # -- thread ---------------------------------------------------------------------------------

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._loop, name="inkbridge-recognition", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """Ask the thread to stop. A model call already in flight is not interrupted; the thread
        is a daemon, so it never holds up process exit."""
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout)

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _loop(self) -> None:
        while not self._stop.is_set() and not self.stopped:
            try:
                self.run_once()
            except Exception:
                log.exception("recognition pass failed")
            self._wake.wait(self.poll_s)
            self._wake.clear()

    # -- one pass -------------------------------------------------------------------------------

    def run_once(self) -> int:
        """Read what needs reading now; return the number of model calls made."""
        if self.stopped:
            return 0
        conn = db.connect()  # its own connection: never shares a request's transaction
        try:
            return sum(self._read_document(conn, d) for d in self.documents)
        finally:
            conn.close()

    def _idle(self, conn, document_id: str) -> bool:
        updated = db.document_updated_at(conn, document_id)
        if updated is None:
            return False
        return self._clock() - datetime.fromisoformat(updated).timestamp() >= self.idle_s

    def request(self, document_id: str, region_ids: Iterable[str], ttl_s: float = 60.0) -> bool:
        """Read these regions now, without waiting for the canvas to go idle (check_sync is
        waiting on them). False if this worker will not read them: canvas not opted in, or the
        worker is stopped or not running, so the caller need not wait."""
        if document_id not in self.documents or self.stopped or not self.is_alive():
            return False
        expires = self._clock() + ttl_s
        with self._lock:
            pending = self._urgent.setdefault(document_id, {})
            for rid in region_ids:
                pending[rid] = expires
        self._wake.set()
        return True

    def _urgent_ids(self, document_id: str) -> set[str]:
        now = self._clock()
        with self._lock:
            pending = self._urgent.get(document_id, {})
            for rid in [r for r, t in pending.items() if t <= now]:
                del pending[rid]
            return set(pending)

    def _done_urgent(self, document_id: str, region_id: str) -> None:
        with self._lock:
            self._urgent.get(document_id, {}).pop(region_id, None)

    def _may_go_on(self, conn, document_id: str, urgent: bool = False) -> bool:
        """Checked before every chunk: stop, a fatal error, a global pause or new drawing (the
        idle delay does not apply to a chunk check_sync asked for)."""
        return (
            not self._stop.is_set()
            and not self.stopped
            and self._clock() >= self._paused_until
            and (urgent or self._idle(conn, document_id))
        )

    def _read_document(self, conn, document_id: str) -> int:
        calls, recognized = 0, []
        candidates = db.recognition_candidates(conn, document_id)
        keys = {(c["id"], c["content_hash"]) for c in candidates}
        for store in (self._failures, self._unsaved):
            for key in [k for k in store if k not in keys]:
                del store[key]  # superseded ink or a gone chunk: forget it
        urgent = self._urgent_ids(document_id)
        candidates.sort(key=lambda c: c["id"] not in urgent)  # stable: asked-for chunks first
        try:
            for region in candidates:
                asked = region["id"] in urgent
                if not self._may_go_on(conn, document_id, asked):
                    break
                if asked:
                    self._done_urgent(document_id, region["id"])
                key = (region["id"], region["content_hash"])
                failed = self._failures.get(key)
                if failed and self._clock() < failed[1]:
                    continue
                reading = self._unsaved.pop(key, None)
                if reading is None:
                    # Re-checked under the lock crop uploads take: the ink may have changed
                    # since the candidates were listed (earlier calls take seconds).
                    try:
                        png = db.read_fresh_crop(conn, region["id"], region["content_hash"])
                    except sqlite3.OperationalError as e:  # locked: try it on the next pass
                        log.warning("checking %s failed (%s); will retry", key[0], e)
                        continue
                    if png is None:
                        continue
                    calls += 1
                    try:
                        reading = self.recognizer(png, None)
                    except PermanentError as e:
                        self.stopped = True
                        log.error("recognition worker stopped: %s", e)
                        break
                    except Exception as e:  # noqa: BLE001 - a model failure never reaches the editor
                        self._back_off(key, e)
                        continue
                    self._failures.pop(key, None)
                try:
                    db.save_model_reading(conn, region["id"], region["content_hash"], reading)
                except sqlite3.OperationalError as e:  # locked: keep the reading, no new call
                    conn.rollback()
                    self._unsaved[key] = reading
                    log.warning("saving the reading of %s failed (%s); will retry", key[0], e)
                    continue
                recognized.append(region["id"])
        finally:
            if recognized and self._publish is not None:
                self._publish(
                    document_id,
                    {
                        "type": "chunks.updated",
                        "version": db.get_scene(conn, document_id)[0],
                        "stale_crops": db.stale_crop_ids(conn, document_id),
                        "recognized": recognized,
                    },
                )
        return calls

    def _back_off(self, key: tuple[str, str], error: Exception) -> None:
        count = self._failures.get(key, (0, 0.0))[0] + 1
        delay = min(self._backoff_s * 2 ** (count - 1), self._backoff_max_s)
        self._failures[key] = (count, self._clock() + delay)
        if isinstance(error, RateLimited | RecognizerTimeout):
            # The provider is the problem, not this chunk: trying the next one would hit it too.
            self._paused_until = self._clock() + delay
        log.warning(
            "recognition of %s failed (%s: %s); retry in %.0f s",
            key[0],
            type(error).__name__,
            error,
            delay,
        )
