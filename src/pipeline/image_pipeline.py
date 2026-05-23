# src/pipeline/image_pipeline.py
"""
v60.1.0 Phase 9: 이미지 생성 파이프라인 모듈

media_factory.py에서 추출한 이미지 생성 관련 7개 주요 메서드.
3개 카테고리:
  1. SD Infrastructure (2): boot_sd_webui, set_sd_model
  2. Image Generation (3): generate_images_v59, generate_images_v33, generate_images
  3. Helpers (2): pre_analyze_scenes, get_safe_fallback_image

원본 위치: media_factory.py L676-889, L1686-1757, L1761-2505,
          L2510-2827, L3143-3275
"""
import base64
import hashlib
import json
import os
import random
import re
import sys
import subprocess
import time
import threading
import logging
from typing import Dict, Any, List, Optional, Callable, Tuple

import requests

logger = logging.getLogger(__name__)

from utils.videotoon_contract import actor_id_from_slot
from utils.secret_redaction import redact_sensitive_text
from config.settings import config
try:
    from config.pack_config import ACTIVE_PACK, PACK_CONFIG_AVAILABLE
except ImportError:
    ACTIVE_PACK = None
    PACK_CONFIG_AVAILABLE = False

# v60.1.0: _sanitize_for_path를 pipeline_utils 정식 버전으로 통합
from pipeline.pipeline_utils import sanitize_for_path as _sanitize_for_path


def _minimal_png_bytes() -> bytes:
    """Return a 1x1 black PNG for environments without Pillow."""
    import struct
    import zlib

    sig = b'\x89PNG\r\n\x1a\n'
    ihdr_data = struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0)
    ihdr_crc = struct.pack('>I', zlib.crc32(b'IHDR' + ihdr_data) & 0xffffffff)
    ihdr = struct.pack('>I', 13) + b'IHDR' + ihdr_data + ihdr_crc
    raw = zlib.compress(b'\x00\x00\x00\x00')
    idat_crc = struct.pack('>I', zlib.crc32(b'IDAT' + raw) & 0xffffffff)
    idat = struct.pack('>I', len(raw)) + b'IDAT' + raw + idat_crc
    iend_crc = struct.pack('>I', zlib.crc32(b'IEND') & 0xffffffff)
    iend = struct.pack('>I', 0) + b'IEND' + iend_crc
    return sig + ihdr + idat + iend


class ImagePipeline:
    """이미지 생성 파이프라인

    SD WebUI와 통신하여 이미지를 생성하고,
    SceneAnalyzer/PromptComposer/QualityControl/CharacterLibrary와 연동합니다.

    외부 의존성은 생성자 파라미터 또는 콜백으로 주입받습니다.
    """

    # v51: 시니어 초 네거티브 (인물 제외 강화)
    SENIOR_ULTRA_NEGATIVE = (
        "(person:1.6), (people:1.6), (human:1.4), (face:1.5), (portrait:1.4), "
        "(man:1.4), (woman:1.4), (boy:1.3), (girl:1.3), (child:1.3), "
        "(hand:1.3), (finger:1.3), (body:1.2), (head:1.3), (eye:1.3), "
        "(hair:1.2), (skin:1.2)"
    )

    def __init__(
        self,
        channel: str,
        mode: str,
        sd_url: str,
        sd_webui_root: str,
        data_dir: str,
        assets_dir: str,
        video_width: int = 1920,
        video_height: int = 1080,
        styles: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.channel = channel
        self.mode = mode
        self.sd_url = sd_url
        self.sd_webui_root = sd_webui_root
        self.data_dir = data_dir
        self.assets_dir = assets_dir
        self.video_width = video_width
        self.video_height = video_height
        self.styles = styles or {}

        # 외부 콜백 슬롯
        self._apply_consistency_fn: Optional[Callable] = None
        self._cancellation_token = None
        self._quality = None  # QualityPreset

    def set_callbacks(
        self,
        apply_consistency: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
        cancellation_token: Optional[Any] = None,
        quality: Optional[Any] = None,
    ) -> None:
        """
        외부 의존 콜백 주입

        orchestrator가 파이프라인 초기화 시 이 메서드로 의존성을 등록합니다.

        Args:
            apply_consistency: IP-Adapter payload 일관성 적용 콜백 (Dict→Dict)
            cancellation_token: CancellationToken 인스턴스 (취소/일시정지 제어)
            quality: QualityPreset 인스턴스 (이미지 품질/스텝 수 결정)
        """
        if apply_consistency is not None:
            if not callable(apply_consistency):
                logger.warning(f"[ImagePipeline] apply_consistency is not callable: {type(apply_consistency)}")
            else:
                self._apply_consistency_fn = apply_consistency
        if cancellation_token is not None:
            self._cancellation_token = cancellation_token
        if quality is not None:
            self._quality = quality

    def _apply_consistency_to_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """payload에 일관성 설정 적용"""
        if self._apply_consistency_fn:
            return self._apply_consistency_fn(payload)
        return payload

    @staticmethod
    def _resolve_v59_pack_context(mode: str, channel: str) -> Tuple[str, str]:
        pack_id = ACTIVE_PACK.pack_name if (PACK_CONFIG_AVAILABLE and ACTIVE_PACK.is_loaded) else "default"
        if PACK_CONFIG_AVAILABLE and ACTIVE_PACK.is_loaded:
            pack_genre = getattr(ACTIVE_PACK, "genre", "") or ""
            genre = pack_genre.strip() or channel or mode or "horror"
        else:
            genre = channel or mode or "horror"
        return pack_id, genre

    @staticmethod
    def _stable_seed(*parts: Any) -> int:
        joined = "|".join(str(part).strip().lower() for part in parts if part is not None and str(part).strip())
        digest = hashlib.sha256(joined.encode("utf-8")).digest()
        return (int.from_bytes(digest[:8], "big") % 2147483646) + 1

    @classmethod
    def _variant_seed(cls, base_seed: int, attempt: int) -> int:
        return cls._stable_seed(base_seed, "retry", attempt)

    def _resolve_scene_seed(
        self,
        character_id: str = "",
        speaker: str = "",
        location: str = "",
        prompt: str = "",
        mode_tag: str = "image",
    ) -> int:
        narrator_ids = {"narrator", "narration", "나레이션", "나레이터"}
        if character_id and character_id.lower() not in narrator_ids:
            return self._stable_seed(mode_tag, "character", self.channel, self.mode, character_id)
        if location:
            return self._stable_seed(mode_tag, "location", self.channel, self.mode, location)
        if speaker:
            return self._stable_seed(mode_tag, "speaker", self.channel, self.mode, speaker)
        return self._stable_seed(mode_tag, "prompt", self.channel, self.mode, prompt[:160])

    def _apply_cached_scene_seed(
        self,
        payload: Dict[str, Any],
        seed_cache: Dict[str, int],
        character_id: str = "",
        speaker: str = "",
        location: str = "",
        mode_tag: str = "image",
    ) -> Dict[str, Any]:
        """장면 seed를 한 번만 계산하고 speaker alias에도 같은 값을 연결한다."""
        payload = dict(payload)
        speaker_key = speaker.strip().lower() if speaker else ""
        seed_key = character_id or speaker_key or location
        if not seed_key:
            return payload

        seed = seed_cache.get(seed_key)
        if seed is None:
            seed = self._resolve_scene_seed(
                character_id=character_id,
                speaker=speaker_key,
                location=location,
                prompt=payload.get("prompt", ""),
                mode_tag=mode_tag,
            )
            seed_cache[seed_key] = seed

        payload["seed"] = seed

        narrator_ids = {"narrator", "narration", "나레이션", "나레이터"}
        if character_id and speaker_key and speaker_key not in narrator_ids:
            seed_cache.setdefault(speaker_key, seed)

        return payload

    def _apply_vram_safety(self, payload: Dict[str, Any], purpose: str = "image") -> Dict[str, Any]:
        """8GB급 환경에서 SD 요청을 안전 범위로 보정한다."""
        payload = dict(payload)

        width = int(payload.get("width", 0) or 0)
        height = int(payload.get("height", 0) or 0)
        if width > 0 and height > 0:
            safe_width, safe_height = config.clamp_sd_dimensions(width, height, purpose=purpose)
            payload["width"] = safe_width
            payload["height"] = safe_height

        steps = int(payload.get("steps", 0) or 0)
        if steps > 0:
            payload["steps"] = config.clamp_sd_steps(steps, purpose=purpose)

        if config.is_low_vram():
            payload["batch_size"] = 1
            payload["n_iter"] = 1
            if payload.get("enable_hr"):
                payload["enable_hr"] = False

        return payload

    # ================================================================
    # 감정 추출 헬퍼 (v50)
    # ================================================================
    @staticmethod
    def extract_emotion_from_prompt(prompt: str) -> Optional[str]:
        """프롬프트에서 감정 키워드 추출"""
        prompt_lower = prompt.lower()

        emotion_keywords = {
            "sad": ["sad", "crying", "tears", "sobbing", "weeping", "depressed",
                     "melancholy", "gloomy", "슬픈", "우울", "울"],
            "angry": ["angry", "rage", "furious", "shouting", "화난", "분노"],
            "scared": ["scared", "terrified", "frightened", "fear", "무서운", "공포", "두려"],
            "happy": ["happy", "smiling", "joyful", "cheerful", "행복", "미소", "기쁜"],
            "excited": ["surprised", "shocked", "startled", "excited", "놀란", "충격", "흥분"],
            "whisper": ["whisper", "quiet", "soft", "속삭", "조용"],
            "calm": ["calm", "neutral", "expressionless", "peaceful", "평온", "무표정", "차분"],
            "worried": ["worried", "anxious", "nervous", "uneasy", "걱정", "불안", "초조"],
            "desperate": ["desperate", "pleading", "begging", "hopeless", "절박", "간절", "애원"],
        }

        for emotion, keywords in emotion_keywords.items():
            for kw in keywords:
                if kw in prompt_lower:
                    return emotion
        return None

    # ================================================================
    # 1. SD Infrastructure
    # ================================================================
    def boot_sd_webui(self) -> bool:
        """SD WebUI 자동 시동 - Python 직접 실행 방식"""

        logger.info("[SD] SD WebUI 자동 시동 시도")

        sd_root = self.sd_webui_root

        # 플랫폼별 Python 경로
        is_windows = sys.platform == 'win32'
        if is_windows:
            sd_python = os.path.join(sd_root, "venv", "Scripts", "python.exe")
        else:
            sd_python = os.path.join(sd_root, "venv", "bin", "python")
        sd_launch = os.path.join(sd_root, "launch.py")

        if not os.path.exists(sd_python):
            logger.error(f"[SD] Python 없음: {sd_python}")
            return False

        if not os.path.exists(sd_launch):
            logger.error(f"[SD] launch.py 없음: {sd_launch}")
            return False

        try:
            popen_kwargs = {"cwd": sd_root}
            if is_windows:
                popen_kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE

            subprocess.Popen(
                [sd_python, sd_launch, "--api", "--xformers"],
                **popen_kwargs
            )
            logger.info("[SD] SD WebUI 시동 명령 전송")

            # 준비 대기 (최대 180초)
            for i in range(90):  # 2초 * 90 = 180초
                time.sleep(2)
                try:
                    res = requests.get(f"{self.sd_url}/sdapi/v1/sd-models", timeout=5)
                    if res.status_code == 200:
                        logger.info("[SD] SD WebUI 시동 완료")
                        return True
                except (requests.RequestException, ConnectionError, OSError):
                    if i % 15 == 0 and i > 0:
                        pass  # 대기 로그

            logger.error("[SD] SD WebUI 시동 타임아웃")
            return False

        except (OSError, subprocess.SubprocessError) as e:
            logger.error(f"[SD] SD WebUI 시동 실패: {e}")
            return False

    def set_sd_model(self) -> None:
        """
        SD 모델 + VAE 설정 (지수 백오프 적용)

        팩 설정(ACTIVE_PACK.visual_storytelling.sd_model)에서 checkpoint/VAE를
        읽어 SD WebUI에 적용합니다. 팩 미설정 시 채널 기본 모델 사용.

        v59.2.4: 팩 설정에서 checkpoint/VAE 읽기, VAE 자동 적용
        """

        try:
            from config.pack_config import ACTIVE_PACK, PACK_CONFIG_AVAILABLE
        except ImportError:
            PACK_CONFIG_AVAILABLE = False

        logger.info(f"[SD] 채널별 최적화 모델 로드 중... (채널: {self.channel})")

        # v59.3.3: 팩에서 모델/VAE 읽기 (dict/object 양쪽 지원)
        target_model = None
        target_vae = None
        if PACK_CONFIG_AVAILABLE and ACTIVE_PACK.is_loaded:
            vs_config = getattr(ACTIVE_PACK, 'visual_storytelling', None)
            if vs_config:
                if isinstance(vs_config, dict):
                    sd_model = vs_config.get('sd_model', None)
                else:
                    sd_model = getattr(vs_config, 'sd_model', None)
                if sd_model:
                    if isinstance(sd_model, dict):
                        pack_ckpt = sd_model.get('checkpoint', None)
                        pack_vae = sd_model.get('vae', None)
                    else:
                        pack_ckpt = getattr(sd_model, 'checkpoint', None)
                        pack_vae = getattr(sd_model, 'vae', None)
                    if pack_ckpt:
                        if not pack_ckpt.endswith('.safetensors') and not pack_ckpt.endswith('.ckpt'):
                            pack_ckpt += '.safetensors'
                        target_model = pack_ckpt
                        logger.info(f"[SD] 팩 설정 모델: {target_model}")
                    if pack_vae:
                        if not pack_vae.endswith('.safetensors') and not pack_vae.endswith('.pt'):
                            pack_vae += '.safetensors'
                        target_vae = pack_vae
                        logger.info(f"[SD] 팩 설정 VAE: {target_vae}")

        # 팩 설정 없으면 기본값 (v61: MeinaMix V12 통일)
        if not target_model:
            target_model = "meinamix_v12Final.safetensors"

        # 현재 모델 확인 (재시도 포함)
        current_model = None
        current_vae = None
        for attempt in range(3):
            try:
                opt_res = requests.get(f"{self.sd_url}/sdapi/v1/options", timeout=5).json()
                current_model = opt_res.get("sd_model_checkpoint")
                current_vae = opt_res.get("sd_vae")
                break
            except (requests.RequestException, ConnectionError, json.JSONDecodeError, ValueError) as e:
                delay = 1.0 * (2 ** attempt) * (0.5 + random.random())
                logger.warning(f"[SD] 옵션 조회 실패. 재시도 {attempt+1}/3, {delay:.1f}초 대기. 에러: {e}")
                if attempt < 2:
                    time.sleep(delay)

        if current_model is None:
            logger.warning("[SD] SD WebUI 연결 실패. 자동 시동 시도")

            if self.boot_sd_webui():
                for attempt in range(3):
                    try:
                        opt_res = requests.get(f"{self.sd_url}/sdapi/v1/options", timeout=5).json()
                        current_model = opt_res.get("sd_model_checkpoint")
                        current_vae = opt_res.get("sd_vae")
                        if current_model:
                            break
                    except (requests.RequestException, ConnectionError, json.JSONDecodeError):
                        time.sleep(3)

            if current_model is None:
                logger.error("[SD] SD WebUI 시동 실패")
                return

        # 모델 교체
        if target_model not in str(current_model):
            logger.info(f"[SD] 모델 교체 필요: [{current_model}] -> [{target_model}]")

            for attempt in range(3):
                try:
                    res = requests.post(
                        f"{self.sd_url}/sdapi/v1/options",
                        json={"sd_model_checkpoint": target_model},
                        timeout=180,
                    )
                    if res.status_code != 200:
                        logger.warning(f"[SD] 모델 스위칭 응답: HTTP {res.status_code}")
                        time.sleep(15)
                    else:
                        time.sleep(10)

                    # 실제 모델 로드 확인
                    verify_res = requests.get(f"{self.sd_url}/sdapi/v1/options", timeout=10).json()
                    loaded_model = verify_res.get("sd_model_checkpoint", "")
                    if target_model in str(loaded_model):
                        logger.info(f"[SD] 모델 스위칭 확인 완료: {loaded_model}")
                        break
                    else:
                        logger.warning(f"[SD] 모델 미일치: 요청={target_model}, 실제={loaded_model}. 추가 대기...")
                        time.sleep(15)
                        verify_res2 = requests.get(f"{self.sd_url}/sdapi/v1/options", timeout=10).json()
                        loaded_model2 = verify_res2.get("sd_model_checkpoint", "")
                        if target_model in str(loaded_model2):
                            logger.info(f"[SD] 모델 스위칭 확인 완료 (지연): {loaded_model2}")
                            break

                except (requests.RequestException, ConnectionError, json.JSONDecodeError, ValueError) as e:
                    delay = 2.0 * (2 ** attempt) * (0.5 + random.random())
                    logger.warning(f"[SD] 모델 스위칭 실패. 재시도 {attempt+1}/3, {delay:.1f}초 대기. 에러: {e}")
                    if attempt < 2:
                        time.sleep(delay)
            else:
                logger.error(f"[SD] 모델 스위칭 최종 실패: {target_model}")
                return
        else:
            logger.info(f"[SD] 이미 최적 모델 장착됨: {current_model}")

        # v59.2.4: VAE 적용
        if target_vae and target_vae not in str(current_vae or ""):
            logger.info(f"[SD] VAE 교체: [{current_vae}] -> [{target_vae}]")
            try:
                requests.post(
                    f"{self.sd_url}/sdapi/v1/options",
                    json={"sd_vae": target_vae},
                    timeout=30,
                )
                logger.info(f"[SD] VAE 적용 완료: {target_vae}")
            except (requests.RequestException, ConnectionError) as e:
                logger.warning(f"[SD] VAE 적용 실패 (계속 진행): {e}")
        elif target_vae:
            logger.info(f"[SD] 이미 올바른 VAE 장착: {current_vae}")

    # ================================================================
    # 2. Helpers
    # ================================================================
    def pre_analyze_scenes(
        self,
        script_list: List[Dict],
        gemini_model,
        progress_callback: Optional[Callable[[str, int], None]] = None
    ) -> Optional[Dict]:
        """
        v59.8.0: TTS 완료 후 전체 씬 분석을 배치로 실행
        Returns: {index: SceneAnalysisResult} 캐시 dict, 또는 실패 시 None
        """
        try:
            from config.pack_config import ACTIVE_PACK, PACK_CONFIG_AVAILABLE
        except ImportError:
            PACK_CONFIG_AVAILABLE = False

        if not gemini_model:
            logger.info("[v59.8] Gemini 미설정 → 사전 분석 스킵")
            return None

        try:
            from modules_pro.scene_analyzer import SceneAnalyzer

            char_defs = {}
            art_style_cfg = None
            if PACK_CONFIG_AVAILABLE and ACTIVE_PACK.is_loaded:
                vs_config = getattr(ACTIVE_PACK, 'visual_storytelling', None)
                if vs_config:
                    if isinstance(vs_config, dict):
                        char_defs = vs_config.get('characters', {})
                    else:
                        char_defs = getattr(vs_config, 'characters', {})
                art_style_cfg = getattr(ACTIVE_PACK, 'scene_analyzer', None)

            scene_analyzer = SceneAnalyzer(
                gemini_client=gemini_model,
                character_definitions=char_defs,
                art_style_config=art_style_cfg
            )

            dialogues = []
            for item in script_list:
                dialogues.append({
                    "speaker": item.get("speaker", item.get("role", "나레이터")),
                    "text": item.get("text", item.get("dialogue", "")),
                    "location": item.get("location", ""),
                    "location_detail": item.get("location_detail", ""),
                    "time": item.get("time", item.get("time_of_day", "")),
                    "weather": item.get("weather", ""),
                    "atmosphere": item.get("atmosphere", item.get("mood", "")),
                    "image_prompt": item.get("image_prompt", ""),
                })

            total = len(dialogues)
            logger.info(f"[v59.8] 씬 사전 분석 시작: {total}개 대사...")
            if progress_callback:
                progress_callback(f"[v59.8] 씬 사전 분석 중 ({total}개)...", 40)

            _start = time.time()

            results = scene_analyzer.analyze_scene_batch(dialogues, parallel=True)

            _elapsed = time.time() - _start
            logger.info(f"[v59.8] 사전 분석 완료: {len(results)}개 씬 ({_elapsed:.1f}s)")

            cache = {i: result for i, result in enumerate(results)}
            return cache

        except (ImportError, RuntimeError, ValueError, AttributeError) as e:
            logger.warning(f"[v59.8] 사전 분석 실패 (폴백: per-image 분석): {redact_sensitive_text(e)}")
            return None

    def _create_black_placeholder(self, output_path: str, width: int = 0, height: int = 0) -> str:
        """v61.1: 검정 플레이스홀더 PNG 생성 — SD 실패 시 위치 보존용

        최소한의 검정 이미지를 생성하여 이미지 인덱스 위치를 보존합니다.
        PIL이 없으면 1x1 검정 PNG 바이트를 직접 씁니다.
        """
        w = width or self.video_width or 768
        h = height or self.video_height or 432
        try:
            from PIL import Image
            img = Image.new("RGB", (w, h), (0, 0, 0))
            img.save(output_path, "PNG")
        except ImportError:
            # PIL 없이 최소 PNG 생성 (1×1 검정)
            with open(output_path, 'wb') as f:
                f.write(_minimal_png_bytes())
        logger.warning(f"[v61.1] 검정 플레이스홀더 생성: {output_path}")
        return output_path

    def get_safe_fallback_image(self, output_path: str, mode: str) -> Optional[str]:
        """v59: 안전 폴백 이미지 생성"""

        try:
            from config.pack_config import ACTIVE_PACK, PACK_CONFIG_AVAILABLE, get_prompt
        except ImportError:
            PACK_CONFIG_AVAILABLE = False

        try:
            if PACK_CONFIG_AVAILABLE and ACTIVE_PACK.is_loaded:
                safe_prompt = get_prompt("safe_fallback", mode)
            else:
                safe_prompt = "empty room, dim light, no people, cinematic"

            if not safe_prompt:
                safe_prompt = "empty abandoned hallway, flickering light, fog, no people"

            # v61.1 (#27): 팩 SDModelConfig 해상도 우선 사용 (1920×1080 → 768×432)
            # NOTE: get_sd_settings()는 PackSD 반환 (width/height 없음)
            #       SDModelConfig는 ACTIVE_PACK.visual_storytelling.sd_model에 있음
            fb_width = self.video_width
            fb_height = self.video_height
            if PACK_CONFIG_AVAILABLE and ACTIVE_PACK.is_loaded:
                try:
                    vs = getattr(ACTIVE_PACK, 'visual_storytelling', None)
                    _sd_model = None
                    if isinstance(vs, dict):
                        _sd_model = vs.get('sd_model', None)
                    elif vs:
                        _sd_model = getattr(vs, 'sd_model', None)
                    if _sd_model:
                        if isinstance(_sd_model, dict):
                            _w = _sd_model.get('width', 0)
                            _h = _sd_model.get('height', 0)
                        else:
                            _w = getattr(_sd_model, 'width', 0)
                            _h = getattr(_sd_model, 'height', 0)
                        if _w and _h:
                            fb_width = _w
                            fb_height = _h
                except (AttributeError, TypeError, KeyError) as e:
                    logger.debug(f"[v59] safe fallback 해상도 로드 실패, 기본값 사용: {e}")

            payload = {
                "prompt": safe_prompt,
                "negative_prompt": "person, people, face, nsfw",
                "steps": 15,
                "width": fb_width,
                "height": fb_height,
                "sampler_name": "DPM++ 2M Karras",
                "cfg_scale": 6.0,
            }

            resp = requests.post(
                f"{self.sd_url}/sdapi/v1/txt2img",
                json=payload,
                timeout=60
            )

            if resp.status_code == 200:
                data = resp.json()
                if data.get("images"):
                    img_data = base64.b64decode(data["images"][0])
                    with open(output_path, "wb") as f:
                        f.write(img_data)
                    logger.info(f"[v59] 안전 폴백 이미지 생성: {output_path}")
                    return output_path

            # SD 폴백도 실패 시 검정 플레이스홀더 생성 (v61.1: 위치 보존)
            return self._create_black_placeholder(output_path)

        except (requests.RequestException, ConnectionError, OSError, ValueError) as e:
            logger.error(f"[v59] 안전 폴백 실패: {redact_sensitive_text(e)}")
            # v61.1: 최종 폴백 — 검정 플레이스홀더로 위치 보존
            try:
                return self._create_black_placeholder(output_path)
            except OSError:
                return None

    # ================================================================
    # 3. Image Generation — v59 Visual Storytelling
    # ================================================================
    def generate_images_v59(
        self,
        script_list: List[Dict],
        project_name: str,
        mode: str,
        progress_callback: Optional[Callable[[str, int], None]] = None,
        scene_analysis_cache: Optional[Dict] = None,
        checkpoint_callback: Optional[Callable[[int, str, int, int], None]] = None,
    ) -> List[str]:
        """
        v59: Visual Storytelling 파이프라인으로 이미지 생성

        대본의 각 라인에 대해 SceneAnalyzer→PromptComposer→SD WebUI→Gemini QC
        파이프라인을 실행하여 이미지를 생성합니다.

        Args:
            script_list: 대본 라인 리스트 [{speaker, text, image_prompt, emotion}, ...]
            project_name: 프로젝트 이름 (이미지 저장 폴더명)
            mode: 채널 모드 (touching, makjang, horror)
            progress_callback: 진행상황 콜백 (message, percentage)
            scene_analysis_cache: 사전 분석된 씬 캐시 (pre_analyze_scenes 결과)

        Returns:
            생성된 이미지 파일 경로 리스트

        Pipeline:
        - SceneAnalyzer: 장면 분석 (액션/감정/장소)
        - PromptComposer: 최적화된 SD 프롬프트 생성
        - CharacterLibraryManager: 캐릭터 일관성 유지
        - QualityControl: Gemini 비동기 품질 검증
        - SDModelRecommender: 씬별 최적 모델 추천
        """
        import concurrent.futures

        try:
            from config.pack_config import ACTIVE_PACK, PACK_CONFIG_AVAILABLE, get_prompt, get_sd_settings
        except ImportError:
            PACK_CONFIG_AVAILABLE = False

        try:
            from modules_pro.visual_director import visual_director
        except ImportError:
            visual_director = None

        try:
            from pipeline.sd_client import create_sd_client as _create_sd_client_wrapper
        except ImportError:
            _create_sd_client_wrapper = None

        try:
            # v61.1-fix: 모듈 임포트 → 인스턴스 임포트 (Gemini scene analysis 활성화)
            from config.settings_v2 import config
        except ImportError:
            config = None

        logger.info(f"[v59] Visual Storytelling 이미지 생성 시작: {len(script_list)}개 씬")

        # 필수 모델 체크
        pack_id, genre = self._resolve_v59_pack_context(mode=mode, channel=self.channel)

        pack_checkpoint = None
        pack_vae = None
        if PACK_CONFIG_AVAILABLE and ACTIVE_PACK.is_loaded:
            vs_config = getattr(ACTIVE_PACK, 'visual_storytelling', None)
            if vs_config:
                if isinstance(vs_config, dict):
                    sd_model = vs_config.get('sd_model', None)
                else:
                    sd_model = getattr(vs_config, 'sd_model', None)
                if sd_model:
                    if isinstance(sd_model, dict):
                        pack_checkpoint = sd_model.get('checkpoint', None)
                        pack_vae = sd_model.get('vae', None)
                    else:
                        pack_checkpoint = getattr(sd_model, 'checkpoint', None)
                        pack_vae = getattr(sd_model, 'vae', None)

        # SDModelRecommender 체크
        try:
            from modules_pro.sd_model_recommender import SDModelRecommender
            recommender = SDModelRecommender()

            if pack_checkpoint:
                check_result = recommender.check_required_models_for_pack(
                    pack_checkpoint=pack_checkpoint,
                    pack_vae=pack_vae,
                    sd_api_url=self.sd_url
                )
                if not check_result['all_installed']:
                    logger.warning(f"[v59] 필수 모델 미설치: {check_result['missing']}")
                else:
                    logger.info(f"[v59] [OK] 필수 모델 확인 완료: {pack_checkpoint}")
        except (ImportError, requests.RequestException, ConnectionError, RuntimeError) as e:
            logger.warning(f"[v59] 모델 체크 실패 (무시하고 진행): {e}")

        try:
            self.set_sd_model()
        except (requests.RequestException, ConnectionError, OSError, RuntimeError) as e:
            logger.warning(f"[v59] SD model bootstrap failed (continuing): {e}")

        # 저장 디렉토리
        safe_project_name = _sanitize_for_path(project_name)
        save_dir = os.path.join(self.data_dir, "temp_images", safe_project_name)
        os.makedirs(save_dir, exist_ok=True)

        try:
            # Gemini 클라이언트 생성
            gemini_model = None
            try:
                from utils.gemini_compat import configure_gemini, get_gemini_model, GEMINI_AVAILABLE
                if GEMINI_AVAILABLE and config and config.GEMINI_API_KEY:
                    configure_gemini(config.GEMINI_API_KEY)
                    gemini_model = get_gemini_model("auto")
                    if gemini_model:
                        _model_name = getattr(gemini_model, 'model_name', 'unknown')
                        logger.info(f"[v59] Gemini AI 분석 활성화됨 ({_model_name})")
            except (ImportError, ValueError, RuntimeError, OSError) as e:
                logger.warning(f"[v59] Gemini 초기화 실패: {e}")

            # SD 클라이언트 래퍼 생성
            sd_client_wrapper = None
            if _create_sd_client_wrapper:
                sd_client_wrapper = _create_sd_client_wrapper(self.sd_url)

            if visual_director:
                components = visual_director.init_v59_pipeline(
                    pack_id=pack_id,
                    genre=genre,
                    sd_api=sd_client_wrapper,
                    gemini_client=gemini_model
                )
            else:
                components = {}
                logger.warning("[v59] visual_director 미사용, 빈 컴포넌트")

        except (ImportError, RuntimeError, ValueError, AttributeError) as e:
            logger.error(f"[v59] 파이프라인 초기화 실패: {e}")
            # 폴백: v33 방식
            prompts = [item.get('image_prompt', item.get('text', '')) for item in script_list]
            return self.generate_images_v33(prompts, project_name, mode, progress_callback)

        # v59 설정 로드
        vs_config = None
        if PACK_CONFIG_AVAILABLE and ACTIVE_PACK.is_loaded:
            vs_config = getattr(ACTIVE_PACK, 'visual_storytelling', None)

        # 타겟 이미지 수 결정
        target_images = len(script_list)
        if vs_config:
            if isinstance(vs_config, dict):
                img_config = vs_config.get('image_generation', {})
                if isinstance(img_config, dict):
                    configured_target = img_config.get('target_images')
                    if configured_target:
                        target_images = configured_target
                    else:
                        min_images = img_config.get('min_images', len(script_list))
                        target_images = max(min_images, len(script_list))
            else:
                img_config = getattr(vs_config, 'image_generation', None)
                if img_config:
                    if isinstance(img_config, dict):
                        configured_target = img_config.get('target_images')
                    else:
                        configured_target = getattr(img_config, 'target_images', None)
                    if configured_target:
                        target_images = configured_target
                    else:
                        if isinstance(img_config, dict):
                            min_images = img_config.get('min_images', len(script_list))
                        else:
                            min_images = getattr(img_config, 'min_images', len(script_list))
                        target_images = max(min_images, len(script_list))

        logger.info(f"[v59] 타겟 이미지 수: {target_images}장")

        # 컴포넌트 추출
        scene_analyzer = components.get('scene_analyzer')
        prompt_composer = components.get('prompt_composer')
        quality_control = components.get('quality_control')
        char_library = components.get('char_library')
        storytelling_director = components.get('storytelling_director')

        # VisualStorytellingDirector 사용 가능 시
        if storytelling_director and storytelling_director.is_enabled():
            logger.info("[v59] VisualStorytellingDirector 활성화됨 - 통합 파이프라인 사용")

            dialogues = []
            for item in script_list:
                dialogues.append({
                    'speaker': item.get('speaker', item.get('role', '나레이터')),
                    'text': item.get('text', item.get('dialogue', '')),
                    'image_prompt': item.get('image_prompt', ''),
                    'location': item.get('location', ''),
                    'location_detail': item.get('location_detail', ''),
                    'time': item.get('time', item.get('time_of_day', '')),
                    'weather': item.get('weather', ''),
                    'atmosphere': item.get('atmosphere', item.get('mood', '')),
                })

            try:
                _vsd_start = time.time()
                from modules_pro.visual_storytelling_director import StorytellingResult
                # v62.18: 사전 분석 캐시를 VSD에 전달 — 이중 SceneAnalyzer 호출 방지
                result = storytelling_director.process_dialogues(
                    dialogues=dialogues,
                    job_id=_sanitize_for_path(project_name),
                    pre_analyzed_scenes=scene_analysis_cache,
                    image_callback=checkpoint_callback,
                )
                _vsd_elapsed = time.time() - _vsd_start

                generated_files = []
                for img in result.images:
                    if img.path and os.path.exists(img.path):
                        generated_files.append(img.path)

                logger.info(f"[v59] VSD 완료: {len(generated_files)}장 ({_vsd_elapsed:.1f}s)")

                if progress_callback:
                    progress_callback("[v59] 이미지 생성 완료", 75)

                return generated_files

            except (RuntimeError, requests.RequestException, ConnectionError, ValueError, OSError) as e:
                logger.error(f"[v59] VisualStorytellingDirector 실행 실패: {e}")
                # 폴백: 아래 기존 로직

        # 캐릭터 라이브러리 사전 생성
        cl_enabled = True
        if vs_config:
            if isinstance(vs_config, dict):
                cl_cfg = vs_config.get('character_library', {})
                cl_enabled = cl_cfg.get('enabled', True) if isinstance(cl_cfg, dict) else True
            else:
                cl_cfg = getattr(vs_config, 'character_library', None)
                cl_enabled = getattr(cl_cfg, 'enabled', True) if cl_cfg else True

        if not cl_enabled:
            logger.info("[v59] 캐릭터 라이브러리 비활성화 (팩 설정)")

        if char_library and vs_config and cl_enabled:
            characters_def = None
            preferred_slots = []
            preferred_expressions = []
            preferred_poses = []
            if isinstance(vs_config, dict):
                characters_def = vs_config.get('characters', {})
                cl_cfg = vs_config.get('character_library', {}) or {}
            else:
                characters_def = getattr(vs_config, 'characters', {})
                cl_cfg = getattr(vs_config, 'character_library', None)

            if isinstance(cl_cfg, dict):
                preferred_slots = list(cl_cfg.get('preferred_slots', []) or [])
                preferred_expressions = list(cl_cfg.get('preferred_expressions', []) or [])
                preferred_poses = list(cl_cfg.get('preferred_poses', []) or [])
            elif cl_cfg:
                preferred_slots = list(getattr(cl_cfg, 'preferred_slots', []) or [])
                preferred_expressions = list(getattr(cl_cfg, 'preferred_expressions', []) or [])
                preferred_poses = list(getattr(cl_cfg, 'preferred_poses', []) or [])

            if isinstance(characters_def, list):
                actual_chars = {
                    getattr(char, 'id', ''): char for char in characters_def
                    if getattr(char, 'id', '')
                }
            elif characters_def and isinstance(characters_def, dict):
                actual_chars = {k: v for k, v in characters_def.items() if not k.startswith('_')}
            else:
                actual_chars = {}

            if preferred_slots and PACK_CONFIG_AVAILABLE and ACTIVE_PACK.is_loaded:
                slot_defs = getattr(getattr(ACTIVE_PACK, 'motiontoon', None), 'cast_slots', {}) or {}
                preferred_ids = []
                for slot in preferred_slots:
                    slot_data = slot_defs.get(slot, {}) if isinstance(slot_defs, dict) else {}
                    char_id = actor_id_from_slot(slot_data)
                    if char_id and char_id in actual_chars:
                        preferred_ids.append(char_id)
                if preferred_ids:
                    actual_chars = {char_id: actual_chars[char_id] for char_id in preferred_ids}

            if actual_chars:
                    chars_to_generate = []
                    for char_id, char_def in actual_chars.items():
                        if not char_library.has_character(char_id, min_expressions=2, min_images_per_expression=1):
                            chars_to_generate.append((char_id, char_def))

                    if chars_to_generate:
                        logger.info(f"[v59] 캐릭터 라이브러리 사전 생성: {len(chars_to_generate)}개 캐릭터")
                        char_library.sd_api_url = self.sd_url

                        for char_id, char_def in chars_to_generate:
                            char_name = char_def.get('name', char_id) if isinstance(char_def, dict) else getattr(char_def, 'name', char_id)
                            base_prompt = char_def.get('base', '') if isinstance(char_def, dict) else getattr(char_def, 'base_prompt', '')
                            style_prompt = char_def.get('style', '') if isinstance(char_def, dict) else getattr(char_def, 'style_suffix', '')
                            expressions_def = char_def.get('expressions', {}) if isinstance(char_def, dict) else getattr(char_def, 'expressions', {})
                            poses_def = char_def.get('poses', {}) if isinstance(char_def, dict) else getattr(char_def, 'poses', {})
                            full_base = f"{base_prompt}, {style_prompt}".strip(', ')

                            class CharDef:
                                ...

                            char_obj = CharDef()
                            char_obj.id = char_id
                            char_obj.name = char_name
                            char_obj.base_prompt = full_base
                            neg_prompt = char_def.get('negative', '') if isinstance(char_def, dict) else getattr(char_def, 'negative_prompt', '')
                            char_obj.negative_prompt = neg_prompt
                            expr_keys = preferred_expressions or list(expressions_def.keys()) or ['neutral', 'talking', 'fear']
                            pose_keys = preferred_poses or list(poses_def.keys()) or ['standing', 'listening']
                            char_obj.expressions = {expr: expressions_def.get(expr, expr) for expr in expr_keys}
                            char_obj.poses = {pose: poses_def.get(pose, pose) for pose in pose_keys}

                            try:
                                success, paths = char_library.generate_character_library(
                                    character_def=char_obj,
                                    expressions=list(char_obj.expressions.keys())[:4],
                                    poses=list(char_obj.poses.keys())[:3],
                                    images_per_combo=1,
                                )
                                if success:
                                    logger.info(f"[v59] {char_id}: {len(paths)}장 생성 완료")
                            except (RuntimeError, requests.RequestException, ConnectionError, OSError) as e:
                                logger.warning(f"[v59] 캐릭터 라이브러리 생성 실패 ({char_id}): {e}")

        # 팩 SD 설정
        if PACK_CONFIG_AVAILABLE and ACTIVE_PACK.is_loaded:
            pack_sd_positive = get_prompt("sd_positive", mode)
            pack_sd_negative = get_prompt("sd_negative", mode)
            style_pos = pack_sd_positive or "masterpiece, best quality"
            style_neg = pack_sd_negative or "(worst quality:1.4), (low quality:1.4), nsfw"
        else:
            style = self.styles.get(mode, self.styles.get("touching", {}))
            style_pos = style.get("positive", "masterpiece, best quality") if isinstance(style, dict) else "masterpiece, best quality"
            style_neg = style.get("negative", "(worst quality:1.4), nsfw") if isinstance(style, dict) else "(worst quality:1.4), nsfw"

        # 진행률 추적
        progress_lock = threading.Lock()
        completed = [0]
        total = len(script_list)
        generated_files = []
        context_dialogues = []

        # 씬 사전 분석 (캐시 없으면)
        if scene_analysis_cache is None and scene_analyzer:
            logger.info(f"[v59.8] 씬 사전 분석 시작 ({total}개 대사)...")
            scene_analysis_cache = self.pre_analyze_scenes(
                script_list, gemini_model, progress_callback
            )
            if scene_analysis_cache:
                logger.info(f"[v59.8] 캐시 준비 완료: {len(scene_analysis_cache)}개 씬")

        # v61.1 (#29): 캐릭터별 시드 캐시 — 동일 캐릭터/장소 시 시드 유지 (일관성)
        _char_seed_cache: Dict[str, int] = {}

        # v62.11: Gemini QC 완전 제거 (비용 절감 — 이미지마다 비전 API 호출)
        # 로컬 QC (validate_scene_image) 는 유지
        retry_queue = []
        final_images = {}

        def _sd_generate_single(
            idx: int,
            item: Dict[str, Any],
            payload_override: Optional[Dict[str, Any]] = None,
        ) -> None:
            """SD 이미지 생성 (로컬 QC 포함) → Gemini QC 비동기 제출"""
            speaker = item.get('speaker', item.get('role', '나레이터'))
            text = item.get('text', item.get('dialogue', ''))
            base_prompt = item.get('image_prompt', '')

            if self._cancellation_token and self._cancellation_token.is_cancelled:
                return

            try:
                # 1. 씬 분석
                analysis_result = None
                composed = None  # v61: 해상도 참조용 초기화
                image_action = 'new'
                main_emotion = 'neutral'
                main_action = ''

                if scene_analysis_cache and idx in scene_analysis_cache:
                    analysis_result = scene_analysis_cache[idx]
                    if analysis_result:
                        image_action = getattr(analysis_result, 'image_action', 'new')
                        chars = getattr(analysis_result, 'characters', [])
                        if chars and len(chars) > 0:
                            main_char = chars[0]
                            main_emotion = getattr(main_char, 'emotion', 'neutral')
                            main_action = getattr(main_char, 'action', '')
                elif scene_analyzer:
                    try:
                        analysis_result = scene_analyzer.analyze_dialogue(
                            dialogue=text, speaker=speaker, index=idx,
                            context_dialogues=context_dialogues[-5:] if context_dialogues else []
                        )
                        if analysis_result:
                            image_action = getattr(analysis_result, 'image_action', 'new')
                            chars = getattr(analysis_result, 'characters', [])
                            if chars and len(chars) > 0:
                                main_char = chars[0]
                                main_emotion = getattr(main_char, 'emotion', 'neutral')
                                main_action = getattr(main_char, 'action', '')
                    except (RuntimeError, ValueError, AttributeError) as e:
                        logger.warning(f"[v59:{idx}] 씬 분석 실패: {e}")

                # 2. 프롬프트 조합
                if prompt_composer and analysis_result and visual_director:
                    try:
                        composed = prompt_composer.compose_prompt(
                            scene_result=analysis_result,
                            override_positive=style_pos,
                            override_negative=style_neg,
                        )
                        if hasattr(composed, 'positive'):
                            pos_prompt = visual_director.sanitize_positive_v59(composed.positive)
                            neg_prompt = visual_director.build_negative_v59(composed.negative)
                        else:
                            pos_prompt = f"{base_prompt}, {style_pos}"
                            neg_prompt = visual_director.build_negative_v59(style_neg) if visual_director else style_neg
                    except (RuntimeError, ValueError, AttributeError, TypeError) as e:
                        logger.warning(f"[v59:{idx}] 프롬프트 조합 실패: {e}")
                        pos_prompt = f"{base_prompt}, {style_pos}"
                        neg_prompt = visual_director.build_negative_v59(style_neg) if visual_director else style_neg
                elif visual_director:
                    pos_prompt = visual_director.sanitize_positive_v59(f"{base_prompt}, {style_pos}")
                    neg_prompt = visual_director.build_negative_v59(style_neg)
                else:
                    pos_prompt = f"{base_prompt}, {style_pos}"
                    neg_prompt = style_neg

                # 3. 캐릭터 라이브러리 재사용 체크
                reuse_image = None
                char_id = ""
                if char_library:
                    # v62.10: voice_type 우선 사용 — role("관리인","한준" 등 자유이름)로
                    # 캐릭터를 찾으면 CharacterLibraryManager가 107회 WARNING을 내던 버그.
                    # voice_type("middle_man","young_man" 등)이 이미 대본에 있으므로 그걸 우선 사용.
                    _vt = item.get('voice_type', '')
                    speaker_lower = (_vt.lower() if _vt else speaker).lower()
                    char_id = ""
                    if speaker_lower not in ['나레이션', 'narrator', '나레이터', '내레이션']:
                        char_id = char_library.find_character_by_alias(speaker)
                        if not char_id:
                            role_mapping = {
                                '남자': 'man', '여자': 'woman', '주인공': 'protagonist',
                                '할아버지': 'grandpa', '할머니': 'grandma',
                                '귀신': 'ghost', '악역': 'antagonist',
                            }
                            mapped = role_mapping.get(speaker, speaker_lower)
                            char_id = char_library.find_character_by_alias(mapped)
                    if char_id:
                        try:
                            reuse_image = char_library.get_character_image(
                                character_id=char_id,
                                expression=main_emotion,
                                pose=main_action or 'standing',
                                fallback=True
                            )
                        except (KeyError, ValueError, RuntimeError) as e:
                            logger.debug(f"[v59:{idx}] 캐릭터 라이브러리 조회 실패: {e}")

                fname = os.path.join(save_dir, f"scene_{idx:04d}.png")

                # 4. 캐릭터 재사용
                if reuse_image and os.path.exists(reuse_image):
                    import shutil
                    shutil.copy(reuse_image, fname)
                    logger.info(f"[v59:{idx}] 캐릭터 이미지 재사용: {fname}")
                    final_images[idx] = fname
                    with progress_lock:
                        completed[0] += 1
                        if checkpoint_callback:
                            checkpoint_callback(idx, fname, completed[0], total)
                        if progress_callback:
                            pct = 50 + int(25 * completed[0] / total)
                            progress_callback(f"[v59] 이미지 생성 중... ({completed[0]}/{total})", pct)
                    return

                # 5. SD 설정
                sd_cfg = 6.5
                sd_steps = 15
                if PACK_CONFIG_AVAILABLE and ACTIVE_PACK.is_loaded:
                    sd_settings = get_sd_settings()
                    if sd_settings.cfg_scale:
                        sd_cfg = sd_settings.cfg_scale
                    if sd_settings.steps:
                        sd_steps = sd_settings.steps

                # v61: 팩의 SDModelConfig 해상도 우선 (SD 1.5 최적: 768x432)
                # ComposedPrompt에 팩의 sd_model.width/height가 설정됨
                sd_width = composed.width if composed and getattr(composed, 'width', 0) else 0
                sd_height = composed.height if composed and getattr(composed, 'height', 0) else 0
                if not sd_width or not sd_height:
                    sd_width = self.video_width
                    sd_height = self.video_height

                if payload_override:
                    payload = payload_override.copy()
                else:
                    # v61.1 (#28): ComposedPrompt.to_api_params()가 있으면 활용 (clip_skip, sampler 포함)
                    if composed and hasattr(composed, 'to_api_params') and callable(composed.to_api_params):
                        try:
                            payload = composed.to_api_params()
                            # prompt/negative는 sanitize 후 버전으로 override
                            payload["prompt"] = pos_prompt.strip()
                            payload["negative_prompt"] = neg_prompt.strip()
                            # steps/cfg는 팩 설정 우선
                            if sd_steps:
                                payload["steps"] = sd_steps
                            if sd_cfg:
                                payload["cfg_scale"] = sd_cfg
                        except (AttributeError, TypeError, ValueError) as e:
                            logger.debug(f"[v59:{idx}] to_api_params 실패, 수동 구성: {e}")
                            payload = {
                                "prompt": pos_prompt.strip(),
                                "negative_prompt": neg_prompt.strip(),
                                "steps": sd_steps,
                                "width": sd_width,
                                "height": sd_height,
                                "sampler_name": "DPM++ 2M Karras",
                                "cfg_scale": sd_cfg,
                            }
                    else:
                        payload = {
                            "prompt": pos_prompt.strip(),
                            "negative_prompt": neg_prompt.strip(),
                            "steps": sd_steps,
                            "width": sd_width,
                            "height": sd_height,
                            "sampler_name": "DPM++ 2M Karras",
                            "cfg_scale": sd_cfg,
                        }

                # v61.1 (#29): 동일 캐릭터/장소 시드 유지 (일관성)
                _speaker_key = speaker.strip().lower() if speaker else ""
                _scene_location = getattr(analysis_result, 'location', '') if analysis_result else ""
                payload = self._apply_cached_scene_seed(
                    payload,
                    _char_seed_cache,
                    character_id=char_id,
                    speaker=_speaker_key,
                    location=_scene_location,
                    mode_tag="v59",
                )

                # v61.1 (#31): IP-Adapter 일관성 적용
                payload = self._apply_consistency_to_payload(payload)
                payload = self._apply_vram_safety(payload, purpose="image")

                # 6. SD WebUI 호출
                sd_success = False
                for sd_attempt in range(3):
                    try:
                        resp = requests.post(
                            f"{self.sd_url}/sdapi/v1/txt2img",
                            json=payload,
                            timeout=120
                        )
                        if resp.status_code != 200:
                            logger.warning(f"[v59:{idx}] SD status={resp.status_code}, 재시도 {sd_attempt+1}/3")
                            time.sleep(2)
                            continue
                        sd_success = True
                        break
                    except requests.exceptions.Timeout:
                        logger.warning(f"[v59:{idx}] SD 타임아웃, 재시도 {sd_attempt+1}/3")
                        time.sleep(2)
                    except (requests.RequestException, ConnectionError, OSError) as e:
                        logger.warning(f"[v59:{idx}] SD 오류: {e}, 재시도 {sd_attempt+1}/3")
                        time.sleep(2)

                if not sd_success:
                    logger.error(f"[v59:{idx}] SD 3회 실패 → 폴백")
                    final_images[idx] = self.get_safe_fallback_image(fname, mode)
                    return

                try:
                    data = resp.json()
                    if data.get("images"):
                        img_data = base64.b64decode(data["images"][0])
                        with open(fname, "wb") as f:
                            f.write(img_data)

                        # 7. 로컬 QC
                        local_fail = False
                        if quality_control:
                            try:
                                qc_report = quality_control.validate_scene_image(fname)
                                if qc_report and hasattr(qc_report, 'overall_score'):
                                    if qc_report.overall_score < 0.5:
                                        logger.warning(f"[v59:{idx}] 로컬 QC 실패 ({qc_report.overall_score:.2f})")
                                        local_fail = True
                            except (RuntimeError, OSError, ValueError, AttributeError) as e:
                                logger.debug(f"[v59:{idx}] 로컬 QC 오류: {e}")

                        if local_fail:
                            payload['seed'] = self._variant_seed(int(payload.get('seed', 1) or 1), 1)
                            retry_queue.append((idx, 1, payload.copy()))
                            return

                        # 8. 이미지 확정 (v62.11: Gemini QC 제거, 로컬 QC 통과 시 바로 확정)
                        final_images[idx] = fname

                        # v61.1 (#30): context_dialogues에 완료된 대사 추가 (후속 씬 분석 활용)
                        # scene_analyzer.analyze_dialogue는 List[str] 기대 — dict 아님
                        context_dialogues.append(f"[{speaker}] {text}")

                        with progress_lock:
                            completed[0] += 1
                            if checkpoint_callback:
                                checkpoint_callback(idx, fname, completed[0], total)
                            if progress_callback:
                                pct = 50 + int(25 * completed[0] / total)
                                progress_callback(f"[v59] 이미지 생성 중... ({completed[0]}/{total})", pct)

                        logger.info(f"[v59:{idx}] SD 생성 완료, QC 비동기 제출: {fname}")
                    else:
                        logger.warning(f"[v59:{idx}] SD 응답에 이미지 없음")
                        final_images[idx] = self.get_safe_fallback_image(fname, mode)

                except (OSError, ValueError, KeyError, json.JSONDecodeError) as e:
                    logger.warning(f"[v59:{idx}] 이미지 처리 오류: {e}")
                    final_images[idx] = self.get_safe_fallback_image(fname, mode)

            except (RuntimeError, requests.RequestException, ConnectionError,
                    OSError, ValueError, KeyError, TypeError, AttributeError) as e:
                logger.error(f"[v59:{idx}] 씬 처리 실패: {e}")
                fname = os.path.join(save_dir, f"scene_{idx:04d}.png")
                final_images[idx] = self.get_safe_fallback_image(fname, mode)

        # Phase 1: 전체 이미지 순차 SD 생성
        _gen_start = time.time()

        for i, item in enumerate(script_list):
            if self._cancellation_token and self._cancellation_token.is_cancelled:
                break
            _sd_generate_single(i, item)

        # Phase 2: 로컬 QC 실패 이미지 재생성 (최대 2라운드, v62.11: Gemini QC 제거)
        retry_round = 0
        while retry_queue and retry_round < 2:
            retry_round += 1
            current_retries = list(retry_queue)
            retry_queue.clear()
            logger.info(f"[v59.8] 재생성 라운드 {retry_round}: {len(current_retries)}장")

            for idx, attempt, payload_cp in current_retries:
                if self._cancellation_token and self._cancellation_token.is_cancelled:
                    break

                payload_cp['seed'] = self._variant_seed(int(payload_cp.get('seed', 1) or 1), attempt + retry_round)
                fname = os.path.join(save_dir, f"scene_{idx:04d}.png")

                try:
                    resp = requests.post(
                        f"{self.sd_url}/sdapi/v1/txt2img",
                        json=payload_cp,
                        timeout=120
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        if data.get("images"):
                            img_data = base64.b64decode(data["images"][0])
                            with open(fname, "wb") as f:
                                f.write(img_data)
                            final_images[idx] = fname
                            continue
                except (requests.RequestException, ConnectionError, OSError, ValueError) as e:
                    logger.warning(f"[v59:{idx}] 재생성 실패: {e}")

                final_images[idx] = self.get_safe_fallback_image(fname, mode)

        # 남은 retry_queue
        for idx, attempt, payload_cp in retry_queue:
            fname = os.path.join(save_dir, f"scene_{idx:04d}.png")
            if idx not in final_images:
                final_images[idx] = self.get_safe_fallback_image(fname, mode)

        _gen_elapsed = time.time() - _gen_start

        # v61.1: 인덱스 순서 보존 (위치 시프트 방지)
        result_paths = []
        for i in range(total):
            if i in final_images and final_images[i]:
                result_paths.append(final_images[i])
            else:
                # 누락된 인덱스에 검정 플레이스홀더 삽입
                placeholder_path = os.path.join(save_dir, f"scene_{i:04d}.png")
                if not os.path.exists(placeholder_path):
                    self._create_black_placeholder(placeholder_path)
                result_paths.append(placeholder_path)

        logger.info(f"[v59] 이미지 생성 완료: {len(result_paths)}/{total}장 ({_gen_elapsed:.1f}s)")
        return result_paths

    # ================================================================
    # 4. Image Generation — v33 (향상된 이미지 생성)
    # ================================================================
    def generate_images_v33(
        self,
        prompts: List[str],
        project_name: str,
        mode: str,
        progress_callback: Optional[Callable[[str, int], None]] = None
    ) -> List[str]:
        """v33: 향상된 이미지 생성 (진행률 세분화, 취소 지원)"""
        import concurrent.futures

        try:
            from config.pack_config import ACTIVE_PACK, PACK_CONFIG_AVAILABLE, get_prompt, get_sd_settings
        except ImportError:
            PACK_CONFIG_AVAILABLE = False

        try:
            from modules_pro.visual_director import visual_director
        except ImportError:
            visual_director = None

        try:
            # v61.1-fix: 모듈 임포트 → 인스턴스 임포트 (IMAGE_MAX_WORKERS 등 속성 접근)
            from config.settings_v2 import config
        except ImportError:
            config = None

        # NSFW 검수 시스템
        NSFW_DETECTOR_AVAILABLE = False
        content_reviewer = None
        try:
            from core.nsfw_detector import ContentReviewer
            content_reviewer = ContentReviewer()
            NSFW_DETECTOR_AVAILABLE = True
        except ImportError:
            logger.debug("[이미지] NSFW 검수 모듈 미설치 — 건너뜀")
        except (RuntimeError, OSError, ValueError) as e:
            logger.warning(f"[이미지] NSFW 검수 초기화 실패: {e}")

        # 표정 오버레이
        EXPRESSION_OVERLAY_AVAILABLE = False
        expr_overlay_instance = None
        try:
            from core.expression_overlay import ExpressionOverlay
            expr_overlay_instance = ExpressionOverlay()
            EXPRESSION_OVERLAY_AVAILABLE = True
        except ImportError:
            logger.debug("[이미지] ExpressionOverlay 모듈 미설치 — 건너뜀")
        except (RuntimeError, OSError, ValueError) as e:
            logger.warning(f"[이미지] ExpressionOverlay 초기화 실패: {e}")

        # QualityPreset
        try:
            from modules_pro.video_models import QualityPreset
        except ImportError:
            QualityPreset = None

        logger.info(f"[이미지] 생성 시작: {len(prompts)}장")

        safe_project_name = _sanitize_for_path(project_name)
        save_dir = os.path.join(self.data_dir, "temp_images", safe_project_name)
        os.makedirs(save_dir, exist_ok=True)

        # 팩 기반 SD 프롬프트
        if PACK_CONFIG_AVAILABLE and ACTIVE_PACK.is_loaded:
            pack_sd_positive = get_prompt("sd_positive", mode)
            pack_sd_negative = get_prompt("sd_negative", mode)
            if pack_sd_positive:
                style_pos = pack_sd_positive
                style_neg = pack_sd_negative or "(worst quality:1.4), (low quality:1.4), nsfw"
            else:
                style = self.styles.get(mode, self.styles.get("touching", {}))
                style_pos = style.get("positive", "masterpiece") if isinstance(style, dict) else "masterpiece"
                style_neg = style.get("negative", "(worst quality:1.4), nsfw") if isinstance(style, dict) else "(worst quality:1.4), nsfw"
        else:
            style = self.styles.get(mode, self.styles.get("touching", {}))
            style_pos = style.get("positive", "masterpiece") if isinstance(style, dict) else "masterpiece"
            style_neg = style.get("negative", "(worst quality:1.4), nsfw") if isinstance(style, dict) else "(worst quality:1.4), nsfw"

        style_pos = f"{style_pos}, masterpiece, best quality, highly detailed background"
        # v61.1 (#38): SENIOR_ULTRA_NEGATIVE는 시니어 채널에만 적용 (v33 경로)
        if self.channel == "senior":
            style_neg = f"{style_neg}, {self.SENIOR_ULTRA_NEGATIVE}"

        progress_lock = threading.Lock()
        completed = [0]
        total = len(prompts)

        # 프롬프트 사전 정규화
        prompts_normalized = []
        if visual_director:
            for p in prompts:
                p_clean = re.sub(r'[^\w\s가-힣]', ' ', p)
                p_clean = ' '.join(p_clean.split())
                pos, neg = visual_director.finalize(
                    raw_prompt=p_clean,
                    extra_positive=style_pos,
                    extra_negative=style_neg,
                )
                prompts_normalized.append((pos, neg))
        else:
            for p in prompts:
                prompts_normalized.append((f"{p}, {style_pos}", style_neg))

        # 채널별 안전 폴백 프롬프트
        SAFE_FALLBACK_PROMPTS = {
            "daily_life_toon": "clean Korean apartment living room, warm afternoon light, no people, reusable webtoon background, layered-safe center space",
            "mystery_toon": "old Korean apartment hallway at night, restrained shadows, no people, reusable mystery webtoon background, layered-safe center space",
            "videotoon": "clean Korean webtoon background, no people, no UI overlays, reusable layered composition",
        }

        def generate_single_image(idx_prompt_tuple):
            i, p = idx_prompt_tuple

            if self._cancellation_token and self._cancellation_token.is_cancelled:
                return None

            pos, neg = prompts_normalized[i]

            # 품질 기반 steps
            steps = 15
            if QualityPreset and self._quality:
                if self._quality == QualityPreset.FAST:
                    steps = 12
                elif self._quality == QualityPreset.HIGH:
                    steps = 25

            sd_cfg = 6.5
            sd_steps = steps
            if PACK_CONFIG_AVAILABLE and ACTIVE_PACK.is_loaded:
                sd_settings = get_sd_settings()
                if sd_settings.cfg_scale:
                    sd_cfg = sd_settings.cfg_scale
                if sd_settings.steps and QualityPreset and self._quality == QualityPreset.STANDARD:
                    sd_steps = sd_settings.steps

            # v61.1 (#32): 팩 SDModelConfig 해상도 우선 (v33 경로)
            _v33_width = self.video_width
            _v33_height = self.video_height
            if PACK_CONFIG_AVAILABLE and ACTIVE_PACK.is_loaded:
                try:
                    _vs33 = getattr(ACTIVE_PACK, 'visual_storytelling', None)
                    _sdm33 = None
                    if isinstance(_vs33, dict):
                        _sdm33 = _vs33.get('sd_model', None)
                    elif _vs33:
                        _sdm33 = getattr(_vs33, 'sd_model', None)
                    if _sdm33:
                        _w33 = _sdm33.get('width', 0) if isinstance(_sdm33, dict) else getattr(_sdm33, 'width', 0)
                        _h33 = _sdm33.get('height', 0) if isinstance(_sdm33, dict) else getattr(_sdm33, 'height', 0)
                        if _w33 and _h33:
                            _v33_width = _w33
                            _v33_height = _h33
                except (AttributeError, TypeError, KeyError) as e:
                    logger.debug(f"[이미지] v33 해상도 로드 실패, 기본값 사용: {e}")

            payload = {
                "prompt": pos.strip(),
                "negative_prompt": neg.strip(),
                "steps": sd_steps,
                "width": _v33_width,
                "height": _v33_height,
                "sampler_name": "DPM++ 2M Karras",
                "cfg_scale": sd_cfg,
                "seed": self._resolve_scene_seed(prompt=pos, mode_tag="v33"),
            }

            payload = self._apply_consistency_to_payload(payload)
            payload = self._apply_vram_safety(payload, purpose="image")

            max_nsfw_retries = 10
            current_payload = payload.copy()
            current_pos = pos

            for attempt in range(max_nsfw_retries):
                try:
                    if attempt > 0:
                        current_payload["seed"] = self._variant_seed(
                            int(current_payload.get("seed", 1) or 1),
                            attempt,
                        )

                    using_safe_prompt = False
                    if attempt >= 5:
                        channel_key = self.channel if self.channel != "senior" else f"senior_{self.mode or 'touching'}"
                        safe_prompt = SAFE_FALLBACK_PROMPTS.get(channel_key, SAFE_FALLBACK_PROMPTS["daily_life_toon"])
                        current_payload["prompt"] = safe_prompt
                        using_safe_prompt = True

                    res = requests.post(f"{self.sd_url}/sdapi/v1/txt2img", json=current_payload, timeout=120)
                    if res.status_code != 200:
                        continue

                    if res.status_code == 200:
                        # v62.21 C-3: SD 빈 images 배열 가드
                        resp_json = res.json()
                        if not resp_json.get("images"):
                            logger.warning(f"[SD] 빈 images 응답 (scene {i}, attempt {attempt+1})")
                            continue
                        fname = os.path.join(save_dir, f"s_{i:03d}.png")
                        with open(fname, "wb") as f:
                            f.write(base64.b64decode(resp_json["images"][0]))

                        # 안전 프롬프트: QuickScreener만
                        if using_safe_prompt:
                            if NSFW_DETECTOR_AVAILABLE and content_reviewer:
                                channel_type = f"{self.channel}_{self.mode}" if self.mode else self.channel
                                suspicious, reason = content_reviewer.quick_screener.screen(fname, channel_type)
                                if suspicious:
                                    if os.path.exists(fname):
                                        os.remove(fname)
                                    continue
                            return fname

                        # NSFW 검수
                        if NSFW_DETECTOR_AVAILABLE and content_reviewer:
                            channel_type = f"{self.channel}_{self.mode}" if self.mode else self.channel
                            result, reason = content_reviewer.review_image(fname, channel_type)

                            if result == "UNSAFE":
                                if os.path.exists(fname):
                                    os.remove(fname)
                                if attempt < max_nsfw_retries - 1:
                                    if attempt < 5:
                                        fixed_prompt = content_reviewer.suggest_fixed_prompt(current_pos, reason)
                                        if fixed_prompt:
                                            current_pos = fixed_prompt
                                            current_payload["prompt"] = fixed_prompt
                                    continue
                                else:
                                    # v62.21 C-4: 마지막 재시도도 NSFW 검사 + C-3: 빈 images 가드
                                    res = requests.post(f"{self.sd_url}/sdapi/v1/txt2img", json=current_payload, timeout=120)
                                    resp_last = res.json() if res.status_code == 200 else {}
                                    if resp_last.get("images"):
                                        with open(fname, "wb") as f:
                                            f.write(base64.b64decode(resp_last["images"][0]))
                                        # 최종 NSFW 체크
                                        result2, _ = content_reviewer.review_image(fname, channel_type)
                                        if result2 == "UNSAFE":
                                            logger.warning(f"[NSFW] 최종 재시도도 UNSAFE (scene {i}) → 파일 제거")
                                            if os.path.exists(fname):
                                                os.remove(fname)
                                            fname = None  # 이미지 없음 표시
                                    else:
                                        logger.warning(f"[SD] 최종 재시도 빈 응답 (scene {i})")
                                        fname = None

                        # 표정 오버레이
                        if EXPRESSION_OVERLAY_AVAILABLE and visual_director and visual_director.is_character_system_enabled():
                            try:
                                from PIL import Image
                                channel_type = f"{self.channel}_{self.mode}" if self.mode else self.channel
                                emotion = self.extract_emotion_from_prompt(current_pos)
                                if emotion:
                                    img = Image.open(fname)
                                    w, h = img.size
                                    face_region = (w // 4, h // 10, w * 3 // 4, h // 3)
                                    result_img = expr_overlay_instance.apply_expression(
                                        image=img, emotion=emotion,
                                        channel_type=channel_type,
                                        face_region=face_region, intensity=0.8
                                    )
                                    if result_img:
                                        result_img.save(fname, quality=95)
                            except (ImportError, OSError, ValueError, AttributeError) as e:
                                logger.debug(f"[이미지] v59 표정 오버레이 실패 (무시): {i+1}번: {e}")

                        with progress_lock:
                            completed[0] += 1
                            if progress_callback and completed[0] % 5 == 0:
                                pct = 50 + int((completed[0] / total) * 20)
                                progress_callback(f"이미지 생성 중... ({completed[0]}/{total})", pct)

                        return fname

                except (requests.RequestException, ConnectionError, OSError, ValueError, json.JSONDecodeError) as e:
                    # v61.1 (#33): backoff 최대 5초 캡 (기존: 2^9 × random ≈ 24분)
                    delay = min(5.0, 1.0 * (2 ** attempt) * (0.5 + random.random()))
                    logger.warning(f"[이미지] {i+1}번 생성 실패. 재시도 {attempt+1}/{max_nsfw_retries}, {delay:.1f}s 대기")
                    time.sleep(delay)

            # 최종 실패 → 안전 폴백
            try:
                channel_key = self.channel if self.channel != "senior" else f"senior_{self.mode or 'touching'}"
                safe_prompt = SAFE_FALLBACK_PROMPTS.get(channel_key, SAFE_FALLBACK_PROMPTS["daily_life_toon"])
                fallback_payload = {
                    "prompt": safe_prompt,
                    "negative_prompt": neg.strip(),
                    "steps": 15,
                    "width": _v33_width,
                    "height": _v33_height,
                    "sampler_name": "DPM++ 2M Karras",
                    "cfg_scale": 5.0,
                    "seed": self._resolve_scene_seed(prompt=safe_prompt, mode_tag="v33-safe"),
                }
                fallback_payload = self._apply_vram_safety(fallback_payload, purpose="image")
                res = requests.post(f"{self.sd_url}/sdapi/v1/txt2img", json=fallback_payload, timeout=120)
                if res.status_code == 200:
                    # v62.21 C-3: 빈 images 가드
                    resp_fb = res.json()
                    if not resp_fb.get("images"):
                        logger.warning(f"[SD] 안전 폴백 빈 images (scene {i})")
                        return None
                    fname = os.path.join(save_dir, f"s_{i:03d}.png")
                    with open(fname, "wb") as f:
                        f.write(base64.b64decode(resp_fb["images"][0]))
                    with progress_lock:
                        completed[0] += 1
                    return fname
            except (requests.RequestException, ConnectionError, OSError, ValueError) as e:
                logger.error(f"[이미지] {i+1}번 안전 폴백도 실패: {e}")

            return None

        # 워커 수
        if config:
            max_workers = getattr(config, 'IMAGE_MAX_WORKERS', 1)
        else:
            max_workers = 1

        if QualityPreset and self._quality and max_workers > 1:
            if self._quality == QualityPreset.FAST:
                max_workers = min(max_workers + 1, 4)
            elif self._quality == QualityPreset.HIGH:
                max_workers = max(max_workers - 1, 1)

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(generate_single_image, (i, p)): i
                       for i, p in enumerate(prompts)}

            results = [None] * total
            for future in concurrent.futures.as_completed(futures):
                idx = futures[future]
                try:
                    result = future.result()
                    if result:
                        results[idx] = result
                except (RuntimeError, requests.RequestException, ConnectionError,
                        OSError, ValueError, TypeError) as e:
                    import traceback
                    logger.error(f"[이미지] {idx+1}번 생성 중 오류: {e}\n{traceback.format_exc()}")

        # v62.19: 이미지 성공률 임계값 — 30% 미만이면 중단 (전부 검정 영상 방지)
        success_count = sum(1 for r in results if r is not None)
        if total > 0 and success_count < total * 0.3:
            fail_pct = round((total - success_count) / total * 100)
            logger.error(f"[이미지] 실패율 {fail_pct}% ({total - success_count}/{total}) — 임계값 초과, 중단")
            from pipeline.pipeline_utils import safe_print
            safe_print(f"[ERROR] 이미지 생성 실패율 {fail_pct}% — SD WebUI 상태를 확인하세요.")
            return []  # 빈 리스트 → orchestrator에서 제작 중단

        # v61.1 (#35): 위치 보존 — None 대신 검정 플레이스홀더
        files = []
        for i, f in enumerate(results):
            if f is not None:
                files.append(f)
            else:
                placeholder_path = os.path.join(save_dir, f"s_{i:03d}.png")
                if not os.path.exists(placeholder_path):
                    self._create_black_placeholder(placeholder_path)
                files.append(placeholder_path)
        logger.info(f"[이미지] 생성 완료: {success_count}/{total}장 (플레이스홀더 포함 {len(files)})")

        return files

    # ================================================================
    # 5. Image Generation — Legacy (generic)
    # ================================================================
    def generate_images(self, prompts: List[str], project_name: str, mode: str) -> List[str]:
        """이미지 생성 (병렬 처리 최적화) — 레거시 경로"""
        import concurrent.futures

        try:
            from modules_pro.visual_director import visual_director
        except ImportError:
            visual_director = None

        # 표정 오버레이
        EXPRESSION_OVERLAY_AVAILABLE = False
        expr_overlay_instance = None
        try:
            from core.expression_overlay import ExpressionOverlay
            expr_overlay_instance = ExpressionOverlay()
            EXPRESSION_OVERLAY_AVAILABLE = True
        except ImportError:
            logger.debug("[이미지] ExpressionOverlay 모듈 미설치 — 건너뜀 (v33)")
        except (RuntimeError, OSError, ValueError) as e:
            logger.warning(f"[이미지] ExpressionOverlay 초기화 실패 (v33): {e}")

        safe_project_name = _sanitize_for_path(project_name)
        save_dir = os.path.join(self.data_dir, "temp_images", safe_project_name)
        os.makedirs(save_dir, exist_ok=True)
        files: List[str] = []

        style = self.styles.get(mode, self.styles.get("touching", {}))
        style_pos = style.get("positive", "masterpiece") if isinstance(style, dict) else "masterpiece"
        style_neg = style.get("negative", "(worst quality:1.4), nsfw") if isinstance(style, dict) else "(worst quality:1.4), nsfw"
        style_pos = f"{style_pos}, masterpiece, best quality, highly detailed background"
        # v61.1 (#38): SENIOR_ULTRA_NEGATIVE는 시니어 채널에만 적용 (legacy 경로)
        if self.channel == "senior":
            style_neg = f"{style_neg}, {self.SENIOR_ULTRA_NEGATIVE}"

        progress_lock = threading.Lock()
        completed = [0]

        def generate_single_image(idx_prompt_tuple):
            i, p = idx_prompt_tuple

            p_clean = re.sub(r'[^\w\s가-힣]', ' ', p)
            p_clean = ' '.join(p_clean.split())

            if visual_director:
                pos, neg = visual_director.finalize(
                    raw_prompt=p_clean,
                    extra_positive=style_pos,
                    extra_negative=style_neg,
                )
            else:
                pos = f"{p_clean}, {style_pos}"
                neg = style_neg

            payload = {
                "prompt": pos.strip(),
                "negative_prompt": neg.strip(),
                "steps": 15,
                "width": self.video_width,
                "height": self.video_height,
                "sampler_name": "DPM++ 2M Karras",
                "cfg_scale": 6.5,
            }

            if self.channel == "senior":
                payload["cfg_scale"] = 6.0

            payload = self._apply_consistency_to_payload(payload)
            payload = self._apply_vram_safety(payload, purpose="image")

            try:
                res = requests.post(f"{self.sd_url}/sdapi/v1/txt2img", json=payload, timeout=120)
                if res.status_code == 200:
                    # v62.21 C-3: 빈 images 가드
                    resp_v59 = res.json()
                    if not resp_v59.get("images"):
                        logger.warning(f"[SD] v59 순차 빈 images (scene {i})")
                        return None
                    fname = os.path.join(save_dir, f"s_{i:03d}.png")
                    with open(fname, "wb") as f:
                        f.write(base64.b64decode(resp_v59["images"][0]))

                    # 표정 오버레이
                    if EXPRESSION_OVERLAY_AVAILABLE and visual_director and visual_director.is_character_system_enabled():
                        try:
                            from PIL import Image
                            channel_type = f"{self.channel}_{mode}" if mode else self.channel
                            emotion = self.extract_emotion_from_prompt(pos)
                            if emotion:
                                img = Image.open(fname)
                                w, h = img.size
                                face_region = (w // 4, h // 10, w * 3 // 4, h // 3)
                                result_img = expr_overlay_instance.apply_expression(
                                    image=img, emotion=emotion,
                                    channel_type=channel_type,
                                    face_region=face_region, intensity=0.8
                                )
                                if result_img:
                                    result_img.save(fname, quality=95)
                        except (ImportError, OSError, ValueError, AttributeError) as e:
                            logger.debug(f"[이미지] v33 표정 오버레이 실패 (무시): {i+1}번: {e}")

                    with progress_lock:
                        completed[0] += 1

                    return fname
            except (requests.RequestException, ConnectionError, OSError, ValueError) as e:
                logger.warning(f"[이미지] {i+1} 생성 실패: {e}")

            return None

        # v61.1 (#37): max_workers=3 → 1 (RTX 4060 Ti 8GB VRAM 보호)
        max_workers = 1

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(generate_single_image, (i, p)): i
                       for i, p in enumerate(prompts)}

            results = [None] * len(prompts)
            for future in concurrent.futures.as_completed(futures):
                idx = futures[future]
                try:
                    result = future.result()
                    if result:
                        results[idx] = result
                except (RuntimeError, requests.RequestException, ConnectionError,
                        OSError, ValueError, TypeError) as e:
                    logger.warning(f"[이미지] 생성 중 오류: {e}")

        # v61.1: 위치 보존 — None 대신 검정 플레이스홀더 (legacy 경로)
        files = []
        for i, f in enumerate(results):
            if f is not None:
                files.append(f)
            else:
                placeholder_path = os.path.join(save_dir, f"s_{i:03d}.png")
                if not os.path.exists(placeholder_path):
                    self._create_black_placeholder(placeholder_path)
                files.append(placeholder_path)
        return files
