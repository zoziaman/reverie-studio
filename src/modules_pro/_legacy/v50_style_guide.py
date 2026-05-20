# src/modules_pro/v50_style_guide.py
# ============================================================
# [v50] 프리미엄 스타일 가이드
#
# 불쾌한 골짜기 방지를 위한 추상적 인물 표현 + 고품질 배경
# - 사람: 실루엣, 뒷모습, 색깔 형체 (얼굴/신체 디테일 없음)
# - 배경/사물: 고품질 상세 묘사
# ============================================================
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum


class ChannelStyle(Enum):
    """채널별 스타일"""
    HORROR = "horror"
    SENIOR_TOUCHING = "senior_touching"
    SENIOR_MAKJANG = "senior_makjang"


@dataclass
class V50StyleConfig:
    """v50 스타일 설정"""
    # 인물 표현 방식
    human_style: str
    human_weight: float  # 프롬프트 가중치 (1.0 ~ 1.5)

    # 배경 품질
    background_quality: str
    background_weight: float

    # 네거티브 (피해야 할 것들)
    avoid_human: List[str]  # 인물 관련 피해야 할 요소
    avoid_general: List[str]  # 일반 피해야 할 요소

    # 스타일 프리셋
    style_positive: str
    style_negative: str


# ============================================================
# 채널별 스타일 설정
# ============================================================
HORROR_STYLE = V50StyleConfig(
    # v59.5.7: 만화 스타일 인물 (실루엣 → 표정 있는 캐릭터)
    human_style="manga style character, expressive face, dramatic expression, fully clothed, monochrome ink drawing",
    human_weight=1.3,

    # 배경: 고품질 공포 분위기
    background_quality="highly detailed background, 8k environment, cinematic lighting, atmospheric fog, moonlight, volumetric lighting",
    background_weight=1.2,

    # 인물 관련 피해야 할 것 (NSFW만 차단, 얼굴 허용!)
    avoid_human=[
        "nsfw", "nude", "naked", "revealing clothes", "bikini",
        "photorealistic human", "3d render human", "photograph of person"
    ],

    # 일반 피해야 할 것
    avoid_general=[
        "blurry", "low quality", "distorted", "bright", "happy",
        "colorful cartoon", "cute", "3d render", "photorealistic"
    ],

    # 스타일 프리셋
    style_positive="horror manga style, dark atmosphere, eerie, high contrast, cinematic horror, suspenseful, ink lineart",
    style_negative="bright sunny day, cheerful, colorful, photorealistic, 3d render, nsfw, nude"
)


SENIOR_TOUCHING_STYLE = V50StyleConfig(
    # 인물: 따뜻한 수채화 형체, 색깔 덩어리
    human_style="abstract watercolor human figure, soft colored shape as person, warm color blob figure, impressionist human form, gentle silhouette",
    human_weight=1.3,

    # 배경: 고품질 따뜻한 분위기
    background_quality="highly detailed background, warm lighting, soft sunlight, nostalgic atmosphere, 8k environment, golden hour",
    background_weight=1.2,

    # 인물 관련 피해야 할 것
    avoid_human=[
        "detailed face", "realistic face", "portrait", "close-up face",
        "photorealistic human", "detailed hands", "realistic skin texture"
    ],

    # 일반 피해야 할 것
    avoid_general=[
        "dark", "scary", "horror", "intense", "messy",
        "photorealistic", "uncanny", "distorted face"
    ],

    # 스타일 프리셋
    style_positive="warm watercolor painting, soft sunlight, nostalgic, bright and peaceful colors, 2d masterpiece, gentle atmosphere",
    style_negative="dark scary horror, realistic portrait, detailed face, photorealistic human"
)


SENIOR_MAKJANG_STYLE = V50StyleConfig(
    # 인물: 극적인 실루엣, 감정 표현은 자세로
    human_style="dramatic silhouette figure, expressive pose, abstract human form, emotional body language, stylized character shape",
    human_weight=1.3,

    # 배경: 극적인 조명
    background_quality="highly detailed background, dramatic lighting, sharp shadows, cinematic composition, 8k environment",
    background_weight=1.2,

    # 인물 관련 피해야 할 것
    avoid_human=[
        "detailed face", "realistic face", "portrait", "close-up face",
        "photorealistic human", "detailed facial expression"
    ],

    # 일반 피해야 할 것
    avoid_general=[
        "peaceful calm", "monochrome", "cute", "low quality",
        "blurry", "photorealistic face"
    ],

    # 스타일 프리셋
    style_positive="dramatic webtoon style, intense cinematic lighting, sharp shadows, tense atmosphere, emotional scene",
    style_negative="peaceful calm, photorealistic portrait, detailed face"
)


# 스타일 맵 (기본 제공)
STYLE_MAP: Dict[str, V50StyleConfig] = {
    "horror": HORROR_STYLE,
    "senior_touching": SENIOR_TOUCHING_STYLE,
    "senior_makjang": SENIOR_MAKJANG_STYLE,
    "senior": SENIOR_TOUCHING_STYLE,  # 기본값
}

# 채널 카테고리 분류 (동적 확장 가능)
DARK_CHANNELS = {"horror", "thriller", "mystery", "crime", "suspense"}
WARM_CHANNELS = {"senior", "senior_touching", "family", "romance", "healing", "kids"}
DRAMATIC_CHANNELS = {"senior_makjang", "drama", "action", "historical"}


def get_channel_category(channel: str) -> str:
    """
    채널을 카테고리로 분류 (동적 처리)

    Returns:
        "dark", "warm", "dramatic" 중 하나
    """
    channel_lower = channel.lower()

    if channel_lower in DARK_CHANNELS or "horror" in channel_lower or "dark" in channel_lower:
        return "dark"
    elif channel_lower in DRAMATIC_CHANNELS or "makjang" in channel_lower or "drama" in channel_lower:
        return "dramatic"
    elif channel_lower in WARM_CHANNELS or "senior" in channel_lower or "family" in channel_lower:
        return "warm"
    else:
        # 기본값: warm (안전한 스타일)
        return "warm"


def get_style_for_channel(channel: str) -> V50StyleConfig:
    """
    채널에 맞는 스타일 설정 반환 (동적 처리)
    """
    # 먼저 직접 매핑 확인
    if channel in STYLE_MAP:
        return STYLE_MAP[channel]

    # 카테고리 기반 폴백
    category = get_channel_category(channel)

    if category == "dark":
        return HORROR_STYLE
    elif category == "dramatic":
        return SENIOR_MAKJANG_STYLE
    else:
        return SENIOR_TOUCHING_STYLE


# ============================================================
# 프롬프트 변환 함수
# ============================================================
def transform_prompt_for_v50(
    original_prompt: str,
    channel: str,
    has_human: bool = True,
    scene_type: str = "general"
) -> Tuple[str, str]:
    """
    v37 프롬프트를 v50 스타일로 변환

    Args:
        original_prompt: 원본 프롬프트
        channel: 채널 타입 (horror, senior_touching, senior_makjang)
        has_human: 장면에 사람이 등장하는지
        scene_type: 장면 타입 (general, closeup, landscape, action)

    Returns:
        (positive_prompt, negative_prompt) 튜플
    """
    # 동적 스타일 선택 (하드코딩 방지)
    style = get_style_for_channel(channel)

    parts = []

    # 1. 배경 품질 우선 (항상 상세하게)
    parts.append(f"({style.background_quality}:{style.background_weight})")

    # 2. 원본 프롬프트 (인물 관련 키워드 정제)
    cleaned_prompt = _clean_human_details(original_prompt) if has_human else original_prompt
    parts.append(cleaned_prompt)

    # 3. 인물이 있으면 추상적 스타일 적용
    if has_human:
        parts.append(f"({style.human_style}:{style.human_weight})")

    # 4. 스타일 프리셋
    parts.append(style.style_positive)

    # 5. 장면 타입별 추가 요소
    scene_additions = _get_scene_type_additions(scene_type, channel)
    if scene_additions:
        parts.append(scene_additions)

    positive = ", ".join(parts)

    # 네거티브 프롬프트 구성
    negative_parts = []
    if has_human:
        negative_parts.extend(style.avoid_human)
    negative_parts.extend(style.avoid_general)
    negative_parts.append(style.style_negative)

    negative = ", ".join(negative_parts)

    return positive, negative


def _clean_human_details(prompt: str, manga_mode: bool = True) -> str:
    """
    프롬프트에서 인물 묘사 처리

    v59.5.7: manga_mode=True면 인물 키워드 유지 (만화 스타일은 인물 OK)
    manga_mode=False면 구체적 인물 묘사를 추상화 (구 동작)
    """
    # v59.5.7: 만화 모드에서는 인물 묘사를 그대로 유지!
    # 만화/웹툰 스타일은 불쾌한 골짜기가 없으므로 인물 표현 허용
    if manga_mode:
        # NSFW 관련만 제거
        nsfw_keywords = [
            "nsfw", "nude", "naked", "revealing", "bikini", "underwear",
            "bare skin", "exposed", "cleavage", "lingerie"
        ]
        result = prompt.lower()
        for keyword in nsfw_keywords:
            result = result.replace(keyword, "")
        return result

    # 레거시: 포토리얼 모드에서만 인물 추상화 (v50 호환)
    remove_keywords = [
        "detailed face", "beautiful face", "handsome face",
        "clear eyes", "detailed eyes", "realistic eyes",
        "detailed hands", "realistic hands",
        "detailed skin", "realistic skin",
        "portrait style", "close-up portrait"
    ]

    result = prompt.lower()
    for keyword in remove_keywords:
        result = result.replace(keyword, "")

    replacements = {
        "woman standing": "figure standing",
        "man standing": "figure standing",
        "girl walking": "silhouette walking",
        "boy running": "figure running",
        "grandmother": "elderly figure",
        "grandfather": "elderly figure",
        "child playing": "small figure playing",
        "person looking": "figure facing",
    }

    for old, new in replacements.items():
        result = result.replace(old, new)

    return result


def _get_scene_type_additions(scene_type: str, channel: str) -> str:
    """장면 타입별 추가 프롬프트 (동적 카테고리 기반)"""

    category = get_channel_category(channel)

    # 카테고리별 장면 추가 프롬프트
    if category == "dark":
        additions = {
            "general": "atmospheric depth, layered shadows",
            "closeup": "extreme close on object, figure in deep background blur",
            "landscape": "vast eerie landscape, tiny distant figure",
            "action": "motion blur on figure, sharp environment details"
        }
    elif category == "dramatic":
        additions = {
            "general": "dramatic depth of field, intense atmosphere",
            "closeup": "emotional close on object, silhouette in background",
            "landscape": "sweeping cinematic vista, small dramatic figure",
            "action": "dynamic motion, expressive action silhouette"
        }
    else:  # warm
        additions = {
            "general": "warm depth of field, soft focus on figure",
            "closeup": "object focus, abstract figure in background",
            "landscape": "beautiful scenery, small gentle figure",
            "action": "flowing movement, expressive pose silhouette"
        }

    return additions.get(scene_type, "")


# ============================================================
# 장면 분석 함수
# ============================================================
def analyze_scene_for_humans(scene_description: str) -> bool:
    """
    장면 설명에서 사람 등장 여부 판단
    """
    # 영어 키워드 (소문자 비교)
    english_keywords = [
        "person", "man", "woman", "child", "grandmother", "grandfather",
        "figure", "character", "someone", "boy", "girl", "people",
        "silhouette", "human", "lady", "guy", "kid", "elder"
    ]

    # 한국어 키워드 (원본 비교)
    korean_keywords = [
        "사람", "인물", "남자", "여자", "아이", "할머니", "할아버지",
        "주인공", "화자", "그녀", "그", "엄마", "아빠", "부모",
        "아들", "딸", "손자", "손녀", "형", "동생", "누나", "언니",
        "청년", "노인", "아저씨", "아줌마", "소녀", "소년"
    ]

    scene_lower = scene_description.lower()

    # 영어 키워드 검사
    if any(keyword in scene_lower for keyword in english_keywords):
        return True

    # 한국어 키워드 검사 (원본에서)
    if any(keyword in scene_description for keyword in korean_keywords):
        return True

    return False


def get_scene_type(scene_description: str) -> str:
    """
    장면 설명에서 장면 타입 판단
    """
    desc_lower = scene_description.lower()

    # 클로즈업 장면
    closeup_keywords = ["close", "클로즈업", "확대", "zoom", "detail of"]
    if any(kw in desc_lower for kw in closeup_keywords):
        return "closeup"

    # 풍경 장면
    landscape_keywords = ["landscape", "풍경", "전경", "wide shot", "establishing", "마을", "숲", "하늘"]
    if any(kw in desc_lower for kw in landscape_keywords):
        return "landscape"

    # 액션 장면
    action_keywords = ["running", "달리", "뛰", "chase", "fight", "action", "움직"]
    if any(kw in desc_lower for kw in action_keywords):
        return "action"

    return "general"


# ============================================================
# 배치 변환
# ============================================================
def transform_scene_prompts(
    scenes: List[Dict],
    channel: str
) -> List[Dict]:
    """
    여러 장면의 프롬프트를 v50 스타일로 일괄 변환

    Args:
        scenes: 장면 리스트 [{"prompt": "...", "scene_idx": 1}, ...]
        channel: 채널 타입

    Returns:
        변환된 장면 리스트 [{"prompt": "...", "negative": "...", ...}, ...]
    """
    transformed = []

    for scene in scenes:
        original_prompt = scene.get("prompt", "")
        scene_idx = scene.get("scene_idx", 0)

        # 장면 분석
        has_human = analyze_scene_for_humans(original_prompt)
        scene_type = get_scene_type(original_prompt)

        # 프롬프트 변환
        positive, negative = transform_prompt_for_v50(
            original_prompt=original_prompt,
            channel=channel,
            has_human=has_human,
            scene_type=scene_type
        )

        transformed.append({
            "prompt": positive,
            "negative": negative,
            "scene_idx": scene_idx,
            "has_human": has_human,
            "scene_type": scene_type,
            # 원본 보존
            "original_prompt": original_prompt
        })

    return transformed


# ============================================================
# 테스트
# ============================================================
if __name__ == "__main__":
    print("=" * 60)
    print("v50 Premium Style Guide Test")
    print("=" * 60)

    # 테스트 프롬프트
    test_prompts = [
        {
            "prompt": "abandoned hospital corridor with a woman standing at the end",
            "channel": "horror"
        },
        {
            "prompt": "grandmother cooking in a warm kitchen",
            "channel": "senior_touching"
        },
        {
            "prompt": "dark forest path with moonlight",
            "channel": "horror"
        },
        {
            "prompt": "family gathering in countryside home",
            "channel": "senior_touching"
        }
    ]

    for i, test in enumerate(test_prompts, 1):
        print(f"\n[테스트 {i}] {test['channel']}")
        print(f"원본: {test['prompt']}")

        has_human = analyze_scene_for_humans(test['prompt'])
        scene_type = get_scene_type(test['prompt'])

        positive, negative = transform_prompt_for_v50(
            original_prompt=test['prompt'],
            channel=test['channel'],
            has_human=has_human,
            scene_type=scene_type
        )

        print(f"인물: {'있음' if has_human else '없음'}, 타입: {scene_type}")
        print(f"Positive: {positive[:100]}...")
        print(f"Negative: {negative[:80]}...")
