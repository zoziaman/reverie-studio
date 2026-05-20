import sys
import types

from modules_pro.tts_engine import TTSConfig, TTSEngineType
from modules_pro.tts_engine import TTSEngineFactory, get_tts_engine
from modules_pro.tts_supertonic_adapter import SupertonicTTSAdapter
from pipeline.tts_manager import TTSManager


class FakeSupertonicTTS:
    last_instance = None

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.calls = []
        FakeSupertonicTTS.last_instance = self

    def get_voice_style(self, voice_name="M1"):
        return {"voice_name": voice_name}

    def synthesize(self, text, voice_style, **kwargs):
        self.calls.append(
            {
                "text": text,
                "voice": voice_style["voice_name"],
                **kwargs,
            }
        )
        return b"fake-wav-array", 1.23

    def save_audio(self, wav, output_path):
        with open(output_path, "wb") as f:
            f.write(b"RIFF" + b"\x00" * 128)


def install_fake_supertonic(monkeypatch):
    FakeSupertonicTTS.last_instance = None
    monkeypatch.setitem(sys.modules, "supertonic", types.SimpleNamespace(TTS=FakeSupertonicTTS))


def test_supertonic_adapter_uses_builtin_voice_pool_and_shorts_tuning(monkeypatch, tmp_path):
    install_fake_supertonic(monkeypatch)
    adapter = SupertonicTTSAdapter(
        TTSConfig(
            engine_type=TTSEngineType.SUPERTONIC,
            language="ko",
            supertonic_voice_map={"young_woman": "F1"},
            supertonic_total_steps=5,
            supertonic_speed=1.05,
            supertonic_max_chunk_length=120,
            supertonic_silence_duration=0.25,
        )
    )

    out_wav = tmp_path / "line.wav"

    assert adapter.is_available
    assert adapter.synthesize(
        "안녕하세요. 쇼츠 테스트입니다.",
        output_path=str(out_wav),
        language="ko",
        character="young_woman",
    )

    call = FakeSupertonicTTS.last_instance.calls[0]
    assert call["voice"] == "F1"
    assert call["lang"] == "ko"
    assert call["total_steps"] == 5
    assert call["max_chunk_length"] == 120
    assert out_wav.read_bytes().startswith(b"RIFF")


def test_supertonic_adapter_maps_legacy_senior_aliases(monkeypatch, tmp_path):
    install_fake_supertonic(monkeypatch)
    adapter = SupertonicTTSAdapter(TTSConfig(engine_type=TTSEngineType.SUPERTONIC))
    out_wav = tmp_path / "grandma.wav"

    assert adapter.synthesize("할머니 목소리 테스트입니다.", output_path=str(out_wav), character="old_woman")

    assert FakeSupertonicTTS.last_instance.calls[0]["voice"] == "F2"


def test_supertonic_factory_cache_respects_voice_map(monkeypatch):
    install_fake_supertonic(monkeypatch)
    TTSEngineFactory.clear_cache()

    first = get_tts_engine(
        "supertonic",
        supertonic_voice_map={"young_woman": "F1"},
        supertonic_total_steps=5,
    )
    second = get_tts_engine(
        "supertonic",
        supertonic_voice_map={"young_woman": "F4"},
        supertonic_total_steps=5,
    )

    assert first is not second


def test_tts_manager_reference_free_engine_does_not_require_sovits_assets(tmp_path):
    class FakeReferenceFreeEngine:
        requires_reference_audio = False
        is_available = True
        engine_name = "Supertonic 3"

        def __init__(self):
            self.calls = []

        def synthesize(self, **kwargs):
            self.calls.append(kwargs)
            with open(kwargs["output_path"], "wb") as f:
                f.write(b"RIFF" + b"\x00" * 128)
            return True

    manager = TTSManager(
        channel="daily_life_toon",
        target_language="ko",
        sovits_url="http://127.0.0.1:9880",
        sovits_root=str(tmp_path / "sovits"),
        assets_dir=str(tmp_path / "assets"),
        data_dir=str(tmp_path / "data"),
    )
    fake_engine = FakeReferenceFreeEngine()
    manager._tts_engine = fake_engine
    manager._using_sovits = False
    manager.resolve_tts_assets = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("reference-free TTS should not resolve SoVITS assets")
    )
    manager.amplify_tts_volume = lambda *args, **kwargs: None

    out_wav = tmp_path / "supertonic.wav"

    assert manager.generate_single_tts(
        role="나리",
        text="테스트 문장입니다.",
        emotion="happy",
        out_path=str(out_wav),
        text_language="ko",
        voice_type="young_woman",
    )
    assert fake_engine.calls[0]["ref_audio"] == ""
    assert fake_engine.calls[0]["voice_type"] == "young_woman"
    assert out_wav.exists()


def test_tts_manager_reference_free_failure_tries_sovits_fallback(tmp_path):
    class FailingReferenceFreeEngine:
        requires_reference_audio = False
        is_available = True
        engine_name = "Supertonic 3"

        def synthesize(self, **kwargs):
            return False

    manager = TTSManager(
        channel="daily_life_toon",
        target_language="ko",
        sovits_url="http://127.0.0.1:9880",
        sovits_root=str(tmp_path / "sovits"),
        assets_dir=str(tmp_path / "assets"),
        data_dir=str(tmp_path / "data"),
    )
    manager._tts_engine = FailingReferenceFreeEngine()
    manager._using_sovits = False
    manager._ensure_sovits_fallback_ready = lambda: True
    manager.ensure_sovits_engine = lambda: None
    manager.amplify_tts_volume = lambda *args, **kwargs: None

    fallback_calls = []

    def fake_sovits(role_key, emotion, text, out_wav, line_idx, voice_type=None):
        fallback_calls.append((role_key, emotion, text, out_wav, line_idx, voice_type))
        with open(out_wav, "wb") as f:
            f.write(b"RIFF" + b"\x00" * 128)
        return True

    manager.synthesize_with_sovits = fake_sovits

    out_wav = tmp_path / "fallback.wav"
    assert manager.generate_single_tts(
        role="나리",
        text="fallback 테스트입니다.",
        emotion="calm",
        out_path=str(out_wav),
        voice_type="young_woman",
    )
    assert fallback_calls
    assert out_wav.exists()
