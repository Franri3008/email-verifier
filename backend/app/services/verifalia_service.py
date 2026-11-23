import asyncio
import logging
import time
from collections.abc import Sequence
from urllib.parse import urljoin, urlparse

import httpx

from app.core.config import Settings
from app.exceptions.handlers import ServiceError
from app.models.schemas.verification import Quality, VerificationResult
from app.services.retry import send_free, send_paid


logger = logging.getLogger(__name__)


class VerifaliaService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def verify_many(
        self, emails: Sequence[str], quality: Quality
    ) -> dict[str, VerificationResult]:
        unique = list(
            dict.fromkeys(email.strip().lower() for email in emails if email.strip())
        )
        if not unique:
            return {}
        if not self._settings.has_verifalia_credentials:
            raise ServiceError(
                "Verifalia credentials are not configured. Add VERIFALIA_USERNAME and "
                "VERIFALIA_PASSWORD (or VERIFALIA_BEARER_TOKEN) to .env.",
                status_code=503,
            )

        verified: dict[str, VerificationResult] = {}
        async with httpx.AsyncClient(
            timeout=self._settings.request_timeout_seconds,
            follow_redirects=False,
            auth=self._auth(),
            headers=self._headers(),
        ) as client:
            for offset in range(0, len(unique), self._settings.verifalia_chunk_size):
                chunk = unique[offset : offset + self._settings.verifalia_chunk_size]
                entries = await self._submit_and_wait(client, chunk, quality)
                for entry in entries:
                    email = str(entry.get("inputData") or "").strip().lower()
                    if email:
                        verified[email] = self._to_result(email, entry)

        for email in unique:
            if email not in verified:
                verified[email] = VerificationResult(
                    email=email,
                    result="Unverified",
                    classification="Unknown",
                    status="NoResultReturned",
                )
        return verified

    async def _submit_and_wait(
        self,
        client: httpx.AsyncClient,
        emails: Sequence[str],
        quality: Quality,
    ) -> list[dict[str, object]]:
        body = {
            "entries": [
                {"inputData": email, "custom": str(index)}
                for index, email in enumerate(emails)
            ],
            "quality": quality.value,
            "deduplication": "Off",
            "name": "Email check",
        }
        try:
            response = await send_paid(
                lambda: client.post(
                    f"{self._settings.verifalia_base_url}/email-validations",
                    params={"waitTime": 30_000},
                    json=body,
                ),
                "Verifalia",
            )
            response.raise_for_status()
            snapshot = response.json()
            location = response.headers.get("location")
            started = time.monotonic()
            while response.status_code == 202 or not self._is_complete(snapshot):
                if (
                    time.monotonic() - started
                    > self._settings.verification_timeout_seconds
                ):
                    raise ServiceError(
                        "Verifalia is still processing this job. Try a smaller file or retry later.",
                        status_code=504,
                    )
                job_url = (
                    urljoin(self._settings.verifalia_base_url, location)
                    if location
                    else self._job_url(snapshot)
                )
                if not job_url:
                    raise ServiceError("Verifalia did not return a job location.")
                if (
                    urlparse(job_url).netloc
                    != urlparse(self._settings.verifalia_base_url).netloc
                    or urlparse(job_url).scheme != "https"
                ):
                    raise ServiceError("Verifalia returned an unexpected job location.")
                response = await send_free(
                    lambda: client.get(job_url, params={"waitTime": 30_000}),
                    "Verifalia",
                )
                response.raise_for_status()
                snapshot = response.json()
                if response.status_code == 202:
                    await asyncio.sleep(0.75)
            return list(snapshot.get("entries", {}).get("data", []))
        except ServiceError:
            raise
        except httpx.HTTPStatusError as exc:
            detail = self._api_error(exc.response)
            logger.warning(
                "Verifalia rejected validation (HTTP %s)", exc.response.status_code
            )
            raise ServiceError(f"Verifalia verification failed: {detail}") from exc
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Verifalia verification failed (%s)", type(exc).__name__)
            raise ServiceError(
                "Verifalia could not complete the verification."
            ) from exc

    def _auth(self) -> httpx.BasicAuth | None:
        if self._settings.verifalia_bearer_token:
            return None
        return httpx.BasicAuth(
            self._settings.verifalia_username or "",
            self._settings.verifalia_password or "",
        )

    def _headers(self) -> dict[str, str]:
        if self._settings.verifalia_bearer_token:
            return {"Authorization": f"Bearer {self._settings.verifalia_bearer_token}"}
        return {}

    def _job_url(self, snapshot: dict[str, object]) -> str | None:
        overview = snapshot.get("overview")
        if not isinstance(overview, dict) or not overview.get("id"):
            return None
        return f"{self._settings.verifalia_base_url}/email-validations/{overview['id']}"

    @staticmethod
    def _is_complete(snapshot: dict[str, object]) -> bool:
        overview = snapshot.get("overview")
        return (
            isinstance(overview, dict)
            and overview.get("status") == "Completed"
            and isinstance(snapshot.get("entries"), dict)
        )

    @staticmethod
    def _to_result(email: str, entry: dict[str, object]) -> VerificationResult:
        classification = str(entry.get("classification") or "Unknown")
        labels = {
            "Deliverable": "Exists",
            "Undeliverable": "Does not exist",
            "Risky": "Risky / unconfirmed",
            "Unknown": "Unverified",
        }
        suggestions = entry.get("suggestions")
        return VerificationResult(
            email=email,
            result=labels.get(classification, "Unverified"),
            classification=classification,
            status=str(entry.get("status") or "Unknown"),
            normalized_email=entry.get("emailAddress")
            if isinstance(entry.get("emailAddress"), str)
            else None,
            is_disposable=entry.get("isDisposableEmailAddress")
            if isinstance(entry.get("isDisposableEmailAddress"), bool)
            else None,
            is_role_account=entry.get("isRoleAccount")
            if isinstance(entry.get("isRoleAccount"), bool)
            else None,
            is_free_address=entry.get("isFreeEmailAddress")
            if isinstance(entry.get("isFreeEmailAddress"), bool)
            else None,
            suggestions=[str(item) for item in suggestions]
            if isinstance(suggestions, list)
            else [],
        )

    @staticmethod
    def _api_error(response: httpx.Response) -> str:
        try:
            payload = response.json()
            return str(
                payload.get("detail") or payload.get("title") or response.reason_phrase
            )
        except ValueError:
            return response.reason_phrase or f"HTTP {response.status_code}"
