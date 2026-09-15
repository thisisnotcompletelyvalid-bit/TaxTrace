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
REPORTING_AGENCIES_ENDPOINT = f"{API_ROOT}/reporting/agencies/overview/"
SHARD_SUBMISSION_PACE_SECONDS = 0.25

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


def _reporting_agencies_from_response(payload: dict) -> list[dict]:
    """Normalize one reporting-overview page to unique, selectable top-tier agencies."""
    by_abbreviation: dict[str, dict] = {}
    for agency in payload.get("results") or []:
        abbreviation = str(agency.get("abbreviation") or "").strip().upper()
        if not abbreviation:
            raise RuntimeError(
                "USAspending reporting overview returned an agency without an abbreviation"
            )
        by_abbreviation[abbreviation] = {
            "abbreviation": abbreviation,
            "agency_id": agency.get("agency_id"),
            "toptier_code": agency.get("toptier_code"),
            "name": agency.get("agency_name"),
        }
    return sorted(
        by_abbreviation.values(),
        key=lambda agency: (str(agency.get("toptier_code") or ""), agency["abbreviation"]),
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
    containing multiple account submission types is transparently split by submission type.

    Live FY2025 validation further proved that the all-agency File C `award_financial` component
    fails independently after roughly sixteen minutes of upstream generation. File C is therefore
    transport-sharded across the agencies USAspending reports for the exact fiscal year and period,
    using the agency abbreviations explicitly supported by the account-download API. File A/B remain
    all-agency jobs. Shard submissions are lightly paced and transient HTTP/transport failures are
    retried a bounded number of times. Every shard must still be accepted and later reach terminal
    success. Completed official archives are streamed into one local ZIP before the existing
    account-lake materializer sees them. This changes transport only, not source grain,
    fiscal-period evidence, additivity, or release provenance.
    """

    def __init__(self, timeout: float | None = None):
        settings = get_settings()
        self.timeout = timeout or settings.http_timeout_seconds
        self.headers = {"User-Agent": settings.user_agent}

    def _submit_one(self, kind: str, payload: dict) -> USASpendingDownloadJob:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                with httpx.Client(
                    timeout=self.timeout, follow_redirects=True, headers=self.headers
                ) as client:
                    response = client.post(DOWNLOAD_ENDPOINTS[kind], json=payload)
                    response.raise_for_status()
                    data = response.json()
                return USASpendingDownloadJob(kind=kind, request=payload, response=data)
            except httpx.HTTPStatusError as exc:
                last_error = exc
                status_code = exc.response.status_code
                retriable = status_code == 429 or status_code >= 500
                if not retriable or attempt == 2:
                    raise
                time.sleep(2**attempt)
            except httpx.RequestError as exc:
                # A generated-download submission can be dropped before any HTTP response is
                # received (observed as RemoteProtocolError in live validation). Retrying can
                # leave an unreferenced duplicate upstream job if the original request reached
                # USAspending, but TaxTrace records/materializes only the successfully returned
                # job, so this cannot duplicate local source facts.
                last_error = exc
                if attempt == 2:
                    raise
                time.sleep(2**attempt)
        assert last_error is not None
        raise last_error

    def reporting_agencies(self, fiscal_year: int, fiscal_period: int) -> list[dict]:
        """Return agencies with submission data for the exact fiscal year and period."""
        agencies: dict[str, dict] = {}
        page = 1
        with httpx.Client(
            timeout=self.timeout, follow_redirects=True, headers=self.headers
        ) as client:
            while True:
                response = client.get(
                    REPORTING_AGENCIES_ENDPOINT,
                    params={
                        "fiscal_year": fiscal_year,
                        "fiscal_period": fiscal_period,
                        "page": page,
                        "limit": 100,
                        "sort": "toptier_code",
                        "order": "asc",
                    },
                )
                response.raise_for_status()
                payload = response.json()
                for agency in _reporting_agencies_from_response(payload):
                    agencies[agency["abbreviation"]] = agency

                metadata = payload.get("page_metadata") or {}
                if not metadata.get("hasNext"):
                    break
                next_page = metadata.get("next")
                if next_page is None:
                    raise RuntimeError(
                        "USAspending reporting overview said more pages exist but returned no next page"
                    )
                page = int(next_page)

        if not agencies:
            raise RuntimeError(
                f"USAspending returned no reporting agencies for FY{fiscal_year} P{fiscal_period}"
            )
        return sorted(
            agencies.values(),
            key=lambda agency: (str(agency.get("toptier_code") or ""), agency["abbreviation"]),
        )

    @staticmethod
    def _job_record(job: USASpendingDownloadJob) -> dict:
        return {
            "kind": job.kind,
            "request": job.request,
            "response": job.response,
        }

    @staticmethod
    def _fiscal_period(filters: dict) -> int:
        period = filters.get("period")
        if period is not None:
            return int(period)
        quarter = filters.get("quarter")
        if quarter is not None:
            return int(quarter) * 3
        raise ValueError("File C agency sharding requires a fiscal period or quarter")

    def _submit_file_c_agency_shards(self, payload: dict) -> USASpendingDownloadJob:
        filters = payload.get("filters") or {}
        fiscal_year = int(filters["fy"])
        fiscal_period = self._fiscal_period(filters)
        agencies = self.reporting_agencies(fiscal_year, fiscal_period)
        split_jobs: list[dict] = []
        for index, agency in enumerate(agencies):
            shard_payload = json.loads(json.dumps(payload))
            shard_payload["filters"]["agency"] = agency["abbreviation"]
            try:
                shard = self._submit_one("accounts", shard_payload)
            except (httpx.HTTPError, RuntimeError) as exc:
                label = agency["abbreviation"]
                name = agency.get("name") or "unknown agency"
                raise RuntimeError(
                    f"Failed to submit FY{fiscal_year} P{fiscal_period} File C shard "
                    f"for {label} ({name}); refusing incomplete federal coverage"
                ) from exc
            split_jobs.append(self._job_record(shard))
            if len(agencies) > 5 and index < len(agencies) - 1:
                time.sleep(SHARD_SUBMISSION_PACE_SECONDS)

        synthetic_name = f"FY{fiscal_year}P{fiscal_period}_TaxTrace_AgencySharded_FileC.zip"
        return USASpendingDownloadJob(
            kind="accounts",
            request=payload,
            response={
                "status": "submitted",
                "file_name": synthetic_name,
                "file_url": f"taxtrace-split://{synthetic_name}",
                "split_strategy": "file_c_by_reporting_agency",
                "agency_count": len(agencies),
                "split_jobs": split_jobs,
            },
        )

    def submit(self, kind: str, payload: dict) -> USASpendingDownloadJob:
        if kind not in DOWNLOAD_ENDPOINTS:
            raise ValueError(f"kind must be one of {sorted(DOWNLOAD_ENDPOINTS)}")

        filters = payload.get("filters") or {}
        submission_types = filters.get("submission_types") or []
        agency = str(filters.get("agency") or "all").lower()

        # The full-year all-agency File C generator is independently unreliable upstream.
        # The reporting overview supplies the agencies that actually submitted for this FY/period;
        # abbreviations are valid account-download selectors and partition File C transport without
        # changing the underlying accounting grain.
        if (
            kind == "accounts"
            and submission_types == ["award_financial"]
            and agency == "all"
        ):
            return self._submit_file_c_agency_shards(payload)

        if kind == "accounts" and len(submission_types) > 1:
            split_jobs: list[dict] = []
            file_c_agency_count = 0
            for submission_type in submission_types:
                component_payload = json.loads(json.dumps(payload))
                component_payload["filters"]["submission_types"] = [submission_type]
                component = self.submit(kind, component_payload)
                nested = component.response.get("split_jobs") or []
                if nested:
                    split_jobs.extend(nested)
                    if submission_type == "award_financial":
                        file_c_agency_count = int(component.response.get("agency_count") or 0)
                else:
                    split_jobs.append(self._job_record(component))

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
                    "split_strategy": "submission_type_with_file_c_reporting_agency_shards",
                    "file_c_agency_count": file_c_agency_count,
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
                    component_path = temp_root / f"{archive_index:04d}_{Path(component_name).name}"
                    self.download_completed(component, component_path)
                    with ZipFile(component_path) as source:
                        for member_index, member in enumerate(source.infolist(), start=1):
                            if member.is_dir():
                                continue
                            safe_name = Path(member.filename).name
                            if not safe_name:
                                continue
                            combined_name = (
                                f"component_{archive_index:04d}/"
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
