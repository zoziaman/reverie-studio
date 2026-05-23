import logging

import requests

from modules_pro import scene_analyzer
from pipeline.image_pipeline import ImagePipeline


def _make_pipeline():
    return ImagePipeline(
        channel="horror",
        mode="horror",
        sd_url="http://127.0.0.1:7860",
        sd_webui_root="C:/sd-webui",
        data_dir="C:/tmp/reverie-test",
        assets_dir="C:/tmp/reverie-assets",
    )


def test_pre_analyze_scenes_failure_redacts_api_key_in_log(monkeypatch, caplog):
    api_key = "AIza" + ("v" * 32)

    def fail_batch(self, dialogues, parallel=True):
        raise RuntimeError(f"scene pre-analysis failed for ?key={api_key}")

    monkeypatch.setattr(scene_analyzer.SceneAnalyzer, "analyze_scene_batch", fail_batch)

    pipeline = _make_pipeline()
    caplog.set_level(logging.WARNING)

    result = pipeline.pre_analyze_scenes(
        [{"speaker": "narrator", "text": "문이 천천히 열렸다"}],
        gemini_model=object(),
    )

    assert result is None
    assert api_key not in caplog.text
    assert "key=<redacted>" in caplog.text


def test_safe_fallback_image_failure_redacts_api_key_and_keeps_placeholder(monkeypatch, tmp_path, caplog):
    api_key = "AIza" + ("f" * 32)
    output_path = tmp_path / "fallback.png"

    def fail_post(*args, **kwargs):
        raise requests.RequestException(f"fallback request failed for GEMINI_API_KEY={api_key}")

    monkeypatch.setattr("pipeline.image_pipeline.requests.post", fail_post)

    pipeline = _make_pipeline()
    caplog.set_level(logging.ERROR)

    result = pipeline.get_safe_fallback_image(str(output_path), mode="horror")

    assert result == str(output_path)
    assert output_path.exists()
    assert api_key not in caplog.text
    assert "GEMINI_API_KEY=<redacted>" in caplog.text
