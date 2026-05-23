import logging


def test_set_model_async_redacts_secret_in_failure_callback_and_log(monkeypatch, tmp_path, caplog):
    import utils.sd_model_manager as sd_model_manager
    from config.settings import config

    secret = "hf_" + ("s" * 28)

    def failing_post(*args, **kwargs):
        raise RuntimeError(f"model load failed for HF_TOKEN={secret}")

    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(sd_model_manager.requests, "post", failing_post)
    caplog.set_level(logging.ERROR, logger="utils.sd_model_manager")

    manager = sd_model_manager.SDModelManager(sd_url="http://127.0.0.1:7860")
    callbacks = []

    try:
        future = manager.set_model_async(
            "public-template.safetensors",
            on_complete=lambda success, message: callbacks.append((success, message)),
        )

        assert future.result(timeout=2) is False
    finally:
        manager.close()

    assert callbacks
    assert callbacks[0][0] is False
    assert secret not in callbacks[0][1]
    assert "HF_TOKEN=<redacted>" in callbacks[0][1]
    assert secret not in caplog.text
