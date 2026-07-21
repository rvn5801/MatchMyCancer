"""ClinicalTrials.gov v2 API client.

Provides async access to the ClinicalTrials.gov REST API for searching
studies by condition, biomarker, and other filters.

API docs: https://clinicaltrials.gov/data-api/api

Key design decisions:
  - Async via httpx.AsyncClient — FastAPI-compatible, no thread blocking
  - Context manager for lifecycle — client is created, used, then closed
  - Retry on transient errors (5xx, network timeouts)
  - Pydantic models for both request params and response parsing
  - Rate limiting via configurable delay between requests
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

import httpx
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

BASE_URL = "https://clinicaltrials.gov/api/v2"
DEFAULT_TIMEOUT = 30.0
MAX_RETRIES = 2
RETRY_DELAY = 2.0

# Common trial statuses to filter by
RECRUITING_STATUSES = ["RECRUITING", "NOT_YET_RECRUITING", "ACTIVE_NOT_RECRUITING"]


# ── Response models ─────────────────────────────────────────────────────────


class TrialLocation(BaseModel):
    """A trial site location."""
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None


class TrialSummary(BaseModel):
    """Essential fields extracted from a trial result."""
    nct_id: str = ""
    title: str = ""
    status: str = ""
    phases: List[str] = Field(default_factory=list)
    description: str = ""
    eligibility: str = ""
    locations: List[Dict[str, Any]] = Field(default_factory=list)
    conditions: List[str] = Field(default_factory=list)
    interventions: List[str] = Field(default_factory=list)
    # Freshness fields (added by trial_matcher enrichment)
    verified_on: Optional[str] = None
    tier: str = "MEDIUM"  # HIGHEST, MEDIUM, LOW
    is_stale: bool = False
    # AI eligibility fields (added by trial_matcher for top-N trials)
    eligibility_summary: Optional[List[str]] = None
    eligibility_assessment: Optional[str] = None  # LIKELY/POSSIBLY/UNLIKELY ELIGIBLE
    eligibility_reasoning: Optional[str] = None

    @classmethod
    def from_api_response(cls, trial: Dict[str, Any]) -> "TrialSummary":
        """Parse the nested ClinicalTrials.gov response into a flat summary."""
        proto = trial.get("protocolSection", {})
        ident = proto.get("identificationModule", {})
        status_mod = proto.get("statusModule", {})
        desc = proto.get("descriptionModule", {})
        elig = proto.get("eligibilityModule", {})
        design = proto.get("designModule", {})
        conditions_mod = proto.get("conditionsModule", {})
        arms = proto.get("armsInterventionsModule", {})
        loc = proto.get("contactsLocationsModule", {})

        # Extract conditions
        conditions = conditions_mod.get("conditions", [])

        # Extract interventions
        interventions = []
        for arm in arms.get("interventions", []):
            if arm.get("type") == "DRUG":
                interventions.append(arm.get("name", ""))

        # Extract locations
        locations = []
        for location in loc.get("locations", [])[:5]:
            facility = location.get("facility", "")
            city = location.get("city", "")
            state = location.get("state", "")
            country = location.get("country", "")
            locations.append({
                "facility": facility,
                "city": city,
                "state": state,
                "country": country,
            })

        return cls(
            nct_id=ident.get("nctId", ""),
            title=ident.get("briefTitle", ""),
            status=status_mod.get("overallStatus", ""),
            phases=list(design.get("phases", [])),
            description=(desc.get("briefSummary") or "")[:800],
            eligibility=(elig.get("eligibilityCriteria") or "")[:500],
            locations=locations,
            conditions=conditions,
            interventions=interventions,
        )


# ── Client ──────────────────────────────────────────────────────────────────


class ClinicalTrialsClient:
    """Async client for ClinicalTrials.gov v2 API.

    Usage:
        async with ClinicalTrialsClient() as client:
            studies = await client.search_studies("lung cancer")
            for study in studies:
                print(study.title)
    """

    def __init__(
        self,
        base_url: str = BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        self.base_url = base_url
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self):
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout,
            headers={"Accept": "application/json"},
        )
        return self

    async def __aexit__(self, *args):
        if self._client:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError(
                "Client not initialized. Use 'async with ClinicalTrialsClient() as client:'"
            )
        return self._client

    # ── Public API ──────────────────────────────────────────────────────

    async def search_studies(
        self,
        condition: str,
        intervention: Optional[str] = None,
        status: Optional[List[str]] = None,
        page_size: int = 20,
    ) -> List[TrialSummary]:
        """Search for clinical trials by condition and optional filters.

        Args:
            condition: Disease/condition (e.g., "lung cancer").
            intervention: Optional drug or intervention name.
            status: Trial statuses to include. Defaults to recruiting trials.
            page_size: Results per page (max 100).

        Returns:
            List of TrialSummary objects.
        """
        if status is None:
            status = RECRUITING_STATUSES

        params: Dict[str, Any] = {
            "query.cond": condition,
            "pageSize": min(page_size, 100),
            "format": "json",
            "countTotal": "true",
        }
        if intervention:
            params["query.intr"] = intervention
        if status:
            params["filter.overallStatus"] = "|".join(status)

        logger.info(
            "Searching trials: condition=%s intervention=%s",
            condition,
            intervention or "none",
        )

        data = await self._get("/studies", params=params)
        studies = data.get("studies", [])

        logger.info("Found %d trials for '%s'", len(studies), condition)
        return [TrialSummary.from_api_response(s) for s in studies]

    async def search_by_biomarker(
        self,
        biomarker: str,
        condition: str,
        page_size: int = 20,
    ) -> List[TrialSummary]:
        """Search trials matching a specific biomarker + condition.

        Uses full-text search to find biomarker mentions in trial
        descriptions and eligibility criteria.

        Args:
            biomarker: Gene/biomarker name (e.g., "EGFR", "BRAF V600E").
            condition: Cancer type (e.g., "lung cancer").
            page_size: Results per page.

        Returns:
            List of matching TrialSummary objects.
        """
        params: Dict[str, Any] = {
            "query.term": f"{biomarker} {condition}",
            "pageSize": min(page_size, 100),
            "format": "json",
        }

        logger.info(
            "Searching trials by biomarker: %s + %s", biomarker, condition
        )

        data = await self._get("/studies", params=params)
        studies = data.get("studies", [])

        logger.info(
            "Biomarker search '%s': %d results", biomarker, len(studies)
        )
        return [TrialSummary.from_api_response(s) for s in studies]

    async def get_study(self, nct_id: str) -> Dict[str, Any]:
        """Get full details for a specific trial by NCT ID.

        Args:
            nct_id: ClinicalTrials.gov identifier (e.g., "NCT01234567").

        Returns:
            Full API response dict for the study.
        """
        logger.info("Fetching study: %s", nct_id)
        return await self._get(f"/studies/{nct_id}")

    # ── Internal ────────────────────────────────────────────────────────

    async def _get(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """GET request with retry logic."""
        last_error: Optional[Exception] = None

        for attempt in range(MAX_RETRIES + 1):
            try:
                response = await self.client.get(path, params=params)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                # Don't retry 4xx — the request itself is invalid
                if 400 <= e.response.status_code < 500:
                    logger.error(
                        "Client error %d for %s: %s",
                        e.response.status_code,
                        path,
                        e.response.text[:200],
                    )
                    raise
                last_error = e
                logger.warning(
                    "Server error %d for %s (attempt %d/%d)",
                    e.response.status_code,
                    path,
                    attempt + 1,
                    MAX_RETRIES + 1,
                )
            except (httpx.TimeoutException, httpx.NetworkError) as e:
                last_error = e
                logger.warning(
                    "Network error for %s (attempt %d/%d): %s",
                    path,
                    attempt + 1,
                    MAX_RETRIES + 1,
                    e,
                )

            if attempt < MAX_RETRIES:
                await asyncio.sleep(RETRY_DELAY * (attempt + 1))

        logger.error("All %d retries failed for %s", MAX_RETRIES + 1, path)
        raise last_error  # type: ignore[misc]
