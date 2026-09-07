import json
import logging
import re
from collections.abc import Sequence
from urllib.parse import urlparse

import httpx

from app.core.config import Settings
from app.exceptions.handlers import ServiceError
from app.models.schemas.verification import Candidate, ModelId


logger = logging.getLogger(__name__)
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class OpenRouterService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def find_candidates(
        self,
        names: Sequence[tuple[str, str]],
        model: ModelId,
        shared_context: str = "",
    ) -> dict[str, list[Candidate]]:
        if not self._settings.openrouter_api_key:
            raise ServiceError(
                "OPENROUTER_API_KEY is not configured. Add it to the root .env file.",
                status_code=503,
            )

        records = [{"row_id": row_id, "name": name} for row_id, name in names]
        prompt = (
            "Find publicly documented professional or institutional email addresses for each "
            "person below. Search the web when useful. Never invent an address or infer a pattern "
            "without evidence. Return up to 5 distinct candidates per person. If none can be "
            "supported, return an empty candidates array. Confidence must be high, medium, or low. "
            "source_url should be the page supporting the address when available. "
            f"Shared context: {shared_context or 'None supplied'}.\n"
            f"People: {json.dumps(records, ensure_ascii=False)}"
        )
        schema = {
            "type": "object",
            "properties": {
                "people": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "row_id": {"type": "string"},
                            "candidates": {
                                "type": "array",
                                "maxItems": 5,
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "email": {"type": "string"},
                                        "confidence": {
                                            "type": "string",
                                            "enum": ["high", "medium", "low"],
                                        },
                                        "source_url": {"type": ["string", "null"]},
                                        "rationale": {"type": ["string", "null"]},
                                    },
                                    "required": [
                                        "email",
                                        "confidence",
                                        "source_url",
                                        "rationale",
                                    ],
                                    "additionalProperties": False,
                                },
                            },
                        },
                        "required": ["row_id", "candidates"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["people"],
            "additionalProperties": False,
        }
        body = {
            "model": model.value,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a cautious professional contact researcher. Only surface public "
                        "work addresses; do not return personal addresses or unsupported guesses."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "tools": [
                {
                    "type": "openrouter:web_search",
                    "web_search": {
                        "max_total_results": max(5, min(len(names) * 3, 30))
                    },
                }
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "email_candidates",
                    "strict": True,
                    "schema": schema,
                },
            },
            "provider": {"require_parameters": True},
        }
        headers = {
            "Authorization": f"Bearer {self._settings.openrouter_api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": self._settings.openrouter_site_url,
            "X-Title": self._settings.openrouter_app_name,
        }
        try:
            async with httpx.AsyncClient(
                timeout=self._settings.request_timeout_seconds
            ) as client:
                response = await client.post(
                    f"{self._settings.openrouter_base_url}/chat/completions",
                    headers=headers,
                    json=body,
                )
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPStatusError as exc:
            detail = self._api_error(exc.response)
            logger.warning(
                "OpenRouter rejected lookup (HTTP %s)", exc.response.status_code
            )
            raise ServiceError(f"OpenRouter lookup failed: {detail}") from exc
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("OpenRouter lookup failed (%s)", type(exc).__name__)
            raise ServiceError(
                "OpenRouter could not complete the email lookup."
            ) from exc

        try:
            content = payload["choices"][0]["message"]["content"]
            if isinstance(content, list):
                content = "".join(
                    item.get("text", "") for item in content if isinstance(item, dict)
                )
            parsed = json.loads(content)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise ServiceError(
                "OpenRouter returned an unreadable candidate list."
            ) from exc

        requested_ids = {row_id for row_id, _ in names}
        result: dict[str, list[Candidate]] = {row_id: [] for row_id in requested_ids}
        for person in parsed.get("people", []):
            row_id = str(person.get("row_id", ""))
            if row_id not in requested_ids:
                continue
            seen: set[str] = set()
            for raw_candidate in person.get("candidates", []):
                email = str(raw_candidate.get("email", "")).strip().lower()
                if not EMAIL_PATTERN.fullmatch(email) or email in seen:
                    continue
                seen.add(email)
                source_url = self._safe_source_url(raw_candidate.get("source_url"))
                result[row_id].append(
                    Candidate(
                        email=email,
                        confidence=raw_candidate.get("confidence", "unknown"),
                        source_url=source_url,
                        rationale=raw_candidate.get("rationale"),
                    )
                )
        return result

    @staticmethod
    def _safe_source_url(value: object) -> str | None:
        if not isinstance(value, str):
            return None
        parsed = urlparse(value)
        return value if parsed.scheme in {"http", "https"} and parsed.netloc else None

    @staticmethod
    def _api_error(response: httpx.Response) -> str:
        try:
            payload = response.json()
            error = payload.get("error")
            error_message = error.get("message") if isinstance(error, dict) else error
            return str(error_message or payload.get("detail") or response.reason_phrase)
        except ValueError:
            return response.reason_phrase or f"HTTP {response.status_code}"
