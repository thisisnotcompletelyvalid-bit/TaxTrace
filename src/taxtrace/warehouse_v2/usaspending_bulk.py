from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from taxtrace.config import get_settings
from taxtrace.warehouse_v2.download import stream_download

API_ROOT = "https://api.usaspending.gov/api/v2"
DOWNLOAD_ENDPOINTS = {
    "accounts": f"{API_ROOT}/download/accounts/",
    "awards": f"{API_ROOT}/download/awards/",
    "search": f"{API_ROOT}/download/search/",
    "contracts": f"{API_ROOT}/download/contract/",
    "assistance": f"{API_ROOT}/download/assistance/",
}
STATUS_ENDPOINT = f"{API_ROOT}/download/status/"

# USAspending can report `ready` before the generated object is retrievable from
# files.usaspending.gov. A real account-download run observed the transition
# `ready` -> `finished`; only the latter had a stable HTTP 200 archive. Keep
# `ready` deliberately out of this terminal-success set.
TERMINAL_SUCCESS_STATES = {"finished", "complete", "completed", "success", "done"}
TERMINAL_FAILURE_STATES = {"failed", "error", "cancelled", "canceled"}


@dataclass(frozen=True)
class USASpendingDownloadJob:
    kind: str
    request: dict
    response: dict

    @property
    def file_name(self) -> str | None:
        return self.response.get("file_name") or self.response.get("filename")

    @property
    def direct_url(self) -> str | None:
        return (
            self.response.get("file_url")
            or self.response.get("download_url")
            or self.response.get("url")
        )


class USASpendingBulkClient:
    """Durable client around USAspending's official asynchronous bulk-download surface.

    USAspending returns the eventual file URL when a job is submitted, before the archive is
    necessarily retrievable. TaxTrace therefore polls the status endpoint whenever a file name
    is present and only downloads after a terminal success state such as `finished`.
    """

    def __init__(self, timeout: float | None = None):
        settings = get_settings()
        self.timeout = timeout or settings.http_timeout_seconds
        self.headers = {"User-Agent": settings.user_agent}

    def submit(self, kind: str, payload: dict) -> USASpendingDownloadJob:
        if kind not in DOWNLOAD_ENDPOINTS:
            raise ValueError(f"kind must be one of {sorted(DOWNLOAD_ENDPOINTS)}")
        with httpx.Client(
            timeout=self.timeout, follow_redirects=True, headers=self.headers
        ) as client:
            response = client.post(DOWNLOAD_ENDPOINTS[kind], json=payload)
            response.raise_for_status()
            data = response.json()
        return USASpendingDownloadJob(kind=kind, request=payload, response=data)

    def status(self, file_name: str) -> dict:
        with httpx.Client(
            timeout=self.timeout, follow_redirects=True, headers=self.headers
        ) as client:
            response = client.get(STATUS_ENDPOINT, params={"file_name": file_name})
            response.raise_for_status()
            return response.json()

    def wait(
        self,
        job: USASpendingDownloadJob,
        *,
        poll_seconds: float = 5,
        max_polls: int = 240,
    ) -> dict:
        if not job.file_name:
            if job.direct_url:
                return {**job.response, "status": job.response.get("status", "complete")}
            raise RuntimeError(f"USAspending did not return a file name or URL: {job.response}")

        latest: dict = {}
        for _ in range(max_polls):
            latest = self.status(job.file_name)
            state = str(latest.get("status") or latest.get("state") or "").lower()
            if state in TERMINAL_SUCCESS_STATES:
                return {**job.response, **latest}
            if state in TERMINAL_FAILURE_STATES:
                raise RuntimeError(f"USAspending download failed: {latest}")
            time.sleep(poll_seconds)
        raise TimeoutError(
            f"USAspending download did not complete after {max_polls} polls: {latest}"
        )

    def download_completed(self, response: dict, destination: Path) -> Path:
        state = str(response.get("status") or response.get("state") or "").lower()
        if state and state not in TERMINAL_SUCCESS_STATES:
            raise RuntimeError(
                "USAspending archive is not in a terminal success state; "
                f"refusing an early download attempt: {state!r}"
            )
        url = response.get("file_url") or response.get("download_url") or response.get("url")
        if not url:
            raise RuntimeError(f"Completed USAspending response has no download URL: {response}")
        return stream_download(url, destination).path


def load_payload(path: Path) -> dict:
    return json.loads(path.read_text())
