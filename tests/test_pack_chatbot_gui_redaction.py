from tools.pack_chatbot_gui import ChatWorker


class FailingChat:
    def __init__(self, secret):
        self.secret = secret

    def send_message(self, message):
        raise RuntimeError(f"gui chat failed for GEMINI_API_KEY={self.secret}")


def test_chat_worker_redacts_secret_in_error_signal():
    secret = "AIza" + ("g" * 32)
    worker = ChatWorker(FailingChat(secret), "hello")
    errors = []
    worker.error_occurred.connect(errors.append)

    worker.run()

    assert errors
    assert secret not in errors[0]
    assert "GEMINI_API_KEY=<redacted>" in errors[0]
