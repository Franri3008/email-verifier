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
