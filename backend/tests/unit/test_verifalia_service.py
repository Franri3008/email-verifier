from app.core.config import Settings
from app.services.verifalia_service import VerifaliaService


def test_maps_verifalia_classifications_to_plain_results() -> None:
    service = VerifaliaService(Settings())

    deliverable = service._to_result(
        "ada@example.org",
        {"classification": "Deliverable", "status": "Success"},
    )
    risky = service._to_result(
        "ada@example.org",
        {"classification": "Risky", "status": "ServerIsCatchAll"},
    )
    unknown = service._to_result(
        "ada@example.org",
        {"classification": "FutureClassification", "status": "NewStatus"},
    )

    assert deliverable.result == "Exists"
    assert risky.result == "Risky / unconfirmed"
    assert unknown.result == "Unverified"


def test_builds_job_url_from_snapshot() -> None:
    service = VerifaliaService(Settings(verifalia_base_url="https://example.test/v2.7"))
    snapshot = {"overview": {"id": "job-123", "status": "InProgress"}}

    assert (
        service._job_url(snapshot)
        == "https://example.test/v2.7/email-validations/job-123"
    )
