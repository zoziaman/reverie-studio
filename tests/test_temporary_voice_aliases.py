import json
from pathlib import Path

from modules_pro.script_writers import ScriptWriter
from pipeline.text_processor import TextProcessor
from pipeline.tts_manager import TTSManager


def test_text_processor_normalizes_child_aliases():
    tp = TextProcessor()

    assert tp.role_key_normalize("아이") == "child"
    assert tp.role_key_normalize("어린이") == "child"
    assert tp.role_key_normalize("child") == "child"


def test_script_writer_normalizes_child_role_to_child_voice_type():
    result = ScriptWriter._normalize_script(
        [{"role": "아이", "text": "안녕하세요", "emotion": "calm", "voice_type": ""}]
    )

    assert result[0]["voice_type"] == "child"


def test_tts_manager_resolves_temporary_voice_aliases(tmp_path):
    assets_dir = Path(tmp_path) / "assets"
    models_dir = assets_dir / "models"
    models_dir.mkdir(parents=True)
    (models_dir / "voice_metadata.json").write_text("{}", encoding="utf-8")

    for role in ("young_man", "young_woman"):
        role_dir = models_dir / role
        role_dir.mkdir()
        (role_dir / "gpt_weights.ckpt").write_bytes(b"gpt")
        (role_dir / "sovits_weights.pth").write_bytes(b"sovits")
        (role_dir / "calm.wav").write_bytes(b"RIFFdemo")

    mgr = TTSManager(
        channel="senior",
        target_language="ko",
        sovits_url="http://127.0.0.1:9880",
        sovits_root=str(tmp_path / "sovits"),
        assets_dir=str(assets_dir),
        data_dir=str(tmp_path / "data"),
        ffmpeg_path="",
    )
    mgr.voice_metadata = json.loads((models_dir / "voice_metadata.json").read_text(encoding="utf-8"))

    middle_gpt, middle_sovits, middle_ref, _ = mgr.resolve_tts_assets(
        role_key="middle_man",
        emotion="calm",
        voice_type="middle_man",
    )
    child_gpt, child_sovits, child_ref, _ = mgr.resolve_tts_assets(
        role_key="child",
        emotion="calm",
        voice_type="child",
    )

    assert middle_gpt.endswith("young_man\\gpt_weights.ckpt") or middle_gpt.endswith("young_man/gpt_weights.ckpt")
    assert middle_sovits.endswith("young_man\\sovits_weights.pth") or middle_sovits.endswith("young_man/sovits_weights.pth")
    assert middle_ref.endswith("young_man\\calm.wav") or middle_ref.endswith("young_man/calm.wav")

    assert child_gpt.endswith("young_woman\\gpt_weights.ckpt") or child_gpt.endswith("young_woman/gpt_weights.ckpt")
    assert child_sovits.endswith("young_woman\\sovits_weights.pth") or child_sovits.endswith("young_woman/sovits_weights.pth")
    assert child_ref.endswith("young_woman\\calm.wav") or child_ref.endswith("young_woman/calm.wav")


def test_tts_manager_valid_voice_types_excludes_temp_aliases_for_strict_checks(tmp_path):
    assets_dir = Path(tmp_path) / "assets"
    models_dir = assets_dir / "models"
    models_dir.mkdir(parents=True)
    (models_dir / "voice_metadata.json").write_text('{"young_man": {}, "young_woman": {}}', encoding="utf-8")

    mgr = TTSManager(
        channel="senior",
        target_language="ko",
        sovits_url="http://127.0.0.1:9880",
        sovits_root=str(tmp_path / "sovits"),
        assets_dir=str(assets_dir),
        data_dir=str(tmp_path / "data"),
        ffmpeg_path="",
    )

    alias_enabled = mgr._get_valid_voice_types(include_aliases=True)
    strict_types = mgr._get_valid_voice_types(include_aliases=False)

    assert "middle_man" in alias_enabled
    assert "middle_man" not in strict_types
    assert "young_man" in strict_types
