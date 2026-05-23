from pathlib import Path

from modules_pro.quality_control import (
    QualityCheckResult,
    QualityControl,
    QualityControlConfig,
    QualityReport,
    QualityStatus,
)


def test_quality_report_warning_is_non_blocking():
    report = QualityReport(
        image_path="dummy.png",
        overall_status=QualityStatus.WARNING,
        overall_score=0.73,
        checks=[
            QualityCheckResult(
                check_name="artifacts",
                status=QualityStatus.WARNING,
                score=0.7,
                message="minor artifact warning",
            )
        ],
    )

    assert report.passed is True
    assert len(report.failed_checks) == 0
    assert len(report.warning_checks) == 1


def test_quality_control_does_not_save_warning_reports(tmp_path, monkeypatch):
    qc = QualityControl(
        config=QualityControlConfig(
            save_failed_images=True,
            failed_images_path=str(tmp_path / "failed"),
        )
    )
    image_path = tmp_path / "scene.png"
    image_path.write_bytes(b"fake")

    calls = []

    def fake_save_failed_image(path, report):
        calls.append((path, report.overall_status))

    monkeypatch.setattr(qc, "_save_failed_image", fake_save_failed_image)
    monkeypatch.setattr(
        qc,
        "_check_resolution",
        lambda _: QualityCheckResult("resolution", QualityStatus.PASSED, 1.0, "ok"),
    )
    monkeypatch.setattr(
        qc,
        "_check_aspect_ratio",
        lambda _: QualityCheckResult("aspect_ratio", QualityStatus.WARNING, 0.7, "warn"),
    )
    monkeypatch.setattr(
        qc,
        "_check_blur",
        lambda _: QualityCheckResult("blur", QualityStatus.PASSED, 1.0, "ok"),
    )
    monkeypatch.setattr(
        qc,
        "_check_color_depth",
        lambda _: QualityCheckResult("color_depth", QualityStatus.PASSED, 1.0, "ok"),
    )
    monkeypatch.setattr(
        qc,
        "_check_artifacts",
        lambda _: QualityCheckResult("artifacts", QualityStatus.PASSED, 1.0, "ok"),
    )
    monkeypatch.setattr(
        qc,
        "_check_uncanny_valley",
        lambda _: QualityCheckResult("uncanny_valley", QualityStatus.PASSED, 1.0, "ok"),
    )

    report = qc.validate_scene_image(str(image_path))

    assert report.overall_status == QualityStatus.WARNING
    assert report.passed is True
    assert calls == []


def test_quality_control_redacts_secret_in_local_validation_error(monkeypatch, tmp_path, caplog):
    import modules_pro.quality_control as quality_control

    secret = "sk-" + ("q" * 32)
    qc = QualityControl()
    qc._cv2_available = True
    caplog.set_level("WARNING")
    image_path = tmp_path / "scene.png"
    image_path.write_bytes(b"fake")

    def failing_imread(*args, **kwargs):
        raise RuntimeError(f"local validation failed for OPENAI_API_KEY={secret}")

    monkeypatch.setattr(quality_control, "_cv2_imread_safe", failing_imread)

    result = qc._check_uncanny_valley(str(image_path))

    assert result.status == QualityStatus.SKIPPED
    assert secret not in result.message
    assert "OPENAI_API_KEY=<redacted>" in result.message
    assert secret not in caplog.text
