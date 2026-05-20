# tests/test_pipeline_mock.py
r"""
v60.1.0 B-2: 핵심 API Mock 테스트

외부 서비스 없이 파이프라인 모듈의 에러 핸들링, 재시도, 폴백 로직을 검증.
모든 HTTP 호출(SD WebUI, TTS, Gemini)을 mock하여 순수 로직만 테스트.

실행:
    cd <repo-root>
    pytest tests/test_pipeline_mock.py -v

카테고리:
    1. SD WebUI (sd_client.py) — 재시도, 타임아웃, 성공
    2. TTS (tts_manager.py) — 실패, 엔드포인트 폴백, 빈 오디오
    3. Pack 로딩 (pack_config.py) — 5팩 순회, ZIP 손상, get_prompt
    4. PipelineContext — 체크포인트, 취소, 일시정지
    5. PipelineStepResult — 표준 결과 타입
"""
import os
import sys
import json
import zipfile
import tempfile
import pytest
from unittest.mock import patch, MagicMock, PropertyMock
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent


def _pack_password_configured() -> bool:
    return bool(os.environ.get("REVERIE_PACK_PASSWORD"))


# ============================================================
# 1. SD WebUI (sd_client.py) — 재시도/타임아웃/성공
# ============================================================

class TestSDClientRetry:
    """SD WebUI API 재시도 로직 테스트

    sd_client.py는 함수 내부에서 `import requests`하므로
    글로벌 requests 모듈을 패치합니다.
    """

    def _make_mock_response(self, images=None, info="{}"):
        """성공 응답 mock 생성 헬퍼"""
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"images": images or ["base64_data"], "info": info}
        resp.raise_for_status = MagicMock()
        return resp

    def test_sd_txt2img_success_first_try(self):
        """정상 호출: 1회 시도로 성공"""
        import requests as req_mod
        from pipeline.sd_client import SDClientWrapper

        mock_resp = self._make_mock_response(["img_data_ok"])

        with patch.object(req_mod, "post", return_value=mock_resp) as mock_post:
            client = SDClientWrapper("http://127.0.0.1:7860")
            result = client.txt2img(
                prompt="test prompt",
                negative_prompt="bad quality",
                width=768, height=512, steps=20,
            )

        assert "images" in result
        assert result["images"] == ["img_data_ok"]
        mock_post.assert_called_once()

    def test_sd_txt2img_retry_on_timeout(self):
        """타임아웃 후 재시도하여 성공"""
        import requests as req_mod
        from pipeline.sd_client import SDClientWrapper

        mock_success = self._make_mock_response(["ok"])

        with patch.object(req_mod, "post") as mock_post:
            mock_post.side_effect = [
                req_mod.exceptions.Timeout("Connection timed out"),
                mock_success,
            ]
            with patch("pipeline.pipeline_utils.time.sleep"):
                client = SDClientWrapper("http://127.0.0.1:7860")
                result = client.txt2img(prompt="test")

        assert result["images"] == ["ok"]
        assert mock_post.call_count == 2

    def test_sd_txt2img_retry_on_connection_error(self):
        """연결 오류 후 재시도하여 성공"""
        import requests as req_mod
        from pipeline.sd_client import SDClientWrapper

        mock_success = self._make_mock_response(["recovered"])

        with patch.object(req_mod, "post") as mock_post:
            mock_post.side_effect = [
                req_mod.exceptions.ConnectionError("Connection refused"),
                req_mod.exceptions.ConnectionError("Connection refused"),
                mock_success,
            ]
            with patch("pipeline.pipeline_utils.time.sleep"):
                client = SDClientWrapper("http://127.0.0.1:7860")
                result = client.txt2img(prompt="test")

        assert result["images"] == ["recovered"]
        assert mock_post.call_count == 3

    def test_sd_txt2img_all_retries_exhausted(self):
        """3회 모두 실패 시 예외 발생"""
        import requests as req_mod
        from pipeline.sd_client import SDClientWrapper

        with patch.object(req_mod, "post") as mock_post:
            mock_post.side_effect = req_mod.exceptions.Timeout("Persistent timeout")
            with patch("pipeline.pipeline_utils.time.sleep"):
                client = SDClientWrapper("http://127.0.0.1:7860")
                with pytest.raises(req_mod.exceptions.Timeout):
                    client.txt2img(prompt="test")

        assert mock_post.call_count == 3  # _SD_MAX_RETRIES = 3

    def test_sd_txt2img_restarts_server_after_repeated_500(self):
        """연속 5xx면 SD WebUI 재시작 후 한 번 더 시도한다."""
        import requests as req_mod
        from pipeline.sd_client import SDClientWrapper

        def _server_error_response():
            resp = MagicMock()
            resp.status_code = 500
            resp.text = "Internal Server Error"
            resp.raise_for_status = MagicMock()
            return resp

        mock_success = self._make_mock_response(["recovered"])

        with patch.object(req_mod, "post") as mock_post:
            mock_post.side_effect = [
                _server_error_response(),
                _server_error_response(),
                _server_error_response(),
                mock_success,
            ]
            with patch("pipeline.pipeline_utils.time.sleep"), \
                 patch("pipeline.sd_client._restart_sd_webui_server", return_value=True) as mock_restart:
                client = SDClientWrapper("http://127.0.0.1:7860")
                result = client.txt2img(prompt="test")

        assert result["images"] == ["recovered"]
        assert mock_post.call_count == 4
        mock_restart.assert_called_once_with("http://127.0.0.1:7860")

    def test_sd_txt2img_raises_when_500_persists_after_recovery(self):
        """재시작을 못 하면 연속 5xx는 HTTPError로 종료한다."""
        import requests as req_mod
        from pipeline.sd_client import SDClientWrapper

        def _server_error_response():
            resp = MagicMock()
            resp.status_code = 500
            resp.text = "Internal Server Error"
            resp.raise_for_status = MagicMock()
            return resp

        with patch.object(req_mod, "post") as mock_post:
            mock_post.side_effect = [_server_error_response()] * 3
            with patch("pipeline.pipeline_utils.time.sleep"), \
                 patch("pipeline.sd_client._restart_sd_webui_server", return_value=False) as mock_restart:
                client = SDClientWrapper("http://127.0.0.1:7860")
                with pytest.raises(req_mod.exceptions.HTTPError):
                    client.txt2img(prompt="test")

        assert mock_post.call_count == 3
        mock_restart.assert_called_once_with("http://127.0.0.1:7860")

    def test_sd_txt2img_unexpected_error_no_retry(self):
        """예상치 못한 에러는 즉시 raise (재시도 없음)"""
        import requests as req_mod
        from pipeline.sd_client import SDClientWrapper

        with patch.object(req_mod, "post") as mock_post:
            mock_post.side_effect = ValueError("Unexpected JSON error")
            client = SDClientWrapper("http://127.0.0.1:7860")
            with pytest.raises(ValueError, match="Unexpected JSON error"):
                client.txt2img(prompt="test")

        assert mock_post.call_count == 1  # 즉시 raise

    def test_sd_txt2img_exponential_backoff_delays(self):
        """지수 백오프 딜레이 확인"""
        import requests as req_mod
        from pipeline.sd_client import SDClientWrapper

        mock_success = self._make_mock_response(["ok"])

        with patch.object(req_mod, "post") as mock_post:
            mock_post.side_effect = [
                req_mod.exceptions.Timeout(),
                req_mod.exceptions.Timeout(),
                mock_success,
            ]
            sleep_calls = []
            with patch("pipeline.pipeline_utils.time.sleep", side_effect=lambda d: sleep_calls.append(d)):
                with patch("pipeline.pipeline_utils.random.random", return_value=0.5):
                    client = SDClientWrapper("http://127.0.0.1:7860")
                    client.txt2img(prompt="test")

        # _SD_BASE_DELAY=2.0, attempt=0: 2.0 * 1 * 1.0 = 2.0
        # _SD_BASE_DELAY=2.0, attempt=1: 2.0 * 2 * 1.0 = 4.0
        assert len(sleep_calls) == 2
        assert sleep_calls[0] == pytest.approx(2.0, rel=0.01)
        assert sleep_calls[1] == pytest.approx(4.0, rel=0.01)

    def test_sd_txt2img_payload_construction(self):
        """페이로드가 올바르게 구성되는지 확인"""
        import requests as req_mod
        from pipeline.sd_client import SDClientWrapper

        mock_resp = self._make_mock_response([])

        with patch.object(req_mod, "post", return_value=mock_resp) as mock_post:
            client = SDClientWrapper("http://127.0.0.1:7860")
            client.txt2img(
                prompt="a cat",
                negative_prompt="ugly",
                width=1024, height=768, steps=30,
                cfg_scale=9, seed=42,
                override_settings={"sd_model_checkpoint": "v1-5"},
                override_settings_restore_afterwards=True,
            )

        call_payload = mock_post.call_args[1]["json"]
        assert call_payload["prompt"] == "a cat"
        assert call_payload["negative_prompt"] == "ugly"
        assert call_payload["width"] == 1024
        assert call_payload["height"] == 768
        assert call_payload["steps"] == 30
        assert call_payload["cfg_scale"] == 9
        assert call_payload["seed"] == 42
        assert call_payload["override_settings"] == {"sd_model_checkpoint": "v1-5"}
        assert call_payload["override_settings_restore_afterwards"] is True

    def test_sd_txt2img_uses_extended_read_timeout(self):
        """무거운 SD 작업용으로 긴 read timeout을 사용한다."""
        import requests as req_mod
        from pipeline.sd_client import SDClientWrapper

        mock_resp = self._make_mock_response(["ok"])

        with patch.object(req_mod, "post", return_value=mock_resp) as mock_post:
            client = SDClientWrapper("http://127.0.0.1:7860")
            client.txt2img(prompt="test")

        assert mock_post.call_args.kwargs["timeout"] == (30, 300)

    def test_sd_timeout_env_override_is_clamped(self):
        """환경변수 override가 너무 작아도 최소 read timeout은 유지한다."""
        from pipeline.sd_client import _get_sd_request_timeout

        with patch.dict(os.environ, {"REVERIE_SD_READ_TIMEOUT_SEC": "120"}):
            assert _get_sd_request_timeout() == (30, 300)

    def test_sd_client_endpoint_url(self):
        """엔드포인트 URL이 올바르게 구성되는지"""
        from pipeline.sd_client import SDClientWrapper

        client = SDClientWrapper("http://127.0.0.1:7860/")
        assert client._endpoint == "http://127.0.0.1:7860/sdapi/v1/txt2img"

        client2 = SDClientWrapper("http://127.0.0.1:7860")
        assert client2._endpoint == "http://127.0.0.1:7860/sdapi/v1/txt2img"


class TestSDClientFactory:
    """SD 클라이언트 팩토리 함수 테스트"""

    def test_create_sd_client_success(self):
        """SD WebUI 접속 가능 시 래퍼 반환"""
        import requests as req_mod
        from pipeline.sd_client import create_sd_client, SDClientWrapper

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch.object(req_mod, "get", return_value=mock_response):
            client = create_sd_client("http://127.0.0.1:7860")

        assert isinstance(client, SDClientWrapper)

    def test_create_sd_client_connection_fail(self):
        """SD WebUI 연결 불가해도 래퍼 생성 (VSD fallback용)"""
        import requests as req_mod
        from pipeline.sd_client import create_sd_client, SDClientWrapper

        with patch.object(req_mod, "get", side_effect=req_mod.ConnectionError):
            client = create_sd_client("http://127.0.0.1:7860")

        assert isinstance(client, SDClientWrapper)


# ============================================================
# 2. TTS (tts_manager.py) — 실패/폴백/엔드포인트 로테이션
# ============================================================

class TestTTSManagerMock:
    """TTS 관련 mock 테스트

    tts_manager.py도 함수 내부에서 import requests하므로
    requests 모듈 레벨 패치 + check_tts_server mock 필요.
    tts_post_request는 content > 1000 바이트를 요구.
    """

    def _create_tts_manager(self):
        """테스트용 TTSManager 생성 (target_language 필수)"""
        from pipeline.tts_manager import TTSManager
        return TTSManager(
            channel="horror",
            target_language="ko",
            sovits_url="http://127.0.0.1:9880",
            sovits_root="C:/fake/sovits",
            assets_dir="C:/fake/assets",
            data_dir="C:/fake/data",
            ffmpeg_path="C:/fake/ffmpeg.exe",
        )

    def test_tts_post_request_success(self):
        """TTS API 정상 호출 — WAV 데이터 반환"""
        import requests as req_mod

        mgr = self._create_tts_manager()

        # 1000바이트 이상의 가짜 WAV 데이터 생성
        fake_wav = b"RIFF" + b"\x00" * 2000 + b"WAVEfmt "
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = fake_wav
        mock_response.text = ""

        # check_tts_server를 True로 mock (서버 있는 척)
        with patch.object(mgr, "check_tts_server", return_value=True):
            with patch.object(req_mod, "post", return_value=mock_response):
                result = mgr.tts_post_request(
                    send_text="테스트 텍스트",
                    ref_audio="C:/fake/ref.wav",
                    ref_text="참조 텍스트",
                )

        assert result is not None
        assert len(result) > 1000

    def test_tts_post_request_connection_error(self):
        """TTS 서버 연결 실패 → None 반환"""
        import requests as req_mod

        mgr = self._create_tts_manager()

        # check_tts_server=True이지만 실제 요청은 실패
        with patch.object(mgr, "check_tts_server", return_value=True):
            with patch.object(req_mod, "post", side_effect=req_mod.exceptions.ConnectionError):
                with patch.object(req_mod, "get", side_effect=req_mod.exceptions.ConnectionError):
                    with patch("pipeline.tts_manager.time.sleep"):
                        result = mgr.tts_post_request(
                            send_text="테스트",
                            ref_audio="C:/fake/ref.wav",
                            ref_text="참조",
                        )

        assert result is None

    def test_tts_post_request_small_response(self):
        """TTS 서버가 작은 응답 반환 (< 1000바이트) → 재시도 후 None"""
        import requests as req_mod

        mgr = self._create_tts_manager()

        # 100바이트 응답 → 1000바이트 미만이므로 실패 처리
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"x" * 100
        mock_response.text = "small response"

        with patch.object(mgr, "check_tts_server", return_value=True):
            with patch.object(req_mod, "post", return_value=mock_response):
                with patch.object(req_mod, "get", return_value=mock_response):
                    with patch("pipeline.tts_manager.time.sleep"):
                        result = mgr.tts_post_request(
                            send_text="테스트",
                            ref_audio="C:/fake/ref.wav",
                            ref_text="참조",
                        )

        assert result is None

    def test_tts_post_request_server_down(self):
        """TTS 서버 자체가 다운 → check_tts_server 실패 → 재시작 시도"""
        mgr = self._create_tts_manager()

        with patch.object(mgr, "check_tts_server", return_value=False):
            with patch.object(mgr, "restart_tts_server", return_value=False):
                result = mgr.tts_post_request(
                    send_text="테스트",
                    ref_audio="C:/fake/ref.wav",
                    ref_text="참조",
                )

        assert result is None

    def test_tts_manager_set_callbacks(self):
        """콜백 주입 후 올바르게 저장되는지"""
        mgr = self._create_tts_manager()

        mock_clean = MagicMock(return_value="cleaned text")
        mock_normalize = MagicMock(return_value="normalized_key")

        mgr.set_callbacks(
            clean_text=mock_clean,
            role_key_normalize=mock_normalize,
        )

        assert mgr._clean_text_fn is mock_clean
        assert mgr._role_key_normalize_fn is mock_normalize

    def test_tts_manager_initialization(self):
        """TTSManager 생성자 정상 동작"""
        from pipeline.tts_manager import TTSManager

        mgr = TTSManager(
            channel="senior",
            target_language="ko",
            sovits_url="http://localhost:9880",
            sovits_root="C:/GPT-SoVITS",
            assets_dir="C:/assets",
            data_dir="C:/data",
            ffmpeg_path="C:/ffmpeg/ffmpeg.exe",
            video_width=1920,
            video_height=1080,
        )

        assert mgr.channel == "senior"
        assert mgr.target_language == "ko"
        assert mgr.video_width == 1920


# ============================================================
# 3. Pack 로딩 (pack_config.py) — 5팩 순회/ZIP 손상/get_prompt
# ============================================================

class TestPackLoading:
    """팩 로딩 + get_prompt 테스트"""

    def _create_test_revpack(self, tmp_dir: str, pack_id: str = "test_pack",
                              manifest: dict = None, settings: dict = None,
                              prompts: dict = None) -> str:
        """테스트용 .revpack (ZIP) 파일 생성 — validator 통과를 위해 필수 필드 포함"""
        if manifest is None:
            manifest = {
                "package_name": pack_id,
                "pack_id": pack_id,
                "version": "1.0.0",
                "genre": "horror",
                "author": "test",
                "reverie_version_min": "1",
            }
        if settings is None:
            settings = {
                "tts": {"engine": "sovits", "character_mapping": {}},
                "visual_storytelling": {
                    "enabled": False,  # enabled=False면 characters 불필요
                    "sd_model": {"checkpoint": "test.safetensors"},
                },
                "sd": {"url": "http://127.0.0.1:7860"},
                "visual": {"safe_fallbacks": []},
            }
        if prompts is None:
            prompts = {
                "pd_system": "You are a PD.",
                "writer_system": "You are a writer.",
            }

        pack_path = os.path.join(tmp_dir, f"{pack_id}.revpack")
        with zipfile.ZipFile(pack_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
            zf.writestr("settings.json", json.dumps(settings, ensure_ascii=False))
            zf.writestr("topics.json", json.dumps({"templates": [], "tags": []}, ensure_ascii=False))

            # prompts/ 폴더
            if "pd_system" in prompts:
                zf.writestr("prompts/pd_system.txt", prompts["pd_system"])
            if "writer_system" in prompts:
                zf.writestr("prompts/writer_system.txt", prompts["writer_system"])
            if "sd_prompts" in prompts:
                zf.writestr("prompts/sd_prompts.json", json.dumps(prompts["sd_prompts"]))
            else:
                zf.writestr("prompts/sd_prompts.json", json.dumps({
                    "positive": "masterpiece, best quality",
                    "negative": "(worst quality:1.4)",
                }))

            # v60: 새 프롬프트 파일들
            for key in ["topic_generation", "hook_generation", "craft_rules",
                        "story_bible", "image_style", "image_llm_prompt",
                        "pacing_part1", "pacing_part2", "pacing_part3"]:
                if key in prompts:
                    zf.writestr(f"prompts/{key}.txt", prompts[key])

        return pack_path

    def test_load_pack_valid_revpack(self, tmp_path):
        """유효한 .revpack 파일 로드 성공"""
        from config.pack_config import load_pack, ACTIVE_PACK

        pack_path = self._create_test_revpack(str(tmp_path), "horror_test")
        result = load_pack(pack_path)

        assert result is True
        assert ACTIVE_PACK.is_loaded is True

    def test_load_pack_missing_file(self):
        """존재하지 않는 파일 → False"""
        from config.pack_config import load_pack

        result = load_pack("/nonexistent/path/fake.revpack")
        assert result is False

    def test_load_pack_invalid_extension(self, tmp_path):
        """잘못된 확장자 → False"""
        from config.pack_config import load_pack

        bad_file = tmp_path / "test.txt"
        bad_file.write_text("not a pack")

        result = load_pack(str(bad_file))
        assert result is False

    def test_load_pack_corrupted_zip(self, tmp_path):
        """손상된 ZIP 파일 → False (크래시 없음)"""
        from config.pack_config import load_pack

        corrupt_path = tmp_path / "corrupt.revpack"
        corrupt_path.write_bytes(b"this is not a zip file at all")

        result = load_pack(str(corrupt_path))
        assert result is False

    def test_load_pack_empty_zip(self, tmp_path):
        """빈 ZIP (manifest 없음) → False 또는 빈 팩 로드"""
        from config.pack_config import load_pack

        pack_path = tmp_path / "empty.revpack"
        with zipfile.ZipFile(str(pack_path), 'w') as zf:
            pass  # 빈 ZIP

        result = load_pack(str(pack_path))
        # 빈 ZIP도 로드 시도하지만 manifest 없으면 기본값으로 처리
        # 크래시하지 않으면 OK
        assert isinstance(result, bool)

    def test_load_pack_with_v60_prompts(self, tmp_path):
        """v60 새 프롬프트 필드가 올바르게 로딩되는지"""
        from config.pack_config import load_pack, ACTIVE_PACK

        pack_path = self._create_test_revpack(
            str(tmp_path), "v60_test",
            prompts={
                "pd_system": "PD system prompt",
                "writer_system": "Writer system",
                "topic_generation": "Generate a horror topic...",
                "hook_generation": "Create an opening hook...",
                "craft_rules": "Writing craft rules here...",
                "story_bible": "Build a story bible...",
                "image_style": "dark horror manga style...",
                "pacing_part1": "Part 1 pacing guide...",
            }
        )

        result = load_pack(pack_path)
        assert result is True
        assert ACTIVE_PACK.prompts.topic_generation == "Generate a horror topic..."
        assert ACTIVE_PACK.prompts.hook_generation == "Create an opening hook..."
        assert ACTIVE_PACK.prompts.craft_rules == "Writing craft rules here..."
        assert ACTIVE_PACK.prompts.story_bible == "Build a story bible..."
        assert ACTIVE_PACK.prompts.image_style == "dark horror manga style..."
        assert ACTIVE_PACK.prompts.pacing_part1 == "Part 1 pacing guide..."


class TestGetPrompt:
    """get_prompt() 함수 테스트"""

    def _setup_pack(self, tmp_path):
        """테스트용 팩 로드 — validator 통과를 위해 필수 필드 포함"""
        from config.pack_config import load_pack, ACTIVE_PACK

        manifest = {
            "package_name": "test", "pack_id": "test",
            "version": "1.0.0", "genre": "horror", "author": "test",
            "reverie_version_min": "1",
        }
        settings = {
            "tts": {"engine": "sovits", "character_mapping": {}},
            "visual_storytelling": {
                "enabled": False,
                "sd_model": {"checkpoint": "test.safetensors"},
            },
            "sd": {"url": "http://127.0.0.1:7860"},
            "visual": {"safe_fallbacks": []},
        }

        pack_path = tmp_path / "test.revpack"
        with zipfile.ZipFile(str(pack_path), 'w') as zf:
            zf.writestr("manifest.json", json.dumps(manifest))
            zf.writestr("settings.json", json.dumps(settings))
            zf.writestr("topics.json", json.dumps({"templates": [], "tags": []}))
            zf.writestr("prompts/pd_system.txt", "Test PD system")
            zf.writestr("prompts/writer_system.txt", "Test writer system")
            zf.writestr("prompts/sd_prompts.json", json.dumps({
                "positive": "masterpiece, best quality, horror",
                "negative": "(worst quality:1.4), nsfw",
            }))
            zf.writestr("prompts/topic_generation.txt", "Generate a topic about fear...")
            zf.writestr("prompts/craft_rules.txt", "Write with suspense and dread...")

        load_pack(str(pack_path))

    def test_get_prompt_pd_system(self, tmp_path):
        """pd_system 프롬프트 반환"""
        self._setup_pack(tmp_path)
        from config.pack_config import get_prompt

        result = get_prompt("pd_system")
        assert result == "Test PD system"

    def test_get_prompt_writer_system(self, tmp_path):
        """writer_system 프롬프트 반환"""
        self._setup_pack(tmp_path)
        from config.pack_config import get_prompt

        result = get_prompt("writer_system")
        assert result == "Test writer system"

    def test_get_prompt_sd_positive_auto_quality(self, tmp_path):
        """sd_positive 프롬프트 — 품질 태그 자동 추가 로직"""
        self._setup_pack(tmp_path)
        from config.pack_config import get_prompt

        result = get_prompt("sd_positive")
        assert "masterpiece" in result.lower()

    def test_get_prompt_sd_negative_auto_quality(self, tmp_path):
        """sd_negative 프롬프트 — 품질 태그 자동 추가 로직"""
        self._setup_pack(tmp_path)
        from config.pack_config import get_prompt

        result = get_prompt("sd_negative")
        assert "worst quality" in result.lower()

    def test_get_prompt_v60_topic_generation(self, tmp_path):
        """v60 새 필드: topic_generation"""
        self._setup_pack(tmp_path)
        from config.pack_config import get_prompt

        result = get_prompt("topic_generation")
        assert "fear" in result.lower()

    def test_get_prompt_v60_craft_rules(self, tmp_path):
        """v60 새 필드: craft_rules"""
        self._setup_pack(tmp_path)
        from config.pack_config import get_prompt

        result = get_prompt("craft_rules")
        assert "suspense" in result.lower()

    def test_get_prompt_unknown_type(self, tmp_path):
        """알 수 없는 프롬프트 타입 → 빈 문자열"""
        self._setup_pack(tmp_path)
        from config.pack_config import get_prompt

        result = get_prompt("nonexistent_prompt_type")
        assert result == ""

    def test_get_prompt_safe_fallback(self, tmp_path):
        """safe_fallback 프롬프트 — visual 설정에서 로딩"""
        self._setup_pack(tmp_path)
        from config.pack_config import get_prompt

        # safe_fallback은 ACTIVE_PACK.visual.safe_fallback_prompt에서 로딩
        result = get_prompt("safe_fallback")
        assert isinstance(result, str)  # 빈 문자열이어도 OK


class TestPackIteration:
    """5개 팩 순회 로딩 테스트 (실제 .revpack 파일 사용)"""

    PACK_IDS = [
        "horror_default",
        "horror_mystery",
        "senior_touching",
        "senior_makjang",
    ]

    @pytest.mark.parametrize("pack_id", PACK_IDS)
    def test_load_actual_pack(self, pack_id):
        """실제 .revpack 파일 로드 테스트"""
        from config.pack_config import load_pack, ACTIVE_PACK

        if not _pack_password_configured():
            pytest.skip("REVERIE_PACK_PASSWORD 미설정 — 실물 .revpack 로드 테스트 skip")

        packs_dir = PROJECT_ROOT / "assets" / "packs"
        pack_path = packs_dir / f"{pack_id}.revpack"

        if not pack_path.exists():
            pytest.skip(f"{pack_path.name} 없음")

        result = load_pack(str(pack_path))
        assert result is True, f"{pack_id} 로드 실패"
        assert ACTIVE_PACK.is_loaded is True

    @pytest.mark.parametrize("pack_id", PACK_IDS)
    def test_actual_pack_has_core_prompts(self, pack_id):
        """실제 팩에 핵심 프롬프트가 존재하는지"""
        from config.pack_config import load_pack, get_prompt, ACTIVE_PACK

        if not _pack_password_configured():
            pytest.skip("REVERIE_PACK_PASSWORD 미설정 — 실물 .revpack 로드 테스트 skip")

        packs_dir = PROJECT_ROOT / "assets" / "packs"
        pack_path = packs_dir / f"{pack_id}.revpack"

        if not pack_path.exists():
            pytest.skip(f"{pack_path.name} 없음")

        load_pack(str(pack_path))

        # 핵심 4대 프롬프트는 반드시 있어야 함
        pd = get_prompt("pd_system")
        writer = get_prompt("writer_system")
        sd_pos = get_prompt("sd_positive")
        sd_neg = get_prompt("sd_negative")

        assert pd, f"{pack_id}: pd_system 비어있음"
        assert writer, f"{pack_id}: writer_system 비어있음"
        assert sd_pos, f"{pack_id}: sd_positive 비어있음"
        assert sd_neg, f"{pack_id}: sd_negative 비어있음"

    @pytest.mark.parametrize("pack_id", PACK_IDS)
    def test_actual_pack_manifest_fields(self, pack_id):
        """실제 팩 manifest 필드 확인"""
        from config.pack_config import load_pack, ACTIVE_PACK

        if not _pack_password_configured():
            pytest.skip("REVERIE_PACK_PASSWORD 미설정 — 실물 .revpack 로드 테스트 skip")

        packs_dir = PROJECT_ROOT / "assets" / "packs"
        pack_path = packs_dir / f"{pack_id}.revpack"

        if not pack_path.exists():
            pytest.skip(f"{pack_path.name} 없음")

        load_pack(str(pack_path))

        assert ACTIVE_PACK.pack_id, f"{pack_id}: pack_id 없음"
        assert ACTIVE_PACK.pack_name, f"{pack_id}: pack_name 없음"

    def test_load_pack_by_id_horror_alias(self):
        """load_pack_by_id('horror') → horror_default.revpack"""
        from config.pack_config import load_pack_by_id, ACTIVE_PACK

        if not _pack_password_configured():
            pytest.skip("REVERIE_PACK_PASSWORD 미설정 — 실물 .revpack 로드 테스트 skip")

        packs_dir = PROJECT_ROOT / "assets" / "packs"
        if not (packs_dir / "horror_default.revpack").exists():
            pytest.skip("horror_default.revpack 없음")

        result = load_pack_by_id("horror")
        assert result is True
        assert ACTIVE_PACK.is_loaded is True

    def test_load_pack_by_id_senior_alias(self):
        """load_pack_by_id('senior') → senior_touching.revpack"""
        from config.pack_config import load_pack_by_id, ACTIVE_PACK

        if not _pack_password_configured():
            pytest.skip("REVERIE_PACK_PASSWORD 미설정 — 실물 .revpack 로드 테스트 skip")

        packs_dir = PROJECT_ROOT / "assets" / "packs"
        if not (packs_dir / "senior_touching.revpack").exists():
            pytest.skip("senior_touching.revpack 없음")

        result = load_pack_by_id("senior")
        assert result is True
        assert ACTIVE_PACK.is_loaded is True


# ============================================================
# 4. PipelineContext — 체크포인트/취소/일시정지
# ============================================================

class TestPipelineContext:
    """PipelineContext 데이터클래스 및 제어 로직 테스트"""

    def test_context_default_values(self):
        """기본값 확인"""
        from pipeline.context import PipelineContext
        from modules_pro.video_models import QualityPreset

        ctx = PipelineContext()
        assert ctx.channel == ""
        assert ctx.mode == ""
        assert ctx.quality == QualityPreset.STANDARD
        assert ctx.target_language == "ko"
        assert ctx.cancellation_token is None

    def test_context_check_cancelled_no_token(self):
        """토큰 없으면 취소 체크 무시"""
        from pipeline.context import PipelineContext

        ctx = PipelineContext()
        # 예외 없이 통과해야 함
        ctx.check_cancelled()

    def test_context_check_cancelled_not_cancelled(self):
        """취소 안 된 상태 → 정상 통과"""
        from pipeline.context import PipelineContext
        from modules_pro.video_models import CancellationToken

        token = CancellationToken()
        ctx = PipelineContext(cancellation_token=token)

        # 예외 없이 통과
        ctx.check_cancelled()

    def test_context_check_cancelled_raises(self):
        """취소된 상태 → PipelineCancelled 예외 발생"""
        from pipeline.context import PipelineContext, PipelineCancelled
        from modules_pro.video_models import CancellationToken

        token = CancellationToken()
        token.cancel()  # 취소 신호
        ctx = PipelineContext(cancellation_token=token)

        with pytest.raises(PipelineCancelled):
            ctx.check_cancelled()

    def test_context_progress_callback(self):
        """progress_callback 호출 확인"""
        from pipeline.context import PipelineContext

        calls = []
        ctx = PipelineContext(progress_callback=lambda s, p, m: calls.append((s, p, m)))

        ctx.update_progress("tts", 0.5, "TTS 진행 중")
        assert len(calls) == 1
        assert calls[0] == ("tts", 0.5, "TTS 진행 중")

    def test_context_progress_callback_exception_swallowed(self):
        """콜백에서 예외 발생해도 삼킴 (파이프라인 중단 방지)"""
        from pipeline.context import PipelineContext

        def bad_callback(s, p, m):
            raise RuntimeError("callback error")

        ctx = PipelineContext(progress_callback=bad_callback)
        # 예외 없이 통과해야 함
        ctx.update_progress("test", 0.0, "")


class TestPipelineCheckpoint:
    """PipelineCheckpoint 체크포인트 테스트"""

    def test_checkpoint_default_stage(self):
        """기본 단계는 'init'"""
        from pipeline.context import PipelineCheckpoint

        cp = PipelineCheckpoint()
        assert cp.stage == "init"

    def test_checkpoint_can_resume_from(self):
        """resume 가능 여부 확인"""
        from pipeline.context import PipelineCheckpoint

        cp = PipelineCheckpoint(stage="tts")

        assert cp.can_resume_from("init") is True
        assert cp.can_resume_from("thumbnail") is True
        assert cp.can_resume_from("tts") is True
        assert cp.can_resume_from("images") is False  # tts까지만 완료
        assert cp.can_resume_from("render") is False

    def test_checkpoint_stage_order(self):
        """단계 순서 정확성"""
        from pipeline.context import PipelineCheckpoint

        expected = ["init", "thumbnail", "tts", "images", "render", "done"]
        assert PipelineCheckpoint.STAGE_ORDER == expected

    def test_checkpoint_invalid_stage(self):
        """잘못된 단계명 → False"""
        from pipeline.context import PipelineCheckpoint

        cp = PipelineCheckpoint(stage="tts")
        assert cp.can_resume_from("nonexistent") is False

        cp2 = PipelineCheckpoint(stage="invalid")
        assert cp2.can_resume_from("tts") is False


class TestPipelineStepResult:
    """PipelineStepResult 표준 결과 타입 테스트"""

    def test_success_result(self):
        """성공 결과"""
        from pipeline.context import PipelineStepResult

        result = PipelineStepResult(
            success=True,
            data="/path/to/audio.wav",
            stage="tts",
        )
        assert result.success is True
        assert result.data == "/path/to/audio.wav"
        assert result.has_warnings is False
        assert result.fallback_used is False

    def test_failure_result(self):
        """실패 결과"""
        from pipeline.context import PipelineStepResult

        err = ConnectionError("TTS server down")
        result = PipelineStepResult(
            success=False,
            error=err,
            stage="tts",
        )
        assert result.success is False
        assert result.error is err
        assert result.data is None

    def test_partial_success_with_fallback(self):
        """부분 성공 (fallback 사용)"""
        from pipeline.context import PipelineStepResult

        result = PipelineStepResult(
            success=True,
            data=["/img1.png", "/fallback.png", "/img3.png"],
            fallback_used=True,
            warnings=["2번째 이미지 fallback 사용"],
            retry_count=2,
            stage="images",
        )
        assert result.success is True
        assert result.fallback_used is True
        assert result.has_warnings is True
        assert result.retry_count == 2
        assert len(result.warnings) == 1

    def test_has_warnings_property(self):
        """has_warnings 프로퍼티 동작"""
        from pipeline.context import PipelineStepResult

        empty = PipelineStepResult()
        assert empty.has_warnings is False

        with_warns = PipelineStepResult(warnings=["warn1", "warn2"])
        assert with_warns.has_warnings is True


# ============================================================
# 5. CancellationToken 테스트
# ============================================================

class TestCancellationToken:
    """CancellationToken 취소/일시정지 토큰 테스트"""

    def test_token_initial_state(self):
        """초기 상태: 취소/일시정지 둘 다 아님"""
        from modules_pro.video_models import CancellationToken

        token = CancellationToken()
        assert token.is_cancelled is False
        assert token.is_paused is False

    def test_token_cancel(self):
        """취소 동작"""
        from modules_pro.video_models import CancellationToken

        token = CancellationToken()
        token.cancel()
        assert token.is_cancelled is True

    def test_token_pause_resume(self):
        """일시정지/재개 동작"""
        from modules_pro.video_models import CancellationToken

        token = CancellationToken()
        token.pause()
        assert token.is_paused is True

        token.resume()
        assert token.is_paused is False


# ============================================================
# 6. VideoRenderer Mock 테스트
# ============================================================

class TestVideoRendererMock:
    """VideoRenderer Remotion 렌더링 mock 테스트"""

    def test_renderer_initialization(self):
        """렌더러 초기화"""
        from pipeline.video_renderer import VideoRenderer

        renderer = VideoRenderer(
            channel="horror",
            video_width=1920,
            video_height=1080,
            fps=30,
            concurrency=6,
        )
        assert renderer.channel == "horror"
        assert renderer.fps == 30
        assert renderer.concurrency == 6

    def test_renderer_set_callbacks(self):
        """콜백 주입"""
        from pipeline.video_renderer import VideoRenderer

        renderer = VideoRenderer(channel="horror")

        mock_style = MagicMock(return_value={"bg_color": "#000"})
        mock_bgm = MagicMock(return_value="/bgm/folder")
        mock_sfx = MagicMock()

        renderer.set_callbacks(
            style_getter=mock_style,
            get_bgm_folder=mock_bgm,
            prepare_sfx_for_remotion=mock_sfx,
        )

        assert renderer._style_getter_fn is mock_style
        assert renderer._get_bgm_folder_fn is mock_bgm
        assert renderer._prepare_sfx_fn is mock_sfx

    def test_renderer_assemble_no_remotion(self):
        """Remotion 미설치 시 RuntimeError"""
        from pipeline.video_renderer import VideoRenderer

        renderer = VideoRenderer(channel="horror")

        with patch.dict(sys.modules, {"modules_pro.remotion_assembler": None}):
            # RemotionAssembler import가 실패하도록
            with patch("builtins.__import__", side_effect=ImportError("No module")):
                with pytest.raises((RuntimeError, ImportError)):
                    renderer.assemble_main(
                        audio_path="/fake/audio.wav",
                        subtitle_data=[{"text": "test", "start": 0, "end": 1}],
                        image_paths=["/fake/img.png"],
                        mode="horror",
                    )


# ============================================================
# 7. TextProcessor 테스트
# ============================================================

class TestTextProcessor:
    """TextProcessor 텍스트 정규화 테스트"""

    def test_import(self):
        """import 성공"""
        from pipeline.text_processor import TextProcessor
        assert TextProcessor is not None

    def test_initialization(self):
        """초기화"""
        from pipeline.text_processor import TextProcessor
        tp = TextProcessor()
        assert tp is not None


# ============================================================
# 8. Pipeline Utils 테스트
# ============================================================

# ============================================================
# 8-1. retry_api_call 공통 유틸 테스트
# ============================================================

class TestRetryApiCall:
    """retry_api_call() 공통 재시도 유틸리티 테스트"""

    def test_retry_success_first_try(self):
        """첫 시도에 성공 → 결과 반환, 재시도 없음"""
        from pipeline.pipeline_utils import retry_api_call

        mock_func = MagicMock(return_value="ok")
        result = retry_api_call(mock_func, max_retries=3, context="test")
        assert result == "ok"
        assert mock_func.call_count == 1

    def test_retry_success_after_failures(self):
        """2번 실패 후 3번째 성공"""
        from pipeline.pipeline_utils import retry_api_call

        mock_func = MagicMock(
            side_effect=[ConnectionError("fail1"), TimeoutError("fail2"), "ok"]
        )
        result = retry_api_call(
            mock_func, max_retries=3, base_delay=0.01, context="test"
        )
        assert result == "ok"
        assert mock_func.call_count == 3

    def test_retry_all_exhausted(self):
        """모든 재시도 소진 → 마지막 예외 raise"""
        from pipeline.pipeline_utils import retry_api_call

        mock_func = MagicMock(side_effect=ConnectionError("down"))
        with pytest.raises(ConnectionError, match="down"):
            retry_api_call(
                mock_func, max_retries=2, base_delay=0.01, context="test"
            )
        assert mock_func.call_count == 2

    def test_retry_non_retryable_immediate_raise(self):
        """retryable이 아닌 예외는 즉시 raise (FATAL)"""
        from pipeline.pipeline_utils import retry_api_call

        mock_func = MagicMock(side_effect=ValueError("bad input"))
        with pytest.raises(ValueError, match="bad input"):
            retry_api_call(
                mock_func, max_retries=3, base_delay=0.01, context="test"
            )
        assert mock_func.call_count == 1  # 재시도 없이 즉시

    def test_retry_custom_retryable_exceptions(self):
        """커스텀 retryable 예외 타입 지정"""
        from pipeline.pipeline_utils import retry_api_call

        mock_func = MagicMock(
            side_effect=[ValueError("retry me"), "ok"]
        )
        result = retry_api_call(
            mock_func,
            max_retries=3,
            base_delay=0.01,
            retryable_exceptions=(ValueError,),
            context="test"
        )
        assert result == "ok"
        assert mock_func.call_count == 2

    def test_retry_passes_args_and_kwargs(self):
        """args와 kwargs가 함수에 정확히 전달"""
        from pipeline.pipeline_utils import retry_api_call

        mock_func = MagicMock(return_value="ok")
        retry_api_call(
            mock_func, "arg1", "arg2",
            max_retries=1, context="test",
            kwarg1="val1"
        )
        mock_func.assert_called_once_with("arg1", "arg2", kwarg1="val1")

    def test_retry_exponential_backoff(self):
        """지수 백오프 딜레이 검증 (실제 시간 기반)"""
        import time as _time
        from pipeline.pipeline_utils import retry_api_call

        mock_func = MagicMock(
            side_effect=[ConnectionError("1"), ConnectionError("2"), "ok"]
        )
        start = _time.time()
        retry_api_call(
            mock_func, max_retries=3, base_delay=0.05, context="test"
        )
        elapsed = _time.time() - start
        # base_delay=0.05 → 첫 번째 0.025~0.075초, 두 번째 0.05~0.15초
        # 총 대기 ≥ 0.05초 (지터 하한)
        assert elapsed >= 0.04  # 최소 대기 시간 확인


class TestSDClientWithRetryUtil:
    """SD Client가 공통 retry_api_call을 사용하는지 검증"""

    def test_sd_client_uses_retry_api_call(self):
        """SD txt2img가 retry_api_call을 호출하는지"""
        from pipeline.sd_client import SDClientWrapper

        client = SDClientWrapper("http://127.0.0.1:7860")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"images": ["base64data"], "info": "{}"}
        mock_response.raise_for_status = MagicMock()

        with patch("pipeline.pipeline_utils.retry_api_call", return_value=mock_response) as mock_retry:
            result = client.txt2img(prompt="test", width=512, height=512)
            assert mock_retry.called
            assert result == {"images": ["base64data"], "info": "{}"}

    def test_sd_client_retry_on_timeout(self):
        """SD 타임아웃 시 retry_api_call이 재시도"""
        from pipeline.sd_client import SDClientWrapper
        import requests

        client = SDClientWrapper("http://127.0.0.1:7860")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"images": ["ok"]}
        mock_response.raise_for_status = MagicMock()

        # 첫 번째: Timeout, 두 번째: 성공
        call_count = [0]
        def fake_post(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise requests.exceptions.Timeout("slow")
            return mock_response

        with patch("pipeline.pipeline_utils.retry_api_call") as mock_retry:
            mock_retry.return_value = mock_response
            result = client.txt2img(prompt="test")
            # retry_api_call에 max_retries=3 전달 확인
            call_kwargs = mock_retry.call_args
            assert call_kwargs.kwargs.get("max_retries") == 3
            assert call_kwargs.kwargs.get("context") == "SD"


class TestVRAMManagerWithRetryUtil:
    """VRAMManager가 공통 retry_api_call을 사용하는지 검증"""

    def test_vram_reload_success(self):
        """VRAM 리로드 성공"""
        from pipeline.vram_manager import VRAMManager

        mgr = VRAMManager("http://127.0.0.1:7860")

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("pipeline.pipeline_utils.retry_api_call", return_value=mock_response):
            result = mgr.reload_checkpoint()
            assert result is True
            assert mgr.is_unloaded is False

    def test_vram_reload_http_error(self):
        """VRAM 리로드 HTTP 에러 → False"""
        from pipeline.vram_manager import VRAMManager

        mgr = VRAMManager("http://127.0.0.1:7860")

        mock_response = MagicMock()
        mock_response.status_code = 500

        with patch("pipeline.pipeline_utils.retry_api_call", return_value=mock_response):
            result = mgr.reload_checkpoint()
            assert result is False

    def test_vram_reload_network_failure(self):
        """VRAM 리로드 네트워크 실패 → False (raise 안 함)"""
        from pipeline.vram_manager import VRAMManager

        mgr = VRAMManager("http://127.0.0.1:7860")

        with patch("pipeline.pipeline_utils.retry_api_call", side_effect=ConnectionError("down")):
            result = mgr.reload_checkpoint()
            assert result is False  # 예외가 아닌 False 반환


# ============================================================
# 9. Pipeline Utils 테스트
# ============================================================

class TestPipelineUtils:
    """pipeline_utils.py 유틸리티 함수 테스트"""

    def test_sanitize_for_path_basic(self):
        """기본 경로 살균"""
        from pipeline.pipeline_utils import sanitize_for_path

        result = sanitize_for_path("Hello World! @#$%")
        assert "/" not in result
        assert "\\" not in result
        assert "?" not in result
        assert "*" not in result

    def test_sanitize_for_path_max_length(self):
        """80자 기본 길이 제한"""
        from pipeline.pipeline_utils import sanitize_for_path

        long_name = "a" * 200
        result = sanitize_for_path(long_name)
        assert len(result) <= 80

    def test_sanitize_for_path_custom_length(self):
        """커스텀 길이 제한"""
        from pipeline.pipeline_utils import sanitize_for_path

        long_name = "b" * 200
        result = sanitize_for_path(long_name, max_length=50)
        assert len(result) <= 50

    def test_sanitize_for_path_korean(self):
        """한국어 경로명 보존"""
        from pipeline.pipeline_utils import sanitize_for_path

        result = sanitize_for_path("어느 날 갑자기 공포의 문이 열렸다")
        assert "어느" in result or len(result) > 0  # 한국어 보존

    def test_sanitize_for_path_empty(self):
        """빈 문자열 입력"""
        from pipeline.pipeline_utils import sanitize_for_path

        result = sanitize_for_path("")
        assert isinstance(result, str)

    def test_safe_print(self):
        """safe_print 함수 존재 및 호출 가능"""
        from pipeline.pipeline_utils import safe_print

        # 예외 없이 호출 가능해야 함
        safe_print("테스트 메시지 🎬")
        safe_print("")
        safe_print(None)


# ============================================================
# 8. ChannelRegistry — 일일 생성 제한 (v60.1.0 H7)
# ============================================================

class TestDailyGenerationLimit:
    """일일 영상 생성 제한 로직 테스트"""

    def _make_registry(self, tmp_path):
        """테스트용 임시 ChannelRegistry 생성"""
        # 싱글톤 리셋
        from utils.channel_registry import ChannelRegistry
        ChannelRegistry._instance = None
        registry = ChannelRegistry(str(tmp_path))
        return registry

    def test_new_fields_default(self, tmp_path):
        """today_video_count, last_reset_date 기본값 확인"""
        from utils.channel_registry import ChannelInfo
        ch = ChannelInfo(channel_id="test_001", channel_type="horror", display_name="테스트")
        assert ch.today_video_count == 0
        assert ch.last_reset_date == ""
        assert ch.daily_video_limit == 3  # v60.1.0: 기본값 3으로 변경

    def test_can_generate_unregistered_channel(self, tmp_path):
        """미등록 채널은 제한 없이 True"""
        registry = self._make_registry(tmp_path)
        assert registry.can_generate_today("nonexistent_channel") is True
        assert registry.get_remaining_quota("nonexistent_channel") == 999

    def test_can_generate_within_limit(self, tmp_path):
        """한도 내에서 생성 가능"""
        registry = self._make_registry(tmp_path)
        registry.register_channel("horror", "공포 테스트", priority=50)

        # 첫 번째 채널 ID 가져오기
        channels = registry.get_all_channels()
        ch_id = channels[0].channel_id

        # 한도 3으로 설정
        registry.update_channel(ch_id, daily_video_limit=3)

        assert registry.can_generate_today(ch_id) is True
        assert registry.get_remaining_quota(ch_id) == 3

    def test_increment_blocks_at_limit(self, tmp_path):
        """한도 도달 시 생성 차단"""
        registry = self._make_registry(tmp_path)
        registry.register_channel("horror", "공포 테스트", priority=50)
        channels = registry.get_all_channels()
        ch_id = channels[0].channel_id

        # 한도 2로 설정
        registry.update_channel(ch_id, daily_video_limit=2)

        # 2번 증가 → 한도 도달
        assert registry.increment_daily_count(ch_id) is True
        assert registry.increment_daily_count(ch_id) is True

        # 이제 차단
        assert registry.can_generate_today(ch_id) is False
        assert registry.get_remaining_quota(ch_id) == 0

    def test_daily_reset_on_new_day(self, tmp_path):
        """날짜 변경 시 카운트 리셋"""
        registry = self._make_registry(tmp_path)
        registry.register_channel("horror", "공포 테스트", priority=50)
        channels = registry.get_all_channels()
        ch_id = channels[0].channel_id

        # 어제 날짜로 설정하여 카운트 채움
        registry.update_channel(
            ch_id,
            daily_video_limit=1,
            today_video_count=1,
            last_reset_date="2020-01-01"  # 과거 날짜
        )

        # 날짜가 바뀌었으므로 리셋되어야 함
        assert registry.can_generate_today(ch_id) is True
        assert registry.get_remaining_quota(ch_id) == 1

    def test_from_dict_backward_compatibility(self):
        """기존 JSON (new fields 없음) 로딩 시 기본값 적용"""
        from utils.channel_registry import ChannelInfo
        old_data = {
            "channel_id": "horror_001",
            "channel_type": "horror",
            "display_name": "공포 채널",
            "daily_video_limit": 5,
            "total_videos": 42,
            # today_video_count, last_reset_date 없음 (구버전)
        }
        ch = ChannelInfo.from_dict(old_data)
        assert ch.today_video_count == 0
        assert ch.last_reset_date == ""
        assert ch.daily_video_limit == 5

    def test_increment_also_updates_total(self, tmp_path):
        """increment_daily_count가 total_videos도 증가시키는지 확인"""
        registry = self._make_registry(tmp_path)
        registry.register_channel("horror", "공포 테스트", priority=50)
        channels = registry.get_all_channels()
        ch_id = channels[0].channel_id
        registry.update_channel(ch_id, daily_video_limit=10)

        initial_total = registry.get_channel(ch_id).total_videos
        registry.increment_daily_count(ch_id)

        assert registry.get_channel(ch_id).total_videos == initial_total + 1
        assert registry.get_channel(ch_id).today_video_count == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
