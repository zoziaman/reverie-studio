import importlib
import os
import sys


class FailingChat:
    def __init__(self, secret):
        self.secret = secret

    def send_message(self, message):
        raise RuntimeError(f"pack creator failed for GEMINI_API_KEY={self.secret}")


def test_gemini_worker_redacts_secret_in_error_signal():
    module = _import_pack_creator_module()
    secret = "AIza" + ("w" * 32)
    worker = module.GeminiWorker(model=None, chat=FailingChat(secret), message="hello")
    errors = []
    worker.error_occurred.connect(errors.append)

    worker.run()

    assert errors
    assert secret not in errors[0]
    assert "GEMINI_API_KEY=<redacted>" in errors[0]


def _import_pack_creator_module():
    original_warnings = os.environ.get("PYTHONWARNINGS")
    try:
        sys.modules.pop("tools.pack_creator_full", None)
        return importlib.import_module("tools.pack_creator_full")
    finally:
        if original_warnings is None:
            os.environ.pop("PYTHONWARNINGS", None)
        else:
            os.environ["PYTHONWARNINGS"] = original_warnings
        importlib.invalidate_caches()
