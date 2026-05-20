from types import SimpleNamespace

from utils import shorts_manager
from utils.shorts_manager import ensure_shorts_title, normalize_shorts_plan


def test_ensure_shorts_title_appends_suffix_once():
    assert ensure_shorts_title("충격의 한마디").endswith("#Shorts")
    assert ensure_shorts_title("충격의 한마디 #Shorts").count("#Shorts") == 1


def test_normalize_shorts_plan_uses_cold_open_and_tags():
    plan = normalize_shorts_plan(
        {},
        topic="버려진 편지의 진실",
        hook="끝내 못한 말이 있었다",
        cold_open=[
            {"text": "엄마, 그 편지 내가 숨겼어요."},
            {"text": "그날의 진실은 생각보다 잔인했습니다.", "_is_bridge": True},
        ],
        tags="감동,가족",
    )

    assert plan["enabled"] is True
    assert plan["hook_line"] == "엄마, 그 편지 내가 숨겼어요."
    assert "shorts" in [tag.lower() for tag in plan["tags"]]
    assert plan["duration_sec"] == 35


def test_build_shorts_variant_maps_filtered_video_explicitly(monkeypatch, tmp_path):
    video_path = tmp_path / "source.mp4"
    video_path.write_bytes(b"fake")
    captured = {}

    monkeypatch.setattr(shorts_manager, "get_ffmpeg_path", lambda: "ffmpeg")

    def fake_run(cmd, capture_output, text, timeout):
        captured["cmd"] = cmd
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(shorts_manager.subprocess, "run", fake_run)

    shorts_manager.build_shorts_variant(
        str(video_path),
        output_dir=str(tmp_path),
        project_name="demo",
    )

    cmd = captured["cmd"]
    filter_arg = cmd[cmd.index("-filter_complex") + 1]
    assert filter_arg.endswith("[v]")
    assert cmd[cmd.index("-map") + 1] == "[v]"
