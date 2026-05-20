from config.settings_v2 import ReverieSettings
from pipeline.image_pipeline import ImagePipeline
from pipeline.thumbnail_maker import ThumbnailMaker


def test_low_vram_settings_clamp_dimensions_and_concurrency():
    settings = ReverieSettings(
        GPU_VRAM_GB=8,
        LOW_VRAM_MODE=True,
        REMOTION_CONCURRENCY=6,
        IMAGE_MAX_WORKERS=3,
    )

    assert settings.is_low_vram() is True
    assert settings.IMAGE_MAX_WORKERS == 1
    assert settings.REMOTION_CONCURRENCY == 2
    assert settings.clamp_sd_dimensions(1280, 720, purpose="image") == (768, 432)
    assert settings.clamp_sd_dimensions(1920, 1080, purpose="thumbnail") == (1280, 720)
    assert settings.clamp_sd_steps(28, purpose="image") == 18
    assert settings.get_safe_remotion_concurrency(6) == 2


def test_image_pipeline_applies_low_vram_payload_safety(monkeypatch):
    import pipeline.image_pipeline as image_pipeline_module

    settings = ReverieSettings(GPU_VRAM_GB=8, LOW_VRAM_MODE=True)
    monkeypatch.setattr(image_pipeline_module, "config", settings)

    pipeline = ImagePipeline(
        channel="senior",
        mode="touching",
        sd_url="http://127.0.0.1:7860",
        sd_webui_root="C:/AI/webui",
        data_dir="C:/ReverieStudio/data",
        assets_dir="C:/ReverieStudio/assets",
        video_width=1280,
        video_height=720,
    )

    payload = pipeline._apply_vram_safety(
        {
            "width": 1280,
            "height": 720,
            "steps": 28,
            "batch_size": 2,
            "n_iter": 3,
            "enable_hr": True,
        },
        purpose="image",
    )

    assert payload["width"] == 768
    assert payload["height"] == 432
    assert payload["steps"] == 18
    assert payload["batch_size"] == 1
    assert payload["n_iter"] == 1
    assert payload["enable_hr"] is False


def test_thumbnail_maker_applies_low_vram_payload_safety(monkeypatch):
    import pipeline.thumbnail_maker as thumbnail_maker_module

    settings = ReverieSettings(GPU_VRAM_GB=8, LOW_VRAM_MODE=True)
    monkeypatch.setattr(thumbnail_maker_module, "config", settings)

    maker = ThumbnailMaker(
        sd_url="http://127.0.0.1:7860",
        data_dir="C:/ReverieStudio/data",
        assets_dir="C:/ReverieStudio/assets",
        video_width=1920,
        video_height=1080,
    )

    payload = maker._apply_vram_safety(
        {
            "width": 1920,
            "height": 1080,
            "steps": 30,
            "batch_size": 2,
            "n_iter": 2,
        }
    )

    assert payload["width"] == 1280
    assert payload["height"] == 720
    assert payload["steps"] == 20
    assert payload["batch_size"] == 1
    assert payload["n_iter"] == 1
