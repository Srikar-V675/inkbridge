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
        # (Starlette's TestClient ships its own), and any 4xx/5xx must become an ApiError.
        if r.is_error:
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
