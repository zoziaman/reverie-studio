import logging

from factory.pack_designer import PackDesigner


def test_pack_designer_concept_failure_redacts_gemini_api_key(caplog):
    api_key = "AIza" + ("s" * 32)

    class FakeGeminiModel:
        def generate_content(self, prompt):
            raise RuntimeError(f"request failed for GEMINI_API_KEY={api_key}")

    designer = PackDesigner.__new__(PackDesigner)
    designer.gemini_model = FakeGeminiModel()

    caplog.set_level(logging.WARNING)

    concept = designer._generate_channel_concept("horror", "", "silhouette", {})

    assert concept["channel_name"]
    assert api_key not in caplog.text
    assert "GEMINI_API_KEY=<redacted>" in caplog.text
