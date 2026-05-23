import requests

from insight.ai_gatekeeper import AIGatekeeper


def test_ai_gatekeeper_http_error_hides_gemini_api_key(monkeypatch):
    api_key = "AIza" + ("d" * 32)

    class FakeGetResponse:
        status_code = 404
        content = b""

    class FakePostResponse:
        def raise_for_status(self):
            raise requests.HTTPError(
                "403 Client Error: Forbidden for url: "
                f"https://generativelanguage.googleapis.com/v1beta/models/model:generateContent?key={api_key}"
            )

        def json(self):
            return {}

    monkeypatch.setattr("insight.ai_gatekeeper.requests.get", lambda *args, **kwargs: FakeGetResponse())
    monkeypatch.setattr("insight.ai_gatekeeper.requests.post", lambda *args, **kwargs: FakePostResponse())

    gatekeeper = AIGatekeeper(api_key=api_key)

    result = gatekeeper.analyze_video(
        video_id="video-1",
        title="test title",
        description="test description",
        thumbnail_url="https://example.invalid/thumb.jpg",
    )

    assert result.content_type == "UNKNOWN"
    assert api_key not in result.drop_reason
    assert "key=<redacted>" in result.drop_reason


def test_ai_gatekeeper_direct_http_error_has_no_secret_cause(monkeypatch):
    api_key = "AIza" + ("e" * 32)

    class FakeGetResponse:
        status_code = 404
        content = b""

    class FakePostResponse:
        def raise_for_status(self):
            raise requests.HTTPError(
                "403 Client Error: Forbidden for url: "
                f"https://generativelanguage.googleapis.com/v1beta/models/model:generateContent?key={api_key}"
            )

        def json(self):
            return {}

    monkeypatch.setattr("insight.ai_gatekeeper.requests.get", lambda *args, **kwargs: FakeGetResponse())
    monkeypatch.setattr("insight.ai_gatekeeper.requests.post", lambda *args, **kwargs: FakePostResponse())

    gatekeeper = AIGatekeeper(api_key=api_key)

    try:
        gatekeeper._call_gemini_with_image("prompt", "https://example.invalid/thumb.jpg")
    except RuntimeError as exc:
        assert api_key not in str(exc)
        assert "key=<redacted>" in str(exc)
        assert exc.__cause__ is None
    else:
        raise AssertionError("expected RuntimeError")
