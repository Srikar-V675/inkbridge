"""Thin HTTP client for the Inkbridge API. The MCP server's only route to state."""

import os
from typing import Any
from urllib.parse import quote

import httpx

DEFAULT_URL = "http://127.0.0.1:8000"


class ApiError(Exception):
    """An API failure phrased so an agent knows what to do next."""


class NotFound(ApiError):
    """The API answered 404: the resource does not exist (as opposed to any other failure)."""


NO_REGION = "Call list_regions or read_canvas to see valid ids."
NO_CANVAS = "Check document_id (omit it for the default canvas; GET /documents lists the canvases)."


class Conflict(ApiError):
    """The API answered 409 (for an op: it already moved on to another status)."""


def _detail_text(r: httpx.Response) -> str:
    """The API's own explanation of a refused request, short enough for a tool error."""
    try:
        body = r.json()
    except ValueError:
        return ""
    detail = body.get("detail") if isinstance(body, dict) else None
    if isinstance(detail, dict):
        return str(detail.get("msg") or detail.get("code") or detail)[:500]
    return str(detail)[:500] if detail is not None else ""


def _coded_detail(r: httpx.Response) -> str:
    """The API's message only when it sent a coded one ({code, msg}); a bare 'Not Found' is noise."""
    try:
        body = r.json()
    except ValueError:
        return ""
    detail = body.get("detail") if isinstance(body, dict) else None
    return _detail_text(r) if isinstance(detail, dict) and detail else ""


class ApiClient:
    def __init__(self, http: httpx.Client | None = None):
        self._owns_http = http is None  # a client passed in (tests) belongs to the caller
        self.http = http or httpx.Client(
            base_url=os.environ.get("INKBRIDGE_API_URL", DEFAULT_URL), timeout=30
        )
        self.default_document = os.environ.get("INKBRIDGE_DOCUMENT", "default")

    def close(self) -> None:
        if self._owns_http:
            self.http.close()

    @staticmethod
    def _status_error(code: int) -> ApiError:
        return ApiError(
            f"The Inkbridge API returned an error ({code}). "
            "Retry, or call list_regions to check the request is valid; see the server log."
        )

    @classmethod
    def _wrap(cls, exc: Exception) -> ApiError:
        if isinstance(exc, httpx.HTTPStatusError):
            return cls._status_error(exc.response.status_code)
        return ApiError(f"Unexpected response from the Inkbridge API ({exc.__class__.__name__}).")

    def _get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        not_found: str = NO_REGION,
    ) -> httpx.Response:
        query = {k: v for k, v in (params or {}).items() if v is not None}
        try:
            r = self.http.get(path, params=query)
        except httpx.HTTPError as e:
            raise ApiError(
                f"Cannot reach the Inkbridge API ({e.__class__.__name__}). "
                "Is `make dev-server` running, and is INKBRIDGE_API_URL correct?"
            ) from e
        if r.status_code == 404:
            raise NotFound(f"Not found: {path}. {not_found} {_coded_detail(r)}".strip())
        if r.status_code == 410:
            raise ApiError(_coded_detail(r) or "That chunk no longer exists; call read_canvas.")
        # By status code, not raise_for_status(): the error class differs between httpx builds
        # (Starlette's TestClient ships its own). Anything but 2xx is an ApiError, including an
        # unfollowed 3xx, which would otherwise pass as an empty image or a JSON decode error.
        if not r.is_success:
            raise self._status_error(r.status_code)
        return r

    def _post(self, path: str, body: dict, timeout: float | None = None) -> httpx.Response:
        try:
            r = self.http.post(path, json=body, **({"timeout": timeout} if timeout else {}))
        except httpx.HTTPError as e:
            raise ApiError(
                f"Cannot reach the Inkbridge API ({e.__class__.__name__}). "
                "Is `make dev-server` running, and is INKBRIDGE_API_URL correct?"
            ) from e
        if r.status_code == 404:
            raise NotFound(f"Not found: {path}. Check the canvas id (document_id).")
        if r.status_code == 422:
            raise ApiError(
                "The Inkbridge API rejected the request (422): each chunk needs an id and a hash, "
                "as stored in the note's frontmatter."
            )
        if not r.is_success:
            raise self._status_error(r.status_code)
        return r

    def _put(self, path: str, body: dict) -> httpx.Response:
        try:
            r = self.http.put(path, json=body)
        except httpx.HTTPError as e:
            raise self._wrap(e) from e
        if r.status_code == 404:
            raise NotFound(NO_CANVAS)
        if r.status_code == 422:
            raise ApiError("The Inkbridge API rejected the request (422): brief is over 4000 characters.")
        if not r.is_success:
            raise self._status_error(r.status_code)
        return r

    def _json(self, r: httpx.Response) -> Any:
        try:
            return r.json()
        except ValueError as e:
            raise self._wrap(e) from e

    def _document(self, document_id: str | None) -> str:
        return quote(document_id or self.default_document, safe="")

    def list_regions(self, document_id: str | None, kind: str | None, limit: int) -> list[dict]:
        path = f"/documents/{self._document(document_id)}/regions"
        return self._json(self._get(path, {"kind": kind, "limit": limit}, not_found=NO_CANVAS))

    def get_region(self, region_id: str) -> dict:
        return self._json(self._get(f"/regions/{quote(region_id, safe='')}"))

    def get_image(self, region_id: str) -> bytes:
        return self._get(f"/regions/{quote(region_id, safe='')}/image").content

    def get_ink(self, region_id: str) -> dict:
        return self._json(self._get(f"/regions/{quote(region_id, safe='')}/ink"))

    def search(self, query: str, limit: int, document_id: str | None = None) -> list[dict]:
        params = {"q": query, "limit": limit, "document_id": document_id or self.default_document}
        return self._json(self._get("/search", params))

    def retrieve(self, query: str, scope: str, k: int, document_id: str | None = None) -> dict:
        params = {"q": query, "scope": scope, "k": k, "document_id": document_id or self.default_document}
        return self._json(self._get("/retrieve", params, not_found=NO_CANVAS))

    def get_chunks(self, document_id: str | None) -> dict:
        path = f"/documents/{self._document(document_id)}/chunks"
        return self._json(self._get(path, not_found=NO_CANVAS))

    def get_subgraph(
        self,
        document_id: str | None,
        chunk_id: str,
        depth: int,
        direction: str,
        max_nodes: int,
        max_edges: int | None,
        mermaid: bool,
    ) -> dict:
        path = f"/documents/{self._document(document_id)}/graph/subgraph"
        params = {
            "chunk_id": chunk_id,
            "depth": depth,
            "direction": direction,
            "max_nodes": max_nodes,
            "max_edges": max_edges,
            "mermaid": str(mermaid).lower(),
        }
        return self._json(self._get(path, params, not_found=NO_CANVAS))

    def get_graph_path(
        self,
        document_id: str | None,
        from_chunk: str,
        to_chunk: str,
        direction: str,
        mermaid: bool,
    ) -> dict:
        path = f"/documents/{self._document(document_id)}/graph/path"
        params = {
            "from_chunk": from_chunk,
            "to_chunk": to_chunk,
            "direction": direction,
            "mermaid": str(mermaid).lower(),
        }
        return self._json(self._get(path, params, not_found=NO_CANVAS))

    def get_brief(self, document_id: str | None) -> dict:
        path = f"/documents/{self._document(document_id)}/brief"
        return self._json(self._get(path, not_found=NO_CANVAS))

    def set_brief(self, document_id: str | None, brief: str) -> dict:
        path = f"/documents/{self._document(document_id)}/brief"
        return self._json(self._put(path, {"brief": brief}))

    def get_changes(self, document_id: str | None, since: int | None, mark_seen: bool) -> dict:
        path = f"/documents/{self._document(document_id)}/changes"
        params = {"since": since, "mark_seen": "true" if mark_seen else None}
        return self._json(self._get(path, params, not_found=NO_CANVAS))

    def get_components(self, document_id: str | None) -> dict:
        path = f"/documents/{self._document(document_id)}/graph/components"
        return self._json(self._get(path, not_found=NO_CANVAS))

    def get_overview(
        self, document_id: str | None, max_width: int | None = None, offset: int = 0
    ) -> tuple[bytes, int | None]:
        """One overview band as PNG, and the offset of the band after it (None on the last one)."""
        path = f"/documents/{self._document(document_id)}/overview"
        r = self._get(path, {"max_width": max_width, "offset": offset}, not_found=NO_CANVAS)
        nxt = r.headers.get("X-Overview-Next")
        return r.content, int(nxt) if nxt is not None else None

    def check_sync(self, document_id: str | None, chunks: list[dict], wait_s: float) -> dict:
        # The API may wait up to wait_s for readings: give the HTTP call room beyond that.
        return self._json(
            self._post(
                f"/documents/{self._document(document_id)}/check_sync",
                {"chunks": chunks, "wait_s": wait_s},
                timeout=wait_s + 30,
            )
        )

    def _send(self, method: str, path: str, body: dict) -> Any:
        try:
            r = self.http.request(method, path, json=body)
        except httpx.HTTPError as e:
            raise ApiError(
                f"Cannot reach the Inkbridge API ({e.__class__.__name__}). "
                "Is `make dev-server` running, and is INKBRIDGE_API_URL correct?"
            ) from e
        if r.status_code == 404:
            raise NotFound(f"Not found: {path}. {_detail_text(r)}".strip())
        if r.status_code == 409:
            raise Conflict(f"Conflict on {path}: {_detail_text(r)}")
        if r.status_code == 422:
            raise ApiError(f"The Inkbridge API refused the request: {_detail_text(r)}")
        if not r.is_success:
            raise self._status_error(r.status_code)
        return self._json(r)

    def create_op(self, document_id: str | None, op_type: str, payload: dict) -> dict:
        doc = document_id or self.default_document
        return self._send(
            "POST", f"/documents/{quote(doc, safe='')}/ops", {"type": op_type, "payload": payload}
        )

    def list_questions(self, document_id: str | None, status: str | None, limit: int) -> list[dict]:
        path = f"/documents/{self._document(document_id)}/questions"
        return self._json(self._get(path, {"status": status, "limit": limit}, not_found=NO_CANVAS))[
            "questions"
        ]

    def answer_question(
        self, question_id: str, answer_md: str, sources: list[dict], canvas_text: str | None = None
    ) -> dict:
        body = {"answer_md": answer_md, "sources": sources}
        if canvas_text is not None:
            body["canvas_text"] = canvas_text
        return self._send("POST", f"/questions/{quote(question_id, safe='')}/answer", body)

    def get_op(self, op_id: str) -> dict:
        return self._json(self._get(f"/ops/{quote(op_id, safe='')}"))

    def set_op_status(self, op_id: str, status: str) -> dict:
        return self._send("PATCH", f"/ops/{quote(op_id, safe='')}", {"status": status})

    def get_sketch(self, region_id: str) -> dict:
        return self._json(self._get(f"/regions/{quote(region_id, safe='')}/sketch"))

    def get_sketch_image(self, region_id: str) -> bytes:
        return self._get(f"/regions/{quote(region_id, safe='')}/sketch.png").content

    def create_document(self, title: str) -> dict:
        return self._send("POST", "/documents", {"title": title})

    def list_tasks(self, document_id: str | None, status: str | None, limit: int) -> list[dict]:
        path = f"/documents/{self._document(document_id)}/tasks"
        return self._json(self._get(path, {"status": status, "limit": limit}, not_found=NO_CANVAS))[
            "tasks"
        ]

    def claim_task(self, task_id: str, claimed_by: str) -> dict:
        return self._send(
            "POST", f"/tasks/{quote(task_id, safe='')}/claim", {"claimed_by": claimed_by}
        )

    def complete_task(self, task_id: str, status: str, error: str | None) -> dict:
        body = {"status": status, **({"error": error} if error else {})}
        return self._send("POST", f"/tasks/{quote(task_id, safe='')}/complete", body)
