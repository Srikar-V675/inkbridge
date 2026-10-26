"""Background recognition of chunks (tech ref 6 and 9.5, decision 0017).

A daemon thread with its own SQLite connection wakes every `poll_s`, and for each opted-in canvas
that has been idle for `idle_s` reads the active regions whose crop is fresh (png_stale = 0) and
whose content_hash has no reading yet. Readings are a cache keyed by (region, content_hash), so
unchanged or merely moved ink never calls the model. Model failures back off per (region, hash)
and are only logged; drawing never waits on this thread.

Privacy: the Gemini free tier may train on what it receives, so nothing is read unless its canvas
id is listed in INKBRIDGE_RECOGNIZE_DOCUMENTS (test and eval pages only).
"""

import logging
import os
import threading
import time
from collections.abc import Callable, Iterable
from datetime import datetime
from pathlib import Path

from inkbridge import db
from inkbridge.recognizer import PermanentError, Recognizer

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
        self._failures: dict[tuple[str, str], tuple[int, float]] = {}  # -> (count, retry_at)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.stopped = False  # a PermanentError (missing or rejected key) ends the worker

    @classmethod
    def from_env(cls, recognizer: Recognizer | None = None, **kw) -> "RecognitionWorker | None":
        """The configured worker, or None when no canvas is opted in or the model cannot start."""
        raw = os.environ.get("INKBRIDGE_RECOGNIZE_DOCUMENTS", "")
        documents = tuple(d.strip() for d in raw.split(",") if d.strip())
        if not documents:
            return None
        if recognizer is None:
            from inkbridge.recognizer.gemini import default_recognizer

            try:
                recognizer = default_recognizer()
            except PermanentError as e:
                log.warning("recognition worker not started: %s", e)
                return None
        idle = float(os.environ.get("INKBRIDGE_RECOGNIZE_IDLE_S", "5"))
        return cls(recognizer, documents, idle_s=idle, **kw)

    # -- thread ---------------------------------------------------------------------------------

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._loop, name="inkbridge-recognition", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
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
            self._stop.wait(self.poll_s)

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

    def _read_document(self, conn, document_id: str) -> int:
        calls, recognized = 0, []
        for region in db.recognition_candidates(conn, document_id):
            # Checked before every call: a canvas being drawn on again is left alone.
            if self._stop.is_set() or self.stopped or not self._idle(conn, document_id):
                break
            key = (region["id"], region["content_hash"])
            failed = self._failures.get(key)
            if failed and self._clock() < failed[1]:
                continue
            try:
                png = Path(region["png_path"]).read_bytes()
            except OSError:
                continue  # the crop file is missing: nothing to read until the browser saves one
            calls += 1
            try:
                reading = self.recognizer(png, None)
            except PermanentError as e:
                self.stopped = True
                log.error("recognition worker stopped: %s", e)
                break
            except Exception as e:  # noqa: BLE001 - never let a model failure reach the editor
                self._back_off(key, e)
                continue
            self._failures.pop(key, None)
            db.save_model_reading(conn, region["id"], region["content_hash"], reading)
            recognized.append(region["id"])
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
        log.warning(
            "recognition of %s failed (%s: %s); retry in %.0f s",
            key[0],
            type(error).__name__,
            error,
            delay,
        )
