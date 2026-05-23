# src/modules_pro/scene_analyzer.py
# ============================================================
# v59: Scene Analyzer - AI 기반 장면 분석
# 대사를 분석하여 캐릭터, 장소, 시간, 감정, 행동 등을 추출
# v59.1.9: timeout + 폴백 + 진행 로그 추가 (hang 방지)
# ============================================================

import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field, asdict

from utils.secret_redaction import redact_sensitive_text

try:
    from utils.logger import get_logger
    logger = get_logger("scene_analyzer")
except ImportError:
    logger = logging.getLogger(__name__)

# v62.21 M-1: 함수 내 import → 모듈 레벨로 이동 (v62.17c 패턴 방지)
# 함수 내 from import 시 Python이 해당 변수를 함수 전체에서 local로 마킹 → UnboundLocalError 위험
try:
    from config.pack_config import get_atmosphere_config, PACK_CONFIG_AVAILABLE
except ImportError:
    get_atmosphere_config = None
    PACK_CONFIG_AVAILABLE = False


# ============================================================
# 분석 결과 데이터 클래스
# ============================================================

@dataclass
class CharacterState:
    """캐릭터 상태"""
    id: str = ""                      # 캐릭터 ID (pack_config의 CharacterDefinition.id와 매칭)
    name: str = ""                    # 원본 이름 (대사에서 추출된)
    emotion: str = "neutral"          # 감정 (neutral, happy, sad, fear, anger, surprise)
    action: str = ""                  # 행동 (talking, walking, running, sitting, etc.)
    is_speaker: bool = False          # 현재 대사를 말하는 캐릭터인지


@dataclass
class SceneAnalysisResult:
    """장면 분석 결과"""
    # 장면 ID
    scene_id: str = ""
    dialogue_index: int = 0           # 대사 인덱스

    # 등장 캐릭터
    characters: List[CharacterState] = field(default_factory=list)

    # 장면 설정
    location: str = ""                # 장소
    location_detail: str = ""         # 장소 상세 (SD 프롬프트용)
    time_of_day: str = ""             # 시간대 (dawn, morning, afternoon, evening, night)
    weather: str = ""                 # 날씨 (clear, cloudy, rainy, foggy, snowy)
    atmosphere: str = ""              # 분위기 (peaceful, tense, mysterious, romantic, horror)

    # 스토리 흐름
    story_beat: str = ""              # 스토리 비트 (exposition, rising, climax, falling, resolution)
    tension_level: int = 5            # 긴장도 (1-10)

    # 이미지 결정
    image_action: str = "new"         # new, expression, pose, reuse
    reuse_reason: str = ""            # reuse 시 이유

    # 프롬프트 힌트
    scene_keywords: List[str] = field(default_factory=list)  # SD 프롬프트에 사용할 키워드
    sd_prompt: str = ""               # v59.2.2: Gemini가 직접 생성한 SD 프롬프트

    # 원본 데이터
    continuity_hint: str = ""         # 이전 컷과 이어지게 만들 힌트
    camera_shot: str = ""             # close-up, wide shot, low angle ...
    key_props: List[str] = field(default_factory=list)       # letter, knife, phone ...
    outfit_hint: str = ""             # same outfit continuity hint
    original_dialogue: str = ""
    speaker: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환"""
        result = asdict(self)
        result['characters'] = [asdict(c) for c in self.characters]
        return result


# ============================================================
# SceneAnalyzer 클래스
# ============================================================

class SceneAnalyzer:
    """
    v59: AI 기반 장면 분석기

    대사를 분석하여 시각화에 필요한 정보를 추출합니다:
    - 등장 캐릭터와 감정/행동
    - 장소, 시간, 날씨
    - 분위기와 긴장도
    - 이미지 액션 결정 (new/expression/pose/reuse)
    """

    # v59.5.6: 기본 아트 스타일 (하위호환 — art_style_config=None일 때 사용)
    DEFAULT_ART_STYLE = {
        "art_style_prefix": "monochrome manga, black and white ink drawing,",
        "art_style_description": "같은 만화가의 빈티지 한국 공포 만화",
        "texture_keywords": "clean lineart, high contrast, ink strokes, vintage manhwa, rough ink texture",
        "forbidden_styles": "colorful, 3d render, photorealistic, photograph, watercolor, pixel art, oil painting, anime, modern anime, cel shading",
        "good_examples": [
            # v62.17: 외모 키워드(long black hair, white dress, elderly woman 등) 제거
            "monochrome manga, black and white ink drawing, (solo, terrified expression, backing away:1.3), dark hallway, flickering light, medium shot, fully clothed",
            "monochrome manga, black and white ink drawing, (solo, trembling, clutching old diary:1.3), dusty attic, single lamp, close-up, fully clothed",
            "monochrome manga, black and white ink drawing, (long empty corridor:1.4), eerie fog, moonlight through window, wide shot",
            "monochrome manga, black and white ink drawing, (solo, worried expression, leaning forward:1.3), candlelight, tense atmosphere, bust shot, fully clothed"
        ]
    }

    def __init__(self, gemini_client=None, character_definitions: Any = None,
                 art_style_config: Dict[str, Any] = None):
        """
        Args:
            gemini_client: Gemini API 클라이언트 (None이면 내부 생성)
            character_definitions: 팩에서 정의된 캐릭터 (List 또는 Dict)
            art_style_config: 팩 JSON의 scene_analyzer 블록 (None이면 DEFAULT_ART_STYLE 사용)
        """
        self.gemini_client = gemini_client

        # v59.5.6: 데이터 드리븐 아트 스타일 (팩 불가지론)
        self.art_style = art_style_config if art_style_config else self.DEFAULT_ART_STYLE
        logger.info(f"[SceneAnalyzer] 아트 스타일: {self.art_style.get('art_style_prefix', 'DEFAULT')[:50]}...")

        # v59.3.0: 공통 유틸 사용 (dict → list 변환)
        if character_definitions is None:
            self.character_definitions = []
        elif isinstance(character_definitions, dict):
            from modules_pro.prompt_composer import char_defs_from_dict
            self.character_definitions = char_defs_from_dict(
                character_definitions, include_aliases=True, include_lora=False
            )
            logger.debug(f"[SceneAnalyzer] dict → list 변환: {len(self.character_definitions)}개")
        else:
            self.character_definitions = list(character_definitions) if character_definitions else []

        # 캐릭터 별칭 → ID 매핑 생성
        self.alias_to_id: Dict[str, str] = {}
        self._build_alias_mapping()

        # 이전 장면 캐시 (연속성 판단용)
        self.previous_scenes: List[SceneAnalysisResult] = []
        self.max_cache_size = 10

        logger.info(f"[SceneAnalyzer] 초기화 완료: {len(self.character_definitions)}개 캐릭터 정의")

    def _format_good_examples(self) -> str:
        """v59.5.6: 팩 아트 스타일의 좋은 예시 포맷팅"""
        examples = self.art_style.get('good_examples', [])
        if not examples:
            prefix = self.art_style.get('art_style_prefix', 'monochrome manga,')
            return f'- 좋은 예: "{prefix} creepy doll on chair, dusty empty room, dim window light, uncanny, wide shot"'
        lines = []
        for ex in examples[:3]:  # 최대 3개만
            lines.append(f'- 좋은 예: "{ex}"')
        return "\n".join(lines)

    def _build_alias_mapping(self):
        """캐릭터 별칭 매핑 생성"""
        for char in self.character_definitions:
            char_id = getattr(char, 'id', '')
            char_name = getattr(char, 'name', '')
            aliases = getattr(char, 'aliases', [])

            if char_id:
                # 이름 매핑
                if char_name:
                    self.alias_to_id[char_name.lower()] = char_id
                # 별칭 매핑
                for alias in aliases:
                    self.alias_to_id[alias.lower()] = char_id

        logger.debug(f"[SceneAnalyzer] 별칭 매핑: {self.alias_to_id}")

    def _get_character_id(self, name: str) -> str:
        """이름/별칭에서 캐릭터 ID 찾기"""
        return self.alias_to_id.get(name.lower(), name.lower())

    def _create_analysis_prompt(self, dialogue: str, speaker: str,
                                 context_dialogues: List[str] = None,
                                 previous_sd_prompts: List[str] = None) -> str:
        """
        분석용 프롬프트 생성
        v59.3.0: 스타일 통일 + 캐릭터 외모 + 이전 장면 맥락 전달
        """

        # 캐릭터 정보 (별칭 + 외모 + ID 목록)
        char_info = ""
        char_appearance = ""
        char_id_list = []  # v59.3.0: FIX-8 - enum 제약용 ID 목록
        if self.character_definitions:
            char_list = []
            appearance_list = []
            for char in self.character_definitions:
                char_id = getattr(char, 'id', '')
                char_name = getattr(char, 'name', '')
                aliases = getattr(char, 'aliases', [])
                # v59.3.0: 외모 정보 추출
                base_prompt = getattr(char, 'base_prompt', '')
                if not base_prompt:
                    # dict 기반 캐릭터인 경우
                    base_prompt = getattr(char, 'base', '')
                if char_id:
                    char_id_list.append(char_id)
                    alias_str = ", ".join(aliases) if aliases else "없음"
                    char_list.append(f"- {char_id}: {char_name} (별칭: {alias_str})")
                    if base_prompt:
                        appearance_list.append(f"- {char_name}({char_id}): {base_prompt}")
            if char_list:
                char_info = "등록된 캐릭터:\n" + "\n".join(char_list)
            if appearance_list:
                char_appearance = "\n".join(appearance_list)

        # 컨텍스트 (이전 대사들)
        context_str = ""
        if context_dialogues:
            context_str = "이전 대사:\n" + "\n".join([f"- {d}" for d in context_dialogues[-3:]])

        # v59.5: 이전 장면 sd_prompt (시각적 연속성) - 더 긴 참조 + 강화된 지시
        prev_prompts_str = ""
        if previous_sd_prompts:
            prompt_lines = []
            for i, sp in enumerate(previous_sd_prompts[-5:]):
                if sp:
                    prompt_lines.append(f"  [{len(previous_sd_prompts)-len(previous_sd_prompts[-5:])+i+1}번째 장면]: {sp[:200]}")
            if prompt_lines:
                prev_prompts_str = "[Previous scene sd_prompts - visual continuity required!]\n" + "\n".join(prompt_lines) + "\n★ Same location → reuse 70%+ background keywords / Different location → smooth transition"

        # v59.9.0: 캐릭터 외모 섹션 — 역할 분리 (외모는 PromptComposer가 주입)
        char_appearance_section = ""
        if char_appearance:
            char_appearance_section = f"""
[Character Appearance Dictionary — REFERENCE ONLY! Do NOT put in sd_prompt!]
{char_appearance}
★ Appearance keywords (hair, face, clothing, age, gender) are auto-injected in post-processing!
★ Including appearance in sd_prompt → double injection → token waste + conflict!
★ sd_prompt should ONLY contain: action/pose/emotion/location/atmosphere/camera!
★ Instead, specify the correct character ID in characters[].name → appearance auto-applied"""

        # v59.3.0: Gemini에게 SD 프롬프트를 직접 생성시킴 (강화된 규칙)
        prompt = f"""Analyze the following dialogue line and extract visualization data as JSON.

Current dialogue:
Speaker: {speaker}
Content: "{dialogue}"

{context_str}

{char_info}

Respond with the following JSON format ONLY (no code blocks, pure JSON):
{{
    "characters": [
        {{
            "name": "Character English ID (MUST select from the list below!)",
            "emotion": "emotion (neutral/happy/sad/fear/anger/surprise/calm/excited)",
            "action": "action (talking/listening/walking/running/sitting/standing/looking/etc)",
            "is_speaker": true/false
        }}
    ],
    "location": "location in Korean (한옥/숲/도시/실내 etc.)",
    "location_detail": "detailed location description in English (for SD prompt)",
    "time_of_day": "time (dawn/morning/afternoon/evening/night)",
    "weather": "weather (clear/cloudy/rainy/foggy/snowy/none)",
    "atmosphere": "mood (peaceful/tense/mysterious/romantic/horror/sad/exciting)",
    "story_beat": "story beat (exposition/rising/climax/falling/resolution)",
    "tension_level": 5,
    "scene_keywords": ["English keywords for SD prompt", "..."],
    "sd_prompt": "supplemental visual cue keywords only (client compiles final SD prompt from structured fields)",
    "camera_shot": "camera keyword extracted from sd_prompt (close-up/wide shot/low angle/etc)",
    "key_props": ["important props visible in this panel", "..."],
    "outfit_hint": "short outfit label if obvious, otherwise empty string"
}}

Rules:
1. Infer the visual scene from dialogue content and context
2. location_detail must be in English, suitable for SD image generation
3. scene_keywords: 3-5 visual element keywords
4. Reasonably infer unspecified information from context
5. The client compiles the final SD prompt. Prioritize accuracy in characters/location/key_props/camera_shot over creative wording in sd_prompt.
6. If no other character is mentioned, include only the speaker
7. [CRITICAL!] characters[].name MUST use one of the English IDs below:
   Allowed IDs: [{', '.join(char_id_list) if char_id_list else 'narrator'}]
   ★ Korean names (주인공, 나레이터, etc.) are FORBIDDEN! Use English IDs ONLY!

=== sd_prompt Writing Rules (v59.9.0 - SD1.5 story-driven + role separation) ===

[🔒 TOP PRIORITY: The story must be readable from images alone!]
- Viewers should understand "what's happening" by looking at images in sequence WITHOUT subtitles
- Key actions/objects from dialogue MUST be reflected in sd_prompt!
- Abstract concepts (fear, tension, anxiety) → express via objects/actions: fear→dark shadow, tension→clenched fist, anxiety→shaking hand

[🔒🔒🔒 sd_prompt Structure — Write in THIS order! 🔒🔒🔒]
sd_prompt must contain ONLY these elements (in this order!):
1. Art style: "{self.art_style.get('art_style_prefix', 'monochrome manga, black and white ink drawing,')}" (DO NOT CHANGE!)
2. If character scene: "solo" (ONLY when a character appears! Omit for background scenes!)
3. Action/Pose: sitting, running, looking down, clenched fists, pointing, turning around, etc.
4. Emotional expression: angry expression, tearful eyes, warm smile, shocked face, etc.
5. Key objects: important props mentioned in dialogue (letter, mirror, knife, phone, etc.)
6. Location/Background: dark room, traditional korean house interior, hospital hallway, etc.
7. Lighting/Mood: dim lighting, dramatic shadows, warm golden light, etc.
8. Camera/Composition: close-up, wide shot, low angle, dutch angle, etc.

★★★ NEVER include in sd_prompt ★★★
- Character appearance: hair color, face shape, wrinkles, clothing → auto-injected! Including = duplication!
- Gender/Age: woman, man, elderly, young → auto-handled via characters[].name ID!
- Generic person keywords like "person", "figure", "character" → "solo" + action is sufficient!
Example: ❌ "solo elderly woman with grey hair in hanbok, angry expression"
         ✅ "solo, angry expression, clenched fists, slamming table, traditional room, close-up"

[🔒 SD Weight Rules — Apply (keyword:1.3~1.5) to scene focus!]
- Determine scene type and weight the focal keywords:
  Character action: "(solo, angry expression, slamming table:1.3), dark room, ..."
  Object-focused: "(creepy old doll on chair:1.4), dusty room, ..."
  Space-focused: "(long dark corridor:1.3), abandoned, eerie, ..."
- Weight range: 1.3~1.5 (NEVER exceed 1.5), apply to only 1-2 keywords per scene
- Decision criterion: "Where should the viewer's eye go?" → weight THAT element

[🔒 Art Style Consistency — NEVER change!]
- sd_prompt MUST start with: "{self.art_style.get('art_style_prefix', 'monochrome manga, black and white ink drawing,')}"
- Forbidden styles: {self.art_style.get('forbidden_styles', 'colorful, 3d render, photorealistic, photograph')}
- Every scene must look like {self.art_style.get('art_style_description', 'the same artist drew all panels in the same manga')}
- Texture keywords: {self.art_style.get('texture_keywords', 'clean lineart, high contrast')}

[🔒 SD 1.5 Token Limit (75 tokens = ~15 keywords)]
- sd_prompt: 10-15 English keywords (comma-separated), NEVER exceed 18
- Character appearance is added in post-processing, so 10-15 is sufficient here!
- Keyword list ONLY! Sentence-form is FORBIDDEN!
- Good example: "{self.art_style.get('art_style_prefix', 'monochrome manga, black and white ink drawing,')} (solo, furious expression, slamming table:1.3), traditional Korean room, harsh shadow, close-up, fully clothed"
- Good example: "{self.art_style.get('art_style_prefix', 'monochrome manga, black and white ink drawing,')} (blood-stained letter on wooden desk:1.4), dim lamp, dust particles, extreme close-up"
- Good example: "{self.art_style.get('art_style_prefix', 'monochrome manga, black and white ink drawing,')} (solo, running desperately:1.3), dark narrow hallway, flickering light, wide shot, fully clothed"
- Bad example: "a dark and eerie scene showing a young man standing alone..." (sentence-form forbidden!)
- Bad example: "elderly woman with grey hair in hanbok..." (no appearance! auto-injected!)
- Bad example: "{self.art_style.get('art_style_prefix', 'monochrome manga,')[:20]}... horror, dark, scary, atmosphere" (mood only without objects = empty image!)

[🔒 Mandatory Safety Rules]
- "fully clothed" is REQUIRED for TYPE A and TYPE B (character scenes). For TYPE C (background/object/atmosphere — no person), omit "fully clothed" entirely.
- NSFW/nudity/sexually suggestive content is ABSOLUTELY FORBIDDEN.
{char_appearance_section}

[🔒 Character Presence Decision — Only 3 cases exist!]
A. Character dialogue/action scene (ONLY for non-narrator speakers!):
   → sd_prompt includes "solo" + action/pose/emotional expression
   → characters[].name = speaker's English ID (appearance auto-applied!)
   → In dialogue scenes, draw ONLY the speaker! Omit the listener!
   Example: [Grandmother's line] "이게 무슨 짓이야!" → "solo, furious expression, pointing finger, traditional room interior, dramatic lighting, medium shot"

B. Narration describing a SPECIFIC character's PHYSICAL ACTION (not atmosphere/setting):
   → ★ The narrator itself NEVER appears on screen! Narrator is voice-only! (speaker = 나레이션/나레이터/narrator/narration → always Case B or C, NEVER Case A)
   → ONLY use Case B when narration explicitly describes someone DOING something physical!
   → sd_prompt: "solo" + action/emotion, characters[].name = that character's ID
   Example: [Narration] "She ran desperately down the corridor"
       → characters: woman, sd_prompt: "solo, running desperately, dark hallway, flickering light, wide shot"

C. Background/Object/Atmosphere scene (★ USE THIS MORE OFTEN! ★):
   → characters MUST be an EMPTY array []! No person keywords! No "solo"!
   → sd_prompt: location/objects/atmosphere/lighting ONLY
   → ★★★ At least 30-40% of narration scenes SHOULD be Case C! ★★★
   → Case C creates visual breathing room and builds atmosphere — essential for good storytelling!

   USE Case C for ALL of these narration types:
   - Setting/atmosphere description: "그날 밤, 마을은 고요했다" → background!
   - Time passing: "시간이 흘러..." → background!
   - Internal monologue/thought: "도대체 무슨 일이 벌어진 거지?" → background (location where character IS)
   - Sound description: "복도에서 이상한 소리가 들려왔다" → background (the corridor)!
   - Object focus: "책상 위에 핏자국 묻은 편지가 있었다" → object close-up!
   - Emotional atmosphere: "공포가 서서히 밀려왔다" → atmospheric background!

   Example: [Narration] "That night, the village was silent"
       → characters: [], sd_prompt: "quiet village at night, moonlight, empty street, wide shot"
   Example: [Narration] "A blood-stained letter lay on the table"
       → characters: [], sd_prompt: "(blood-stained letter on wooden table:1.4), dim lamp, close-up"
   Example: [Narration] "Strange sounds echoed through the corridor"
       → characters: [], sd_prompt: "(long dark corridor:1.3), flickering fluorescent light, eerie atmosphere, wide shot"
   Example: [Narration] "What on earth was happening?"
       → characters: [], sd_prompt: "dimly lit room interior, shadows on wall, unsettling atmosphere, medium shot"

★ Decision criterion: "If drawing this as a webtoon panel, is a person absolutely necessary?"
  → Character is PHYSICALLY DOING something specific → Case A or B
  → Atmosphere, setting, object, thought, sound, emotion → Case C!
  → When in doubt → Case C! (Background panels create rhythm and variety!)

[🔒 Scene Continuity]
- Same location continues → maintain location/lighting keywords (e.g., hallway, dim lighting → keep)
- Location change → transition naturally with keywords (hallway → kitchen)
- ★ Scene-specific props (mirror, letter, knife) → use in THAT scene only! NEVER carry over to next scene!
- Time progression → express via lighting keywords (night → dawn = change lighting)
{prev_prompts_str}

[🔒 Camera/Composition Diversity — Webtoon-level visuals!]
- Same location 2+ consecutive times → MUST change composition/angle!
- Emotional dialogue → close-up, extreme close-up
- Space description → wide shot, establishing shot
- Action scene → dynamic angle, low angle
- Object discovery → object extreme close-up
- Camera keywords: wide shot, close-up, extreme close-up, low angle, high angle, dutch angle, bird's eye view, over the shoulder, POV
- 3 consecutive same angles FORBIDDEN!"""

        return prompt

    @staticmethod
    def _extract_camera_shot(sd_prompt: str) -> str:
        prompt = (sd_prompt or "").lower()
        camera_keywords = [
            "extreme close-up",
            "medium close-up",
            "close-up",
            "bust shot",
            "medium shot",
            "wide shot",
            "establishing shot",
            "low angle",
            "high angle",
            "dutch angle",
            "bird's eye view",
            "over the shoulder",
            "pov",
        ]
        for keyword in camera_keywords:
            if keyword in prompt:
                return keyword
        return ""

    @staticmethod
    def _extract_key_props(dialogue: str, sd_prompt: str, scene_keywords: List[str]) -> List[str]:
        text = " ".join([
            dialogue or "",
            sd_prompt or "",
            ", ".join(scene_keywords or []),
        ]).lower()
        prop_aliases = {
            "letter": ["letter", "편지", "envelope", "봉투"],
            "mirror": ["mirror", "거울"],
            "knife": ["knife", "칼", "커터칼"],
            "phone": ["phone", "smartphone", "휴대폰", "전화기"],
            "photograph": ["photograph", "photo", "picture", "사진"],
            "diary": ["diary", "journal", "일기장", "수첩", "노트"],
            "doll": ["doll", "인형"],
            "candle": ["candle", "촛불", "candlestick"],
            "key": ["key", "열쇠"],
            "ring": ["ring", "반지"],
            "cup": ["cup", "mug", "찻잔", "컵"],
            "book": ["book", "책"],
            "document": ["document", "file folder", "서류", "문서"],
            "blanket": ["blanket", "이불", "담요"],
            "wheelchair": ["wheelchair", "휠체어"],
        }

        props: List[str] = []
        for canonical, aliases in prop_aliases.items():
            if any(alias in text for alias in aliases):
                props.append(canonical)
        return props[:3]

    def _extract_outfit_hint(self, dialogue: str, sd_prompt: str, char_ids: List[str]) -> str:
        prompt_lower = " ".join([dialogue or "", sd_prompt or ""]).lower()
        outfit_keywords = [
            "school uniform",
            "white dress",
            "dark coat",
            "business suit",
            "sweater",
            "cardigan",
            "hoodie",
            "uniform",
            "casual outfit",
            "casual clothes",
            "modest dress",
            "modest clothing",
            "neat clothing",
            "hospital gown",
        ]
        for keyword in outfit_keywords:
            if keyword in prompt_lower:
                return keyword

        for char_id in char_ids:
            char_obj = None
            for char in self.character_definitions or []:
                if getattr(char, "id", "") == char_id:
                    char_obj = char
                    break
            if not char_obj:
                continue
            base_prompt = getattr(char_obj, "base_prompt", "") or getattr(char_obj, "base", "")
            base_lower = base_prompt.lower()
            for keyword in outfit_keywords:
                if keyword in base_lower:
                    return keyword
            if "hanbok" in base_lower:
                return "hanbok"
        return ""

    def _hydrate_visual_state(self, result: SceneAnalysisResult) -> SceneAnalysisResult:
        result.camera_shot = result.camera_shot or self._extract_camera_shot(result.sd_prompt)
        result.key_props = result.key_props or self._extract_key_props(
            result.original_dialogue,
            result.sd_prompt,
            result.scene_keywords,
        )
        char_ids = [c.id for c in result.characters if getattr(c, "id", "")]
        result.outfit_hint = result.outfit_hint or self._extract_outfit_hint(
            result.original_dialogue,
            result.sd_prompt,
            char_ids,
        )
        return result

    def _parse_analysis_response(self, response: str, dialogue: str,
                                  speaker: str, index: int) -> SceneAnalysisResult:
        """AI 응답 파싱"""
        result = SceneAnalysisResult(
            scene_id=f"scene_{index:04d}",
            dialogue_index=index,
            original_dialogue=dialogue,
            speaker=speaker
        )

        try:
            # JSON 추출 (코드블록 제거)
            json_str = response.strip()
            if "```json" in json_str:
                json_str = json_str.split("```json")[1].split("```")[0]
            elif "```" in json_str:
                json_str = json_str.split("```")[1].split("```")[0]

            data = json.loads(json_str)

            # 캐릭터 파싱
            for char_data in data.get("characters", []):
                char_name = char_data.get("name", "")
                char_state = CharacterState(
                    id=self._get_character_id(char_name),
                    name=char_name,
                    emotion=char_data.get("emotion", "neutral"),
                    action=char_data.get("action", ""),
                    is_speaker=char_data.get("is_speaker", False)
                )
                result.characters.append(char_state)

            # 장면 정보
            result.location = data.get("location", "")
            result.location_detail = data.get("location_detail", "")
            result.time_of_day = data.get("time_of_day", "")
            result.weather = data.get("weather", "")
            result.atmosphere = data.get("atmosphere", "")
            result.story_beat = data.get("story_beat", "")
            # v62.17: tension_level 문자열 방어 파싱 + 범위 클램핑 1~10
            _tl = data.get("tension_level", 5)
            try:
                result.tension_level = max(1, min(10, int(str(_tl).strip().split()[0])))
            except (ValueError, IndexError):
                result.tension_level = 5
            result.scene_keywords = data.get("scene_keywords", [])
            result.sd_prompt = data.get("sd_prompt", "")  # v59.2.2
            result.camera_shot = data.get("camera_shot", "")
            result.key_props = data.get("key_props", [])
            result.outfit_hint = data.get("outfit_hint", "")

        except json.JSONDecodeError as e:
            logger.warning(f"[SceneAnalyzer] JSON 파싱 실패: {e}")
            # 기본값으로 폴백
            result.characters.append(CharacterState(
                id=self._get_character_id(speaker),
                name=speaker,
                emotion="neutral",
                action="talking",
                is_speaker=True
            ))
        except Exception as e:
            logger.error(f"[SceneAnalyzer] 분석 파싱 오류: {e}")

        return self._hydrate_visual_state(result)

    def _determine_image_action(self, current: SceneAnalysisResult) -> str:
        """이미지 액션 결정 (new/expression/pose/reuse)"""

        if not self.previous_scenes:
            return "new"

        # v61.1 (#74): 직전 장면뿐만 아니라 같은 장소의 최근 장면도 참조
        prev = self.previous_scenes[-1]
        # 같은 장소의 최근 장면 찾기 (reuse 판단 개선)
        if current.location and current.location != prev.location:
            same_location = [s for s in self.previous_scenes if s.location == current.location]
            if same_location:
                # 같은 장소로 돌아온 경우 → 해당 장면과 비교
                prev = same_location[-1]
                logger.debug(f"[SceneAnalyzer] (#74) 같은 장소 재방문: {current.location}")

        # 1. 장소가 바뀌면 → new
        current.continuity_hint = self._build_continuity_hint(current, prev)
        if current.location and prev.location:
            if current.location != prev.location:
                logger.debug(f"[SceneAnalyzer] 장소 변경: {prev.location} → {current.location}")
                return "new"

        # 2. 등장 캐릭터가 바뀌면 → new
        current_char_ids = {c.id for c in current.characters}
        prev_char_ids = {c.id for c in prev.characters}
        if current_char_ids != prev_char_ids:
            logger.debug(f"[SceneAnalyzer] 캐릭터 변경: {prev_char_ids} → {current_char_ids}")
            return "new"

        # 3. 같은 캐릭터, 같은 장소
        if current.characters and prev.characters:
            curr_main = current.characters[0]
            prev_main = prev.characters[0]

            # 감정만 바뀌면 → expression_swap
            if curr_main.emotion != prev_main.emotion:
                if curr_main.action == prev_main.action:
                    logger.debug(f"[SceneAnalyzer] 표정 변경: {prev_main.emotion} → {curr_main.emotion}")
                    return "expression"

            # 행동만 바뀌면 → pose_swap
            if curr_main.action != prev_main.action:
                logger.debug(f"[SceneAnalyzer] 포즈 변경: {prev_main.action} → {curr_main.action}")
                return "pose"

        # 4. 분위기/긴장도 크게 바뀌면 → new
        # v61.1 (#72): >=3 → >=2 (점진적 빌드업도 시각적 변화 반영)
        if abs(current.tension_level - prev.tension_level) >= 2:
            logger.debug(f"[SceneAnalyzer] 긴장도 급변: {prev.tension_level} → {current.tension_level}")
            return "new"

        # 5. 그 외 → reuse
        current.reuse_reason = "장면 변화 없음"
        return "reuse"

    def _build_continuity_hint(self, current: SceneAnalysisResult,
                               prev: SceneAnalysisResult) -> str:
        """이전 컷과 연결될 때 인물/배경 고정 힌트를 만든다."""
        hints: List[str] = []
        narrator_ids = {"narrator", "narration", "나레이션", "나레이터"}

        current_ids = [c.id for c in current.characters if getattr(c, "id", "")]
        prev_ids = [c.id for c in prev.characters if getattr(c, "id", "")]
        shared_ids = [
            char_id for char_id in current_ids
            if char_id in prev_ids and char_id.lower() not in narrator_ids
        ]

        if shared_ids:
            hints.append("same character as previous panel, same face, same hairstyle, same outfit")
            current_main = current.characters[0] if current.characters else None
            prev_main = prev.characters[0] if prev.characters else None
            if current_main and prev_main:
                if current_main.action != prev_main.action:
                    hints.append("change pose only, keep character design identical")
                elif current_main.emotion != prev_main.emotion:
                    hints.append("change expression only, keep pose and design identical")

        if current.location and prev.location and current.location == prev.location:
            hints.append("same location, same lighting, same background layout, new comic-panel framing")

        return ", ".join(hints)

    # v59.1.9: Gemini API 호출 설정
    GEMINI_TIMEOUT = 30       # v59.5.5: 20→30초 (폴백 방지)
    GEMINI_MAX_RETRIES = 2    # 최대 재시도 횟수
    GEMINI_RETRY_DELAY = 1    # 재시도 대기 (초)

    def analyze_dialogue(self, dialogue: str, speaker: str = "나레이터",
                         index: int = 0, context_dialogues: List[str] = None,
                         skip_action_decision: bool = False,
                         previous_sd_prompts: List[str] = None) -> SceneAnalysisResult:
        """
        단일 대사 분석
        v59.1.9: timeout + retry + 폴백 (hang 방지)
        v59.2.3: skip_action_decision 옵션 (병렬 분석용)
        v59.3.0: previous_sd_prompts로 시각적 연속성 유지

        Args:
            dialogue: 대사 내용
            speaker: 화자
            index: 대사 인덱스
            context_dialogues: 이전 대사들 (컨텍스트)
            skip_action_decision: True면 image_action 결정/캐시 업데이트 생략 (병렬용)
            previous_sd_prompts: 이전 장면의 sd_prompt 리스트 (시각적 연속성)

        Returns:
            SceneAnalysisResult
        """
        logger.debug(f"[SceneAnalyzer] 분석 시작: [{index}] [{speaker}] {dialogue[:30]}...")

        # Gemini 클라이언트 확인
        if not self.gemini_client:
            logger.warning("[SceneAnalyzer] Gemini 클라이언트 없음 - 기본 분석 사용")
            return self._fallback_analysis(dialogue, speaker, index)

        # v59.1.9: retry 루프 (timeout 포함)
        last_error = None
        for attempt in range(1, self.GEMINI_MAX_RETRIES + 1):
            try:
                # 프롬프트 생성 (v59.3.0: 이전 sd_prompt 전달)
                prompt = self._create_analysis_prompt(
                    dialogue, speaker, context_dialogues,
                    previous_sd_prompts=previous_sd_prompts
                )

                # AI 분석 요청 (v62.39: try/except TypeError — raw genai.GenerativeModel timeout 미지원 대응)
                start_time = time.time()
                try:
                    response = self.gemini_client.generate_content(
                        prompt, timeout=self.GEMINI_TIMEOUT
                    )
                except TypeError:
                    response = self.gemini_client.generate_content(prompt)
                elapsed = time.time() - start_time

                if response and hasattr(response, 'text') and response.text:
                    result = self._parse_analysis_response(response.text, dialogue, speaker, index)
                    result = self._post_process_sd_prompt(result)  # v59.9.0: 후처리
                    logger.debug(f"[SceneAnalyzer] [{index}] AI 분석 성공 ({elapsed:.1f}s)")
                else:
                    logger.warning(f"[SceneAnalyzer] [{index}] 빈 응답 → 폴백")
                    result = self._fallback_analysis(dialogue, speaker, index)

                # v59.2.3: 병렬 모드에서는 image_action/캐시 스킵
                if not skip_action_decision:
                    result.image_action = self._determine_image_action(result)
                    self.previous_scenes.append(result)
                    if len(self.previous_scenes) > self.max_cache_size:
                        self.previous_scenes.pop(0)

                return result

            except TimeoutError:
                last_error = f"timeout ({self.GEMINI_TIMEOUT}s)"
                logger.warning(
                    f"[SceneAnalyzer] [{index}] 타임아웃 (시도 {attempt}/{self.GEMINI_MAX_RETRIES})"
                )
                if attempt < self.GEMINI_MAX_RETRIES:
                    time.sleep(self.GEMINI_RETRY_DELAY)
            except Exception as e:
                last_error = redact_sensitive_text(e)
                logger.warning(
                    f"[SceneAnalyzer] [{index}] 분석 실패 (시도 {attempt}/{self.GEMINI_MAX_RETRIES}): {last_error}"
                )
                if attempt < self.GEMINI_MAX_RETRIES:
                    time.sleep(self.GEMINI_RETRY_DELAY)

        # 모든 시도 실패 → 폴백
        logger.warning(f"[SceneAnalyzer] [{index}] 모든 시도 실패 ({last_error}) → 규칙 기반 폴백")
        result = self._fallback_analysis(dialogue, speaker, index)

        # v59.2.3: 병렬 모드에서는 캐시 스킵
        if not skip_action_decision:
            self.previous_scenes.append(result)
            if len(self.previous_scenes) > self.max_cache_size:
                self.previous_scenes.pop(0)

        return self._hydrate_visual_state(result)

    def _fallback_analysis(self, dialogue: str, speaker: str, index: int) -> SceneAnalysisResult:
        """폴백 분석 (AI 없이 규칙 기반)"""
        result = SceneAnalysisResult(
            scene_id=f"scene_{index:04d}",
            dialogue_index=index,
            original_dialogue=dialogue,
            speaker=speaker
        )

        # v62: 나레이터는 배경 장면으로 처리 (인물 삽입 안 함)
        narrator_names = ('나레이션', '나레이터', 'narrator', 'narration')
        is_narrator = speaker.lower().strip() in narrator_names

        if is_narrator:
            # 나레이터 → 배경 장면 (characters 빈 배열)
            logger.debug(f"[SceneAnalyzer] [{index}] 나레이터 폴백 → 배경 장면")
        else:
            # 실제 캐릭터 화자 → 인물 장면
            result.characters.append(CharacterState(
                id=self._get_character_id(speaker),
                name=speaker,
                emotion=self._detect_emotion_from_text(dialogue),
                action="talking",
                is_speaker=True
            ))

        # 키워드 기반 장소 추측
        result.location = self._detect_location_from_text(dialogue)
        result.time_of_day = self._detect_time_from_text(dialogue)
        result.atmosphere = self._detect_atmosphere_from_text(dialogue)
        # v61.1 (#71): 텍스트 기반 tension 추정 (하드코딩 5 제거)
        result.tension_level = self._estimate_tension_from_text(dialogue, result.atmosphere)

        # v60: 팩에서 분위기 맵 로딩 (하드코딩 제거)
        # v62.21 M-1: 모듈 레벨 import 사용 (함수 내 import 제거)
        pack_mood_map = {}
        try:
            if PACK_CONFIG_AVAILABLE and get_atmosphere_config:
                atmos_config = get_atmosphere_config()
                if atmos_config and atmos_config.mood_map:
                    pack_mood_map = atmos_config.mood_map
        except Exception:
            pass

        if not pack_mood_map:
            # 팩 없을 때 기본 폴백
            # v61.1 (#75): 시니어/감동 장르 분위기 추가
            pack_mood_map = {
                "horror": "ominous shadows, eerie fog",
                "tense": "harsh lighting, long shadows",
                "mysterious": "dim mysterious light, obscured details",
                "sad": "cold muted tones, overcast sky",
                "peaceful": "soft warm light, gentle atmosphere",
                "romantic": "warm golden glow, dreamy haze",
                "exciting": "dynamic lighting, vivid contrast",
                "happy": "bright warm lighting, golden hour glow, cheerful",
                "neutral": "natural indoor lighting, calm atmosphere",
            }
        atmos_kw = pack_mood_map.get(result.atmosphere, "moody atmospheric lighting")
        art_prefix = self.art_style.get('art_style_prefix', 'monochrome manga, black and white ink drawing,')
        art_texture = self.art_style.get('texture_keywords', 'high contrast lineart')

        # v61.1 (#70): 폴백에도 장면 정보 포함 (location, emotion, action)
        scene_details = []
        if result.location:
            scene_details.append(result.location)
        if result.characters:
            main_char = result.characters[0]
            if main_char.emotion and main_char.emotion != "neutral":
                scene_details.append(f"{main_char.emotion} expression")
            if main_char.action and main_char.action != "talking":
                scene_details.append(main_char.action)
        if result.time_of_day:
            scene_details.append(result.time_of_day)
        scene_detail_str = ", ".join(scene_details) if scene_details else "indoor scene"

        # v62.17: 인물 장면에는 fully clothed 추가 (NSFW 방지), 배경 장면에는 불필요
        if result.characters:
            result.sd_prompt = f"{art_prefix} (solo, {scene_detail_str}:1.3), {atmos_kw}, {art_texture}, fully clothed"
        else:
            result.sd_prompt = f"{art_prefix} ({scene_detail_str}:1.3), {atmos_kw}, {art_texture}"

        # 이미지 액션
        result.image_action = self._determine_image_action(result)

        return self._hydrate_visual_state(result)

    def _detect_emotion_from_text(self, text: str) -> str:
        """텍스트에서 감정 추출 (규칙 기반)"""
        text_lower = text.lower()

        emotion_keywords = {
            "fear": ["무섭", "두렵", "겁", "떨리", "소름", "공포"],
            "sad": ["슬프", "눈물", "울", "그리", "아프", "힘들"],
            "happy": ["기쁘", "행복", "웃", "좋", "즐거", "신나"],
            "anger": ["화나", "분노", "짜증", "열받", "미치"],
            "surprise": ["놀라", "깜짝", "헉", "어머", "세상에"],
        }

        for emotion, keywords in emotion_keywords.items():
            if any(kw in text_lower for kw in keywords):
                return emotion

        return "neutral"

    def _detect_location_from_text(self, text: str) -> str:
        """텍스트에서 장소 추출"""
        location_keywords = {
            "숲": ["숲", "나무", "산", "등산"],
            "집": ["집", "방", "거실", "부엌", "화장실"],
            "도시": ["거리", "도로", "빌딩", "가게"],
            "학교": ["학교", "교실", "운동장"],
            "한옥": ["한옥", "마루", "대청", "기와"],
        }

        for location, keywords in location_keywords.items():
            if any(kw in text for kw in keywords):
                return location

        return ""

    def _detect_time_from_text(self, text: str) -> str:
        """텍스트에서 시간대 추출"""
        time_keywords = {
            "night": ["밤", "자정", "새벽", "어둠", "달"],
            "morning": ["아침", "해돋이", "일어나"],
            "afternoon": ["낮", "점심", "오후"],
            "evening": ["저녁", "해질녘", "노을"],
        }

        for time, keywords in time_keywords.items():
            if any(kw in text for kw in keywords):
                return time

        return ""

    def _detect_atmosphere_from_text(self, text: str) -> str:
        """텍스트에서 분위기 추출 (v60: 팩에서 키워드 로딩)"""
        # v60: 팩에서 분위기 키워드 로딩
        # v62.21 M-1: 모듈 레벨 import 사용 (함수 내 import 제거)
        pack_atmos_keywords = {}
        try:
            if PACK_CONFIG_AVAILABLE and get_atmosphere_config:
                atmos_config = get_atmosphere_config()
                if atmos_config and atmos_config.keywords:
                    pack_atmos_keywords = atmos_config.keywords
        except Exception:
            pass

        if not pack_atmos_keywords:
            # 팩 없을 때 기본 폴백
            # v61.1 (#75): 시니어/감동 장르 키워드 추가
            pack_atmos_keywords = {
                "horror": ["무섭", "소름", "공포", "귀신", "유령"],
                "mysterious": ["이상", "수상", "의문", "비밀"],
                "peaceful": ["평화", "조용", "편안", "따뜻", "포근"],
                "tense": ["긴장", "위험", "급박", "충격"],
                "sad": ["슬프", "애잔", "그리움", "눈물", "울먹", "아쉬움"],
                "happy": ["기쁨", "행복", "웃음", "즐거", "감사", "축하"],
                "romantic": ["사랑", "설렘", "두근", "고백"],
            }

        for atmosphere, keywords in pack_atmos_keywords.items():
            if any(kw in text for kw in keywords):
                return atmosphere

        return "neutral"

    def _estimate_tension_from_text(self, text: str, atmosphere: str) -> int:
        """v61.1 (#71): 텍스트 기반 긴장도 추정 (1-10)"""
        tension = 4  # 기본 중간값

        # 분위기 기반 기본 tension
        atmos_tension = {
            "horror": 7, "tense": 7, "mysterious": 6,
            "sad": 4, "peaceful": 2, "neutral": 4,
            "romantic": 3, "exciting": 6, "happy": 3,
        }
        tension = atmos_tension.get(atmosphere, 4)

        # 고긴장 키워드 보정 (+2)
        high_tension = ["갑자기", "비명", "죽", "피", "도망", "심장이", "소리가", "뒤에서", "누군가"]
        if any(kw in text for kw in high_tension):
            tension = min(10, tension + 2)

        # 저긴장 키워드 보정 (-1)
        low_tension = ["평화", "웃으며", "조용히", "따뜻", "감사"]
        if any(kw in text for kw in low_tension):
            tension = max(1, tension - 1)

        # 느낌표/물음표 밀도 보정
        excl_count = text.count("!") + text.count("?")
        if excl_count >= 3:
            tension = min(10, tension + 1)

        return tension

    # ============================================================
    # v59.9.0: sd_prompt 후처리 — 범용 품질 보증
    # ============================================================

    # 캐릭터 외모 패턴 (PromptComposer가 주입하므로 SceneAnalyzer에서 제거)
    # 순서 중요: SOLO+인물 구문을 먼저, 그 다음 개별 외모 패턴
    _APPEARANCE_PATTERNS = [
        # ★ 최우선: "solo [나이/수식어] [성별]" 전체 구문 → "solo"로 교체 (with 등 잔재 방지)
        r'\bsolo\s+(?:(?:young|elderly|old|middle-aged|aged|teenage|adult|korean|japanese)\s+)*(?:woman|man|girl|boy|lady|gentleman|female|male|grandmother|grandfather)(?:\s+with)?\b',
        # 성별+나이 조합 (solo 없는 경우)
        r'\b(?:young|elderly|old|middle-aged|aged|teenage|adult)\s+(?:woman|man|girl|boy|lady|gentleman|female|male|grandmother|grandfather)\b',
        # 단독 성별 (쉼표로 구분된 독립 키워드)
        r'(?:^|,)\s*(?:woman|man|girl|boy|grandmother|grandfather)\s*(?:,|$)',
        # 머리카락 묘사
        r'\b(?:long|short|black|white|grey|gray|silver|brown|dark|blonde|curly|straight)\s+hair(?:\s+in\s+\w+)?\b',
        # 얼굴/피부 묘사
        r'\b(?:wrinkled|aged|smooth|youthful|pale|dark|tanned)\s+(?:face|skin)\b',
        # 의상 묘사 (구체적)
        r'\b(?:traditional\s+)?hanbok\b',
        r'\b(?:business\s+)?suit\b',
        r'\bcardigan\b',
        r'\bblouse\b',
        r'\bdress\s+shirt\b',
        # 체형
        r'\b(?:hunched|tall|short|thin|heavy|slim)\s+(?:posture|build|figure|frame)\b',
        # 안경/수염 등 개인 특징
        r'\b(?:glasses|spectacles|beard|mustache|bald)\b',
    ]

    def _post_process_sd_prompt(self, result: SceneAnalysisResult) -> SceneAnalysisResult:
        """
        v59.9.0: Gemini sd_prompt 후처리 — 범용 품질 보증

        역할 분리 원칙:
        - SceneAnalyzer: 장면/구도/행동/분위기만 생성
        - PromptComposer: 캐릭터 외모 주입 담당

        이 메서드는:
        1. 인물 장면에 "solo" 보장
        2. Gemini가 넣은 외모 키워드 제거 (PromptComposer 이중 삽입 방지)
        3. 빈 characters인데 인물 키워드 있으면 경고
        """
        sd = result.sd_prompt
        if not sd:
            return result

        art_prefix = self.art_style.get('art_style_prefix', '')

        # --- 1. 인물 장면에 "solo" 보장 ---
        has_real_character = False
        narrator_ids = ('narrator', '나레이션', '나레이터', 'narration')
        if result.characters:
            for c in result.characters:
                c_id = getattr(c, 'id', '') or ''
                if c_id.lower() not in narrator_ids:
                    has_real_character = True
                    break

        if has_real_character and 'solo' not in sd.lower():
            # 아트 스타일 프리픽스 뒤에 solo 삽입
            if art_prefix and sd.lower().startswith(art_prefix.lower()[:20]):
                # 프리픽스 끝에 삽입
                prefix_end = sd.find(',', len(art_prefix) - 5)
                if prefix_end > 0:
                    sd = sd[:prefix_end + 1] + ' solo,' + sd[prefix_end + 1:]
                else:
                    sd = sd + ', solo'
            else:
                sd = 'solo, ' + sd

        # --- 2. Gemini가 넣은 외모 키워드 제거 (이중 삽입 방지) ---
        for pattern in self._APPEARANCE_PATTERNS:
            # "solo woman" → "solo" 특수 처리
            if pattern.startswith(r'\bsolo\s+'):
                sd = re.sub(pattern, 'solo', sd, flags=re.IGNORECASE)
            else:
                sd = re.sub(pattern, '', sd, flags=re.IGNORECASE)

        # --- 3. 빈 characters인데 solo가 있으면 제거 (배경 장면) ---
        if not has_real_character:
            sd = re.sub(r'\bsolo\b\s*,?\s*', '', sd, flags=re.IGNORECASE)

        # --- 4. 정리: 빈 쉼표, 이중 공백 ---
        sd = re.sub(r',\s*,', ',', sd)            # ,, → ,
        sd = re.sub(r'\s+', ' ', sd)               # 이중 공백
        sd = sd.strip().strip(',').strip()          # 앞뒤 쉼표/공백

        if sd != result.sd_prompt:
            logger.debug(f"[SceneAnalyzer] v59.9.0 후처리: {result.sd_prompt[:80]}... → {sd[:80]}...")

        result.sd_prompt = sd
        return self._hydrate_visual_state(result)

    # v59.2.3: 병렬 처리 설정
    PARALLEL_MAX_WORKERS = 4    # v62.19: 8→4 (Gemini 레이트 리밋 초과 + 내부 ThreadPool 중첩 방지)

    def _create_batch_analysis_prompt(self, dialogues: List[Dict[str, str]],
                                       previous_sd_prompts: Optional[List[str]] = None,
                                       global_info: Optional[Dict[str, Any]] = None) -> str:
        """
        v62.15: 배치 씬 분석 프롬프트 (전면 재설계)
        v62.20: 청크 간 시각 연속성 — 글로벌 3막 구조 + 이전 씬 sd_prompt 참조 추가
        - 규칙 먼저 → 데이터 나중 (LLM 프롬프팅 원칙)
        - 섹션 최소화 + 각 규칙 직후 Bad/Good 예시 연결
        - 배치 고유 강점 (전체 조망, 일관성, 아크) 활용
        """
        # 캐릭터 정보
        char_info = ""
        char_id_list = []
        char_appearance = ""
        if self.character_definitions:
            char_list = []
            appearance_list = []
            for char in self.character_definitions:
                char_id = getattr(char, 'id', '')
                char_name = getattr(char, 'name', '')
                aliases = getattr(char, 'aliases', [])
                base_prompt = getattr(char, 'base_prompt', '') or getattr(char, 'base', '')
                if char_id:
                    char_id_list.append(char_id)
                    alias_str = ", ".join(aliases) if aliases else "없음"
                    char_list.append(f"- {char_id}: {char_name} (별칭: {alias_str})")
                    if base_prompt:
                        appearance_list.append(f"- {char_name}({char_id}): {base_prompt}")
            if char_list:
                char_info = "\n".join(char_list)
            if appearance_list:
                char_appearance = "\n".join(appearance_list)

        # 캐릭터 외모 섹션 (sd_prompt에 넣지 말라는 경고 포함)
        char_appearance_section = ""
        if char_appearance:
            char_appearance_section = f"""
CHARACTER APPEARANCE (post-processing auto-injects these — DO NOT put in sd_prompt!):
{char_appearance}
→ Putting appearance in sd_prompt causes double-injection and visual artifacts. Use character ID only."""

        # 대사 목록 JSON
        dialogue_list = json.dumps(
            [{"index": i, "speaker": d.get("speaker", "나레이터"), "text": d.get("text", "")}
             for i, d in enumerate(dialogues)],
            ensure_ascii=False, indent=2
        )

        art_style_prefix = self.art_style.get('art_style_prefix', 'monochrome manga, black and white ink drawing,')
        forbidden_styles = self.art_style.get('forbidden_styles', 'colorful, 3d render, photorealistic')
        # art_style_desc: 현재 프롬프트에서 미사용 — 삭제하지 않고 주석 처리 (향후 STEP 1에 추가 가능)
        # art_style_desc = self.art_style.get('art_style_description', 'the same manga artist drew all panels')
        texture_kw = self.art_style.get('texture_keywords', 'clean lineart, high contrast')
        # pack_examples: 팩의 good_examples는 외모 키워드가 섞일 수 있어 프롬프트에 삽입하지 않음
        # _format_good_examples() 호출 자체를 제거 (미사용 + 위험)
        total = len(dialogues)

        # v62.20: 3막 분기점 — 글로벌 스토리 위치 기반 (청크 분할 시에도 올바른 텐션 매핑)
        if global_info and global_info.get("total_scenes", 0) > total:
            # 청크 모드: 글로벌 인덱스 기반으로 이 청크가 어느 Act에 속하는지 계산
            g_total = global_info["total_scenes"]
            g_start = global_info["chunk_start"]
            g_act1_end = g_total // 3 - 1
            g_act2_end = (g_total * 2) // 3 - 1
            # 이 청크의 로컬 인덱스(0~total-1) → 글로벌 인덱스(g_start~g_start+total-1) 매핑
            act_lines = []
            for local_i in range(total):
                gi = g_start + local_i
                if gi <= g_act1_end:
                    act_lines.append((local_i, "Act 1: Setup/exposition", "2-4"))
                elif gi <= g_act2_end:
                    act_lines.append((local_i, "Act 2: Rising conflict", "4-7"))
                else:
                    act_lines.append((local_i, "Act 3: Climax/resolution", "8-10 at peak, 2-4 at end"))
            # 연속 구간 요약 (예: "index 0-10: Act 2, tension 4-7")
            act_ranges = []
            if not act_lines:
                act_lines = [(0, "Act 1: Setup/exposition", "2-4")]
            cur_act, cur_tension, range_start = act_lines[0][1], act_lines[0][2], 0
            for local_i, act, tension in act_lines[1:]:
                if act != cur_act:
                    act_ranges.append(f"- index {range_start} to {local_i - 1}: {cur_act} → tension_level {cur_tension}")
                    cur_act, cur_tension, range_start = act, tension, local_i
            act_ranges.append(f"- index {range_start} to {total - 1}: {cur_act} → tension_level {cur_tension}")
            act_guide = "\n".join(act_ranges)
            chunk_position = f"This is chunk {global_info['chunk_index']+1}/{global_info['total_chunks']} of a {g_total}-scene story (global scenes {g_start} to {global_info['chunk_end']})."
            # act1_last 등은 프롬프트 하단 예시에서 미사용이므로 더미 할당
            act1_last = max(0, total // 3 - 1)
        else:
            # 단일 청크 / 글로벌 정보 없음: 기존 동작
            act1_last = max(0, total // 3 - 1)
            act2_first = act1_last + 1
            act2_last = max(act2_first, (total * 2) // 3 - 1)
            act3_first = act2_last + 1
            act_guide = (
                f"- index 0 to {act1_last}: Act 1: Setup/exposition → tension_level 2-4\n"
                f"- index {act2_first} to {act2_last}: Act 2: Rising conflict → tension_level 4-7\n"
                f"- index {act3_first} to {total-1}: Act 3: Climax/resolution → tension_level 8-10 at peak, 2-4 at end"
            )
            chunk_position = ""

        # good_examples에서 외모 키워드 포함 여부 확인 후 안전한 예시로 보정
        # (_format_good_examples()는 팩의 art_style.good_examples를 사용하므로 그대로 유지,
        #  단 Bad 예시에서 이미 외모 금지를 명시함)

        # v62.20: 이전 청크 sd_prompt 참조 (시각 연속성)
        prev_prompts_section = ""
        if previous_sd_prompts:
            g_start = global_info["chunk_start"] if global_info else 0
            prev_lines = []
            for pi, sp in enumerate(previous_sd_prompts):
                prev_idx = g_start - len(previous_sd_prompts) + pi
                prev_lines.append(f"  [scene {prev_idx}]: {sp[:150]}")
            prev_prompts_section = f"""
━━━ PREVIOUS SCENES (visual continuity reference) ━━━
The following sd_prompts were generated for scenes immediately before this chunk:
{chr(10).join(prev_lines)}
→ If same location recurs in this chunk, reuse 70%+ of their location/lighting keywords.
→ Maintain consistent atmosphere progression — do NOT reset mood/tension abruptly.
"""

        prompt = f"""You are a visual director. Read ALL {total} dialogue lines below, understand the full story arc, then produce a JSON array with one scene design per line.
{f"{chr(10)}{chunk_position}" if chunk_position else ""}
{prev_prompts_section}
━━━ STEP 1: MAP THE DRAMATIC ARC ━━━
Before writing any sd_prompt, read all {total} lines and assign tension_level based on story position:
{act_guide}
Each index belongs to exactly ONE act (no overlap). tension_level MUST follow the mapping above — do NOT assign the same value to every entry.

━━━ STEP 2: CHARACTER & APPEARANCE RULES ━━━
{f"Characters (use these IDs only — Korean names FORBIDDEN):{chr(10)}{char_info}" if char_info else "No character definitions loaded. Use 'narrator' as the only allowed ID."}
Allowed character IDs: [{', '.join(char_id_list) if char_id_list else 'narrator'}]
{char_appearance_section}
CRITICAL: characters[].name MUST be one of the English IDs listed above. Korean names are FORBIDDEN.
CRITICAL: speaker is 나레이션/나레이터/narrator/narration → characters[] MUST be [] (narrator = voice only, no visible body).

━━━ STEP 3: SCENE TYPE — assign ONE type per entry ━━━

TYPE A — Character speaking or acting:
  characters: [{{"name": "<one of the allowed IDs above>", "emotion": "fear", "action": "trembling", "is_speaker": true}}]
  sd_prompt: → see Good examples below (TYPE A)
  Rule: Draw ONLY the speaker. Listener is off-screen.

TYPE B — Narration describing a specific character physically doing something:
  (ONLY when narration says someone IS doing a physical action — not atmosphere/thought/sound)
  characters: [{{"name": "<one of the allowed IDs above>", "emotion": "fear", "action": "running", "is_speaker": false}}]
  sd_prompt: → see Good examples below (TYPE B)
  ✓ "그녀는 복도를 달렸다" → TYPE B (physical action)
  ✗ "공포가 밀려왔다" → NOT TYPE B (atmosphere → use TYPE C)

TYPE C — Background / object / atmosphere (NO person):
  Use for 30-40% of all narration lines.
  characters: []   ← EMPTY, no exceptions
  sd_prompt: → see Good examples below (TYPE C)
  NO "solo". NO person keywords.
  ✓ Use TYPE C for: setting description / time passing / internal monologue / sound / object focus / emotional atmosphere
  Example: "그날 밤, 마을은 고요했다" → "{art_style_prefix} (quiet village at night:1.4), moonlight, empty street, eerie silence, wide shot"
  Example: "책상 위에 핏자국 묻은 편지가 있었다" → "{art_style_prefix} (blood-stained letter on desk:1.4), dim lamp, dust, extreme close-up"

━━━ STEP 4: SD PROMPT CONSTRUCTION RULES ━━━

Write sd_prompt in this exact order:
  1. "{art_style_prefix}"  ← always first, never change
  2. focal element with weight: (action+emotion:1.3) or (object:1.4) or (location:1.3)
  3. key prop from dialogue (letter / knife / phone / etc.) — only if dialogue mentions it
  4. location keywords
  5. lighting/mood
  6. camera angle
  7. "fully clothed"  ← always last (TYPE A/B only — omit for TYPE C which has no person)

Weight rules: use (keyword:1.3~1.5) on 1-2 elements only. Never exceed 1.5.
Token budget: 10-15 keywords total, comma-separated. No sentences.
Forbidden styles: {forbidden_styles}
Texture: {texture_kw}

APPEARANCE FORBIDDEN in sd_prompt:
  ✗ "elderly woman with grey hair" → auto-injected from character ID
  ✗ "old man in hanbok" → auto-injected
  ✓ Just use "solo, clenched fist, angry expression" — appearance applied automatically

PROPS RULE: A prop (letter/knife/photograph) appears in sd_prompt ONLY when that dialogue mentions it.
  ✗ Do NOT carry props across to the next scene.

CAMERA DISTRIBUTION across all {total} scenes:
  ~30% wide shots (establishing, space description)
  ~40% close-ups (emotional dialogue, reaction)
  ~30% dutch/low/high/POV angles (tension, confrontation, discovery)
  3 consecutive identical angles FORBIDDEN.

Good sd_prompt examples (action/object/location only — NO appearance words):
✓ TYPE A: "{art_style_prefix} (solo, furious expression, slamming table:1.3), traditional Korean room, harsh overhead shadow, close-up, fully clothed"
✓ TYPE A: "{art_style_prefix} (solo, trembling, clutching phone:1.3), dimly lit bedroom, cold blue light, medium shot, fully clothed"
✓ TYPE B: "{art_style_prefix} (solo, running desperately:1.3), dark narrow hallway, flickering fluorescent light, dynamic low angle, fully clothed"
✓ TYPE C: "{art_style_prefix} (blood-stained letter on wooden desk:1.4), dim lamp, dust particles, extreme close-up"
✓ TYPE C: "{art_style_prefix} (empty village road at night:1.3), moonlight, dense fog, eerie silence, wide establishing shot"
✗ Bad: "a dark eerie scene showing a young man standing alone in fear" (sentences forbidden — keywords only)
✗ Bad: "elderly grandmother with white hair in hanbok, angry expression" (NO appearance — auto-injected from character ID)
✗ Bad: "{art_style_prefix} horror, dark, scary, tense atmosphere" (mood only, no focal object = empty meaningless image)

━━━ STEP 5: VISUAL CONSISTENCY ━━━
Same location recurring (e.g., 거실 at index 3 and index 18):
  → Keep 70%+ of location/lighting keywords identical
  → Only change: action, emotion, camera angle
Time passes within same location → change only lighting keywords (night→faint dawn light)
Location changes → share 1-2 atmospheric keywords for smooth visual transition.

━━━ OUTPUT ━━━
Return a JSON array with exactly {total} objects (index 0 to {total-1}).
Pure JSON only — no markdown, no code blocks, no text before or after the array.
Keep each sd_prompt to 10-15 keywords max to stay within output token limits.

Schema — TWO examples showing the difference between character scene and background scene:

TYPE A/B example (character present — use YOUR allowed ID, not "grandma"):
{{
  "index": 0,
  "characters": [{{"name": "{char_id_list[0] if char_id_list else 'grandma'}", "emotion": "fear", "action": "trembling", "is_speaker": true}}],
  "location": "거실",
  "location_detail": "living room at night",
  "time_of_day": "night",
  "weather": "none",
  "atmosphere": "tense",
  "story_beat": "rising",
  "tension_level": 6,
  "scene_keywords": ["confrontation", "shadows", "candlelight"],
  "sd_prompt": "{art_style_prefix} (solo, trembling, covering mouth:1.3), living room, candlelight, dutch angle, fully clothed",
  "camera_shot": "dutch angle",
  "key_props": ["candle"],
  "outfit_hint": ""
}}

TYPE C example (NO person — characters MUST be [], NO fully clothed):
{{
  "index": 1,
  "characters": [],
  "location": "복도",
  "location_detail": "dark corridor",
  "time_of_day": "night",
  "weather": "none",
  "atmosphere": "horror",
  "story_beat": "rising",
  "tension_level": 7,
  "scene_keywords": ["darkness", "isolation", "cold"],
  "sd_prompt": "{art_style_prefix} (long dark corridor:1.4), moonlight through window, cracked floor, wide shot",
  "camera_shot": "wide shot",
  "key_props": [],
  "outfit_hint": ""
}}

RULE: characters[] = [] for TYPE C. Do NOT invent a character for narrator-only / atmosphere lines.

━━━ DIALOGUES TO ANALYZE ━━━
{dialogue_list}

Output the JSON array now (start with [ immediately):"""

        return prompt

    # v62.18: 청크 크기 — Gemini 출력 토큰 한도(8K) 안에 들도록 35개씩 분할
    BATCH_CHUNK_SIZE = 35

    def _analyze_batch_chunked(self, dialogues: List[Dict[str, str]]) -> List[SceneAnalysisResult]:
        """
        v62.18: 청크 단위 배치 호출
        104개 → 35개씩 3청크 = Gemini 3회 호출 (출력 토큰 한도 안전)
        청크 실패 시 → 해당 청크만 병렬 폴백 (전체 순차 폴백 방지)
        v62.20: 청크 간 시각 연속성 보장 — 이전 청크 sd_prompts + 글로벌 3막 구조 전달
        """
        total = len(dialogues)
        chunk_size = self.BATCH_CHUNK_SIZE
        chunks = []
        for start in range(0, total, chunk_size):
            end = min(start + chunk_size, total)
            chunks.append((start, end))

        logger.info(f"[SceneAnalyzer] v62.18 청크 배치: {total}개 → {len(chunks)}청크 (각 {chunk_size}개, Gemini {len(chunks)}회)")

        all_results: List[SceneAnalysisResult] = []
        batch_start = time.time()
        # v62.20: 청크 간 시각 연속성 — 이전 청크의 마지막 5개 sd_prompt 축적
        prev_chunk_prompts: List[str] = []

        for chunk_idx, (start, end) in enumerate(chunks):
            chunk_dialogues = dialogues[start:end]
            chunk_label = f"청크 {chunk_idx+1}/{len(chunks)} [{start}-{end-1}]"

            # v62.20: 글로벌 스토리 위치 정보 (3막 구조 올바른 매핑용)
            global_info = {
                "total_scenes": total,
                "chunk_start": start,
                "chunk_end": end - 1,
                "chunk_index": chunk_idx,
                "total_chunks": len(chunks),
            }

            try:
                logger.info(f"[SceneAnalyzer] {chunk_label}: {len(chunk_dialogues)}개 배치 호출")
                chunk_results = self._analyze_batch_single_call(
                    chunk_dialogues, index_offset=start,
                    previous_sd_prompts=prev_chunk_prompts,
                    global_info=global_info,
                )
                all_results.extend(chunk_results)
                logger.info(f"[SceneAnalyzer] {chunk_label}: 성공 ({len(chunk_results)}개)")

                # v62.20: 다음 청크를 위해 이 청크의 마지막 5개 sd_prompt 수집
                prev_chunk_prompts = [r.sd_prompt for r in chunk_results[-5:] if r.sd_prompt]
            except Exception as e:
                logger.warning(
                    f"[SceneAnalyzer] {chunk_label}: 배치 실패 ({redact_sensitive_text(e)}) → 병렬 폴백"
                )
                # 해당 청크만 병렬 폴백 (전체가 아니라 실패 청크만)
                fallback_results = self._analyze_batch_parallel(chunk_dialogues)
                # 인덱스 보정
                for i, r in enumerate(fallback_results):
                    r.dialogue_index = start + i
                    r.scene_id = f"scene_{start + i:04d}"
                all_results.extend(fallback_results)
                logger.info(f"[SceneAnalyzer] {chunk_label}: 병렬 폴백 완료 ({len(fallback_results)}개)")
                # 폴백 결과에서도 sd_prompt 수집 (시각 연속성 유지 시도)
                prev_chunk_prompts = [r.sd_prompt for r in fallback_results[-5:] if r.sd_prompt]

            # 청크 간 rate limiting (0.3초)
            if chunk_idx < len(chunks) - 1:
                time.sleep(0.3)

        elapsed = time.time() - batch_start
        logger.info(f"[SceneAnalyzer] v62.20 청크 배치 완료: {len(all_results)}/{total}개 ({elapsed:.1f}s)")
        return all_results

    def _analyze_batch_single_call(self, dialogues: List[Dict[str, str]],
                                    index_offset: int = 0,
                                    previous_sd_prompts: Optional[List[str]] = None,
                                    global_info: Optional[Dict[str, Any]] = None) -> List[SceneAnalysisResult]:
        """
        v62.10: 단일 청크를 1회 Gemini 호출로 분석
        v62.18: index_offset 추가 (청크 분할 시 글로벌 인덱스 유지)
        v62.20: previous_sd_prompts + global_info 추가 (청크 간 시각 연속성)
        실패 시 → 예외 발생 (호출자가 폴백 결정)
        """
        total = len(dialogues)
        logger.info(f"[SceneAnalyzer] 배치 단일 호출: {total}개 (offset={index_offset})")

        if not self.gemini_client:
            raise RuntimeError("Gemini 클라이언트 없음")

        try:
            prompt = self._create_batch_analysis_prompt(
                dialogues,
                previous_sd_prompts=previous_sd_prompts,
                global_info=global_info,
            )
            start_time = time.time()
            try:
                response = self.gemini_client.generate_content(
                    prompt, timeout=180  # v62.18: 35개 청크 기준 충분한 시간
                )
            except TypeError:
                response = self.gemini_client.generate_content(prompt)
            elapsed = time.time() - start_time

            if not response or not hasattr(response, 'text') or not response.text:
                raise RuntimeError("배치 호출 빈 응답")

            # JSON 파싱
            json_str = response.text.strip()
            if "```json" in json_str:
                json_str = json_str.split("```json")[1].split("```")[0]
            elif "```" in json_str:
                json_str = json_str.split("```")[1].split("```")[0]

            data = json.loads(json_str)
            if not isinstance(data, list):
                raise RuntimeError("배치 응답이 JSON 배열 아님")

            # 인덱스별로 정렬
            data_by_index = {item.get("index", i): item for i, item in enumerate(data)}

            results = []
            for i, d in enumerate(dialogues):
                speaker = d.get("speaker", "나레이터")
                text = d.get("text", "")
                item = data_by_index.get(i)

                global_idx = index_offset + i
                if not item:
                    logger.warning(f"[SceneAnalyzer] [{global_idx}] 배치 결과 없음 → 개별 폴백")
                    result = self._fallback_analysis(text, speaker, global_idx)
                else:
                    # SceneAnalysisResult 조립
                    result = SceneAnalysisResult(
                        scene_id=f"scene_{global_idx:04d}",
                        dialogue_index=global_idx,
                        original_dialogue=text,
                        speaker=speaker
                    )
                    for char_data in item.get("characters", []):
                        char_name = char_data.get("name", "")
                        result.characters.append(CharacterState(
                            id=self._get_character_id(char_name),
                            name=char_name,
                            emotion=char_data.get("emotion", "neutral"),
                            action=char_data.get("action", ""),
                            is_speaker=char_data.get("is_speaker", False)
                        ))
                    result.location = item.get("location", "")
                    result.location_detail = item.get("location_detail", "")
                    result.time_of_day = item.get("time_of_day", "")
                    result.weather = item.get("weather", "")
                    result.atmosphere = item.get("atmosphere", "")
                    result.story_beat = item.get("story_beat", "")
                    # v62.17: tension_level 방어 파싱 + 범위 클램핑 1~10
                    _tl = item.get("tension_level", 5)
                    try:
                        result.tension_level = max(1, min(10, int(str(_tl).strip().split()[0])))
                    except (ValueError, IndexError):
                        result.tension_level = 5
                    result.scene_keywords = item.get("scene_keywords", [])
                    result.sd_prompt = item.get("sd_prompt", "")
                    result.camera_shot = item.get("camera_shot", "")
                    result.key_props = item.get("key_props", [])
                    result.outfit_hint = item.get("outfit_hint", "")
                    result = self._post_process_sd_prompt(result)

                # image_action 순차 결정 (순서 의존)
                result.image_action = self._determine_image_action(result)
                self.previous_scenes.append(result)
                if len(self.previous_scenes) > self.max_cache_size:
                    self.previous_scenes.pop(0)

                results.append(result)

            logger.info(
                f"[SceneAnalyzer] v62.10 배치 완료: {total}개 → Gemini 1회 ({elapsed:.1f}s) "
                f"파싱 성공 {len([r for r in results if r.location])}개"
            )
            return results

        except json.JSONDecodeError as e:
            # v62.17: 부분 복구 시도 — 잘린 JSON 배열 끝에 ] 붙여서 재파싱
            logger.warning(f"[SceneAnalyzer] 배치 JSON 파싱 실패: {e} → 부분 복구 시도")
            try:
                raw = response.text.strip() if response and hasattr(response, 'text') else ""
                if raw and raw.startswith("[") and not raw.rstrip().endswith("]"):
                    fixed = raw.rstrip().rstrip(",") + "]"
                    data = json.loads(fixed)
                    if isinstance(data, list) and len(data) > 0:
                        logger.info(f"[SceneAnalyzer] 부분 복구 성공: {len(data)}/{total}개 → 나머지는 개별 폴백")
                        json_str = fixed  # 복구된 JSON으로 정상 경로 재진입
                        # data_by_index 조립 및 results 반환 (정상 경로 코드 중복 최소화)
                        data_by_index = {item.get("index", i): item for i, item in enumerate(data)}
                        results = []
                        for i, d in enumerate(dialogues):
                            # v62.21 C-5: 글로벌 인덱스 사용 (청크 2+ 에서 오프셋 적용)
                            global_idx = index_offset + i
                            speaker = d.get("speaker", "나레이터")
                            text = d.get("text", "")
                            item = data_by_index.get(i)
                            if not item:
                                result = self._fallback_analysis(text, speaker, global_idx)
                            else:
                                result = SceneAnalysisResult(
                                    scene_id=f"scene_{global_idx:04d}", dialogue_index=global_idx,
                                    original_dialogue=text, speaker=speaker
                                )
                                for char_data in item.get("characters", []):
                                    char_name = char_data.get("name", "")
                                    result.characters.append(CharacterState(
                                        id=self._get_character_id(char_name), name=char_name,
                                        emotion=char_data.get("emotion", "neutral"),
                                        action=char_data.get("action", ""),
                                        is_speaker=char_data.get("is_speaker", False)
                                    ))
                                result.location = item.get("location", "")
                                result.location_detail = item.get("location_detail", "")
                                result.time_of_day = item.get("time_of_day", "")
                                result.weather = item.get("weather", "")
                                result.atmosphere = item.get("atmosphere", "")
                                result.story_beat = item.get("story_beat", "")
                                _tl = item.get("tension_level", 5)
                                try:
                                    result.tension_level = max(1, min(10, int(str(_tl).strip().split()[0])))
                                except (ValueError, IndexError):
                                    result.tension_level = 5
                                result.scene_keywords = item.get("scene_keywords", [])
                                result.sd_prompt = item.get("sd_prompt", "")
                                result.camera_shot = item.get("camera_shot", "")
                                result.key_props = item.get("key_props", [])
                                result.outfit_hint = item.get("outfit_hint", "")
                                result = self._post_process_sd_prompt(result)
                            result.image_action = self._determine_image_action(result)
                            self.previous_scenes.append(result)
                            if len(self.previous_scenes) > self.max_cache_size:
                                self.previous_scenes.pop(0)
                            results.append(result)
                        return results
            except Exception as e2:
                logger.warning(f"[SceneAnalyzer] 부분 복구도 실패: {e2}")
            raise  # v62.18: 호출자(_analyze_batch_chunked)가 청크별 폴백 결정
        except Exception as e:
            raise  # v62.18: 호출자가 해당 청크만 병렬 폴백

    def analyze_scene_batch(self, dialogues: List[Dict[str, str]],
                            parallel: bool = True) -> List[SceneAnalysisResult]:
        """
        여러 대사 일괄 분석
        v62.10: 전체 턴 1회 배치 호출 우선 (비용 최소화)
        v62.18: 35개 청크 분할 (Gemini 8K 출력 한도 대응, 3회 호출로 104개 처리)
                실패 시 → 병렬 폴백 (순차 대신)

        Args:
            dialogues: [{"speaker": "...", "text": "..."}, ...]
            parallel: True면 병렬 분석 (기본값, v62.18에서는 청크 배치 우선)

        Returns:
            List[SceneAnalysisResult]
        """
        total = len(dialogues)
        logger.info(f"[SceneAnalyzer] 일괄 분석 시작: {total}개 대사 (v62.18 청크 배치)")

        # 소량(3개 이하)은 순차
        if total <= 3:
            return self._analyze_batch_sequential(dialogues)

        # v62.18: 청크 단위 배치 호출 (35개씩 → 104개 = 3회 Gemini 호출)
        return self._analyze_batch_chunked(dialogues)

    def _analyze_batch_sequential(self, dialogues: List[Dict[str, str]]) -> List[SceneAnalysisResult]:
        """v59.3.0: 순차 분석 (이전 sd_prompt 축적하여 전달)"""
        total = len(dialogues)
        results = []
        context = []
        recent_sd_prompts = []  # v59.3.0: sd_prompt 축적
        batch_start = time.time()
        fallback_count = 0
        log_interval = max(1, total // 10)

        for i, d in enumerate(dialogues):
            speaker = d.get("speaker", "나레이터")
            text = d.get("text", "")

            result = self.analyze_dialogue(
                dialogue=text,
                speaker=speaker,
                index=i,
                context_dialogues=context[-5:],
                previous_sd_prompts=recent_sd_prompts[-5:]  # v59.5: 5개로 확장 (연속성 강화)
            )
            results.append(result)
            context.append(f"[{speaker}] {text}")

            # v59.3.0: sd_prompt 축적
            sd_prompt = getattr(result, 'sd_prompt', '')
            if sd_prompt:
                recent_sd_prompts.append(sd_prompt)
                if len(recent_sd_prompts) > 5:
                    recent_sd_prompts.pop(0)

            if result.atmosphere == "neutral" and not result.location:
                fallback_count += 1

            if (i + 1) % log_interval == 0 or (i + 1) == total:
                elapsed = time.time() - batch_start
                pct = ((i + 1) / total) * 100
                logger.info(
                    f"[SceneAnalyzer] 진행: {i + 1}/{total} ({pct:.0f}%) "
                    f"[{elapsed:.1f}s 경과]"
                )

        elapsed_total = time.time() - batch_start
        logger.info(
            f"[SceneAnalyzer] 순차 분석 완료: {total}개 장면 ({elapsed_total:.1f}s), "
            f"폴백 {fallback_count}건"
        )
        return results

    # v61.1 (#69): 배치 단위 크기 (순차+병렬 하이브리드)
    PARALLEL_BATCH_SIZE = 10

    def _analyze_batch_parallel(self, dialogues: List[Dict[str, str]]) -> List[SceneAnalysisResult]:
        """
        v59.2.3: ThreadPoolExecutor 병렬 분석
        v61.1 (#69): 배치 단위 순차+병렬 하이브리드
                 → 10턴씩 배치를 순차 처리 (배치 간 previous_sd_prompts 전달)
                 → 배치 내부는 병렬 (속도 유지)
        v61.1 (#77): 배치 간 0.5초 sleep (rate limiting)

        핵심 원리:
        - 10턴 배치 내부: 병렬 Gemini 호출 (같은 배치의 sd_prompts 공유 불가)
        - 배치 간: 이전 배치의 sd_prompts를 다음 배치에 전달 (연속성)
        - _determine_image_action()은 최종 순차 적용 (이전 장면 비교 필요)
        """
        total = len(dialogues)
        batch_start = time.time()

        # Phase 1: 컨텍스트 사전 계산 (순차, 매우 빠름)
        contexts: List[List[str]] = []
        running_context: List[str] = []
        for d in dialogues:
            speaker = d.get("speaker", "나레이터")
            text = d.get("text", "")
            contexts.append(running_context[-5:].copy())  # v59.5: 5개로 확장
            running_context.append(f"[{speaker}] {text}")

        logger.info(f"[SceneAnalyzer] 컨텍스트 사전 계산 완료, 배치 병렬 분석 시작 (batch={self.PARALLEL_BATCH_SIZE}, workers={self.PARALLEL_MAX_WORKERS})")

        # Phase 2: 배치 단위 병렬 Gemini API 호출
        raw_results: Dict[int, SceneAnalysisResult] = {}
        completed_count = 0
        fallback_count = 0
        log_interval = max(1, total // 10)
        recent_sd_prompts: List[str] = []  # v61.1 (#69): 배치 간 sd_prompt 전달

        for batch_idx in range(0, total, self.PARALLEL_BATCH_SIZE):
            batch_end = min(batch_idx + self.PARALLEL_BATCH_SIZE, total)
            batch_dialogues = list(range(batch_idx, batch_end))

            # v61.1 (#77): 배치 간 rate limiting (첫 배치 제외)
            if batch_idx > 0:
                time.sleep(0.5)

            with ThreadPoolExecutor(max_workers=self.PARALLEL_MAX_WORKERS) as executor:
                future_to_index = {}
                for i in batch_dialogues:
                    d = dialogues[i]
                    speaker = d.get("speaker", "나레이터")
                    text = d.get("text", "")

                    # v61.1 (#69): 이전 배치의 sd_prompts 전달
                    future = executor.submit(
                        self.analyze_dialogue,
                        dialogue=text,
                        speaker=speaker,
                        index=i,
                        context_dialogues=contexts[i],
                        skip_action_decision=True,
                        previous_sd_prompts=recent_sd_prompts[-5:] if recent_sd_prompts else None
                    )
                    future_to_index[future] = i

                for future in as_completed(future_to_index):
                    idx = future_to_index[future]
                    try:
                        result = future.result()
                        raw_results[idx] = result

                        if result.atmosphere == "neutral" and not result.location:
                            fallback_count += 1

                    except Exception as e:
                        logger.error(f"[SceneAnalyzer] [{idx}] 병렬 분석 예외: {redact_sensitive_text(e)}")
                        d = dialogues[idx]
                        # VER-4: 폴백 분석도 실패할 수 있으므로 이중 보호
                        try:
                            raw_results[idx] = self._fallback_analysis(
                                d.get("text", ""), d.get("speaker", "나레이터"), idx
                            )
                        except Exception as e2:
                            logger.error(f"[SceneAnalyzer] [{idx}] 폴백도 실패: {redact_sensitive_text(e2)}")
                            raw_results[idx] = SceneAnalysisResult(
                                scene_id=f"scene_{idx:04d}",
                                dialogue_index=idx,
                                original_dialogue=d.get("text", ""),
                                speaker=d.get("speaker", "나레이터"),
                                image_action="new"
                            )
                        fallback_count += 1

                    completed_count += 1
                    if completed_count % log_interval == 0 or completed_count == total:
                        elapsed = time.time() - batch_start
                        pct = (completed_count / total) * 100
                        logger.info(
                            f"[SceneAnalyzer] 병렬 진행: {completed_count}/{total} ({pct:.0f}%) "
                            f"[{elapsed:.1f}s 경과]"
                        )

            # v61.1 (#69): 이 배치 결과에서 sd_prompts 수집
            for i in batch_dialogues:
                if i in raw_results:
                    sd = getattr(raw_results[i], 'sd_prompt', '')
                    if sd:
                        recent_sd_prompts.append(sd)
                        if len(recent_sd_prompts) > 10:
                            recent_sd_prompts.pop(0)

        parallel_elapsed = time.time() - batch_start
        logger.info(f"[SceneAnalyzer] Gemini 병렬 호출 완료: {parallel_elapsed:.1f}s")

        # Phase 3: 순차 image_action 결정 (순서 의존적)
        ordered_results: List[SceneAnalysisResult] = []
        for i in range(total):
            # v62.21 H-11: raw_results[i] KeyError 방지 (future 무음 실패 대비)
            result = raw_results.get(i)
            if result is None:
                d = dialogues[i] if i < len(dialogues) else {"speaker": "나레이터", "text": ""}
                logger.warning(f"[SceneAnalyzer] [{i}] 병렬 결과 누락 → 폴백")
                result = self._fallback_analysis(
                    d.get("text", ""), d.get("speaker", "나레이터"), i
                )
                raw_results[i] = result

            # 순차적으로 image_action 결정 + 캐시 업데이트
            result.image_action = self._determine_image_action(result)
            self.previous_scenes.append(result)
            if len(self.previous_scenes) > self.max_cache_size:
                self.previous_scenes.pop(0)

            ordered_results.append(result)

        elapsed_total = time.time() - batch_start
        logger.info(
            f"[SceneAnalyzer] 병렬 분석 완료: {total}개 장면 ({elapsed_total:.1f}s, "
            f"순차 대비 ~{total * 10 / max(elapsed_total, 0.1):.0f}x), "
            f"폴백 {fallback_count}건"
        )
        return ordered_results

    def reset_cache(self):
        """이전 장면 캐시 초기화"""
        self.previous_scenes.clear()
        logger.info("[SceneAnalyzer] 캐시 초기화됨")

    def get_scene_summary(self, results: List[SceneAnalysisResult]) -> Dict[str, Any]:
        """분석 결과 요약"""
        if not results:
            return {}

        action_counts = {"new": 0, "expression": 0, "pose": 0, "reuse": 0}
        locations = set()
        atmospheres = set()

        for r in results:
            action_counts[r.image_action] = action_counts.get(r.image_action, 0) + 1
            if r.location:
                locations.add(r.location)
            if r.atmosphere:
                atmospheres.add(r.atmosphere)

        return {
            "total_scenes": len(results),
            "action_counts": action_counts,
            "unique_locations": list(locations),
            "unique_atmospheres": list(atmospheres),
            "new_images_needed": action_counts["new"],
            "expression_swaps": action_counts["expression"],
            "pose_swaps": action_counts["pose"],
            "reuses": action_counts["reuse"],
        }


# ============================================================
# 테스트
# ============================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    print("=== SceneAnalyzer 테스트 ===\n")

    # 테스트용 캐릭터 정의 (Mock)
    class MockCharDef:
        def __init__(self, id, name, aliases):
            self.id = id
            self.name = name
            self.aliases = aliases

    characters = [
        MockCharDef("narrator", "나레이터", ["화자", "이야기꾼"]),
        MockCharDef("chulsoo", "철수", ["주인공", "청년"]),
        MockCharDef("younghee", "영희", ["여자", "그녀"]),
    ]

    analyzer = SceneAnalyzer(gemini_client=None, character_definitions=characters)

    # 테스트 대사
    test_dialogues = [
        {"speaker": "나레이터", "text": "그날 밤, 철수는 숲속 깊은 곳에서 이상한 소리를 들었다."},
        {"speaker": "철수", "text": "뭐지... 이 소리는? 소름이 돋는다..."},
        {"speaker": "나레이터", "text": "갑자기 눈앞에 하얀 그림자가 나타났다."},
        {"speaker": "철수", "text": "으악! 뭐야!"},
    ]

    print("1. 일괄 분석 테스트:")
    results = analyzer.analyze_scene_batch(test_dialogues)

    for r in results:
        print(f"\n   [{r.dialogue_index}] {r.speaker}: {r.original_dialogue[:20]}...")
        print(f"       action: {r.image_action}")
        print(f"       emotion: {r.characters[0].emotion if r.characters else 'N/A'}")
        print(f"       atmosphere: {r.atmosphere}")

    print("\n2. 요약:")
    summary = analyzer.get_scene_summary(results)
    print(f"   총 장면: {summary['total_scenes']}")
    print(f"   새 이미지 필요: {summary['new_images_needed']}")
    print(f"   표정 변경: {summary['expression_swaps']}")
    print(f"   포즈 변경: {summary['pose_swaps']}")
    print(f"   재사용: {summary['reuses']}")

    print("\n[OK] 테스트 완료!")
