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
ACCOUNT_AGENCIES_ENDPOINT = f"{API_ROOT}/bulk_download/list_agencies/"
SHARD_SUBMISSION_PACE_SECONDS = 2.0
SHARD_INITIAL_SETTLE_SECONDS = 2.0

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
    """Normalize one reporting-overview page to agencies with a submission in that period."""
    by_abbreviation: dict[str, dict] = {}
    for agency in payload.get("results") or []:
        # The reporting overview intentionally returns broader DABS agencies with null
        # period-specific fields when they did not submit in the requested period.
        # `recent_publication_date` is populated only when that period has a submission.
        if not agency.get("recent_publication_date"):
            continue
        abbreviation = str(agency.get("abbreviation") or "").strip().upper()
        if not abbreviation:
            raise RuntimeError(
                "USAspending reporting overview returned a current-period agency "
                "without an abbreviation"
            )
        toptier_code = str(agency.get("toptier_code") or "").strip()
        if not toptier_code:
            raise RuntimeError(
                "USAspending reporting overview returned a current-period agency "
                "without a toptier code"
            )
        by_abbreviation[abbreviation] = {
            "abbreviation": abbreviation,
            "toptier_code": toptier_code,
            "name": agency.get("agency_name"),
        }
    return sorted(
        by_abbreviation.values(),
        key=lambda agency: (agency["toptier_code"], agency["abbreviation"]),
    )


def _account_agency_ids_from_response(payload: dict) -> dict[str, int]:
    """Return {toptier_code: toptier_agency_id} from the bulk account-agency reference."""
    raw_agencies = payload.get("agencies") or []
    if isinstance(raw_agencies, dict):
        agencies = [
            *(raw_agencies.get("cfo_agencies") or []),
            *(raw_agencies.get("other_agencies") or []),
        ]
    elif isinstance(raw_agencies, list):
        agencies = raw_agencies
    else:
        raise RuntimeError("USAspending account-agency reference returned an invalid agencies shape")

    by_code: dict[str, int] = {}
    for agency in agencies:
        toptier_code = str(agency.get("toptier_code") or "").strip()
        raw_id = agency.get("toptier_agency_id")
        if not toptier_code or raw_id is None:
            raise RuntimeError(
                "USAspending account-agency reference returned an agency without "
                "toptier_code/toptier_agency_id"
            )
        try:
            toptier_agency_id = int(raw_id)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                f"USAspending returned invalid toptier_agency_id {raw_id!r} "
                f"for toptier code {toptier_code}"
            ) from exc
        prior = by_code.get(toptier_code)
        if prior is not None and prior != toptier_agency_id:
            raise RuntimeError(
                f"USAspending returned conflicting toptier agency IDs for {toptier_code}: "
                f"{prior} and {toptier_agency_id}"
            )
        by_code[toptier_code] = toptier_agency_id

    if not by_code:
        raise RuntimeError("USAspending returned no account agencies")
    return by_code


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
    transport-sharded across agencies with actual submissions for the exact fiscal year and period.
    That reporting universe is strictly joined by `toptier_code` to USAspending's account-agency
    reference, which supplies the numeric `toptier_agency_id` accepted by the account-download
    filter. File A/B remain all-agency jobs. Shard submissions are lightly paced and transient
    HTTP/transport failures are retried a bounded number of times. Every shard must still be
    accepted and later reach terminal success. Completed official archives are streamed into one
    local ZIP before the existing account-lake materializer sees them. This changes transport only,
    not source grain, fiscal-period evidence, additivity, or release provenance.
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
        """Return agencies with an actual submission for the exact fiscal year and period."""
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
                f"USAspending returned no current-period reporting agencies "
                f"for FY{fiscal_year} P{fiscal_period}"
            )
        return sorted(
            agencies.values(),
            key=lambda agency: (agency["toptier_code"], agency["abbreviation"]),
        )

    def account_agency_ids(self) -> dict[str, int]:
        """Return the official internal toptier agency IDs accepted by account downloads."""
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                with httpx.Client(
                    timeout=self.timeout, follow_redirects=True, headers=self.headers
                ) as client:
                    response = client.post(
                        ACCOUNT_AGENCIES_ENDPOINT,
                        json={"type": "account_agencies"},
                    )
                    response.raise_for_status()
                    return _account_agency_ids_from_response(response.json())
            except httpx.HTTPStatusError as exc:
                last_error = exc
                status_code = exc.response.status_code
                retriable = status_code == 429 or status_code >= 500
                if not retriable or attempt == 2:
                    raise
                time.sleep(2**attempt)
            except httpx.RequestError as exc:
                last_error = exc
                if attempt == 2:
                    raise
                time.sleep(2**attempt)
        assert last_error is not None
        raise last_error

    def current_reporting_account_agencies(
        self,
        fiscal_year: int,
        fiscal_period: int,
    ) -> list[dict]:
        """Join exact-period reporting agencies to valid account-download toptier IDs."""
        reporting = self.reporting_agencies(fiscal_year, fiscal_period)
        account_ids = self.account_agency_ids()
        joined: list[dict] = []
        missing: list[str] = []
        for agency in reporting:
            toptier_code = agency["toptier_code"]
            toptier_agency_id = account_ids.get(toptier_code)
            if toptier_agency_id is None:
                missing.append(f"{toptier_code}:{agency['abbreviation']}")
                continue
            joined.append(
                {
                    **agency,
                    "toptier_agency_id": toptier_agency_id,
                }
            )
        if missing:
            raise RuntimeError(
                "USAspending current-period reporting agencies are missing from the "
                "account-agency reference; refusing incomplete File C coverage: "
                + ", ".join(sorted(missing))
            )
        return joined

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
        """Generate complete File C coverage with only one agency job outstanding at a time.

        USAspending's account generator has repeatedly dropped Treasury File C submissions
        when TaxTrace first queued a fleet of agency jobs. The identical Treasury Federal
        Account request succeeds when generated in isolation. Keep the source partition
        unchanged, but serialize each current-period agency through submit -> terminal
        success before creating the next job. Every agency must still succeed.
        """
        filters = payload.get("filters") or {}
        fiscal_year = int(filters["fy"])
        fiscal_period = self._fiscal_period(filters)
        agencies = self.current_reporting_account_agencies(fiscal_year, fiscal_period)
        completed_responses: list[dict] = []

        for index, agency in enumerate(agencies):
            shard_payload = json.loads(json.dumps(payload))
            shard_payload["filters"]["agency"] = str(agency["toptier_agency_id"])
            if index > 0:
                time.sleep(SHARD_SUBMISSION_PACE_SECONDS)
            try:
                shard = self._submit_one("accounts", shard_payload)
                completed = self.wait(shard)
            except (httpx.HTTPError, RuntimeError, TimeoutError) as exc:
                label = agency["abbreviation"]
                name = agency.get("name") or "unknown agency"
                raise RuntimeError(
                    f"Failed to generate FY{fiscal_year} P{fiscal_period} File C shard "
                    f"for {label} ({name}, toptier_agency_id={agency['toptier_agency_id']}); "
                    "refusing incomplete federal coverage"
                ) from exc
            completed_responses.append(completed)

        synthetic_name = f"FY{fiscal_year}P{fiscal_period}_TaxTrace_AgencySharded_FileC.zip"
        return USASpendingDownloadJob(
            kind="accounts",
            request=payload,
            response={
                "status": "finished",
                "file_name": synthetic_name,
                "file_url": f"taxtrace-split://{synthetic_name}",
                "split_strategy": "file_c_sequential_current_reporting_toptier_agency_id",
                "agency_count": len(agencies),
                "split_responses": completed_responses,
            },
        )

    def submit(self, kind: str, payload: dict) -> USASpendingDownloadJob:
        if kind not in DOWNLOAD_ENDPOINTS:
            raise ValueError(f"kind must be one of {sorted(DOWNLOAD_ENDPOINTS)}")

        filters = payload.get("filters") or {}
        submission_types = filters.get("submission_types") or []
        agency = str(filters.get("agency") or "all").lower()

        # The full-year all-agency File C generator is independently unreliable upstream.
        # The reporting overview establishes exact-period coverage; the account-agency reference
        # supplies the numeric toptier_agency_id selector for each current reporting agency.
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
                    "split_strategy": (
                        "submission_type_with_file_c_current_reporting_toptier_agency_id_shards"
                    ),
                    "file_c_agency_count": file_c_agency_count,
                    "split_jobs": split_jobs,
                },
            )

        return self._submit_one(kind, payload)

    def status(self, file_name: str) -> dict:
        """Fetch one USAspending job status with bounded transient transport retries."""
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                with httpx.Client(
                    timeout=self.timeout, follow_redirects=True, headers=self.headers
                ) as client:
                    response = client.get(STATUS_ENDPOINT, params={"file_name": file_name})
                    response.raise_for_status()
                    return response.json()
            except httpx.HTTPStatusError as exc:
                last_error = exc
                code = exc.response.status_code
                retriable = code == 429 or code >= 500
                if not retriable or attempt == 2:
                    raise
                time.sleep(2**attempt)
            except httpx.RequestError as exc:
                last_error = exc
                if attempt == 2:
                    raise
                time.sleep(2**attempt)
        assert last_error is not None
        raise last_error

    def wait(
        self,
        job: USASpendingDownloadJob,
        *,
        poll_seconds: float = 5,
        max_polls: int = 240,
    ) -> dict:
        split_responses = job.response.get("split_responses") or []
        if split_responses:
            state = str(job.response.get("status") or "").lower()
            if state in TERMINAL_SUCCESS_STATES:
                return job.response

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
