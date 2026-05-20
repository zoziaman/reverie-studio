# -*- coding: utf-8 -*-
"""
콘텐츠 번역기 (Content Translator)

v57.0.0: 시나리오 및 메타데이터 다국어 번역
- Gemini API를 활용한 고품질 번역
- JSON 구조 유지하며 번역
- 비용 무료 (Gemini Free Tier)

Author: Reverie Studio
"""

import json
import logging
import threading
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# 지원 언어 맵핑
LANGUAGE_NAMES = {
    "ko": "Korean",
    "en": "English",
    "ja": "Japanese",
    "zh": "Chinese"
}

# 번역 프롬프트 템플릿
TRANSLATION_PROMPT_TEMPLATE = """You are a professional translator specializing in YouTube video content.
Translate the following {content_type} from {source_lang} to {target_lang}.

IMPORTANT RULES:
1. Maintain the exact same JSON structure
2. Only translate text values, keep all keys unchanged
3. Preserve any special formatting, emojis, or markers
4. Adapt cultural references naturally for the target audience
5. Keep the tone and emotion consistent with the original
6. For horror content, maintain suspense and tension
7. For emotional content, preserve the touching elements

Content to translate:
{content}

Return ONLY the translated JSON, no explanations."""


@dataclass
class TranslationResult:
    """번역 결과"""
    success: bool
    original: Any
    translated: Any
    source_language: str
    target_language: str
    error_message: Optional[str] = None


class ContentTranslator:
    """
    콘텐츠 번역기

    시나리오, 제목, 설명, 태그 등을 다국어로 번역
    Gemini API 활용 (무료)

    v57.0.0: 초기 구현
    """

    _instance: Optional['ContentTranslator'] = None
    _lock = threading.Lock()

    def __new__(cls):
        """싱글톤 패턴"""
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        """초기화"""
        if self._initialized:
            return

        self._initialized = True
        self._api_lock = threading.Lock()
        self._model = None

        # Gemini 모델 초기화
        self._init_gemini()

        logger.info("ContentTranslator 초기화 완료")

    def _init_gemini(self):
        """Gemini 모델 초기화"""
        try:
            from utils.gemini_compat import get_gemini_model
            self._model = get_gemini_model()
            logger.info("Gemini 모델 로드 완료")
        except Exception as e:
            logger.error(f"Gemini 모델 초기화 실패: {e}")
            self._model = None

    def is_available(self) -> bool:
        """번역 기능 사용 가능 여부"""
        return self._model is not None

    def translate_scenario(
        self,
        scenario: Dict[str, Any],
        target_language: str,
        source_language: str = "ko"
    ) -> TranslationResult:
        """
        시나리오 JSON 전체 번역

        Args:
            scenario: 시나리오 딕셔너리 (scenes, dialogues 등)
            target_language: 타겟 언어 코드 (en, ja, zh)
            source_language: 소스 언어 코드 (기본: ko)

        Returns:
            TranslationResult: 번역 결과
        """
        if not self.is_available():
            return TranslationResult(
                success=False,
                original=scenario,
                translated=None,
                source_language=source_language,
                target_language=target_language,
                error_message="Gemini 모델을 사용할 수 없습니다"
            )

        if target_language == source_language:
            # 같은 언어면 번역 불필요
            return TranslationResult(
                success=True,
                original=scenario,
                translated=scenario,
                source_language=source_language,
                target_language=target_language
            )

        try:
            # 번역할 텍스트 필드만 추출
            translatable = self._extract_translatable_fields(scenario)

            # Gemini로 번역
            prompt = TRANSLATION_PROMPT_TEMPLATE.format(
                content_type="video scenario",
                source_lang=LANGUAGE_NAMES.get(source_language, source_language),
                target_lang=LANGUAGE_NAMES.get(target_language, target_language),
                content=json.dumps(translatable, ensure_ascii=False, indent=2)
            )

            with self._api_lock:
                response = self._model.generate_content(prompt)
                translated_text = response.text.strip()

            # JSON 파싱
            # ```json ... ``` 블록 제거
            if translated_text.startswith("```"):
                lines = translated_text.split("\n")
                translated_text = "\n".join(lines[1:-1])

            translated_data = json.loads(translated_text)

            # 원본 구조에 번역 적용
            result_scenario = self._apply_translation(scenario, translated_data)

            logger.info(f"시나리오 번역 완료: {source_language} → {target_language}")

            return TranslationResult(
                success=True,
                original=scenario,
                translated=result_scenario,
                source_language=source_language,
                target_language=target_language
            )

        except json.JSONDecodeError as e:
            logger.error(f"번역 결과 JSON 파싱 실패: {e}")
            return TranslationResult(
                success=False,
                original=scenario,
                translated=None,
                source_language=source_language,
                target_language=target_language,
                error_message=f"JSON 파싱 실패: {e}"
            )
        except Exception as e:
            logger.error(f"시나리오 번역 실패: {e}")
            return TranslationResult(
                success=False,
                original=scenario,
                translated=None,
                source_language=source_language,
                target_language=target_language,
                error_message=str(e)
            )

    def translate_metadata(
        self,
        title: str,
        description: str,
        tags: List[str],
        target_language: str,
        source_language: str = "ko"
    ) -> TranslationResult:
        """
        영상 메타데이터 번역

        Args:
            title: 영상 제목
            description: 영상 설명
            tags: 태그 리스트
            target_language: 타겟 언어 코드
            source_language: 소스 언어 코드

        Returns:
            TranslationResult: 번역 결과
        """
        if not self.is_available():
            return TranslationResult(
                success=False,
                original={"title": title, "description": description, "tags": tags},
                translated=None,
                source_language=source_language,
                target_language=target_language,
                error_message="Gemini 모델을 사용할 수 없습니다"
            )

        if target_language == source_language:
            original = {"title": title, "description": description, "tags": tags}
            return TranslationResult(
                success=True,
                original=original,
                translated=original,
                source_language=source_language,
                target_language=target_language
            )

        try:
            metadata = {
                "title": title,
                "description": description,
                "tags": tags
            }

            prompt = TRANSLATION_PROMPT_TEMPLATE.format(
                content_type="YouTube video metadata",
                source_lang=LANGUAGE_NAMES.get(source_language, source_language),
                target_lang=LANGUAGE_NAMES.get(target_language, target_language),
                content=json.dumps(metadata, ensure_ascii=False, indent=2)
            )

            with self._api_lock:
                response = self._model.generate_content(prompt)
                translated_text = response.text.strip()

            # JSON 파싱
            if translated_text.startswith("```"):
                lines = translated_text.split("\n")
                translated_text = "\n".join(lines[1:-1])

            translated_data = json.loads(translated_text)

            logger.info(f"메타데이터 번역 완료: {source_language} → {target_language}")

            return TranslationResult(
                success=True,
                original=metadata,
                translated=translated_data,
                source_language=source_language,
                target_language=target_language
            )

        except Exception as e:
            logger.error(f"메타데이터 번역 실패: {e}")
            return TranslationResult(
                success=False,
                original={"title": title, "description": description, "tags": tags},
                translated=None,
                source_language=source_language,
                target_language=target_language,
                error_message=str(e)
            )

    def translate_text(
        self,
        text: str,
        target_language: str,
        source_language: str = "ko"
    ) -> str:
        """
        단일 텍스트 번역

        Args:
            text: 번역할 텍스트
            target_language: 타겟 언어 코드
            source_language: 소스 언어 코드

        Returns:
            str: 번역된 텍스트 (실패 시 원본 반환)
        """
        if not self.is_available() or target_language == source_language:
            return text

        try:
            prompt = f"""Translate the following text from {LANGUAGE_NAMES.get(source_language, source_language)} to {LANGUAGE_NAMES.get(target_language, target_language)}.
Return ONLY the translated text, nothing else.

Text: {text}"""

            with self._api_lock:
                response = self._model.generate_content(prompt)
                return response.text.strip()

        except Exception as e:
            logger.error(f"텍스트 번역 실패: {e}")
            return text

    def _extract_translatable_fields(self, scenario: Dict[str, Any]) -> Dict[str, Any]:
        """번역 대상 필드만 추출"""
        result = {}

        # 제목, 설명
        if "title" in scenario:
            result["title"] = scenario["title"]
        if "description" in scenario:
            result["description"] = scenario["description"]

        # 씬별 대사
        if "scenes" in scenario:
            result["scenes"] = []
            for scene in scenario["scenes"]:
                scene_data = {}
                if "narration" in scene:
                    scene_data["narration"] = scene["narration"]
                if "dialogue" in scene:
                    scene_data["dialogue"] = scene["dialogue"]
                if "dialogues" in scene:
                    scene_data["dialogues"] = scene["dialogues"]
                if "text" in scene:
                    scene_data["text"] = scene["text"]
                if scene_data:
                    result["scenes"].append(scene_data)

        # 태그
        if "tags" in scenario:
            result["tags"] = scenario["tags"]

        return result

    def _apply_translation(
        self,
        original: Dict[str, Any],
        translated: Dict[str, Any]
    ) -> Dict[str, Any]:
        """번역된 내용을 원본 구조에 적용"""
        import copy
        result = copy.deepcopy(original)

        # 단순 필드 적용
        for key in ["title", "description", "tags"]:
            if key in translated:
                result[key] = translated[key]

        # 씬 적용
        if "scenes" in translated and "scenes" in result:
            for i, trans_scene in enumerate(translated["scenes"]):
                if i < len(result["scenes"]):
                    for key in ["narration", "dialogue", "dialogues", "text"]:
                        if key in trans_scene:
                            result["scenes"][i][key] = trans_scene[key]

        return result


# ========== 헬퍼 함수 ==========

_translator_instance: Optional[ContentTranslator] = None

def get_translator() -> ContentTranslator:
    """
    ContentTranslator 싱글톤 가져오기

    Returns:
        ContentTranslator: 싱글톤 인스턴스
    """
    global _translator_instance

    if _translator_instance is None:
        _translator_instance = ContentTranslator()

    return _translator_instance
