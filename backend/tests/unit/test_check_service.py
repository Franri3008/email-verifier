import asyncio

from app.models.schemas.verification import (
    Candidate,
    ModelId,
    Quality,
    VerificationResult,
)
from app.services.check_service import CheckService
from app.services.evidence_service import EvidenceService


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
    service = CheckService(lookup, verifier, EvidenceService(None))

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
    service = CheckService(lookup, verifier, EvidenceService(None))

    response = asyncio.run(
        service.check("broken@address", "", ModelId.GPT_LUNA, Quality.STANDARD)
    )

    assert response.lookup_used is False
    assert lookup.calls == 0
    assert verifier.emails == ["broken@address"]


class StubEvidence:
    def __init__(self, verdicts) -> None:
        self.verdicts = verdicts
        self.calls: list = []

    async def assess(self, name, context, candidates):
        self.calls.append((name, context, [c.email for c in candidates]))
        return [
            c.model_copy(
                update={
                    "verdict": self.verdicts[c.email][0],
                    "verdict_reason": self.verdicts[c.email][1],
                }
            )
            for c in candidates
        ]


def test_rejected_candidates_are_shown_but_not_sent_to_verifalia() -> None:
    lookup = StubLookup()
    verifier = StubVerifier()
    evidence = StubEvidence(
        {
            "ada@university.example": ("Confirmed", "page found"),
            "ada@institute.example": ("Rejected", "not on page"),
        }
    )
    service = CheckService(lookup, verifier, evidence)

    response = asyncio.run(
        service.check("Ada Lovelace", "University", ModelId.GPT_LUNA, Quality.STANDARD)
    )

    assert evidence.calls == [
        (
            "Ada Lovelace",
            "University",
            ["ada@university.example", "ada@institute.example"],
        )
    ]
    assert verifier.emails == ["ada@university.example"]
    assert [
        (r.email, r.result, r.verdict, r.verdict_reason) for r in response.results
    ] == [
        ("ada@university.example", "Exists", "Confirmed", "page found"),
        ("ada@institute.example", "Unverified", "Rejected", "not on page"),
    ]


def test_all_rejected_candidates_skip_verifalia() -> None:
    verifier = StubVerifier()
    evidence = StubEvidence(
        {
            "ada@university.example": ("Rejected", "other person"),
            "ada@institute.example": ("Rejected", "not on page"),
        }
    )
    service = CheckService(StubLookup(), verifier, evidence)

    response = asyncio.run(
        service.check("Ada Lovelace", "", ModelId.GPT_LUNA, Quality.STANDARD)
    )

    assert verifier.emails == []
    assert {r.result for r in response.results} == {"Unverified"}


def test_candidates_without_source_are_unproven_by_default() -> None:
    verifier = StubVerifier()
    response = asyncio.run(
        CheckService(StubLookup(), verifier, EvidenceService(None)).check(
            "Ada Lovelace", "", ModelId.GPT_LUNA, Quality.STANDARD
        )
    )

    assert {(r.verdict, r.verdict_reason) for r in response.results} == {
        ("Unproven", "no source")
    }


def test_direct_addresses_skip_the_evidence_step() -> None:
    verifier = StubVerifier()
    evidence = StubEvidence({})
    response = asyncio.run(
        CheckService(StubLookup(), verifier, evidence).check(
            "ada@university.example", "", ModelId.GPT_LUNA, Quality.STANDARD
        )
    )

    assert evidence.calls == []
    assert verifier.emails == ["ada@university.example"]
    assert response.results[0].verdict is None
