# Gemini API 호환성 래퍼
# Version: 2.2.0

"""
google.genai 기반 Gemini API 래퍼

v59.1.8: 구 SDK 의존 제거 → google.genai 중심으로 통합
v59.1.9: timeout 실제 구현 (ThreadPoolExecutor), hang 완전 방지
- 신규 API: Client 기반 (google.genai)
- 기존 호출부 호환: model.generate_content(prompt) 인터페이스 유지
- 모델 우선순위: gemini-3.0-flash → gemini-2.5-flash → gemini-2.0-flash
- timeout 구현: ThreadPoolExecutor + future.result(timeout=N) (hang 방지)

사용법:
    from utils.gemini_compat import configure_gemini, get_gemini_model

    configure_gemini(api_key)
    model = get_gemini_model()  # 자동으로 최신 모델 선택
    response = model.generate_content("Hello!")
    print(response.text)
"""

import os
import mimetypes
import logging
import concurrent.futures
from typing import Optional, Any

logger = logging.getLogger(__name__)

# ============================================================
# API 사용 가능 여부
# ============================================================
GENAI_NEW_AVAILABLE = False  # google.genai - 우선

_genai_client = None  # google.genai Client 인스턴스
_api_key_stored = None  # 저장된 API 키
genai_version = "unknown"

# 신규 패키지 먼저 시도
try:
    from google import genai as genai_new
    GENAI_NEW_AVAILABLE = True
    genai_version = f"google.genai {genai_new.__version__}"
    logger.info(f"Using new google.genai package (v{genai_new.__version__})")
except ImportError:
    pass

GEMINI_AVAILABLE = GENAI_NEW_AVAILABLE


# ============================================================
# 호환성 래퍼 클래스
# 기존 코드: model.generate_content(prompt) → response.text
# 신규 API: client.models.generate_content(model=..., contents=...)
# 이 래퍼가 둘을 연결
# ============================================================

class _GeminiModelWrapper:
    """
    기존 GenerativeModel 인터페이스를 유지하면서
    신규 google.genai Client API를 사용하는 래퍼

    사용법 (기존과 동일):
        model = get_gemini_model("gemini-3.0-flash")
        response = model.generate_content("분석해줘")
        print(response.text)
    """

    def __init__(self, client, model_name: str):
        self._client = client
        self._model_name = model_name
        logger.info(f"[GeminiWrapper] 모델 래퍼 생성: {model_name}")

    # v59.1.9: 기본 timeout (초)
    DEFAULT_TIMEOUT = 30

    def generate_content(self, prompt, timeout: int = None, **kwargs):
        """
        기존 GenerativeModel.generate_content() 호환 인터페이스
        v59.1.9: ThreadPoolExecutor 기반 timeout 구현 (hang 완전 방지)

        Args:
            prompt: 문자열 또는 리스트 (멀티모달)
            timeout: API 응답 대기 최대 시간(초). None이면 DEFAULT_TIMEOUT 사용
            **kwargs: 추가 설정

        Returns:
            API 응답 객체 (response.text 접근 가능)

        Raises:
            TimeoutError: timeout 초과 시
            Exception: API 호출 실패 시
        """
        effective_timeout = timeout if timeout is not None else self.DEFAULT_TIMEOUT

        try:
            # 프롬프트 타입 처리
            if isinstance(prompt, str):
                contents = prompt
            elif isinstance(prompt, list):
                contents = prompt
            else:
                contents = str(prompt)

            # v59.5.5: generation_config → config 변환
            # 호환 래퍼가 넘긴 generation_config 객체를
            # google.genai config 파라미터로 변환
            # ★ safety_settings 주입보다 먼저 실행 (generation_config의 temperature 등 보존)
            if 'generation_config' in kwargs:
                gen_cfg = kwargs.pop('generation_config')
                if 'config' not in kwargs:
                    try:
                        from google.genai import types
                        config_dict = {}
                        for attr in ['temperature', 'top_p', 'top_k', 'max_output_tokens',
                                     'candidate_count', 'stop_sequences']:
                            val = getattr(gen_cfg, attr, None)
                            if val is not None:
                                config_dict[attr] = val
                        # v62.3: thinking_budget 지원 — 0이면 thinking 비활성화
                        tb = getattr(gen_cfg, 'thinking_budget', None)
                        if tb is not None:
                            try:
                                config_dict['thinking_config'] = types.ThinkingConfig(thinking_budget=tb)
                            except Exception:
                                logger.debug(f"[GeminiWrapper] ThinkingConfig 생성 실패, 무시")
                        if config_dict:
                            kwargs['config'] = types.GenerateContentConfig(**config_dict)
                    except Exception as e:
                        logger.warning(f"[GeminiWrapper] generation_config 변환 실패, 무시: {e}")

            # v62: safety_settings 자동 주입 (공포 콘텐츠 안전 필터 해제)
            # Gemini 기본값 BLOCK_MEDIUM_AND_ABOVE → 공포 콘텐츠 차단 → response.text=None
            # ★ 기존 config가 있으면 safety_settings만 병합, 없으면 새로 생성
            try:
                from google.genai import types
                _safety = [
                    types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_ONLY_HIGH"),
                    types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_ONLY_HIGH"),
                    types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_ONLY_HIGH"),
                    types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_ONLY_HIGH"),
                ]
                if 'config' in kwargs:
                    # 기존 config에 safety_settings가 없으면 추가
                    existing_cfg = kwargs['config']
                    if hasattr(existing_cfg, 'safety_settings') and not existing_cfg.safety_settings:
                        existing_cfg.safety_settings = _safety
                    elif not hasattr(existing_cfg, 'safety_settings'):
                        existing_cfg.safety_settings = _safety
                else:
                    kwargs['config'] = types.GenerateContentConfig(safety_settings=_safety)
            except Exception as e:
                logger.debug(f"[GeminiWrapper] safety_settings 주입 실패 (무시): {e}")

            # v59.1.9: ThreadPoolExecutor로 timeout 강제 적용
            # v62.19: shutdown(wait=False, cancel_futures=True) — timeout 시 배경 스레드 블로킹 방지
            executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            try:
                future = executor.submit(
                    self._client.models.generate_content,
                    model=self._model_name,
                    contents=contents,
                    **kwargs
                )
                try:
                    response = future.result(timeout=effective_timeout)
                except concurrent.futures.TimeoutError:
                    logger.error(
                        f"[GeminiWrapper] TIMEOUT ({effective_timeout}s) - "
                        f"모델: {self._model_name}, 프롬프트: {str(prompt)[:80]}..."
                    )
                    raise TimeoutError(
                        f"Gemini API 응답 대기 시간 초과 ({effective_timeout}초)"
                    )
            finally:
                executor.shutdown(wait=False, cancel_futures=True)

            return response

        except TimeoutError:
            raise  # timeout은 그대로 전파
        except Exception as e:
            logger.error(f"[GeminiWrapper] generate_content 실패 ({self._model_name}): {e}")
            raise

    @property
    def model_name(self) -> str:
        return self._model_name

    def __repr__(self):
        return f"GeminiModelWrapper(model={self._model_name})"


# ============================================================
# 공개 API 함수
# ============================================================

def configure_gemini(api_key: str) -> bool:
    """
    Gemini API 키 설정

    Args:
        api_key: Gemini API 키

    Returns:
        성공 여부
    """
    global _genai_client, _api_key_stored

    if not GEMINI_AVAILABLE:
        logger.error("Gemini API 패키지가 설치되어 있지 않습니다.")
        return False

    try:
        _api_key_stored = api_key

        _genai_client = genai_new.Client(api_key=api_key)
        logger.info(f"Gemini API configured with {genai_version} (Client 방식)")

        return True

    except Exception as e:
        logger.error(f"Gemini API 설정 실패: {e}")
        return False


# v62.10: 모델 후보 목록 (우선순위 순) — Gemini 3 Flash Preview 추가
GEMINI_MODEL_CANDIDATES = [
    "gemini-3-flash-preview",   # v62.10: Gemini 3 Flash (실제 API 이름, gemini-3.0-flash는 존재 안 함)
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-1.5-flash",
]


def get_gemini_model(
    model_name: str = "auto",
    **kwargs
) -> Optional[Any]:
    """
    Gemini 모델 인스턴스 반환

    Args:
        model_name: 모델 이름 또는 "auto" (자동 선택)
            - "auto": GEMINI_MODEL_CANDIDATES에서 순차 시도
            - 특정 이름: 해당 모델 직접 사용
        **kwargs: 추가 모델 설정

    Returns:
        GeminiModelWrapper 또는 None
    """
    if not GEMINI_AVAILABLE:
        return None

    return _get_model_new_api(model_name, **kwargs)


def _get_model_new_api(model_name: str, **kwargs) -> Optional[_GeminiModelWrapper]:
    """신규 google.genai API로 모델 생성"""
    global _genai_client

    if not _genai_client:
        # configure_gemini 호출 전이면 환경변수에서 시도
        api_key = _api_key_stored or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if api_key:
            _genai_client = genai_new.Client(api_key=api_key)
        else:
            logger.error("[GeminiCompat] API 키 없음 - configure_gemini() 먼저 호출 필요")
            return None

    if model_name == "auto":
        # v59.1.9: 자동 선택 - ping 테스트 (timeout=10초)
        PING_TIMEOUT = 10
        for candidate in GEMINI_MODEL_CANDIDATES:
            try:
                logger.info(f"[GeminiCompat] 모델 ping 테스트: {candidate} (timeout={PING_TIMEOUT}s)")
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(
                        _genai_client.models.generate_content,
                        model=candidate,
                        contents="ping"
                    )
                    response = future.result(timeout=PING_TIMEOUT)

                if response and hasattr(response, 'text'):
                    logger.info(f"[GeminiCompat] 모델 자동 선택 성공: {candidate}")
                    return _GeminiModelWrapper(_genai_client, candidate)
            except concurrent.futures.TimeoutError:
                logger.warning(f"[GeminiCompat] {candidate} ping 타임아웃 ({PING_TIMEOUT}s)")
                continue
            except Exception as e:
                logger.debug(f"[GeminiCompat] {candidate} 시도 실패: {e}")
                continue

        logger.error("[GeminiCompat] 사용 가능한 모델 없음")
        return None
    else:
        # 특정 모델 직접 사용
        return _GeminiModelWrapper(_genai_client, model_name)


def generate_content(
    model: Any,
    prompt: str,
    timeout: int = None,
    **kwargs
) -> Optional[str]:
    """
    콘텐츠 생성 (편의 함수)

    Args:
        model: GeminiModelWrapper 인스턴스
        prompt: 프롬프트 텍스트
        timeout: API 응답 대기 최대 시간(초). None이면 기본값 사용
        **kwargs: 추가 생성 설정

    Returns:
        생성된 텍스트 또는 None
    """
    if model is None:
        return None

    try:
        # v59.1.9: timeout 전달
        call_kwargs = dict(**kwargs)
        if timeout is not None:
            call_kwargs['timeout'] = timeout

        response = model.generate_content(prompt, **call_kwargs)

        # 응답에서 텍스트 추출
        if hasattr(response, 'text'):
            return response.text
        elif hasattr(response, 'parts'):
            return ''.join(part.text for part in response.parts if hasattr(part, 'text'))
        else:
            return str(response)

    except TimeoutError:
        logger.warning(f"콘텐츠 생성 타임아웃 (prompt: {str(prompt)[:50]}...)")
        return None
    except Exception as e:
        logger.error(f"콘텐츠 생성 실패: {e}")
        return None


def build_image_part(image_path: str) -> Optional[Any]:
    """이미지 파일을 Gemini 입력 파트로 변환."""
    if not image_path or not os.path.exists(image_path):
        return None

    try:
        if GENAI_NEW_AVAILABLE:
            from google.genai import types

            mime_type, _ = mimetypes.guess_type(image_path)
            if not mime_type:
                mime_type = "image/png"
            with open(image_path, "rb") as f:
                return types.Part.from_bytes(data=f.read(), mime_type=mime_type)

        from PIL import Image

        return Image.open(image_path)
    except Exception as e:
        logger.error(f"이미지 파트 생성 실패: {e}")
        return None


def generate_vision_content(
    model: Any,
    prompt: str,
    image_paths: list[str],
    timeout: int = None,
    **kwargs
) -> Optional[Any]:
    """텍스트 + 이미지 입력으로 Gemini Vision 호출."""
    if model is None:
        return None

    contents = [prompt]
    for image_path in image_paths:
        image_part = build_image_part(image_path)
        if image_part is not None:
            contents.append(image_part)

    if len(contents) == 1:
        return None

    try:
        call_kwargs = dict(**kwargs)
        if timeout is not None:
            call_kwargs["timeout"] = timeout
        return model.generate_content(contents, **call_kwargs)
    except Exception as e:
        logger.error(f"Vision 콘텐츠 생성 실패: {e}")
        return None


def get_version_info() -> dict:
    """
    Gemini API 버전 정보 반환

    Returns:
        버전 정보 딕셔너리
    """
    return {
        "available": GEMINI_AVAILABLE,
        "new_api": GENAI_NEW_AVAILABLE,
        "version": genai_version,
        "client_ready": _genai_client is not None,
    }


# ============================================================
# 편의 함수
# ============================================================

def quick_generate(
    prompt: str,
    api_key: str = None,
    model_name: str = "auto"
) -> Optional[str]:
    """
    빠른 텍스트 생성 (일회성)

    Args:
        prompt: 프롬프트
        api_key: API 키 (없으면 환경변수에서)
        model_name: 모델 이름 ("auto"면 자동 선택)

    Returns:
        생성된 텍스트 또는 None
    """
    api_key = api_key or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        logger.error("API 키가 필요합니다.")
        return None

    if not configure_gemini(api_key):
        return None

    model = get_gemini_model(model_name)
    return generate_content(model, prompt)


# ============================================================
# 테스트
# ============================================================

if __name__ == "__main__":
    print("Gemini Compatibility Layer v2.0")
    print("-" * 40)

    info = get_version_info()
    print(f"Available: {info['available']}")
    print(f"New API (google.genai): {info['new_api']}")
    print(f"Using: {info['version']}")
    print(f"Client Ready: {info['client_ready']}")
    print(f"Model Candidates: {GEMINI_MODEL_CANDIDATES}")
