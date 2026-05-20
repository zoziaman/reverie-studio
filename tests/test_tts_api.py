"""Opt-in live GPT-SoVITS API smoke test.

The live server test is intentionally skipped by default so normal pytest runs
do not hit localhost services or write generated audio into the repository.
Run it only with REVERIE_RUN_LIVE_TTS_TESTS=1 after configuring local paths.
"""

import os
from pathlib import Path

import pytest
import requests


pytestmark = pytest.mark.skipif(
    os.environ.get("REVERIE_RUN_LIVE_TTS_TESTS") != "1",
    reason="live GPT-SoVITS smoke test is opt-in",
)


def test_live_gpt_sovits_tts_api(tmp_path):
    base_url = os.environ.get("SOVITS_URL", "http://127.0.0.1:9880").rstrip("/")
    wav_path = os.environ.get("REVERIE_TTS_REF_WAV", "")
    gpt_path = os.environ.get("REVERIE_TTS_GPT_WEIGHT", "")
    sov_path = os.environ.get("REVERIE_TTS_SOVITS_WEIGHT", "")

    missing = [name for name, value in {
        "REVERIE_TTS_REF_WAV": wav_path,
        "REVERIE_TTS_GPT_WEIGHT": gpt_path,
        "REVERIE_TTS_SOVITS_WEIGHT": sov_path,
    }.items() if not value or not Path(value).exists()]
    if missing:
        pytest.skip(f"live TTS paths not configured: {', '.join(missing)}")

    for endpoint, query_value in (
        ("set_gpt_weights", gpt_path),
        ("set_sovits_weights", sov_path),
        ("set_refer_audio", wav_path),
    ):
        response = requests.get(
            f"{base_url}/{endpoint}",
            params={"weights_path": query_value} if "weights" in endpoint else {"refer_audio_path": query_value},
            timeout=30,
        )
        assert response.status_code == 200

    response = requests.post(
        f"{base_url}/tts",
        json={
            "text": "안녕하세요",
            "text_lang": "ko",
            "prompt_lang": "ko",
            "prompt_text": "네",
        },
        timeout=30,
    )
    assert response.status_code == 200
    assert len(response.content) > 1000

    out_wav = tmp_path / "tts_result.wav"
    out_wav.write_bytes(response.content)
    assert out_wav.stat().st_size > 1000
