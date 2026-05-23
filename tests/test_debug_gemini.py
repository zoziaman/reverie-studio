import importlib.util
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_debug_gemini(monkeypatch):
    fake_google = types.ModuleType("google")
    fake_genai = types.ModuleType("google.generativeai")
    fake_genai.configure = lambda api_key=None: None
    fake_genai.list_models = lambda: []
    fake_genai.GenerativeModel = lambda name: None
    fake_google.generativeai = fake_genai

    fake_dotenv = types.ModuleType("dotenv")
    fake_dotenv.load_dotenv = lambda: None

    monkeypatch.setitem(sys.modules, "google", fake_google)
    monkeypatch.setitem(sys.modules, "google.generativeai", fake_genai)
    monkeypatch.setitem(sys.modules, "dotenv", fake_dotenv)

    spec = importlib.util.spec_from_file_location(
        "debug_gemini_under_test",
        ROOT / "scripts" / "debug_gemini.py",
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_debug_gemini_import_has_no_side_effects_or_secret_preview(monkeypatch, capsys):
    fake_key = "AIza" + ("a" * 32)
    monkeypatch.setenv("GEMINI_API_KEY", fake_key)

    _load_debug_gemini(monkeypatch)

    output = capsys.readouterr().out
    assert output == ""
    assert fake_key[:10] not in output


def test_debug_gemini_describes_key_state_without_revealing_value(monkeypatch):
    module = _load_debug_gemini(monkeypatch)

    assert module._describe_key_state("") == "missing"
    assert module._describe_key_state(None) == "missing"
    assert module._describe_key_state("AIza" + ("b" * 32)) == "configured (value hidden)"
