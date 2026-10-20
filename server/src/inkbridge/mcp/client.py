"""Thin HTTP client for the Inkbridge API. The MCP server's only route to state."""

import os
from typing import Any

import httpx

DEFAULT_URL = "http://127.0.0.1:8000"


class ApiError(Exception):
    """An API failure phrased so an agent knows what to do next."""


class ApiClient:
    def __init__(self, http: httpx.Client | None = None):
        self.http = http or httpx.Client(
            base_url=os.environ.get("INKBRIDGE_API_URL", DEFAULT_URL), timeout=30
        )
        self.default_document = os.environ.get("INKBRIDGE_DOCUMENT", "default")

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
            raise ApiError(f"Not found: {path}. Call list_regions to see valid region ids.")
        r.raise_for_status()
        return r

    def list_regions(self, document_id: str | None, kind: str | None, limit: int) -> list[dict]:
        doc = document_id or self.default_document
        return self._get(f"/documents/{doc}/regions", kind=kind, limit=limit).json()

    def get_region(self, region_id: str) -> dict:
        return self._get(f"/regions/{region_id}").json()

    def get_image(self, region_id: str) -> bytes:
        return self._get(f"/regions/{region_id}/image").content

    def get_ink(self, region_id: str) -> dict:
        return self._get(f"/regions/{region_id}/ink").json()

    def search(self, query: str, limit: int) -> list[dict]:
        return self._get("/search", q=query, limit=limit, document_id=self.default_document).json()
