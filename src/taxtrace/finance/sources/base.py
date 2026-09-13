from __future__ import annotations

import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

from taxtrace.config import get_settings


class SourceDownloadError(RuntimeError):
    pass


class HttpFetcher:
    def __init__(self, timeout: float | None = None, retries: int = 3):
        settings = get_settings()
        self.timeout = timeout or settings.http_timeout_seconds
        self.retries = retries
        self.headers = {"User-Agent": settings.user_agent}

    def get_bytes(self, url: str) -> bytes:
        last_exc: Exception | None = None
        for attempt in range(self.retries):
            try:
                with httpx.Client(timeout=self.timeout, follow_redirects=True, headers=self.headers) as client:
                    response = client.get(url)
                    response.raise_for_status()
                    return response.content
            except Exception as exc:  # retry network and 5xx-ish client errors uniformly
                last_exc = exc
                if attempt + 1 < self.retries:
                    time.sleep(2**attempt)
        raise SourceDownloadError(f"Unable to download {url}: {last_exc}") from last_exc

    def get_json(self, url: str, params: dict | None = None) -> dict:
        last_exc: Exception | None = None
        for attempt in range(self.retries):
            try:
                with httpx.Client(timeout=self.timeout, follow_redirects=True, headers=self.headers) as client:
                    response = client.get(url, params=params)
                    response.raise_for_status()
                    return response.json()
            except Exception as exc:
                last_exc = exc
                if attempt + 1 < self.retries:
                    time.sleep(2**attempt)
        raise SourceDownloadError(f"Unable to query {url}: {last_exc}") from last_exc


def filename_from_url(url: str, fallback: str) -> str:
    name = Path(urlparse(url).path).name
    return name or fallback
