from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

import httpx

from taxtrace.config import get_settings


@dataclass(frozen=True)
class DownloadedFile:
    path: Path
    sha256: str
    byte_count: int


def stream_download(url: str, destination: Path, *, overwrite: bool = False) -> DownloadedFile:
    """Stream a large public file to disk without holding it in memory."""
    settings = get_settings()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and not overwrite:
        digest = hashlib.sha256()
        size = 0
        with destination.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
                size += len(chunk)
        return DownloadedFile(destination, digest.hexdigest(), size)

    temporary = destination.with_suffix(destination.suffix + ".partial")
    digest = hashlib.sha256()
    size = 0
    headers = {"User-Agent": settings.user_agent}
    try:
        with httpx.Client(
            timeout=httpx.Timeout(settings.http_timeout_seconds, read=None),
            follow_redirects=True,
            headers=headers,
        ) as client:
            with client.stream("GET", url) as response:
                response.raise_for_status()
                with temporary.open("wb") as handle:
                    for chunk in response.iter_bytes(chunk_size=1024 * 1024):
                        if not chunk:
                            continue
                        handle.write(chunk)
                        digest.update(chunk)
                        size += len(chunk)
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink(missing_ok=True)
    return DownloadedFile(destination, digest.hexdigest(), size)
