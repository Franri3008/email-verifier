import asyncio

from app.models.schemas.verification import (
    Candidate,
    ModelId,
    Quality,
    VerificationResult,
)
from app.services.check_service import CheckService


class StubLookup:
    calls = 0

    async def find_candidates(self, names, model, context):
        self.calls += 1
        return {
            "simple": [
                Candidate(email="ada@university.example", confidence="high"),
                Candidate(email="ada@institute.example", confidence="medium"),
            ]
        }


class StubVerifier:
    def __init__(self) -> None:
        self.emails: list[str] = []

    async def verify_many(self, emails, quality):
        self.emails = list(emails)
        return {
            email: VerificationResult(
                email=email,
                result="Exists",
                classification="Deliverable",
                status="Success",
            )
            for email in emails
        }


def test_name_lookup_verifies_every_candidate() -> None:
    lookup = StubLookup()
    verifier = StubVerifier()
    service = CheckService(lookup, verifier)

    response = asyncio.run(
        service.check("Ada Lovelace", "University", ModelId.GPT_LUNA, Quality.STANDARD)
    )

    assert response.lookup_used is True
    assert verifier.emails == ["ada@university.example", "ada@institute.example"]
    assert [result.candidate_confidence for result in response.results] == [
        "high",
        "medium",
    ]


def test_any_at_sign_input_is_sent_directly_to_verifalia() -> None:
    lookup = StubLookup()
    verifier = StubVerifier()
    service = CheckService(lookup, verifier)

    response = asyncio.run(
        service.check("broken@address", "", ModelId.GPT_LUNA, Quality.STANDARD)
    )

    assert response.lookup_used is False
    assert lookup.calls == 0
    assert verifier.emails == ["broken@address"]
