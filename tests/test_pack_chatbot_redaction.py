import importlib
import sys


class FailingChat:
    def __init__(self, secret):
        self.secret = secret

    def send_message(self, user_input):
        raise RuntimeError(f"chat failed for GEMINI_API_KEY={self.secret}")


def test_pack_chatbot_send_message_redacts_secret_in_error_response():
    original_stdout = sys.stdout
    original_stdin = sys.stdin
    try:
        module = _import_pack_chatbot_module()
    finally:
        _restore_standard_stream("stdout", original_stdout)
        _restore_standard_stream("stdin", original_stdin)

    secret = "AIza" + ("c" * 32)
    chatbot = module.PackChatbot.__new__(module.PackChatbot)
    chatbot.chat = FailingChat(secret)

    response = chatbot.send_message("hello")

    assert secret not in response
    assert "GEMINI_API_KEY=<redacted>" in response


def test_pack_chatbot_import_does_not_replace_standard_streams():
    original_stdout = sys.stdout
    original_stdin = sys.stdin

    try:
        _import_pack_chatbot_module()

        assert sys.stdout is original_stdout
        assert sys.stdin is original_stdin
    finally:
        _restore_standard_stream("stdout", original_stdout)
        _restore_standard_stream("stdin", original_stdin)


def _import_pack_chatbot_module():
    sys.modules.pop("tools.pack_chatbot_test", None)
    try:
        return importlib.import_module("tools.pack_chatbot_test")
    finally:
        importlib.invalidate_caches()


def _restore_standard_stream(name, original_stream):
    current_stream = getattr(sys, name)
    if current_stream is original_stream:
        return

    setattr(sys, name, original_stream)
    try:
        current_stream.detach()
    except Exception:
        pass
