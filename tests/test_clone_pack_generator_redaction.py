import logging

from factory.clone_pack_generator import ClonePackGenerator


def test_clone_pack_writer_prompt_redacts_gemini_failure_log(caplog):
    api_key = "AIza" + ("r" * 32)

    class FakeGemini:
        def generate_content(self, prompt):
            raise RuntimeError(f"request failed for ?key={api_key}")

    generator = ClonePackGenerator.__new__(ClonePackGenerator)
    generator.gemini = FakeGemini()

    caplog.set_level(logging.WARNING)

    prompt = generator._generate_writer_system_prompt("horror", "")

    assert prompt
    assert api_key not in caplog.text
    assert "key=<redacted>" in caplog.text
