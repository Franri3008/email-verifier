import io
import asyncio

import pandas as pd

from app.core.config import Settings
from app.models.schemas.verification import (
    Candidate,
    ModelId,
    Quality,
    VerificationResult,
)
from app.repositories.batch_repository import BatchRepository
from app.services.batch_service import BatchService


class StubOpenRouter:
    async def find_candidates(self, names, model, context):
        return {}


class StubVerifalia:
    async def verify_many(self, emails, quality):
        return {
            email: VerificationResult(
                email=email,
                result="Exists",
                classification="Deliverable",
                status="Success",
            )
            for email in emails
        }


def make_service() -> BatchService:
    return BatchService(
        Settings(),
        BatchRepository(60),
        StubOpenRouter(),
        StubVerifalia(),
    )


def test_split_emails_normalizes_and_deduplicates() -> None:
    assert make_service()._split_emails(
        " A@EXAMPLE.COM; b@example.org\na@example.com "
    ) == [
        "a@example.com",
        "b@example.org",
    ]


def test_split_emails_preserves_invalid_addresses_for_verifalia() -> None:
    assert make_service()._split_emails("not-an-email; foo@invalid") == [
        "not-an-email",
        "foo@invalid",
    ]


def test_excel_formula_like_values_are_neutralized() -> None:
    assert make_service()._safe_excel_value("=2+2") == "'=2+2"
    assert make_service()._safe_excel_value("Ada") == "Ada"


def test_reads_xlsx_with_case_insensitive_email_column() -> None:
    buffer = io.BytesIO()
    pd.DataFrame({"Name": ["Ada"], " EMAIL ": ["ada@example.org"]}).to_excel(
        buffer, index=False
    )

    frame = make_service()._read_file(buffer.getvalue(), "contacts.xlsx")

    assert make_service()._find_column(frame, "email") == " EMAIL "


def test_result_columns_keep_detailed_verifalia_fields() -> None:
    result = VerificationResult(
        email="ada@example.org",
        result="Exists",
        classification="Deliverable",
        status="Success",
        is_role_account=False,
    )
    candidate = Candidate(email="ada@example.org", confidence="high")

    row = make_service()._result_columns(result, candidate)

    assert row["result"] == "Exists"
    assert row["verifalia_status"] == "Success"
    assert row["candidate_confidence"] == "high"


def test_processes_and_stores_a_downloadable_workbook() -> None:
    source = io.BytesIO()
    pd.DataFrame(
        {"name": ["Ada", "Grace"], "email": ["ada@example.org", "grace@example.org"]}
    ).to_excel(source, index=False)
    service = make_service()

    response = asyncio.run(
        service.process(
            source.getvalue(),
            "people.xlsx",
            model=ModelId.GPT_LUNA,
            quality=Quality.STANDARD,
            generate_missing=False,
            context="",
        )
    )
    filename, content = service.download(response.batch_id)

    assert response.summary.emails_checked == 2
    assert response.summary.counts == {"Exists": 2}
    assert filename == "people-verified.xlsx"
    output = pd.read_excel(io.BytesIO(content))
    assert output["result"].tolist() == ["Exists", "Exists"]


class CountingOpenRouter:
    def __init__(self, fail_after=None):
        self.calls = []
        self.fail_after = fail_after

    async def find_candidates(self, names, model, context):
        if self.fail_after is not None and len(self.calls) >= self.fail_after:
            raise RuntimeError("provider down")
        self.calls.append(list(names))
        return {
            row_id: [Candidate(email=f"{name.lower()}@example.org", confidence="high")]
            for row_id, name in names
        }


class CountingVerifalia(StubVerifalia):
    def __init__(self):
        self.calls = []

    async def verify_many(self, emails, quality):
        self.calls.append(list(emails))
        return await super().verify_many(emails, quality)


def workbook(frame: pd.DataFrame) -> bytes:
    source = io.BytesIO()
    frame.to_excel(source, index=False)
    return source.getvalue()


def test_lookup_chunk_size_depends_on_model() -> None:
    settings = Settings()
    assert settings.lookup_chunk_size_for(ModelId.CLAUDE_OPUS) == 10
    assert settings.lookup_chunk_size_for(ModelId.CLAUDE_SONNET) == 10
    assert settings.lookup_chunk_size_for(ModelId.CLAUDE_HAIKU) == 25
    assert settings.lookup_chunk_size_for(ModelId.GPT_LUNA) == 25

    lookup = CountingOpenRouter()
    service = BatchService(Settings(), BatchRepository(60), lookup, CountingVerifalia())
    content = workbook(pd.DataFrame({"name": [f"P{i}" for i in range(23)]}))
    asyncio.run(
        service.process(
            content, "people.xlsx", ModelId.CLAUDE_OPUS, Quality.STANDARD, True, ""
        )
    )
    assert [len(chunk) for chunk in lookup.calls] == [10, 10, 3]


def test_progress_is_reported_and_partial_workbook_marks_missing_rows() -> None:
    lookup = CountingOpenRouter(fail_after=1)
    verifier = CountingVerifalia()
    service = BatchService(Settings(), BatchRepository(60), lookup, verifier)
    names = [f"P{i}" for i in range(12)]
    content = workbook(
        pd.DataFrame(
            {"name": ["Direct", *names], "email": ["direct@example.org"] + [""] * 12}
        )
    )
    states = []

    try:
        asyncio.run(
            service.process(
                content,
                "people.xlsx",
                ModelId.CLAUDE_OPUS,
                Quality.STANDARD,
                True,
                "",
                on_progress=states.append,
            )
        )
    except RuntimeError:
        pass
    checkpoint = states[-1]
    assert BatchService.has_progress(checkpoint)
    assert len(checkpoint["candidates"]) == 10
    assert len(checkpoint["verified"]) == 11

    response, unprocessed = service.partial(content, "people.xlsx", True, checkpoint)
    assert unprocessed == [13, 14]
    assert response.summary.counts == {"Exists": 11, "Not processed": 2}
    _, stored = service.download(response.batch_id)
    output = pd.read_excel(io.BytesIO(stored))
    assert output["result"].tolist()[-2:] == ["Not processed", "Not processed"]
    assert BatchService.describe_rows([2, 3, 4, 7, 9, 10]) == "2-4, 7, 9-10"


def test_rerun_skips_rows_that_already_have_results() -> None:
    lookup = CountingOpenRouter()
    verifier = CountingVerifalia()
    service = BatchService(Settings(), BatchRepository(60), lookup, verifier)
    content = workbook(
        pd.DataFrame(
            {
                "name": ["Ada", "Grace", "Alan", "Edsger"],
                "email": ["ada@example.org", "grace@example.org", "", ""],
                "result": ["Does not exist", "Not processed", "No email found", ""],
                "verifalia_status": ["MailboxDoesNotExist", "NotProcessed", "", ""],
            }
        )
    )

    response = asyncio.run(
        service.process(
            content, "people.xlsx", ModelId.GPT_LUNA, Quality.STANDARD, True, ""
        )
    )

    assert verifier.calls == [
        ["grace@example.org"],
        ["alan@example.org", "edsger@example.org"],
    ]
    assert lookup.calls == [[("2", "Alan"), ("3", "Edsger")]]
    _, stored = service.download(response.batch_id)
    output = pd.read_excel(io.BytesIO(stored), dtype=object)
    assert output["result"].tolist() == ["Does not exist", "Exists", "Exists", "Exists"]
    assert output["verifalia_status"].tolist()[0] == "MailboxDoesNotExist"
    assert output["input_result"].tolist()[0] == "Does not exist"


class StubEvidence:
    def __init__(self, rejected=(), fail_after=None):
        self.rejected = set(rejected)
        self.fail_after = fail_after
        self.calls = []

    async def assess_many(self, context, groups):
        if self.fail_after is not None and len(self.calls) >= self.fail_after:
            raise RuntimeError("evidence down")
        self.calls.append([(name, [c.email for c in items]) for name, items in groups])
        return [
            [
                c.model_copy(
                    update={
                        "verdict": "Rejected" if c.email in self.rejected else "Likely",
                        "verdict_reason": "not on page"
                        if c.email in self.rejected
                        else "name missing",
                    }
                )
                for c in items
            ]
            for _, items in groups
        ]


def test_rejected_candidates_skip_verifalia_and_direct_rows_get_no_verdict() -> None:
    verifier = CountingVerifalia()
    evidence = StubEvidence(rejected={"grace@example.org"})
    service = BatchService(
        Settings(), BatchRepository(60), CountingOpenRouter(), verifier, evidence
    )
    content = workbook(
        pd.DataFrame(
            {
                "name": ["Direct", "Ada", "Grace"],
                "email": ["direct@example.org", "", ""],
            }
        )
    )

    response = asyncio.run(
        service.process(
            content, "people.xlsx", ModelId.GPT_LUNA, Quality.STANDARD, True, "CEPS"
        )
    )

    assert evidence.calls == [
        [("Ada", ["ada@example.org"]), ("Grace", ["grace@example.org"])]
    ]
    assert verifier.calls == [["direct@example.org"], ["ada@example.org"]]
    assert response.summary.counts == {"Exists": 2, "Unverified": 1}
    columns = response.columns
    assert columns.index("verdict") == columns.index("candidate_rationale") + 1
    assert columns.index("verdict_reason") == columns.index("verdict") + 1
    _, stored = service.download(response.batch_id)
    output = pd.read_excel(io.BytesIO(stored), dtype=object).fillna("")
    assert output[
        ["result", "verifalia_status", "verdict", "verdict_reason"]
    ].values.tolist() == [
        ["Exists", "Success", "", ""],
        ["Exists", "Success", "Likely", "name missing"],
        ["Unverified", "SkippedRejected", "Rejected", "not on page"],
    ]


def test_rows_are_only_done_after_evidence_and_verification() -> None:
    verifier = CountingVerifalia()
    evidence = StubEvidence(rejected={"p1@example.org"}, fail_after=1)
    service = BatchService(
        Settings(), BatchRepository(60), CountingOpenRouter(), verifier, evidence
    )
    content = workbook(pd.DataFrame({"name": [f"P{i}" for i in range(12)]}))
    states = []

    try:
        asyncio.run(
            service.process(
                content,
                "people.xlsx",
                ModelId.CLAUDE_OPUS,
                Quality.STANDARD,
                True,
                "",
                on_progress=states.append,
            )
        )
    except RuntimeError:
        pass

    checkpoint = states[-1]
    assert len(checkpoint["candidates"]) == 10
    assert checkpoint["candidates"]["1"][0]["verdict"] == "Rejected"
    assert "p1@example.org" not in checkpoint["verified"]
    response, unprocessed = service.partial(content, "people.xlsx", True, checkpoint)
    assert unprocessed == [12, 13]
    assert response.summary.counts == {
        "Exists": 9,
        "Unverified": 1,
        "Not processed": 2,
    }

    _, stored = service.download(response.batch_id)
    rerun_lookup = CountingOpenRouter()
    rerun_verifier = CountingVerifalia()
    rerun_evidence = StubEvidence()
    rerun = BatchService(
        Settings(), BatchRepository(60), rerun_lookup, rerun_verifier, rerun_evidence
    )
    second = asyncio.run(
        rerun.process(
            stored, "people.xlsx", ModelId.CLAUDE_OPUS, Quality.STANDARD, True, ""
        )
    )
    assert rerun_lookup.calls == [[("10", "P10"), ("11", "P11")]]
    assert rerun_verifier.calls == [["p10@example.org", "p11@example.org"]]
    assert second.summary.counts == {"Exists": 11, "Unverified": 1}
    _, final = rerun.download(second.batch_id)
    output = pd.read_excel(io.BytesIO(final), dtype=object).fillna("")
    assert output["verdict"].tolist()[1] == "Rejected"
    assert output["input_verdict"].tolist()[1] == "Rejected"
