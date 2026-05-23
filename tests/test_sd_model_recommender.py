from types import SimpleNamespace


def test_required_model_check_matches_checkpoint_without_extension():
    from modules_pro.sd_model_recommender import SDModelRecommender

    recommender = SDModelRecommender()
    recommender.scan_sd_webui_models = lambda _url=None: {
        "checkpoints": ["mistoonAnime_v10Noobai"],
        "vaes": [],
        "loras": [],
    }

    result = recommender.check_required_models_for_pack(
        pack_checkpoint="mistoonAnime_v10Noobai.safetensors",
        sd_api_url="http://127.0.0.1:7860",
    )

    assert result["all_installed"] is True
    assert result["installed"]["checkpoint"] is True
    assert result["missing"]["checkpoint"] is None


def test_required_model_check_treats_automatic_vae_as_satisfied():
    from modules_pro.sd_model_recommender import SDModelRecommender

    recommender = SDModelRecommender()
    recommender.scan_sd_webui_models = lambda _url=None: {
        "checkpoints": ["counterfeitV30_v30"],
        "vaes": [],
        "loras": [],
    }

    result = recommender.check_required_models_for_pack(
        pack_checkpoint="counterfeitV30_v30.safetensors",
        pack_vae="Automatic",
        sd_api_url="http://127.0.0.1:7860",
    )

    assert result["all_installed"] is True
    assert result["installed"]["vae"] is True
    assert result["missing"]["vae"] is None


def test_image_pipeline_prefers_active_pack_genre_over_mode(monkeypatch):
    import pipeline.image_pipeline as image_pipeline_module
    from pipeline.image_pipeline import ImagePipeline

    monkeypatch.setattr(image_pipeline_module, "PACK_CONFIG_AVAILABLE", True, raising=False)
    monkeypatch.setattr(
        image_pipeline_module,
        "ACTIVE_PACK",
        SimpleNamespace(is_loaded=True, pack_name="생활 사극 채널", genre="senior"),
        raising=False,
    )

    pack_id, genre = ImagePipeline._resolve_v59_pack_context(mode="life_saguk", channel="senior")

    assert pack_id == "생활 사극 채널"
    assert genre == "senior"


def test_download_model_error_redacts_secret_in_return(monkeypatch, tmp_path):
    from modules_pro import sd_model_recommender as recommender_module
    from modules_pro.sd_model_recommender import SDModelRecommender

    secret = "hf_" + ("m" * 28)

    def fail_get(*args, **kwargs):
        raise RuntimeError(f"download failed for HF_TOKEN={secret}")

    monkeypatch.setattr(recommender_module.requests, "get", fail_get)

    recommender = SDModelRecommender()
    success, message = recommender.download_model(
        "https://example.invalid/model.safetensors",
        str(tmp_path / "model.safetensors"),
    )

    assert success is False
    assert secret not in message
    assert "HF_TOKEN=<redacted>" in message
