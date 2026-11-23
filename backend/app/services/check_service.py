from app.models.schemas.verification import (
    ModelId,
    Quality,
    SimpleCheckResponse,
    VerificationResult,
)
from app.services.evidence_service import REJECTED, EvidenceService
from app.services.openrouter_service import OpenRouterService
from app.services.verifalia_service import VerifaliaService


class CheckService:
    def __init__(
        self,
        openrouter: OpenRouterService,
        verifalia: VerifaliaService,
        evidence: EvidenceService,
    ) -> None:
        self._openrouter = openrouter
        self._verifalia = verifalia
        self._evidence = evidence

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
            candidates = await self._evidence.assess(
                query, context, candidate_map.get("simple", [])
            )
            emails = [
                candidate.email
                for candidate in candidates
                if candidate.verdict != REJECTED
            ]
        else:
            emails = list(dict.fromkeys(direct_emails))

        verified = await self._verifalia.verify_many(emails, quality)
        if lookup_used:
            results: list[VerificationResult] = []
            for candidate in candidates:
                result = verified.get(candidate.email)
                if result is None and candidate.verdict == REJECTED:
                    result = VerificationResult(
                        email=candidate.email,
                        result="Unverified",
                        classification="Unknown",
                        status="SkippedRejected",
                    )
                if result:
                    results.append(
                        result.model_copy(
                            update={
                                "candidate_confidence": candidate.confidence,
                                "candidate_source_url": candidate.source_url,
                                "candidate_rationale": candidate.rationale,
                                "verdict": candidate.verdict,
                                "verdict_reason": candidate.verdict_reason,
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
