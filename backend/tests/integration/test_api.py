def test_health_reports_configuration(client) -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert "openrouter_configured" not in response.json()


def test_models_lists_requested_choices(signed_in) -> None:
    client = signed_in
    response = client.get("/api/models")

    assert response.status_code == 200
    assert [model["label"] for model in response.json()] == [
        "GPT-6 Luna",
        "GPT-5.6 Terra",
        "Claude Haiku 5.5",
        "Claude Sonnet 5.5",
        "Claude Opus 5.5",
    ]


def test_localhost_and_loopback_frontends_are_allowed(client) -> None:
    for origin in ("http://localhost:3000", "http://127.0.0.1:3000"):
        response = client.options(
            "/api/health",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
            },
        )
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == origin


def test_batch_rejects_unsupported_file(signed_in) -> None:
    client = signed_in
    response = client.post(
        "/api/batch",
        files={"file": ("contacts.txt", b"email\nada@example.org", "text/plain")},
    )

    assert response.status_code == 415
