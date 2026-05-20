"""
VoiceMode ↔ GPT-SoVITS TTS 프록시 서버
OpenAI TTS API 형식 → GPT-SoVITS API 형식 변환

사용법:
  python tools/tts_proxy.py [--port 8891] [--sovits-url http://127.0.0.1:9880]
"""

import argparse
import io
import json
import logging
import os
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("tts_proxy")

# ── 설정 ──────────────────────────────────────────────
SOVITS_URL = os.environ.get("SOVITS_URL", "http://127.0.0.1:9880")
PROXY_PORT = int(os.environ.get("TTS_PROXY_PORT", "8891"))

# voice → GPT-SoVITS 캐릭터 매핑
# VoiceMode voice 이름을 GPT-SoVITS 참조 오디오로 매핑
# 기본값: narrator_female (찡찡이 기본 목소리)
VOICE_MAP = {
    # 기본 찡찡이 목소리
    "default": "narrator_female",
    "af_heart": "narrator_female",
    "af_sky": "young_woman",
    "af_bella": "narrator_female",
    # 남성
    "am_adam": "young_man",
    "am_echo": "narrator_male",
}

# GPT-SoVITS 모델 경로 (assets/models/ 기준)
DEFAULT_REVERIE_BASE_DIR = Path(__file__).resolve().parents[1]
MODELS_BASE = Path(os.environ.get("REVERIE_BASE_DIR", DEFAULT_REVERIE_BASE_DIR)) / "assets" / "models"


def _find_ref_audio(voice_type: str) -> tuple:
    """voice_type에 해당하는 참조 오디오와 텍스트를 찾는다."""
    voice_dir = MODELS_BASE / voice_type
    if not voice_dir.exists():
        # 폴백: narrator_female
        voice_dir = MODELS_BASE / "narrator_female"

    # calm.wav 우선, 없으면 아무 wav
    ref_audio = voice_dir / "calm.wav"
    if not ref_audio.exists():
        wavs = list(voice_dir.glob("*.wav"))
        if wavs:
            ref_audio = wavs[0]
        else:
            return None, None

    # voice_metadata.json에서 참조 텍스트 로딩
    metadata_path = MODELS_BASE.parent / "voice_metadata.json"
    prompt_text = "안녕하세요."  # 기본값
    if metadata_path.exists():
        try:
            with open(metadata_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            if voice_type in meta:
                emotions = meta[voice_type]
                prompt_text = emotions.get("calm", emotions.get(list(emotions.keys())[0], prompt_text))
        except Exception:
            pass

    return str(ref_audio), prompt_text


def _find_weights(voice_type: str) -> tuple:
    """voice_type에 해당하는 GPT/SoVITS 가중치 경로를 찾는다."""
    voice_dir = MODELS_BASE / voice_type
    if not voice_dir.exists():
        voice_dir = MODELS_BASE / "narrator_female"

    gpt_weights = None
    sovits_weights = None

    for f in voice_dir.iterdir():
        if f.suffix == ".ckpt":
            gpt_weights = str(f)
        elif f.suffix == ".pth":
            sovits_weights = str(f)

    return gpt_weights, sovits_weights


# 현재 로드된 voice_type 캐싱
_current_voice = None


def _ensure_weights(voice_type: str):
    """필요한 경우 GPT-SoVITS 가중치를 로드한다."""
    global _current_voice
    if _current_voice == voice_type:
        return

    gpt_w, sovits_w = _find_weights(voice_type)
    if gpt_w:
        try:
            requests.get(f"{os.environ.get('SOVITS_URL', SOVITS_URL)}/set_gpt_weights", params={"weights_path": gpt_w}, timeout=30)
            log.info(f"GPT 가중치 로드: {gpt_w}")
        except Exception as e:
            log.warning(f"GPT 가중치 로드 실패: {e}")
    if sovits_w:
        try:
            requests.get(f"{os.environ.get('SOVITS_URL', SOVITS_URL)}/set_sovits_weights", params={"weights_path": sovits_w}, timeout=30)
            log.info(f"SoVITS 가중치 로드: {sovits_w}")
        except Exception as e:
            log.warning(f"SoVITS 가중치 로드 실패: {e}")

    _current_voice = voice_type


class TTSProxyHandler(BaseHTTPRequestHandler):
    """OpenAI TTS API → GPT-SoVITS 변환 핸들러"""

    def do_POST(self):
        if self.path == "/v1/audio/speech":
            self._handle_speech()
        else:
            self.send_error(404, "Not Found")

    def do_GET(self):
        if self.path == "/health" or self.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "backend": "gpt-sovits"}).encode())
        elif self.path == "/v1/models":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"data": [{"id": "gpt-sovits", "object": "model"}]}).encode())
        else:
            self.send_error(404, "Not Found")

    def _handle_speech(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(content_length))
        except Exception:
            self.send_error(400, "Invalid JSON")
            return

        text = body.get("input", "")
        voice = body.get("voice", "default")
        speed = body.get("speed", 1.0)

        if not text:
            self.send_error(400, "Missing 'input' field")
            return

        # voice 매핑
        voice_type = VOICE_MAP.get(voice, "narrator_female")
        log.info(f"TTS 요청: voice={voice} → {voice_type}, text={text[:50]}...")

        # 가중치 로드
        _ensure_weights(voice_type)

        # 참조 오디오 찾기
        ref_audio, prompt_text = _find_ref_audio(voice_type)
        if not ref_audio:
            self.send_error(500, f"참조 오디오를 찾을 수 없음: {voice_type}")
            return

        # GPT-SoVITS API 호출
        sovits_url = os.environ.get("SOVITS_URL", SOVITS_URL)
        sovits_payload = {
            "text": text,
            "text_lang": "ko",
            "ref_audio_path": ref_audio,
            "prompt_text": prompt_text,
            "prompt_lang": "ko",
            "top_k": 5,
            "top_p": 1.0,
            "temperature": 1.0,
            "speed_factor": speed,
        }

        try:
            res = requests.post(f"{sovits_url}/tts", json=sovits_payload, timeout=60)
        except requests.exceptions.ConnectionError:
            self.send_error(502, "GPT-SoVITS 서버에 연결할 수 없음")
            return
        except requests.exceptions.Timeout:
            self.send_error(504, "GPT-SoVITS 응답 시간 초과")
            return

        if res.status_code != 200 or len(res.content) < 1000:
            log.error(f"GPT-SoVITS 에러: status={res.status_code}, size={len(res.content)}")
            self.send_error(502, f"GPT-SoVITS 에러: {res.status_code}")
            return

        # WAV 응답 반환
        self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(len(res.content)))
        self.end_headers()
        self.wfile.write(res.content)
        log.info(f"TTS 완료: {len(res.content)} bytes")

    def log_message(self, format, *args):
        """기본 로그 숨기기 (우리 커스텀 로그 사용)"""
        pass


def main():
    parser = argparse.ArgumentParser(description="VoiceMode ↔ GPT-SoVITS TTS 프록시")
    parser.add_argument("--port", type=int, default=PROXY_PORT, help="프록시 포트 (기본: 8891)")
    parser.add_argument("--sovits-url", default=SOVITS_URL, help="GPT-SoVITS URL (기본: http://127.0.0.1:9880)")
    args = parser.parse_args()

    os.environ["SOVITS_URL"] = args.sovits_url

    server = HTTPServer(("0.0.0.0", args.port), TTSProxyHandler)
    log.info(f"🎙️ TTS 프록시 시작: http://0.0.0.0:{args.port}")
    log.info(f"   → GPT-SoVITS: {args.sovits_url}")
    log.info(f"   → 모델 경로: {MODELS_BASE}")
    log.info(f"   VoiceMode에서 TTS_BASE_URLS=http://127.0.0.1:{args.port}/v1 로 설정하세요")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("프록시 종료")
        server.server_close()


if __name__ == "__main__":
    main()
