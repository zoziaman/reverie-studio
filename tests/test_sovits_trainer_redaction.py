def _fake_gs_root(tmp_path):
    root = tmp_path / "GPT-SoVITS"
    (root / "tools").mkdir(parents=True)
    train_dir = root / "GPT_SoVITS"
    train_dir.mkdir()
    (train_dir / "s1_train.py").write_text("# fake", encoding="utf-8")
    (train_dir / "s2_train.py").write_text("# fake", encoding="utf-8")
    return root


def test_training_loop_redacts_secret_in_failed_progress(monkeypatch, tmp_path):
    from utils.sovits_trainer import SoVITSTrainer, TrainingConfig, TrainingStage

    secret = "sk-" + ("v" * 32)
    trainer = SoVITSTrainer(str(_fake_gs_root(tmp_path)))
    trainer.config = TrainingConfig(
        model_name="public-template",
        audio_folder=str(tmp_path / "audio"),
    )
    trainer._is_running = True
    snapshots = []
    trainer.set_progress_callback(
        lambda progress: snapshots.append(
            (progress.stage, progress.message, progress.error)
        )
    )

    monkeypatch.setattr(
        trainer,
        "validate_audio_folder",
        lambda folder: (True, {"file_count": 5}),
    )

    def failing_slicing():
        raise RuntimeError(f"training failed for OPENAI_API_KEY={secret}")

    monkeypatch.setattr(trainer, "_run_slicing", failing_slicing)

    trainer._training_loop()

    assert trainer.progress.stage is TrainingStage.FAILED
    assert trainer.progress.error
    assert secret not in trainer.progress.error
    assert "OPENAI_API_KEY=<redacted>" in trainer.progress.error
    assert snapshots
    failed_stage, failed_message, failed_error = snapshots[-1]
    assert failed_stage is TrainingStage.FAILED
    assert secret not in failed_message
    assert secret not in failed_error
    assert "OPENAI_API_KEY=<redacted>" in failed_message
