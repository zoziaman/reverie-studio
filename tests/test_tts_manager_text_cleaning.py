from types import SimpleNamespace


def _build_manager():
    from pipeline import tts_manager as tts_module

    manager = tts_module.TTSManager.__new__(tts_module.TTSManager)
    manager._clean_text_fn = lambda text: f"caption::{text}"
    manager._clean_text_for_tts_fn = lambda text: f"tts::{text}"
    manager._register_characters_fn = None
    manager._test_mode = False
    manager._test_duration = 0.0
    manager.cancellation_token = None
    manager.data_dir = "C:\\ReverieStudio\\data"
    manager._split_subtitle_entry = lambda entry: [entry]
    manager.estimate_silence_duration = lambda _text: 0.1
    manager.tts_line_to_clip = lambda role, emotion, text, out_wav, i, voice_type="": SimpleNamespace(duration=0.1)
    return manager


def _patch_moviepy(monkeypatch, tts_module):
    monkeypatch.setattr(tts_module, "MOVIEPY_AVAILABLE", True, raising=False)
    monkeypatch.setattr(
        tts_module,
        "AudioClip",
        lambda fn, duration=0.0: SimpleNamespace(duration=duration),
        raising=False,
    )
    monkeypatch.setattr(tts_module.os, "makedirs", lambda *args, **kwargs: None, raising=False)

    class _FinalAudio:
        def write_audiofile(self, *args, **kwargs):
            return None

        def close(self):
            return None

    monkeypatch.setattr(
        tts_module,
        "concatenate_audioclips",
        lambda clips: _FinalAudio(),
        raising=False,
    )


def test_generate_voice_and_subtitles_sequential_uses_tts_cleaner(monkeypatch, tmp_path):
    from pipeline import tts_manager as tts_module

    _patch_moviepy(monkeypatch, tts_module)

    captured = {}
    manager = _build_manager()

    def fake_tts_line_to_clip(role, emotion, text, out_wav, i, voice_type=""):
        captured["speech_text"] = text
        return SimpleNamespace(duration=0.1)

    manager.tts_line_to_clip = fake_tts_line_to_clip

    audio_path, subtitle_data = manager.generate_voice_and_subtitles_sequential(
        script_list=[{"role": "narrator", "voice_type": "narrator", "emotion": "calm", "text": "950324..."}],
        project_name="proj",
        sanitize_fn=lambda text: "proj",
    )

    assert captured["speech_text"] == "tts::950324..."
    assert subtitle_data[0]["text"] == "caption::950324..."
    assert audio_path is not None


def test_generate_voice_and_subtitles_base_path_uses_tts_cleaner(monkeypatch):
    from pipeline import tts_manager as tts_module

    _patch_moviepy(monkeypatch, tts_module)

    captured = {}
    manager = _build_manager()

    def fake_tts_line_to_clip(role, emotion, text, out_wav, i, voice_type=""):
        captured["speech_text"] = text
        return SimpleNamespace(duration=0.1)

    manager.tts_line_to_clip = fake_tts_line_to_clip

    audio_path, subtitle_data = manager.generate_voice_and_subtitles(
        script_list=[{"role": "narrator", "voice_type": "narrator", "emotion": "calm", "text": "0101234"}],
        project_name="proj",
        sanitize_fn=lambda text: "proj",
    )

    assert captured["speech_text"] == "tts::0101234"
    assert subtitle_data[0]["text"] == "caption::0101234"
    assert audio_path is not None
