from app.services.openrouter_service import OpenRouterService


def test_only_allows_http_source_urls() -> None:
    assert OpenRouterService._safe_source_url("https://example.org/contact") == (
        "https://example.org/contact"
    )
    assert OpenRouterService._safe_source_url("javascript:alert(1)") is None
    assert OpenRouterService._safe_source_url("not a url") is None
