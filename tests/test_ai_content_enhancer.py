from utils.ai_content_enhancer import AIContentEnhancer


def test_generate_optimized_title_uses_safe_default_keywords_without_api_key():
    enhancer = AIContentEnhancer()

    result = enhancer.generate_optimized_title(
        original_title="Original story",
        channel="horror",
        mode="horror",
    )

    assert result["original"] == "Original story"
    assert len(result["titles"]) == 3


def test_generate_optimized_title_redacts_api_key_on_ai_failure(monkeypatch, capsys):
    api_key = "AIza" + ("n" * 32)

    class FakeModel:
        def generate_content(self, prompt):
            raise RuntimeError(f"request failed for GEMINI_API_KEY={api_key}")

    monkeypatch.setattr("utils.ai_content_enhancer.configure_gemini", lambda api_key: True)
    monkeypatch.setattr("utils.ai_content_enhancer.get_gemini_model", lambda model_name: FakeModel())

    enhancer = AIContentEnhancer(api_key=api_key)

    result = enhancer.generate_optimized_title(
        original_title="Original story",
        channel="daily_life_toon",
        mode="default",
    )

    output = capsys.readouterr().out
    assert result["original"] == "Original story"
    assert api_key not in output
    assert "GEMINI_API_KEY=<redacted>" in output


def test_generate_tags_redacts_api_key_on_ai_failure(monkeypatch, capsys):
    api_key = "AIza" + ("o" * 32)

    class FakeModel:
        def generate_content(self, prompt):
            raise RuntimeError(f"request failed for ?key={api_key}")

    monkeypatch.setattr("utils.ai_content_enhancer.configure_gemini", lambda api_key: True)
    monkeypatch.setattr("utils.ai_content_enhancer.get_gemini_model", lambda model_name: FakeModel())

    enhancer = AIContentEnhancer(api_key=api_key)

    tags = enhancer.generate_tags(
        title="Original story",
        channel="daily_life_toon",
        mode="default",
    )

    output = capsys.readouterr().out
    assert tags
    assert api_key not in output
    assert "key=<redacted>" in output
