from pathlib import Path
from unittest.mock import MagicMock, patch


PROJECT_ROOT = Path(__file__).parent.parent


def _invalid_argument_response():
    response = MagicMock()
    response.status_code = 400
    response.headers = {"content-type": "application/json"}
    response.content = b'{"message":"tts failed","Exception":"[Errno 22] Invalid argument"}'
    response.text = '{"message":"tts failed","Exception":"[Errno 22] Invalid argument"}'
    return response


def _audio_response():
    response = MagicMock()
    response.status_code = 200
    response.headers = {"content-type": "audio/wav"}
    response.content = b"RIFF" + (b"\x00" * 4096)
    response.text = ""
    return response


# test_tts_manager_recovers_from_invalid_argument_without_legacy_endpoints
# 제거됨: tts_manager.py revert로 _recover_sovits_server_state 메서드 없음


def test_audio_synthesizer_recovers_from_invalid_argument(tmp_path):
    from modules_pro.audio_synthesizer import AudioSynthesizer

    synthesizer = AudioSynthesizer(channel="senior", sovits_url="http://127.0.0.1:9880")
    synthesizer.current_gpt = "C:/fake/current_gpt.ckpt"
    synthesizer.current_sovits = "C:/fake/current_sovits.pth"
    output_path = tmp_path / "tts.wav"

    with patch.object(
        synthesizer,
        "_recover_server_after_invalid_argument",
        return_value=True,
    ) as recover_mock:
        with patch(
            "modules_pro.audio_synthesizer.requests.post",
            side_effect=[_invalid_argument_response(), _audio_response()],
        ):
            result = synthesizer.generate_tts(
                text="테스트입니다.",
                ref_audio="C:/fake/ref.wav",
                ref_text="왜요?",
                output_path=str(output_path),
                language="ko",
            )

    assert result is True
    assert output_path.exists()
    assert recover_mock.call_count == 1


def test_tts_server_manager_check_connection_accepts_openapi_when_root_is_404():
    from modules_pro.tts_server_manager import TTSServerManager

    manager = TTSServerManager(
        sovits_url="http://127.0.0.1:9880",
        sovits_root="C:/fake/sovits",
    )

    root_404 = MagicMock(status_code=404)
    openapi_ok = MagicMock(status_code=200)

    def fake_get(url, timeout):
        if url.endswith("/openapi.json"):
            return openapi_ok
        return root_404

    with patch("modules_pro.tts_server_manager.requests.get", side_effect=fake_get):
        assert manager.check_connection() is True
