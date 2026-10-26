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


class Conflict(ApiError):
    """The API answered 409 (for an op: it already moved on to another status)."""


def _detail_text(r: httpx.Response) -> str:
    """The API's own explanation of a refused request, short enough for a tool error."""
    try:
        detail = r.json().get("detail")
    except ValueError:
        return ""
    if isinstance(detail, dict):
        return str(detail.get("msg") or detail.get("code") or detail)[:500]
    return str(detail)[:500]


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

    def _get(self, path: str, **params: Any) -> httpx.Response:
        params = {k: v for k, v in params.items() if v is not None}
        try:
            r = self.http.get(path, params=params)
        except httpx.HTTPError as e:
            raise ApiError(
                f"Cannot reach the Inkbridge API ({e.__class__.__name__}). "
                "Is `make dev-server` running, and is INKBRIDGE_API_URL correct?"
            ) from e
        if r.status_code == 404:
            raise NotFound(f"Not found: {path}. Call list_regions to see valid region ids.")
        # By status code, not raise_for_status(): the error class differs between httpx builds
        # (Starlette's TestClient ships its own). Anything but 2xx is an ApiError, including an
        # unfollowed 3xx, which would otherwise pass as an empty image or a JSON decode error.
        if not r.is_success:
            raise self._status_error(r.status_code)
        return r

    def _json(self, r: httpx.Response) -> Any:
        try:
            return r.json()
        except ValueError as e:
            raise self._wrap(e) from e

    def list_regions(self, document_id: str | None, kind: str | None, limit: int) -> list[dict]:
        doc = document_id or self.default_document
        return self._json(
            self._get(f"/documents/{quote(doc, safe='')}/regions", kind=kind, limit=limit)
        )

    def get_region(self, region_id: str) -> dict:
        return self._json(self._get(f"/regions/{quote(region_id, safe='')}"))

    def get_image(self, region_id: str) -> bytes:
        return self._get(f"/regions/{quote(region_id, safe='')}/image").content

    def get_ink(self, region_id: str) -> dict:
        return self._json(self._get(f"/regions/{quote(region_id, safe='')}/ink"))

    def search(self, query: str, limit: int) -> list[dict]:
        return self._json(
            self._get("/search", q=query, limit=limit, document_id=self.default_document)
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

    def get_op(self, op_id: str) -> dict:
        return self._json(self._get(f"/ops/{quote(op_id, safe='')}"))

    def set_op_status(self, op_id: str, status: str) -> dict:
        return self._send("PATCH", f"/ops/{quote(op_id, safe='')}", {"status": status})

    def get_sketch(self, region_id: str) -> dict:
        return self._json(self._get(f"/regions/{quote(region_id, safe='')}/sketch"))

    def get_sketch_image(self, region_id: str) -> bytes:
        return self._get(f"/regions/{quote(region_id, safe='')}/sketch.png").content
