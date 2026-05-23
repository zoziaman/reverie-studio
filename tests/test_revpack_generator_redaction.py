from insight import revpack_generator as revpack_module
from insight.revpack_generator import RevpackGenerator


def test_generate_revpack_redacts_secret_in_failure(monkeypatch, tmp_path):
    secret = "sk-" + ("r" * 32)
    monkeypatch.setattr(revpack_module, "PACKAGE_SYSTEM_AVAILABLE", True)

    generator = RevpackGenerator(output_dir=tmp_path)

    def fail_recipe_to_package(*args, **kwargs):
        raise RuntimeError(f"package conversion failed for OPENAI_API_KEY={secret}")

    monkeypatch.setattr(generator, "recipe_to_package", fail_recipe_to_package)

    success, message, output_path = generator.generate_revpack(recipe=object())

    assert success is False
    assert output_path is None
    assert secret not in message
    assert "OPENAI_API_KEY=<redacted>" in message


def test_load_revpack_redacts_secret_in_failure(monkeypatch, tmp_path):
    secret = "hf_" + ("r" * 28)
    revpack_path = tmp_path / "broken.revpack"
    revpack_path.write_bytes(b"fake")

    def fail_zipfile(*args, **kwargs):
        raise RuntimeError(f"zip open failed for HF_TOKEN={secret}")

    monkeypatch.setattr(revpack_module.zipfile, "ZipFile", fail_zipfile)

    generator = RevpackGenerator(output_dir=tmp_path)
    success, message, data = generator.load_revpack(revpack_path)

    assert success is False
    assert data is None
    assert secret not in message
    assert "HF_TOKEN=<redacted>" in message


def test_load_new_format_pack_redacts_secret_in_failure(tmp_path):
    secret = "ya29." + ("r" * 28)

    class FailingZip:
        def read(self, filename):
            raise RuntimeError(f"manifest read failed for GOOGLE_TOKEN={secret}")

    generator = RevpackGenerator(output_dir=tmp_path)
    success, message, data = generator._load_new_format_pack(
        FailingZip(),
        ["manifest.json"],
        tmp_path / "new.revpack",
    )

    assert success is False
    assert data is None
    assert secret not in message
    assert "GOOGLE_TOKEN=<redacted>" in message
