from app.models.schemas.verification import (
    ModelId,
    Quality,
    SimpleCheckResponse,
    VerificationResult,
)
from app.services.openrouter_service import OpenRouterService
from app.services.verifalia_service import VerifaliaService


class CheckService:
    def __init__(
        self,
        openrouter: OpenRouterService,
        verifalia: VerifaliaService,
    ) -> None:
        self._openrouter = openrouter
        self._verifalia = verifalia

    async def check(
        self,
        query: str,
        context: str,
        model: ModelId,
        quality: Quality,
    ) -> SimpleCheckResponse:
        direct_emails = []
        if "@" in query:
            direct_emails = list(
                dict.fromkeys(
                    value.strip().lower()
                    for value in query.replace("\n", ",").replace(";", ",").split(",")
                    if value.strip()
                )
            )
        lookup_used = len(direct_emails) == 0
        candidates = []
        if lookup_used:
            candidate_map = await self._openrouter.find_candidates(
                [("simple", query)], model, context
            )
            candidates = candidate_map.get("simple", [])
            emails = [candidate.email for candidate in candidates]
        else:
            emails = list(dict.fromkeys(direct_emails))

        verified = await self._verifalia.verify_many(emails, quality)
        if lookup_used:
            results: list[VerificationResult] = []
            for candidate in candidates:
                result = verified.get(candidate.email)
                if result:
                    results.append(
                        result.model_copy(
                            update={
                                "candidate_confidence": candidate.confidence,
                                "candidate_source_url": candidate.source_url,
                                "candidate_rationale": candidate.rationale,
                            }
                        )
                    )
        else:
            results = [verified[email] for email in emails if email in verified]

        return SimpleCheckResponse(
            query=query,
            lookup_used=lookup_used,
            model=model.value if lookup_used else None,
            results=results,
        )
