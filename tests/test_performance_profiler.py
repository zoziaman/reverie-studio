import json
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).parent.parent


def test_profiler_writes_json_and_markdown(tmp_path):
    from pipeline.performance_profiler import ProductionPerformanceProfiler

    profiler = ProductionPerformanceProfiler(
        project_name="demo_project",
        data_dir=str(tmp_path),
    )
    profiler.update_overview(channel="senior", script_turns=12)
    profiler.start_stage("tts", "TTS")
    profiler.complete_stage("tts", metadata={"subtitle_count": 12})
    profiler.finalize(status="completed", metadata={"output_path": "demo.mp4"})

    assert Path(profiler.json_path).exists()
    assert Path(profiler.md_path).exists()

    payload = json.loads(Path(profiler.json_path).read_text(encoding="utf-8"))
    assert payload["project_name"] == "demo_project"
    assert payload["status"] == "completed"
    assert payload["overview"]["channel"] == "senior"
    assert payload["stages"][0]["key"] == "tts"
    assert payload["stages"][0]["status"] == "completed"

    markdown = Path(profiler.md_path).read_text(encoding="utf-8")
    assert "Production Performance Report: demo_project" in markdown
    assert "## Stages" in markdown


def test_profiler_derives_throughput_metrics(tmp_path):
    from pipeline.performance_profiler import ProductionPerformanceProfiler

    fake_times = iter([100.0, 100.0, 100.0, 130.0, 130.0, 130.0, 190.0, 190.0, 250.0, 250.0, 250.0])
    with patch("pipeline.performance_profiler.time.time", side_effect=lambda: next(fake_times)):
        profiler = ProductionPerformanceProfiler(
            project_name="throughput_project",
            data_dir=str(tmp_path),
        )
        profiler.update_overview(script_turns=75, subtitle_count=60, image_count=30)
        profiler.start_stage("tts", "TTS")
        profiler.complete_stage("tts")
        profiler.start_stage("images", "이미지 생성")
        profiler.complete_stage("images")
        profiler.finalize(status="completed")

    payload = json.loads(Path(profiler.json_path).read_text(encoding="utf-8"))
    metrics = payload["derived_metrics"]
    assert metrics["tts_turns_per_min"] == 120.0
    assert metrics["images_per_min"] == 30.0
    assert metrics["image_to_script_ratio"] == 0.4


def test_profiler_marks_skipped_stage(tmp_path):
    from pipeline.performance_profiler import ProductionPerformanceProfiler

    profiler = ProductionPerformanceProfiler(
        project_name="resume_project",
        data_dir=str(tmp_path),
    )
    profiler.skip_stage("thumbnail", "썸네일", reason="checkpoint_reused", metadata={"checkpoint_stage": "images"})
    profiler.finalize(status="completed")

    payload = json.loads(Path(profiler.json_path).read_text(encoding="utf-8"))
    assert payload["stages"][0]["status"] == "skipped"
    assert payload["stages"][0]["metadata"]["reason"] == "checkpoint_reused"
