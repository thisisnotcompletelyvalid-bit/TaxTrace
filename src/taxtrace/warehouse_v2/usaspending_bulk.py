from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile

import httpx

from taxtrace.config import get_settings
from taxtrace.warehouse_v2.download import stream_download

API_ROOT = "https://api.usaspending.gov/api/v2"
DOWNLOAD_ENDPOINTS = {
    "accounts": f"{API_ROOT}/download/accounts/",
    "awards": f"{API_ROOT}/download/awards/",
    "bulk_awards": f"{API_ROOT}/bulk_download/awards/",
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
    """Durable client around USAspending's official asynchronous download surfaces.

    `accounts` targets the DATA Act account download. `bulk_awards` targets the
    Custom Award Data Download route, which can emit prime award (D1/D2-shaped)
    and subaward (File F-shaped) data. The plain `awards` kind is retained for
    the Advanced Search award-download route because its request semantics differ.

    USAspending returns the eventual file URL when a job is submitted, before the archive is
    necessarily retrievable. TaxTrace therefore polls the status endpoint whenever a file name
    is present and only downloads after a terminal success state such as `finished`.

    Full-year all-agency account requests are large enough that USAspending can accept the job,
    spend many minutes generating it, and then fail server-side. A/B/C are separate DATA Act
    submission grains and TaxTrace already materializes them into separate datasets, so a request
    containing multiple account submission types is transparently split into one official job per
    submission type. The completed official archives are streamed into one local ZIP before the
    existing account-lake materializer sees them. This changes transport only, not source grain or
    release provenance.
    """

    def __init__(self, timeout: float | None = None):
        settings = get_settings()
        self.timeout = timeout or settings.http_timeout_seconds
        self.headers = {"User-Agent": settings.user_agent}

    def _submit_one(self, kind: str, payload: dict) -> USASpendingDownloadJob:
        with httpx.Client(
            timeout=self.timeout, follow_redirects=True, headers=self.headers
        ) as client:
            response = client.post(DOWNLOAD_ENDPOINTS[kind], json=payload)
            response.raise_for_status()
            data = response.json()
        return USASpendingDownloadJob(kind=kind, request=payload, response=data)

    def submit(self, kind: str, payload: dict) -> USASpendingDownloadJob:
        if kind not in DOWNLOAD_ENDPOINTS:
            raise ValueError(f"kind must be one of {sorted(DOWNLOAD_ENDPOINTS)}")

        filters = payload.get("filters") or {}
        submission_types = filters.get("submission_types") or []
        if kind == "accounts" and len(submission_types) > 1:
            split_jobs: list[dict] = []
            for submission_type in submission_types:
                component_payload = json.loads(json.dumps(payload))
                component_payload["filters"]["submission_types"] = [submission_type]
                component = self._submit_one(kind, component_payload)
                split_jobs.append(
                    {
                        "kind": component.kind,
                        "request": component.request,
                        "response": component.response,
                    }
                )
            fiscal_year = filters.get("fy", "unknown")
            period = filters.get("period") or filters.get("quarter") or "unknown"
            synthetic_name = f"FY{fiscal_year}P{period}_TaxTrace_Split_AccountData.zip"
            return USASpendingDownloadJob(
                kind=kind,
                request=payload,
                response={
                    "status": "submitted",
                    "file_name": synthetic_name,
                    "file_url": f"taxtrace-split://{synthetic_name}",
                    "split_jobs": split_jobs,
                },
            )

        return self._submit_one(kind, payload)

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
        split_jobs = job.response.get("split_jobs") or []
        if split_jobs:
            completed: list[dict] = []
            for item in split_jobs:
                component = USASpendingDownloadJob(
                    kind=item["kind"],
                    request=item["request"],
                    response=item["response"],
                )
                completed.append(
                    self.wait(
                        component,
                        poll_seconds=poll_seconds,
                        max_polls=max_polls,
                    )
                )
            return {
                **job.response,
                "status": "finished",
                "split_responses": completed,
            }

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

    def _combine_split_archives(self, responses: list[dict], destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix="taxtrace-usaspending-", dir=destination.parent) as temp_dir:
            temp_root = Path(temp_dir)
            with ZipFile(
                destination,
                "w",
                compression=ZIP_DEFLATED,
                compresslevel=1,
                allowZip64=True,
            ) as combined:
                for archive_index, component in enumerate(responses, start=1):
                    component_name = (
                        component.get("file_name")
                        or component.get("filename")
                        or f"component_{archive_index:02d}.zip"
                    )
                    component_path = temp_root / Path(component_name).name
                    self.download_completed(component, component_path)
                    with ZipFile(component_path) as source:
                        for member_index, member in enumerate(source.infolist(), start=1):
                            if member.is_dir():
                                continue
                            safe_name = Path(member.filename).name
                            if not safe_name:
                                continue
                            combined_name = (
                                f"component_{archive_index:02d}/"
                                f"{member_index:04d}_{safe_name}"
                            )
                            with source.open(member) as source_file, combined.open(
                                combined_name,
                                "w",
                                force_zip64=True,
                            ) as target_file:
                                shutil.copyfileobj(source_file, target_file, length=1024 * 1024)
        return destination

    def download_completed(self, response: dict, destination: Path) -> Path:
        split_responses = response.get("split_responses") or []
        if split_responses:
            return self._combine_split_archives(split_responses, destination)

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
