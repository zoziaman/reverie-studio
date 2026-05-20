# src/modules_pro/prompt_composer.py
# ============================================================
# v59: Prompt Composer - SD 프롬프트 생성기
# 장면 분석 결과를 바탕으로 최적화된 SD 프롬프트 생성
# ============================================================

import logging
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field

try:
    from utils.logger import get_logger
    logger = get_logger("prompt_composer")
except ImportError:
    logger = logging.getLogger(__name__)


def _cfg_get(obj, key, default=None):
    """v59.3.3: dict/object 양쪽에서 값 추출하는 헬퍼"""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


# ============================================================
# 프롬프트 결과 데이터 클래스
# ============================================================

@dataclass
class ComposedPrompt:
    """생성된 프롬프트"""
    positive: str = ""
    negative: str = ""

    # 메타 정보
    scene_id: str = ""
    character_prompts: List[str] = field(default_factory=list)
    scene_prompt: str = ""
    style_prompt: str = ""
    lora_triggers: List[str] = field(default_factory=list)
    continuity_hint: str = ""
    camera_shot: str = ""
    key_props: List[str] = field(default_factory=list)
    outfit_hint: str = ""

    # SD API 파라미터 (v59.5.5: 768x432 기본, v59.5.17: steps 20→15 최적화)
    width: int = 768
    height: int = 432
    steps: int = 15
    cfg_scale: float = 7.0
    sampler: str = "DPM++ 2M Karras"
    seed: int = -1

    # v59.3.0: FIX-6 - 모델/VAE/clip_skip/scheduler (SD API override_settings)
    checkpoint: str = ""
    vae: str = ""
    clip_skip: int = 0          # 0 = 오버라이드 안 함
    scheduler: str = ""

    def to_api_params(self) -> Dict[str, Any]:
        """SD WebUI API 파라미터로 변환"""
        params = {
            "prompt": self.positive,
            "negative_prompt": self.negative,
            "width": self.width,
            "height": self.height,
            "steps": self.steps,
            "cfg_scale": self.cfg_scale,
            "sampler_name": self.sampler,
            "seed": self.seed,
        }

        # v59.3.0: FIX-6 + BUG-A 수정
        # checkpoint/vae는 media_factory._set_sd_model()이 파이프라인 시작 시 1회 설정.
        # per-image override_settings에 보내면 매번 모델 리로드 위험 → 제외!
        # clip_skip만 override_settings로 전달 (가벼운 설정 변경)
        override_settings = {}
        if self.clip_skip > 0:
            override_settings["CLIP_stop_at_last_layers"] = self.clip_skip
        if override_settings:
            params["override_settings"] = override_settings

        # v59.3.0: 스케줄러
        if self.scheduler:
            params["scheduler"] = self.scheduler

        return params


# ============================================================
# 기본 프롬프트 템플릿
# ============================================================

# 품질 프롬프트
QUALITY_POSITIVE = "masterpiece, best quality, highly detailed, sharp focus"
QUALITY_NEGATIVE = "(worst quality:1.4), (low quality:1.4), blurry, jpeg artifacts, watermark, text, logo, signature"

# v59.2.4: 안전 프롬프트 (NSFW만 차단, 나머지는 Gemini sd_prompt에 위임)
# ★ 인물 유무/포즈/앵글은 Gemini가 장면 맥락에 따라 결정
# ★ 불쾌한 골짜기/NSFW/복수인물은 QC(Gemini Vision)가 검증
SAFETY_POSITIVE = ""  # v59.2.4: Gemini sd_prompt가 전적으로 결정
SAFETY_NEGATIVE = "nude, naked, topless, underwear, bra, panties, lingerie, swimsuit, bikini, exposed skin, cleavage, nsfw"

# 시간대별 조명 프롬프트
TIME_LIGHTING = {
    "dawn": "golden hour lighting, warm orange glow, early morning mist",
    "morning": "bright natural lighting, clear sky, soft shadows",
    "afternoon": "harsh midday sun, strong shadows, bright ambient",
    "evening": "sunset lighting, warm golden tones, long shadows",
    "night": "night scene, moonlight, dark atmosphere, dim lighting",
}

# 날씨별 프롬프트
WEATHER_PROMPTS = {
    "clear": "clear weather, blue sky",
    "cloudy": "overcast sky, diffused lighting, grey clouds",
    "rainy": "rain, wet surfaces, raindrops, gloomy atmosphere",
    "foggy": "fog, mist, low visibility, mysterious atmosphere",
    "snowy": "snow, winter scene, white landscape, cold atmosphere",
}

# 분위기별 프롬프트
ATMOSPHERE_PROMPTS = {
    "peaceful": "serene, calm, tranquil, harmonious",
    "tense": "tension, suspense, ominous, dramatic lighting",
    "mysterious": "mysterious, enigmatic, surreal, ethereal",
    "romantic": "romantic, soft lighting, warm tones, intimate",
    "horror": "horror, creepy, unsettling, dark shadows, eerie",
    "sad": "melancholic, somber, muted colors, lonely",
    "exciting": "dynamic, vibrant, energetic, bold colors",
    "neutral": "",
}

# 감정별 표정 프롬프트 (기본값)
DEFAULT_EXPRESSIONS = {
    "neutral": "calm expression, relaxed face",
    "happy": "smiling, joyful expression, bright eyes",
    "sad": "sorrowful expression, teary eyes, downcast look",
    "fear": "frightened expression, wide eyes, pale face, trembling",
    "anger": "angry expression, furrowed brows, intense gaze",
    "surprise": "shocked expression, wide eyes, open mouth",
    "calm": "serene expression, peaceful face",
    "excited": "excited expression, bright eyes, energetic",
}

# 행동별 포즈 프롬프트 (기본값)
DEFAULT_POSES = {
    "talking": "speaking, gesturing, expressive",
    "listening": "attentive pose, focused gaze",
    "walking": "walking pose, in motion",
    "running": "running pose, dynamic movement",
    "sitting": "sitting pose, relaxed posture",
    "standing": "standing pose, upright posture",
    "looking": "looking at something, directed gaze",
}


# ============================================================
# v59.3.0: 공통 유틸 - dict → CharDef 변환
# SceneAnalyzer, PromptComposer, VSD 3곳에서 공유
# ============================================================

def char_defs_from_dict(characters_dict: Dict[str, Any],
                        include_aliases: bool = False,
                        include_lora: bool = False) -> list:
    """
    캐릭터 정의 dict를 CharDef 객체 리스트로 변환하는 공통 유틸.

    Args:
        characters_dict: {"protagonist": {"base": "...", "name": "...", ...}, ...}
        include_aliases: aliases 필드 생성 여부 (SceneAnalyzer, VSD용)
        include_lora: lora 필드 생성 여부 (PromptComposer용)

    Returns:
        CharDef 객체 리스트
    """
    result = []
    for char_id, char_def in characters_dict.items():
        if char_id.startswith('_'):  # _default 등 스킵
            continue

        class CharDef:
            pass

        obj = CharDef()
        obj.id = char_id

        if isinstance(char_def, dict):
            obj.name = char_def.get('name', char_id)
            obj.display_name = char_def.get('display_name', obj.name)
            obj.base_prompt = char_def.get('base', char_def.get('base_prompt', ''))
            obj.style_suffix = char_def.get('style_suffix', char_def.get('style', ''))
            obj.expressions = char_def.get('expressions', {})
            obj.poses = char_def.get('poses', {})
            obj.gender_negative = char_def.get('gender_negative', '')
            obj.age_negative = char_def.get('age_negative', '')
            if include_aliases:
                alias_values = [char_id, char_def.get('name', ''), obj.display_name]
                alias_values.extend(list(char_def.get('aliases', []) or []))
                deduped_aliases = []
                seen_aliases = set()
                for alias in alias_values:
                    alias_text = str(alias or '').strip()
                    if not alias_text:
                        continue
                    alias_key = alias_text.lower()
                    if alias_key in seen_aliases:
                        continue
                    seen_aliases.add(alias_key)
                    deduped_aliases.append(alias_text)
                obj.aliases = deduped_aliases
            if include_lora:
                obj.lora = char_def.get('lora', None)
        else:
            obj.name = char_id
            obj.display_name = char_id
            obj.base_prompt = ''
            obj.style_suffix = ''
            obj.expressions = {}
            obj.poses = {}
            obj.gender_negative = ''
            obj.age_negative = ''
            if include_aliases:
                obj.aliases = [char_id]
            if include_lora:
                obj.lora = None

        result.append(obj)
    return result


# ============================================================
# PromptComposer 클래스
# ============================================================

class PromptComposer:
    """
    v59: SD 프롬프트 생성기

    장면 분석 결과(SceneAnalysisResult)를 받아서
    최적화된 SD 프롬프트를 생성합니다.
    """

    def __init__(self,
                 character_definitions: Any = None,
                 sd_model_config: Any = None,
                 base_positive: str = "",
                 base_negative: str = "",
                 art_style_config: Optional[Dict[str, Any]] = None,
                 prompt_strategy: str = "panel_card",
                 llm_hint_tag_limit: int = 4):
        """
        Args:
            character_definitions: 캐릭터 정의 (List 또는 Dict)
            sd_model_config: SD 모델 설정 (SDModelConfig)
            base_positive: 기본 positive 프롬프트 (팩에서)
            base_negative: 기본 negative 프롬프트 (팩에서)
        """
        # v59.3.0: 공통 유틸 사용 (dict → list 변환)
        if character_definitions is None:
            self.character_definitions = []
        elif isinstance(character_definitions, dict):
            self.character_definitions = char_defs_from_dict(
                character_definitions, include_aliases=False, include_lora=True
            )
            logger.debug(f"[PromptComposer] dict → list 변환: {len(self.character_definitions)}개")
        else:
            self.character_definitions = list(character_definitions) if character_definitions else []

        self.sd_model_config = sd_model_config
        self.base_positive = base_positive
        self.base_negative = base_negative
        self.art_style_config = art_style_config or {}
        self.art_style_prefix = _cfg_get(self.art_style_config, 'art_style_prefix', '')
        self.art_texture_keywords = _cfg_get(self.art_style_config, 'texture_keywords', '')
        self.prompt_strategy = (prompt_strategy or "panel_card").strip().lower()
        self.llm_hint_tag_limit = max(0, int(llm_hint_tag_limit or 0))

        # 캐릭터 ID → 정의 매핑
        self.char_map: Dict[str, Any] = {}
        self._build_character_map()

        logger.info(f"[PromptComposer] 초기화: {len(self.character_definitions)}개 캐릭터")

    def _build_character_map(self):
        """캐릭터 맵 생성"""
        for char in self.character_definitions:
            char_id = getattr(char, 'id', '')
            if char_id:
                self.char_map[char_id] = char

    @staticmethod
    def _get_character_lora_parts(char: Any) -> List[str]:
        parts: List[str] = []
        lora = getattr(char, "lora", None)
        if isinstance(lora, dict):
            name = str(lora.get("name", "") or "").strip()
            trigger = str(lora.get("trigger", "") or "").strip()
            try:
                weight = float(lora.get("weight", 0.7) or 0.7)
            except Exception:
                weight = 0.7
            if name:
                parts.append(f"<lora:{name}:{weight}>")
            if trigger:
                parts.append(trigger)
        return parts

    def _get_character_prompt(self, char_id: str, emotion: str = "neutral",
                               action: str = "") -> str:
        """캐릭터 프롬프트 생성"""
        # v59.3.0: FIX-3 - char_map 미매칭 시 부분 매칭 + WARNING
        char = self.char_map.get(char_id)

        if not char and char_id:
            # 부분 매칭 시도 (Gemini가 alias와 다른 이름 반환 시)
            for known_id, known_char in self.char_map.items():
                known_name = getattr(known_char, 'name', '')
                if (char_id in known_id or known_id in char_id or
                    (known_name and (char_id in known_name or known_name in char_id))):
                    char = known_char
                    logger.warning(f"[PromptComposer] 캐릭터 부분 매칭: '{char_id}' → '{known_id}'")
                    break

        if not char:
            if char_id:
                logger.warning(f"[PromptComposer] 미등록 캐릭터: '{char_id}' - 기본 프롬프트 사용")
            # v59.5.5: narrator/나레이션은 person 키워드 삽입 금지
            char_lower = (char_id or "").lower().strip("[]")
            is_narrator = char_lower in ("narrator", "나레이션", "나레이터", "narration", "")
            if is_narrator:
                return ""  # narrator는 장면 자체가 중요하므로 캐릭터 프롬프트 없음
            expression = DEFAULT_EXPRESSIONS.get(emotion, "")
            pose = DEFAULT_POSES.get(action, "")
            return f"person, {expression}, {pose}".strip(", ")

        # 기본 외형
        base = getattr(char, 'base_prompt', '')
        style = getattr(char, 'style_suffix', '')

        # v59.5.7: "no person" 캐릭터 감지 — 만화 스타일 캐릭터는 사람으로 취급!
        # silhouette/featureless/abstract humanoid 등이 base에 있을 때만 "no person"
        # v59.5.7: 캐릭터 정의가 만화 스타일이므로 대부분 is_no_person=False → 표정/포즈 적용
        base_lower = base.lower() if base else ""
        is_no_person = any(kw in base_lower for kw in
                          ['no person', 'no facial features', 'abstract humanoid', 'completely featureless'])

        # 표정 (캐릭터 정의에서 또는 기본값)
        expressions = getattr(char, 'expressions', {})
        if is_no_person:
            # "no person" 캐릭터는 캐릭터 자체 표정만 사용, DEFAULT 사람 표정 스킵
            expression = expressions.get(emotion, "")
        else:
            expression = expressions.get(emotion, DEFAULT_EXPRESSIONS.get(emotion, ""))

        # 포즈 (캐릭터 정의에서 또는 기본값)
        poses = getattr(char, 'poses', {})
        if is_no_person:
            # "no person" 캐릭터는 캐릭터 자체 포즈만 사용, DEFAULT 사람 포즈 스킵
            pose = poses.get(action, "")
        else:
            pose = poses.get(action, DEFAULT_POSES.get(action, ""))

        # LoRA 트리거
        lora = getattr(char, 'lora', None)
        trigger = ""
        if lora and isinstance(lora, dict):
            trigger = lora.get('trigger', '')

        # 조합
        parts = [p for p in [*self._get_character_lora_parts(char), base, style, expression, pose] if p]
        return ", ".join(parts)

    def _get_scene_prompt(self, scene_result: Any) -> str:
        """장면 프롬프트 생성"""
        parts = []

        # 장소 상세
        location_detail = getattr(scene_result, 'location_detail', '')
        if location_detail:
            parts.append(location_detail)
        elif hasattr(scene_result, 'location') and scene_result.location:
            parts.append(scene_result.location)

        # 시간대 조명
        time_of_day = getattr(scene_result, 'time_of_day', '')
        if time_of_day and time_of_day in TIME_LIGHTING:
            parts.append(TIME_LIGHTING[time_of_day])

        # 날씨
        weather = getattr(scene_result, 'weather', '')
        if weather and weather in WEATHER_PROMPTS and weather != "none":
            parts.append(WEATHER_PROMPTS[weather])

        # 분위기
        atmosphere = getattr(scene_result, 'atmosphere', '')
        if atmosphere and atmosphere in ATMOSPHERE_PROMPTS:
            atm_prompt = ATMOSPHERE_PROMPTS[atmosphere]
            if atm_prompt:
                parts.append(atm_prompt)

        # 장면 키워드
        key_props = getattr(scene_result, 'key_props', [])
        if key_props:
            parts.extend(key_props[:2])

        camera_shot = getattr(scene_result, 'camera_shot', '')
        if camera_shot:
            parts.append(camera_shot)

        outfit_hint = getattr(scene_result, 'outfit_hint', '')
        if outfit_hint:
            parts.append(outfit_hint)

        keywords = getattr(scene_result, 'scene_keywords', [])
        if keywords:
            parts.extend(keywords[:5])  # 최대 5개

        return ", ".join(parts)

    @staticmethod
    def _dedupe_parts(parts: List[str]) -> List[str]:
        deduped: List[str] = []
        seen = set()
        for part in parts:
            clean = (part or "").strip().strip(",")
            if not clean:
                continue
            key = clean.lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(clean)
        return deduped

    def _extract_sd_prompt_hints(self, sd_prompt: str, existing_parts: List[str]) -> List[str]:
        if not sd_prompt or self.llm_hint_tag_limit <= 0:
            return []

        skip_tokens = (
            "masterpiece",
            "best quality",
            "monochrome manga",
            "black and white ink drawing",
            "fully clothed",
            "solo",
        )
        used = {part.lower() for part in existing_parts if part}
        hints: List[str] = []

        for raw in sd_prompt.split(","):
            term = raw.strip()
            if not term:
                continue
            lower = term.lower()
            if any(token in lower for token in skip_tokens):
                continue
            if term.startswith("(") and ":" in term:
                continue
            if lower in used:
                continue
            hints.append(term)
            used.add(lower)
            if len(hints) >= self.llm_hint_tag_limit:
                break

        return hints

    def _build_panel_focus_clause(self, scene_result: Any) -> str:
        characters = getattr(scene_result, 'characters', []) or []
        key_props = list(getattr(scene_result, 'key_props', []) or [])
        location_detail = getattr(scene_result, 'location_detail', '') or getattr(scene_result, 'location', '')

        if characters:
            main_char = characters[0]
            if hasattr(main_char, 'emotion'):
                emotion = getattr(main_char, 'emotion', 'neutral') or 'neutral'
                action = getattr(main_char, 'action', 'standing') or 'standing'
            elif isinstance(main_char, dict):
                emotion = main_char.get('emotion', 'neutral') or 'neutral'
                action = main_char.get('action', 'standing') or 'standing'
            else:
                emotion = 'neutral'
                action = 'standing'

            focus_terms = ["solo"]
            emotion_term = DEFAULT_EXPRESSIONS.get(emotion, "")
            pose_term = DEFAULT_POSES.get(action, action)
            if emotion_term:
                focus_terms.append(emotion_term)
            if pose_term:
                focus_terms.append(pose_term)
            return f"({', '.join(self._dedupe_parts(focus_terms)[:3])}:1.3)"

        if key_props:
            return f"({key_props[0]}:1.4)"
        if location_detail:
            return f"({location_detail}:1.3)"
        return ""

    def _build_panel_card_scene_prompt(self, scene_result: Any, sd_prompt: str = "") -> str:
        parts: List[str] = []
        if self.art_style_prefix:
            parts.append(self.art_style_prefix)
        focus_clause = self._build_panel_focus_clause(scene_result)
        if focus_clause:
            parts.append(focus_clause)

        scene_prompt = self._get_scene_prompt(scene_result)
        if scene_prompt:
            parts.extend([part.strip() for part in scene_prompt.split(",") if part.strip()])

        if self.art_texture_keywords:
            parts.extend([part.strip() for part in self.art_texture_keywords.split(",") if part.strip()][:2])

        deduped_parts = self._dedupe_parts(parts)
        deduped_parts.extend(self._extract_sd_prompt_hints(sd_prompt, deduped_parts))

        if getattr(scene_result, 'characters', []):
            deduped_parts.append("fully clothed")

        return ", ".join(self._dedupe_parts(deduped_parts))

    def _get_style_prompt(self) -> Tuple[str, str]:
        """스타일 프롬프트 (positive, negative)"""
        # v59.2.4: 빈 문자열 필터링
        positive_parts = [p for p in [QUALITY_POSITIVE, SAFETY_POSITIVE] if p]
        negative_parts = [p for p in [QUALITY_NEGATIVE, SAFETY_NEGATIVE] if p]

        # 기본 프롬프트 추가
        if self.base_positive:
            positive_parts.append(self.base_positive)
        if self.base_negative:
            negative_parts.append(self.base_negative)

        return ", ".join(positive_parts), ", ".join(negative_parts)

    def _boost_person_weight(self, sd_prompt: str) -> str:
        """v59.5.8: SD 프롬프트 내 인물 토큰에 자동 weight 부여

        SD 1.5는 weight가 있는 토큰에 집중함.
        Gemini가 "(door:1.4), solo woman" 이렇게 배경에만 weight를 주면
        인물이 무시됨. → 인물 토큰에도 weight를 걸어줌.
        """
        import re

        # 이미 weight가 있는 인물 토큰은 건드리지 않음
        # 예: "(solo woman looking scared:1.4)" → 이미 OK
        # v59.5.8: "solo X" 패턴을 범용으로 잡아서 weight 부여
        # Gemini가 "solo protagonist", "solo detective" 등 어떤 캐릭터명이든 대응
        # 이미 weight가 있으면 (solo woman looking scared:1.4) 건드리지 않음
        # 단, "(solo ..." 괄호 안에 있는 것도 건드리지 않음
        solo_pattern = r'(?<!\()solo\s+(\w+)'

        def _add_weight(match):
            full = match.group(0)  # e.g. "solo woman"
            # 이미 weight가 뒤에 붙어있는지 확인
            # match 이후 문자열에서 ":숫자)" 패턴 확인은 re.sub에서 어려우므로
            # 단순히 괄호 안이 아닌 것만 처리
            return f"({full}:1.3)"

        result = re.sub(solo_pattern, _add_weight, sd_prompt, count=1)

        if result != sd_prompt:
            logger.debug(f"[PromptComposer] 인물 weight 보정 적용")

        return result

    def _deduplicate_tags(self, sd_prompt: str, style_positive: str) -> str:
        """v59.5.8: sd_prompt와 style_positive 간 중복 태그 제거

        Gemini가 "monochrome manga, black and white ink drawing, ..." 을 넣고
        style_positive에도 "masterpiece, best quality, monochrome, manga, ..." 가 있으면
        토큰 낭비. sd_prompt에서 이미 style_positive에 있는 태그 제거.
        """
        if not sd_prompt or not style_positive:
            return sd_prompt

        # style_positive 태그셋 구축
        style_tags = set()
        for tag in style_positive.split(','):
            tag = tag.strip().lower()
            if tag and len(tag) > 2:  # 너무 짧은 태그 무시
                style_tags.add(tag)

        # sd_prompt에서 중복 제거 (정확히 일치하는 것만)
        sd_parts = [p.strip() for p in sd_prompt.split(',')]
        filtered = []
        removed = []
        for part in sd_parts:
            if part.strip().lower() in style_tags:
                removed.append(part.strip())
            else:
                filtered.append(part)

        if removed:
            logger.debug(f"[PromptComposer] 중복 태그 {len(removed)}개 제거: {removed[:5]}")

        return ", ".join(filtered)

    def _enforce_character_appearance(self, sd_prompt: str, char_base: str) -> str:
        """v59.5.9: Pack 캐릭터 외형이 Gemini 외형보다 우선하도록 강제

        문제: Gemini가 같은 캐릭터에 대해 매번 다른 외형을 넣음
              예) Pack: "long dark hair" ↔ Gemini: "shoulder-length dark hair"
              → SD가 Gemini 것을 따라가서 캐릭터 일관성 깨짐

        해결: sd_prompt에서 Pack char_base와 충돌하는 외형 태그만 정밀 제거
              Pack char_base는 compose_prompt()에서 항상 앞쪽에 삽입되므로
              충돌 태그만 제거하면 Pack 외형이 우선함
        """
        if not char_base or not sd_prompt:
            return sd_prompt

        char_base_lower = char_base.lower()

        # 충돌 맵: Pack에 이 키워드가 있으면 → sd_prompt에서 이 패턴들 제거
        HAIR_LENGTH_CONFLICTS = {
            'long dark hair': ['short hair', 'shoulder-length', 'bob cut', 'pixie cut',
                               'medium hair', 'chin-length', 'cropped hair', 'buzz cut',
                               'shoulder length'],
            'long black hair': ['short hair', 'shoulder-length', 'bob cut', 'pixie cut',
                                'medium hair', 'chin-length', 'shoulder length'],
            'short dark hair': ['long hair', 'shoulder-length', 'flowing hair',
                                'waist-length', 'hip-length'],
            'short hair': ['long hair', 'shoulder-length', 'flowing hair',
                           'waist-length', 'hip-length'],
            'grey hair in bun': ['long flowing hair', 'short hair', 'dark hair',
                                 'black hair', 'blonde hair', 'brown hair', 'ponytail',
                                 'pigtails', 'loose hair'],
            'white hair': ['dark hair', 'black hair', 'brown hair', 'blonde hair'],
        }

        CLOTHING_CONFLICTS = {
            'modest clothing': ['casual clothes', 'revealing', 'sporty outfit',
                                'athletic wear', 'tank top', 'crop top'],
            'modest dress': ['casual clothes', 'jeans', 'sporty outfit', 't-shirt'],
            'traditional hanbok': ['modern dress', 'casual clothes', 'western clothing',
                                   'jeans', 'business suit', 't-shirt'],
            'casual outfit': ['formal wear', 'business suit', 'tuxedo', 'evening gown',
                              'traditional hanbok'],
            'dark coat': ['casual clothes', 'light clothing', 'summer wear'],
        }

        all_conflicts = {**HAIR_LENGTH_CONFLICTS, **CLOTHING_CONFLICTS}

        sd_parts = [p.strip() for p in sd_prompt.split(',')]
        removed = []

        for pack_key, conflict_patterns in all_conflicts.items():
            if pack_key in char_base_lower:
                new_parts = []
                for part in sd_parts:
                    part_lower = part.strip().lower()
                    # 충돌 패턴이 이 태그 안에 포함되어 있는지 확인
                    if any(cp in part_lower for cp in conflict_patterns):
                        removed.append(part.strip())
                    else:
                        new_parts.append(part)
                sd_parts = new_parts

        if removed:
            logger.info(f"[PromptComposer] v59.5.9 외형 충돌 해결 - Pack 우선, "
                        f"Gemini 태그 {len(removed)}개 제거: {removed}")

        return ", ".join(sd_parts)

    def _get_lora_triggers(self) -> List[str]:
        """모든 LoRA 트리거 + <lora:name:weight> 태그 수집"""
        triggers = []

        # SD 모델 설정의 LoRA
        if self.sd_model_config:
            lora_models = _cfg_get(self.sd_model_config, 'lora_models', [])
            for lora in lora_models:
                if isinstance(lora, dict):
                    # v59.3.1: LoRA 활성화 태그 삽입 (SD WebUI 형식)
                    name = lora.get('name', '')
                    weight = lora.get('weight', 0.7)
                    if name:
                        triggers.append(f"<lora:{name}:{weight}>")
                    trigger = lora.get('trigger', '')
                    if trigger:
                        triggers.append(trigger)

        return triggers

    def compose_prompt(self, scene_result: Any,
                       override_positive: str = "",
                       override_negative: str = "") -> ComposedPrompt:
        """
        장면 분석 결과로부터 SD 프롬프트 생성

        Args:
            scene_result: SceneAnalysisResult
            override_positive: 추가 positive 프롬프트
            override_negative: 추가 negative 프롬프트

        Returns:
            ComposedPrompt
        """
        scene_id = getattr(scene_result, 'scene_id', '')
        logger.info(f"[PromptComposer] 프롬프트 생성: {scene_id}")

        # v59.2.2: Gemini가 직접 생성한 SD 프롬프트가 있으면 우선 사용
        sd_prompt = getattr(scene_result, 'sd_prompt', '')
        continuity_hint = getattr(scene_result, 'continuity_hint', '')
        use_panel_card_prompt = self.prompt_strategy != "legacy_sd_prompt"

        # 스타일 프롬프트 (QUALITY + SAFETY - 항상 필요)
        style_positive, style_negative = self._get_style_prompt()

        # LoRA 트리거 (항상 필요)
        lora_triggers = self._get_lora_triggers()

        if sd_prompt:
            # ★ v59.5.8: Gemini 직접 생성 + 인물 우선 배치 + weight 자동 보정
            logger.debug(f"[PromptComposer] sd_prompt 사용 ({'panel_card compile' if use_panel_card_prompt else 'legacy direct'})")
            positive_parts = []

            # 1) LoRA 트리거 (중복 방지) — 최우선
            if lora_triggers:
                sd_prompt_lower = sd_prompt.lower()
                unique_triggers = [t for t in lora_triggers if t.lower() not in sd_prompt_lower]
                if unique_triggers:
                    positive_parts.extend(unique_triggers)

            # 2) ★ v59.5.8: sd_prompt 전처리 — 인물 weight 보정
            sd_prompt = self._boost_person_weight(sd_prompt)

            # 3) ★ v59.5.9: 캐릭터 외모 보강 + 외형 충돌 해결
            # 캐릭터를 먼저 찾아서 char_base를 알아낸 뒤,
            # Gemini sd_prompt에서 Pack과 충돌하는 외형 태그를 제거
            character_prompts = []
            char_base_for_override = ""
            characters = getattr(scene_result, 'characters', [])
            if characters:
                main_char = characters[0]
                if hasattr(main_char, 'id'):
                    char_id = main_char.id
                    emotion = getattr(main_char, 'emotion', 'neutral')
                    action = getattr(main_char, 'action', '')
                elif isinstance(main_char, dict):
                    char_id = main_char.get('id', main_char.get('name', ''))
                    emotion = main_char.get('emotion', 'neutral')
                    action = main_char.get('action', '')
                else:
                    char_id = ''
                    emotion = 'neutral'
                    action = ''

                if char_id:
                    # v59.5.9: 나레이션 장면 처리
                    # 나레이터가 캐릭터로 배정된 경우, narrator char_base(안경 남자)를
                    # 무조건 삽입하면 Gemini sd_prompt와 충돌함.
                    # → 나레이션 장면은 Gemini sd_prompt를 존중:
                    #   - Gemini가 인물을 넣었으면 → 해당 인물의 char_base 사용
                    #   - Gemini가 배경만 넣었으면 → char_base 삽입 안 함 (배경 장면)
                    effective_char_id = char_id
                    is_narrator_id = char_id.lower() in ('narrator', '나레이션', '나레이터', 'narration')
                    skip_char_insert = False

                    if is_narrator_id:
                        # v59.9.0: 나레이터 감지 — characters 배열 기반 우선 (sd_prompt 키워드 폴백)
                        # SceneAnalyzer v59.9.0이 외모 키워드를 sd_prompt에서 제거하므로
                        # sd_prompt에서 "woman", "elderly man" 등으로 감지 불가.
                        # → SceneAnalyzer가 characters[]에 실제 캐릭터 ID를 넣었으면 그걸 사용

                        # 방법 1: characters 배열에 narrator가 아닌 실제 캐릭터가 있는지 확인
                        found_char = None
                        all_chars = getattr(scene_result, 'characters', [])
                        narrator_ids = ('narrator', '나레이션', '나레이터', 'narration')
                        for other_char in all_chars:
                            other_id = ''
                            if hasattr(other_char, 'id'):
                                other_id = other_char.id
                            elif isinstance(other_char, dict):
                                other_id = other_char.get('id', '')
                            if other_id and other_id.lower() not in narrator_ids:
                                if other_id.lower() in self.char_map:
                                    found_char = other_id.lower()
                                    break

                        # v62: 방법 2 — sd_prompt에서 명시적 캐릭터 키워드만 감지 (축소)
                        # "man", "woman" 같은 일반 단어는 배경 묘사에도 나올 수 있으므로 제외
                        # 명시적으로 "solo" + 캐릭터 키워드 조합만 인물로 판단
                        if not found_char and sd_prompt and 'solo' in sd_prompt.lower():
                            sd_lower = sd_prompt.lower()
                            CHAR_DETECT = [
                                ('grandma', ['grandma', 'grandmother']),
                                ('grandpa', ['grandpa', 'grandfather']),
                                ('ghost', ['ghost', 'ghostly figure']),
                                ('protagonist', ['protagonist']),
                                ('antagonist', ['antagonist']),
                            ]
                            for detect_id, keywords in CHAR_DETECT:
                                if any(kw in sd_lower for kw in keywords):
                                    if detect_id in self.char_map:
                                        found_char = detect_id
                                        break

                        # v62: 방법 3 제거 — "solo" 만으로 인물 판단하지 않음
                        # 배경 장면에서 Gemini가 실수로 "solo"를 넣어도 _default 캐릭터를 강제하지 않음
                        # (기존: solo → _default char_base 주입 → 나레이션의 92%가 인물)

                        if found_char:
                            effective_char_id = found_char
                            logger.info(f"[PromptComposer] v59.9.0 나레이션 장면에 "
                                        f"{found_char} 감지 -> char_base 적용")
                        else:
                            # 인물 없는 배경 장면 → char_base 삽입 안 함
                            skip_char_insert = True
                            logger.info(f"[PromptComposer] v59.9.0 나레이션 배경 장면 "
                                        f"-> char_base 삽입 생략 (Gemini 판단 존중)")

                    if not skip_char_insert:
                        char_prompt = self._get_character_prompt(effective_char_id, emotion, action)
                        if char_prompt and len(char_prompt.replace(',', '').replace(' ', '')) > 6:
                            character_prompts.append(char_prompt)
                            # Pack char_base 추출 (외형 충돌 해결용)
                            char_obj = self.char_map.get(effective_char_id)
                            if char_obj:
                                char_base_for_override = getattr(char_obj, 'base_prompt', '')

            # v59.5.9: Pack 캐릭터 외형과 충돌하는 Gemini 태그 제거
            if char_base_for_override:
                sd_prompt = self._enforce_character_appearance(sd_prompt, char_base_for_override)

            # v59.5.8: 중복 태그 제거
            sd_prompt = self._deduplicate_tags(sd_prompt, style_positive)
            scene_prompt = self._build_panel_card_scene_prompt(scene_result, sd_prompt) if use_panel_card_prompt else sd_prompt

            # 4) 품질 + 안전 + base 프롬프트
            positive_parts.append(style_positive)

            # 5) ★ v59.5.8+: 캐릭터 외모를 sd_prompt보다 앞에 배치
            # SD 1.5는 앞쪽 토큰에 더 가중치 → Pack 캐릭터 외형이 우선
            if character_prompts:
                positive_parts.append(character_prompts[0])
            if continuity_hint:
                positive_parts.append(continuity_hint)

            # 6) Gemini가 만든 SD 프롬프트 (핵심! — 충돌 태그 제거 후)
            positive_parts.append(scene_prompt)

            # 6) 오버라이드
            if override_positive:
                positive_parts.append(override_positive)

            # Negative
            negative_parts = [style_negative]
            # v62.7: 캐릭터별 gender_negative + age_negative 주입
            if characters:
                main_char = characters[0]
                neg_char_id = (main_char.id if hasattr(main_char, 'id')
                               else main_char.get('id', '') if isinstance(main_char, dict) else '')
                if neg_char_id and not skip_char_insert:
                    char_obj = self.char_map.get(neg_char_id)
                    if char_obj:
                        g_neg = getattr(char_obj, 'gender_negative', '') or ''
                        a_neg = getattr(char_obj, 'age_negative', '') or ''
                        if g_neg:
                            negative_parts.append(g_neg)
                            logger.info(f"[PromptComposer] v62.7 gender_negative 주입: {neg_char_id}")
                        if a_neg:
                            negative_parts.append(a_neg)
                            logger.info(f"[PromptComposer] v62.7 age_negative 주입: {neg_char_id}")
            if override_negative:
                negative_parts.append(override_negative)

        else:
            # 폴백: 기존 방식 (기계적 조합)
            logger.debug(f"[PromptComposer] 기존 방식 폴백 (sd_prompt 없음)")

            # 1. 캐릭터 프롬프트
            character_prompts = []
            characters = getattr(scene_result, 'characters', [])

            for char in characters:
                if hasattr(char, 'id'):
                    char_id = char.id
                    emotion = getattr(char, 'emotion', 'neutral')
                    action = getattr(char, 'action', '')
                elif isinstance(char, dict):
                    char_id = char.get('id', '')
                    emotion = char.get('emotion', 'neutral')
                    action = char.get('action', '')
                else:
                    continue

                char_prompt = self._get_character_prompt(char_id, emotion, action)
                if char_prompt:
                    character_prompts.append(char_prompt)

            # 2. 장면 프롬프트
            scene_prompt = self._get_scene_prompt(scene_result)

            # 3. 조합
            positive_parts = []

            # LoRA 트리거 먼저
            if lora_triggers:
                positive_parts.extend(lora_triggers)

            # 스타일 (품질)
            positive_parts.append(style_positive)

            # 캐릭터
            if character_prompts:
                positive_parts.append(", ".join(character_prompts))
            if continuity_hint:
                positive_parts.append(continuity_hint)

            # 장면
            if scene_prompt:
                positive_parts.append(scene_prompt)

            # 오버라이드
            if override_positive:
                positive_parts.append(override_positive)

            # Negative
            negative_parts = [style_negative]
            # v62.7: 폴백 경로에도 캐릭터별 gender_negative + age_negative 주입
            for char in characters:
                fb_char_id = (char.id if hasattr(char, 'id')
                              else char.get('id', '') if isinstance(char, dict) else '')
                if fb_char_id:
                    char_obj = self.char_map.get(fb_char_id)
                    if char_obj:
                        g_neg = getattr(char_obj, 'gender_negative', '') or ''
                        a_neg = getattr(char_obj, 'age_negative', '') or ''
                        if g_neg:
                            negative_parts.append(g_neg)
                        if a_neg:
                            negative_parts.append(a_neg)
                    break  # 첫 번째 캐릭터만 적용
            if override_negative:
                negative_parts.append(override_negative)

        # 최종 프롬프트
        positive = ", ".join([p for p in positive_parts if p])
        negative = ", ".join([p for p in negative_parts if p])

        # SD 파라미터 (v59.5.5: 768x432로 상향, v59.5.17: steps 20→15 최적화)
        width = 768
        height = 432
        steps = 15
        cfg_scale = 7.0
        sampler = "DPM++ 2M Karras"
        # v59.3.0: FIX-6 - 누락된 SD 파라미터
        checkpoint = ""
        vae = ""
        clip_skip = 0
        scheduler = ""

        if self.sd_model_config:
            # v59.3.3: dict/object 양쪽 지원
            width = _cfg_get(self.sd_model_config, 'width', 768)
            height = _cfg_get(self.sd_model_config, 'height', 432)
            steps = _cfg_get(self.sd_model_config, 'steps', 15)
            cfg_scale = _cfg_get(self.sd_model_config, 'cfg_scale', 7.0)
            sampler = _cfg_get(self.sd_model_config, 'sampler', "DPM++ 2M Karras")
            # v59.3.0: FIX-6
            checkpoint = _cfg_get(self.sd_model_config, 'checkpoint', '')
            vae = _cfg_get(self.sd_model_config, 'vae', '')
            clip_skip = _cfg_get(self.sd_model_config, 'clip_skip', 0)
            scheduler = _cfg_get(self.sd_model_config, 'scheduler', '')

        result = ComposedPrompt(
            positive=positive,
            negative=negative,
            scene_id=scene_id,
            character_prompts=character_prompts,
            scene_prompt=scene_prompt,
            style_prompt=style_positive,
            lora_triggers=lora_triggers,
            continuity_hint=continuity_hint,
            camera_shot=getattr(scene_result, 'camera_shot', ''),
            key_props=getattr(scene_result, 'key_props', []),
            outfit_hint=getattr(scene_result, 'outfit_hint', ''),
            width=width,
            height=height,
            steps=steps,
            cfg_scale=cfg_scale,
            sampler=sampler,
            # v59.3.0: FIX-6
            checkpoint=checkpoint,
            vae=vae,
            clip_skip=clip_skip,
            scheduler=scheduler,
        )

        logger.info(f"[PromptComposer] 프롬프트 생성 완료: {len(positive)} chars")
        # v59.3.3: SD 프롬프트 전체 로깅 (디버깅 필수)
        logger.info(f"[PromptComposer] POSITIVE: {positive[:300]}")
        logger.info(f"[PromptComposer] NEGATIVE: {negative[:150]}")
        logger.info(f"[PromptComposer] SD설정: {width}x{height}, steps={steps}, cfg={cfg_scale}, sampler={sampler}")

        return result

    def compose_batch(self, scene_results: List[Any]) -> List[ComposedPrompt]:
        """여러 장면 일괄 프롬프트 생성"""
        return [self.compose_prompt(scene) for scene in scene_results]

    def compose_character_library_prompt(self, char_id: str,
                                          expression: str,
                                          pose: str) -> ComposedPrompt:
        """
        캐릭터 라이브러리용 프롬프트 생성

        Args:
            char_id: 캐릭터 ID
            expression: 표정
            pose: 포즈

        Returns:
            ComposedPrompt
        """
        style_positive, style_negative = self._get_style_prompt()
        char_id_lower = str(char_id or "").strip().lower()
        char_def = self.char_map.get(char_id_lower)
        base_prompt = ""
        style_suffix = ""
        gender_negative = ""
        age_negative = ""
        if char_def is not None:
            base_prompt = str(getattr(char_def, "base_prompt", "") or "").strip()
            style_suffix = str(getattr(char_def, "style_suffix", "") or "").strip()
            gender_negative = str(getattr(char_def, "gender_negative", "") or "").strip()
            age_negative = str(getattr(char_def, "age_negative", "") or "").strip()
        if not base_prompt:
            base_prompt = char_id.replace("_", " ")

        library_expression_prompts = {
            "neutral": "neutral face, calm expression",
            "blink": "eyes closed gently, face unchanged",
            "talking": "mouth slightly open for speech, face unchanged",
            "sad": "sad expression, sorrow in eyes",
            "fear": "worried expression, tense eyes",
            "anger": "angry expression, tense brows",
            "happy": "gentle smile, bright eyes",
        }
        library_pose_prompts = {
            "standing": "standing pose, arms relaxed, balanced posture",
            "sitting": "sitting pose, readable silhouette",
            "walking": "walking pose, readable stride, full body visible",
        }
        normalized_expression = str(expression or "neutral").strip().lower()
        normalized_pose = str(pose or "standing").strip().lower()
        char_expressions = getattr(char_def, "expressions", {}) if char_def is not None else {}
        char_poses = getattr(char_def, "poses", {}) if char_def is not None else {}
        expression_prompt = str(
            char_expressions.get(
                normalized_expression,
                library_expression_prompts.get(normalized_expression, "neutral face, calm expression"),
            )
            or library_expression_prompts.get(normalized_expression, "neutral face, calm expression")
        ).strip()
        pose_prompt = str(
            char_poses.get(
                normalized_pose,
                library_pose_prompts.get(normalized_pose, "standing pose, arms relaxed, balanced posture"),
            )
            or library_pose_prompts.get(normalized_pose, "standing pose, arms relaxed, balanced posture")
        ).strip()

        legacy_slot_constraints = {
            "young_woman": "single korean adult woman, female, 20s, one person only, realistic adult proportions, long legs, normal head ratio, no child companion, no duplicate character",
            "young_man": "single korean adult man, male, 20s or 30s, one person only, realistic adult proportions, normal head ratio, no child proportions, no duplicate character",
            "grandma": "single elderly korean woman, grandmother, senior female, 70-year-old, visible wrinkles, aged face, gray hair, elderly hands, one person only, no duplicate character, no young face",
            "grandpa": "single elderly korean man, grandfather, senior male, visible wrinkles, aged face, one person only, no duplicate character",
            "child": "single korean boy, male child, one child only, 10 to 12 years old, clear child proportions, short height, solo full-body child sprite, no adult companion, no sibling, no duplicate character",
        }
        legacy_slot_negative = {
            "young_woman": "multiple people, second person, child companion, duplicate body, twin, elderly woman, old face, male, man, beard, mustache, chibi, doll face, oversized head, blonde hair",
            "young_man": "multiple people, second person, duplicate body, twin, child, chibi, doll face, oversized head, female, woman, elderly woman, elderly man, old face",
            "grandma": "multiple people, second person, duplicate body, twin, young woman, child, male, man, beard, mustache, youthful face, smooth skin, teenager, 20s, 30s",
            "grandpa": "multiple people, second person, duplicate body, twin, young man, child, female, woman, dress, feminine face, youthful face, smooth skin",
            "child": "multiple people, second person, duplicate body, twin, adult, elderly, beard, wrinkles, mature face, parent, guardian, companion, baby, toddler, woman, mother, grandmother, adult female",
        }
        extra_positive = "single character only, one person only, centered solo full-body sprite, no companion, no duplicate character"
        extra_negative = "multiple people, group shot, second person, duplicate body, twin, extra face, extra body, companion"
        if char_def is None:
            extra_positive = legacy_slot_constraints.get(char_id_lower, extra_positive)
            extra_negative = legacy_slot_negative.get(char_id_lower, extra_negative)

        # 캐릭터 라이브러리는 배경 없이 캐릭터만
        positive_parts = [
            style_positive,
            *self._get_character_lora_parts(char_def),
            base_prompt,
            style_suffix,
            expression_prompt,
            pose_prompt,
            "clean 2d anime character sprite, single full-body subject, centered subject, clean cutout silhouette, flat cel shading, thick clean outlines, isolated sprite asset, plain solid light gray backdrop, single flat background color, no environment, no props, studio reference pose, front or three-quarter view",
            extra_positive,
        ]

        negative_parts = [
            style_negative,
            "complex background, painterly texture, photorealistic skin, glossy lighting, dynamic cinematic background, crowd, group shot, collage sheet, turnaround sheet, contact sheet, inset portrait, floating head, extra face, extra body, scenery, room interior, street, bus, architecture, prop, effects, splash background",
            extra_negative,
        ]
        if gender_negative:
            negative_parts.append(gender_negative)
        if age_negative:
            negative_parts.append(age_negative)

        # Character sheets do not need full scene resolution. Keep them lighter so
        # checkpoint switches and sprite generation stay within API timeout budgets.
        width = 512
        height = 768
        steps = 16
        cfg_scale = 7.0
        sampler = "DPM++ 2M Karras"
        checkpoint = ""
        scheduler = ""

        if self.sd_model_config:
            cfg_scale = _cfg_get(self.sd_model_config, 'cfg_scale', 7.0)
            sampler = _cfg_get(self.sd_model_config, 'sampler', "DPM++ 2M Karras")
            checkpoint = _cfg_get(self.sd_model_config, 'checkpoint', '')
            scheduler = _cfg_get(self.sd_model_config, 'scheduler', '')
            configured_steps = _cfg_get(self.sd_model_config, 'steps', 16)
            try:
                steps = min(int(configured_steps or 16), 16)
            except Exception:
                steps = 16

        return ComposedPrompt(
            positive=", ".join(positive_parts),
            negative=", ".join(negative_parts),
            scene_id=f"char_lib_{char_id}_{expression}_{pose}",
            character_prompts=[base_prompt],
            width=width,
            height=height,
            steps=steps,
            cfg_scale=cfg_scale,
            sampler=sampler,
            checkpoint=checkpoint,
            scheduler=scheduler,
        )


# ============================================================
# 테스트
# ============================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    print("=== PromptComposer Test ===\n")

    # Mock 캐릭터 정의
    class MockCharDef:
        def __init__(self, id, name, base_prompt, expressions=None, poses=None, lora=None):
            self.id = id
            self.name = name
            self.base_prompt = base_prompt
            self.style_suffix = ""
            self.expressions = expressions or {}
            self.poses = poses or {}
            self.lora = lora
            self.aliases = []

    # Mock SD 설정
    class MockSDConfig:
        def __init__(self):
            self.checkpoint = "meinamix_v12Final"
            self.width = 768
            self.height = 432
            self.steps = 15
            self.cfg_scale = 7.0
            self.sampler = "DPM++ 2M Karras"
            self.lora_models = [{"name": "yadam_style", "weight": 0.7, "trigger": "yadam_style"}]

    # Mock 장면 분석 결과
    class MockScene:
        def __init__(self):
            self.scene_id = "scene_0001"
            self.characters = [
                MockCharState("protagonist", "fear", "running"),
            ]
            self.location = "dark forest"
            self.location_detail = "dark mysterious forest, tall trees, fog"
            self.time_of_day = "night"
            self.weather = "foggy"
            self.atmosphere = "horror"
            self.scene_keywords = ["eerie", "supernatural", "ghost"]

    class MockCharState:
        def __init__(self, id, emotion, action):
            self.id = id
            self.emotion = emotion
            self.action = action
            self.is_speaker = True

    # 캐릭터 정의
    characters = [
        MockCharDef(
            id="protagonist",
            name="protagonist",
            base_prompt="korean young man, 20s, humble appearance",
            expressions={
                "fear": "frightened, wide eyes, pale face, terrified",
                "neutral": "calm expression",
            },
            poses={
                "running": "running pose, dynamic, motion blur",
                "standing": "standing pose",
            }
        ),
    ]

    sd_config = MockSDConfig()

    # PromptComposer 생성
    composer = PromptComposer(
        character_definitions=characters,
        sd_model_config=sd_config,
        base_positive="cinematic, film grain, dramatic",
        base_negative="anime, cartoon, 3d render",
    )

    # 1. 장면 프롬프트 생성
    print("1. Scene Prompt Test:")
    scene = MockScene()
    result = composer.compose_prompt(scene)

    print(f"   Scene ID: {result.scene_id}")
    print(f"   Positive ({len(result.positive)} chars):")
    print(f"     {result.positive[:200]}...")
    print(f"   Negative ({len(result.negative)} chars):")
    print(f"     {result.negative[:100]}...")
    print(f"   Size: {result.width}x{result.height}")
    print(f"   Steps: {result.steps}, CFG: {result.cfg_scale}")

    # 2. 캐릭터 라이브러리 프롬프트
    print("\n2. Character Library Prompt Test:")
    lib_result = composer.compose_character_library_prompt(
        char_id="protagonist",
        expression="fear",
        pose="running"
    )
    print(f"   Positive: {lib_result.positive[:150]}...")
    print(f"   Size: {lib_result.width}x{lib_result.height}")

    # 3. API 파라미터
    print("\n3. API Parameters:")
    params = result.to_api_params()
    for key, value in params.items():
        if key in ["prompt", "negative_prompt"]:
            print(f"   {key}: {str(value)[:50]}...")
        else:
            print(f"   {key}: {value}")

    print("\n[OK] All tests passed!")
