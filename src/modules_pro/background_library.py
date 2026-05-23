# -*- coding: utf-8 -*-
"""
v59: Background Library Manager
배경 이미지 라이브러리 관리 + 자동 생성

설계서 섹션 3.4 구현
"""

import argparse
import os
import json
import random
import logging
import hashlib
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, List, Any, Tuple
from datetime import datetime

try:
    from utils.logger import get_logger
    logger = get_logger("background_library")
except ImportError:
    logger = logging.getLogger(__name__)


# ============================================================================
# 데이터 클래스 (설계서 3.4)
# ============================================================================

@dataclass
class BackgroundImage:
    """배경 이미지 메타데이터"""
    filename: str
    location: str  # "숲", "마을", "방" 등
    time: str = "any"  # "낮", "밤", "새벽", "저녁", "any"
    weather: str = "any"  # "맑음", "비", "눈", "흐림", "any"
    mood: str = "neutral"  # "peaceful", "horror", "sad", "tense"
    prompt_used: str = ""
    seed: int = 0
    quality_score: float = 0.0
    created_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()


@dataclass
class LocationTemplate:
    """장소별 프롬프트 템플릿"""
    id: str  # "forest", "village", "room"
    name_ko: str  # "숲", "마을", "방"
    name_en: str  # "forest", "village", "room"
    base_prompt: str  # SD 기본 프롬프트
    negative_prompt: str = ""
    keywords: List[str] = field(default_factory=list)  # 장소 인식용 키워드

    def matches(self, location_text: str) -> bool:
        """주어진 텍스트가 이 장소와 매칭되는지 확인"""
        location_lower = location_text.lower()
        name_lower = self.name_ko.lower()

        if name_lower in location_lower or location_lower in name_lower:
            return True

        for keyword in self.keywords:
            if keyword.lower() in location_lower:
                return True

        return False


@dataclass
class BackgroundLibraryConfig:
    """배경 라이브러리 설정"""
    # 스타일
    style_prompt: str = ""
    negative_prompt: str = ""

    # 장소 템플릿
    location_templates: Dict[str, LocationTemplate] = field(default_factory=dict)

    # 시간대 modifier
    time_modifiers: Dict[str, str] = field(default_factory=lambda: {
        "낮": "daylight, bright sun, clear sky",
        "밤": "night time, moonlight, dark, starry sky",
        "새벽": "dawn, early morning light, misty",
        "저녁": "sunset, golden hour, warm light, dusk"
    })

    # 날씨 modifier
    weather_modifiers: Dict[str, str] = field(default_factory=lambda: {
        "맑음": "clear weather, blue sky",
        "비": "rainy, wet, rain drops, overcast",
        "눈": "snowy, winter, snow falling, cold",
        "흐림": "cloudy, overcast, grey sky",
        "안개": "foggy, misty, mysterious atmosphere"
    })

    # 분위기 modifier
    mood_modifiers: Dict[str, str] = field(default_factory=lambda: {
        "peaceful": "peaceful, calm, serene atmosphere",
        "horror": "dark, eerie, unsettling, ominous",
        "sad": "melancholic, lonely, desolate",
        "tense": "tense atmosphere, dramatic lighting",
        "romantic": "romantic, soft lighting, warm colors"
    })

    # 생성 설정
    auto_generate: bool = True
    images_per_location: int = 5

    # 저장 경로
    library_path: str = ""


# ============================================================================
# 장르별 기본 템플릿
# ============================================================================

HORROR_LOCATION_TEMPLATES = {
    "숲": LocationTemplate(
        id="forest",
        name_ko="숲",
        name_en="forest",
        base_prompt="dense dark forest, ancient twisted trees, fog, mysterious atmosphere, korean folklore style",
        negative_prompt="bright, cheerful, cartoon",
        keywords=["산", "나무", "수풀", "산길", "숲속", "산속", "임야"]
    ),
    "마을": LocationTemplate(
        id="village",
        name_ko="마을",
        name_en="village",
        base_prompt="old korean traditional village, thatched roof houses, abandoned, eerie atmosphere, night",
        negative_prompt="modern, bright, crowded",
        keywords=["동네", "시골", "농촌", "초가집", "기와집", "마을길"]
    ),
    "방": LocationTemplate(
        id="room",
        name_ko="방",
        name_en="room",
        base_prompt="korean traditional room, ondol floor, paper doors, dim candlelight, old, dusty",
        negative_prompt="modern, bright, clean",
        keywords=["안방", "사랑채", "별채", "처소", "거처", "집안", "실내"]
    ),
    "묘지": LocationTemplate(
        id="graveyard",
        name_ko="묘지",
        name_en="graveyard",
        base_prompt="old korean graveyard, burial mounds, tombstones, misty, moonlight, eerie",
        negative_prompt="bright, modern",
        keywords=["무덤", "산소", "봉분", "선산", "장지", "분묘"]
    ),
    "절": LocationTemplate(
        id="temple",
        name_ko="절",
        name_en="temple",
        base_prompt="ancient korean buddhist temple, wooden architecture, paper lanterns, incense smoke, mysterious",
        negative_prompt="modern, bright",
        keywords=["사찰", "암자", "법당", "불당", "대웅전", "절간"]
    ),
    "길": LocationTemplate(
        id="road",
        name_ko="길",
        name_en="road",
        base_prompt="lonely korean mountain path, dark forest road, foggy, night, traditional era",
        negative_prompt="modern, highway, car",
        keywords=["도로", "오솔길", "산길", "고갯길", "샛길", "골목"]
    ),
    "강": LocationTemplate(
        id="river",
        name_ko="강",
        name_en="river",
        base_prompt="korean river at night, moonlight reflection, misty, traditional landscape, eerie calm",
        negative_prompt="modern, bridge, boat",
        keywords=["하천", "냇가", "시내", "개울", "물가", "강가", "계곡"]
    ),
    "우물": LocationTemplate(
        id="well",
        name_ko="우물",
        name_en="well",
        base_prompt="old stone well in korean village, abandoned, dark water, eerie, night, horror atmosphere",
        negative_prompt="modern, bright, clean",
        keywords=["샘", "정자", "물통"]
    )
}


YADAM_LOCATION_TEMPLATES = {
    "숲": LocationTemplate(
        id="forest",
        name_ko="숲",
        name_en="forest",
        base_prompt="korean traditional forest, pine trees, bamboo, korean ink painting style, misty mountains",
        negative_prompt="western, modern",
        keywords=["산", "나무", "수풀", "산길", "숲속", "산속"]
    ),
    "마을": LocationTemplate(
        id="village",
        name_ko="마을",
        name_en="village",
        base_prompt="joseon era village, traditional korean houses, tile roof, scholarly atmosphere",
        negative_prompt="modern, western",
        keywords=["동네", "시골", "농촌", "초가집", "기와집"]
    ),
    "서재": LocationTemplate(
        id="study",
        name_ko="서재",
        name_en="study",
        base_prompt="joseon scholar's study room, books, calligraphy, traditional korean interior, ink paintings",
        negative_prompt="modern, western",
        keywords=["책방", "사랑방", "서당", "글방"]
    ),
    "시장": LocationTemplate(
        id="market",
        name_ko="시장",
        name_en="market",
        base_prompt="joseon era traditional market, merchants, colorful stalls, busy atmosphere",
        negative_prompt="modern, western",
        keywords=["장터", "저자거리", "난전"]
    ),
    "궁궐": LocationTemplate(
        id="palace",
        name_ko="궁궐",
        name_en="palace",
        base_prompt="joseon royal palace, grand architecture, traditional korean palace, majestic",
        negative_prompt="modern, simple",
        keywords=["대궐", "왕궁", "내전", "외전"]
    ),
    "기방": LocationTemplate(
        id="gisaeng_house",
        name_ko="기방",
        name_en="gisaeng house",
        base_prompt="joseon era gisaeng house, elegant interior, musical instruments, paper lanterns, romantic",
        negative_prompt="modern, western",
        keywords=["주막", "객주", "술집", "요정"]
    )
}


SENIOR_LOCATION_TEMPLATES = {
    "집": LocationTemplate(
        id="home",
        name_ko="집",
        name_en="home",
        base_prompt="korean elderly home, traditional ondol floor, familiar objects, warm atmosphere, nostalgic",
        negative_prompt="modern apartment, cold",
        keywords=["방", "거실", "마루", "부엌", "안방"]
    ),
    "마을": LocationTemplate(
        id="village",
        name_ko="마을",
        name_en="village",
        base_prompt="1960s korean rural village, nostalgic, warm sunlight, peaceful countryside",
        negative_prompt="modern, urban",
        keywords=["시골", "농촌", "고향", "동네"]
    ),
    "논밭": LocationTemplate(
        id="field",
        name_ko="논밭",
        name_en="field",
        base_prompt="korean rice paddies and fields, farming, traditional rural landscape, golden harvest",
        negative_prompt="modern, urban",
        keywords=["들판", "밭", "농사", "텃밭", "과수원"]
    ),
    "학교": LocationTemplate(
        id="school",
        name_ko="학교",
        name_en="school",
        base_prompt="1960s korean elementary school, wooden building, nostalgic, playground, cherry blossoms",
        negative_prompt="modern, high-rise",
        keywords=["국민학교", "초등학교", "교실", "운동장"]
    ),
    "시장": LocationTemplate(
        id="market",
        name_ko="시장",
        name_en="market",
        base_prompt="1970s korean traditional market, colorful stalls, bustling crowd, nostalgic atmosphere",
        negative_prompt="modern mall",
        keywords=["장터", "오일장", "재래시장", "골목시장"]
    ),
    "병원": LocationTemplate(
        id="hospital",
        name_ko="병원",
        name_en="hospital",
        base_prompt="korean hospital room, patient bed, window view, contemplative mood, soft lighting",
        negative_prompt="horror, dark",
        keywords=["병실", "요양원", "의원"]
    )
}


# ============================================================================
# BackgroundLibrary 클래스
# ============================================================================

LOCATION_ALIAS_GROUPS = {
    "apartment_entrance": [
        "현관", "아파트 현관", "집 현관", "현관문", "신발장", "우산꽂이",
        "우산 꽂이", "우산걸이", "문 앞", "집 앞", "입구", "초인종",
        "apartment entrance", "front door", "doorway", "shoe cabinet",
        "umbrella rack", "umbrella stand", "entrance close-up",
        "entrance final wide shot", "bulletin", "notice board",
    ],
    "apartment_hallway": [
        "복도", "아파트 복도", "공동현관", "계단", "계단참", "복도 테이블",
        "hallway", "apartment hallway", "stairs", "stairwell", "corridor",
        "hallway table",
    ],
    "elevator_lobby": [
        "엘리베이터", "엘리베이터 앞", "엘리베이터 로비", "로비",
        "elevator", "elevator lobby", "apartment lobby", "lobby",
    ],
    "convenience_store": [
        "편의점", "편의점 앞", "편의점 입구", "가게 앞", "가게 입구",
        "매장 앞", "convenience store", "convenience store front",
        "convenience store entrance", "storefront", "shop front",
    ],
    "neighborhood_street": [
        "동네", "골목", "거리", "길거리", "인도", "횡단보도", "버스정류장",
        "neighborhood", "neighborhood street", "city sidewalk", "sidewalk",
        "street", "alley", "bus stop",
    ],
    "kitchen": [
        "부엌", "주방", "식탁", "싱크대", "냉장고",
        "kitchen", "dining table", "breakfast table",
    ],
    "cafe": [
        "카페", "커피숍", "찻집", "테이블",
        "cafe", "coffee shop", "cafe table",
    ],
    "rooftop": [
        "옥상", "빨래줄", "빨래", "옥탑",
        "rooftop", "laundry line", "roof terrace",
    ],
    "집": [
        "한옥", "한옥 마당", "한옥 대문", "마당", "대문", "사랑방",
        "안채", "툇마루", "행랑채", "사립문", "집안", "집 마당",
        "전통 가옥", "전통 가옥 입구", "가옥 입구", "뒤뜰", "서재",
        "hanok", "courtyard", "front gate", "gate exterior", "traditional house",
        "house entrance", "porch", "sarangbang", "inner room", "study room",
        "hallway", "paper doors", "wooden porch", "yard corner", "house", "home",
    ],
    "시장": [
        "장터", "장터 골목", "장터 입구", "시장 골목", "시장 입구",
        "골목시장", "노점거리",
        "market", "market alley", "market gate", "stalls", "merchant street", "bazaar",
    ],
    "마을": [
        "골목", "동네", "마을길", "동구 밖", "시골길",
        "village", "stone wall courtyard",
    ],
    "서재": [
        "study", "study room", "scholar room", "library room", "desk room",
    ],
    "학교": [
        "서당", "학당", "학교 마당",
    ],
    "병원": [
        "약방", "의원", "병실",
    ],
    "들판": [
        "논", "밭", "과수원", "언덕길", "언덕",
        "field", "farm path", "mountain path", "riverbank", "hill path", "rice paddy",
    ],
    "길": [
        "road", "path", "village road", "lane", "dirt road",
    ],
    "강": [
        "river", "stream", "riverbank", "riverside", "brook",
    ],
    "다리": [
        "bridge", "wooden bridge", "stream bridge", "footbridge",
    ],
}


def _clone_location_templates(source: Dict[str, LocationTemplate]) -> Dict[str, LocationTemplate]:
    cloned: Dict[str, LocationTemplate] = {}
    for key, template in source.items():
        cloned[key] = LocationTemplate(
            id=template.id,
            name_ko=template.name_ko,
            name_en=template.name_en,
            base_prompt=template.base_prompt,
            negative_prompt=template.negative_prompt,
            keywords=list(template.keywords or []),
        )
    return cloned


def _base_config_for_profile(profile: str) -> BackgroundLibraryConfig:
    normalized = str(profile or "").strip().lower()
    config = BackgroundLibraryConfig()
    if normalized in ("daily_life_toon", "daily", "videotoon"):
        config.style_prompt = "clean reusable Korean daily-life webtoon background, no characters, layered-safe center space"
        config.negative_prompt = "people, character, face, text, logo, UI card, photorealistic, messy clutter"
        config.location_templates = _clone_location_templates(SENIOR_LOCATION_TEMPLATES)
    elif normalized in ("mystery_toon", "mystery"):
        config.style_prompt = "Korean mystery webtoon background, no characters, restrained shadows, layered-safe composition"
        config.negative_prompt = "people, character, face, readable text, logo, UI card, photorealistic, gore"
        config.location_templates = _clone_location_templates(HORROR_LOCATION_TEMPLATES)
    elif normalized == "horror":
        config.style_prompt = "dark atmosphere, horror movie style, korean folklore, cinematic lighting"
        config.negative_prompt = "bright, cheerful, cartoon, anime, watermark, text"
        config.location_templates = _clone_location_templates(HORROR_LOCATION_TEMPLATES)
    elif normalized == "yadam":
        config.style_prompt = "korean traditional painting style, joseon era, ink wash style, elegant"
        config.negative_prompt = "modern, western, photo, 3d render"
        config.location_templates = _clone_location_templates(YADAM_LOCATION_TEMPLATES)
    elif normalized in ("senior", "touching", "makjang"):
        config.style_prompt = "nostalgic korean countryside, warm colors, soft lighting, emotional"
        config.negative_prompt = "horror, dark, scary, modern urban"
        config.location_templates = _clone_location_templates(SENIOR_LOCATION_TEMPLATES)
    else:
        config.location_templates = _clone_location_templates(HORROR_LOCATION_TEMPLATES)
    return config


def _build_location_templates_from_dict(raw_templates: Dict[str, Any]) -> Dict[str, LocationTemplate]:
    templates: Dict[str, LocationTemplate] = {}
    for key, value in (raw_templates or {}).items():
        if not isinstance(value, dict):
            continue
        templates[str(key)] = LocationTemplate(
            id=str(value.get("id", key) or key),
            name_ko=str(value.get("name_ko", key) or key),
            name_en=str(value.get("name_en", key) or key),
            base_prompt=str(value.get("base_prompt", "") or ""),
            negative_prompt=str(value.get("negative_prompt", "") or ""),
            keywords=list(value.get("keywords", []) or []),
        )
    return templates


def build_background_library_config(
    genre: str,
    config_data: Optional[Dict[str, Any]] = None,
    library_path: str = "",
) -> BackgroundLibraryConfig:
    """Build a background library config from pack data with sane genre defaults."""
    data = config_data or {}
    profile = str(data.get("profile", genre) or genre)
    config = _base_config_for_profile(profile)
    config.library_path = library_path

    if data.get("style_prompt"):
        config.style_prompt = str(data.get("style_prompt") or "")
    if data.get("negative_prompt"):
        config.negative_prompt = str(data.get("negative_prompt") or "")

    location_templates = data.get("location_templates", {}) or {}
    custom_templates = _build_location_templates_from_dict(location_templates)
    if custom_templates:
        config.location_templates = custom_templates

    if "auto_generate" in data:
        config.auto_generate = bool(data.get("auto_generate"))
    if "images_per_location" in data:
        try:
            config.images_per_location = int(data.get("images_per_location") or config.images_per_location)
        except Exception:
            pass

    time_modifiers = data.get("time_modifiers")
    if isinstance(time_modifiers, dict) and time_modifiers:
        config.time_modifiers = dict(time_modifiers)
    weather_modifiers = data.get("weather_modifiers")
    if isinstance(weather_modifiers, dict) and weather_modifiers:
        config.weather_modifiers = dict(weather_modifiers)
    mood_modifiers = data.get("mood_modifiers")
    if isinstance(mood_modifiers, dict) and mood_modifiers:
        config.mood_modifiers = dict(mood_modifiers)

    return config


class BackgroundLibrary:
    """
    v59: 배경 이미지 라이브러리 관리자

    기능:
    - 장소/시간/날씨 기반 배경 이미지 조회
    - SD WebUI API로 배경 이미지 자동 생성
    - 프리셋 배경 라이브러리 관리
    """

    def __init__(
        self,
        pack_id: str,
        genre: str = "daily_life_toon",
        config: Optional[BackgroundLibraryConfig] = None,
        base_path: Optional[str] = None
    ):
        """
        Args:
            pack_id: 팩 ID
            genre: 장르 ("horror", "touching", "makjang", "senior")
            config: 라이브러리 설정 (없으면 장르 기본값)
            base_path: 기본 경로 (기본: assets/backgrounds/{pack_id})
        """
        self.pack_id = pack_id
        self.genre = genre

        # 기본 경로 설정
        if base_path:
            self.base_path = Path(base_path)
        else:
            self.base_path = Path("assets/backgrounds") / pack_id

        # 설정 초기화
        if config:
            self.config = config
        else:
            self.config = self._create_default_config()

        # 라이브러리 데이터
        self.images: Dict[str, List[BackgroundImage]] = {}  # location -> images
        self.index_path = self.base_path / "background_index.json"
        self._selection_counts: Dict[str, int] = {}
        self._last_selected_by_location: Dict[str, str] = {}

        # 로드
        self._load_library()

        logger.info(f"BackgroundLibrary 초기화: pack={pack_id}, genre={genre}, images={self._count_images()}")

    def _create_default_config(self) -> BackgroundLibraryConfig:
        """장르별 기본 설정 생성"""
        return build_background_library_config(
            genre=self.genre,
            config_data=None,
            library_path=str(self.base_path),
        )

    def _load_library(self):
        """라이브러리 인덱스 로드"""
        self.images = {}

        if self.index_path.exists():
            try:
                with open(self.index_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                for location, image_list in data.get("images", {}).items():
                    self.images[location] = [
                        BackgroundImage(**img) for img in image_list
                    ]

                logger.info(f"라이브러리 로드 완료: {self._count_images()}개 이미지")

            except Exception as e:
                logger.error(f"라이브러리 로드 실패: {e}")
                self.images = {}
        else:
            logger.info("라이브러리 인덱스 없음 - 빈 라이브러리로 시작")

    def _save_library(self):
        """라이브러리 인덱스 저장"""
        self.base_path.mkdir(parents=True, exist_ok=True)

        data = {
            "pack_id": self.pack_id,
            "genre": self.genre,
            "updated_at": datetime.now().isoformat(),
            "images": {
                location: [asdict(img) for img in images]
                for location, images in self.images.items()
            }
        }

        with open(self.index_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        logger.info(f"라이브러리 저장 완료: {self.index_path}")

    def _count_images(self) -> int:
        """총 이미지 수"""
        return sum(len(imgs) for imgs in self.images.values())

    def _expand_location_candidates(self, location_text: str) -> List[str]:
        """Expand raw scene location text into template-friendly candidates."""
        raw = str(location_text or "").strip()
        if not raw:
            return []

        candidates: List[str] = [raw]
        lowered = raw.lower()
        for canonical, aliases in LOCATION_ALIAS_GROUPS.items():
            hits = [alias for alias in aliases if alias and alias.lower() in lowered]
            if canonical.lower() in lowered or hits:
                candidates.append(canonical)
                candidates.extend(hits)

        for token in raw.replace("/", " ").replace("-", " ").split():
            token = token.strip()
            if token:
                candidates.append(token)

        unique: List[str] = []
        seen = set()
        for candidate in candidates:
            key = candidate.lower()
            if key in seen:
                continue
            seen.add(key)
            unique.append(candidate)
        return unique

    # ========================================================================
    # 배경 이미지 조회
    # ========================================================================

    def get_background_image(
        self,
        location: str,
        time: str = "any",
        weather: str = "any",
        mood: str = "any"
    ) -> Optional[str]:
        """
        조건에 맞는 배경 이미지 경로 반환

        Args:
            location: 장소 텍스트 (예: "숲", "마을", "어두운 방")
            time: 시간대 (예: "낮", "밤")
            weather: 날씨 (예: "비", "눈")
            mood: 분위기 (예: "horror", "peaceful")

        Returns:
            이미지 경로 또는 None
        """
        # 장소 매칭
        matched_location = self._match_location(location)
        if not matched_location:
            logger.warning(f"매칭되는 장소 없음: {location}")
            return None

        # 해당 장소의 이미지 목록
        location_images = self.images.get(matched_location, [])
        if not location_images:
            logger.warning(f"이미지 없음: {matched_location}")
            return None

        # 조건 필터링
        candidates = []
        for img in location_images:
            score = 0

            # 시간대 매칭
            if time != "any" and img.time != "any":
                if img.time == time:
                    score += 3
                else:
                    continue  # 시간대 불일치 시 제외

            # 날씨 매칭
            if weather != "any" and img.weather != "any":
                if img.weather == weather:
                    score += 2

            # 분위기 매칭
            if mood != "any" and img.mood != "neutral":
                if img.mood == mood:
                    score += 1

            # 품질 점수 가산
            score += img.quality_score * 0.1

            candidates.append((img, score))

        if not candidates:
            # 필터 조건이 너무 엄격하면 모든 이미지에서 랜덤 선택
            candidates = [(img, 0) for img in location_images]

        # 상위 3개 중 랜덤 선택 (다양성)
        candidates.sort(key=lambda x: x[1], reverse=True)
        top_candidates = candidates[:min(3, len(candidates))]
        ranked = []
        for img, score in top_candidates:
            key = f"{matched_location}/{img.filename}"
            reuse_count = self._selection_counts.get(key, 0)
            same_as_last = 1 if self._last_selected_by_location.get(matched_location) == img.filename else 0
            ranked.append((reuse_count, same_as_last, -score, random.random(), img))
        ranked.sort(key=lambda item: (item[0], item[1], item[2], item[3]))
        selected = ranked[0][4]

        image_path = self.base_path / selected.filename
        if image_path.exists():
            key = f"{matched_location}/{selected.filename}"
            self._selection_counts[key] = self._selection_counts.get(key, 0) + 1
            self._last_selected_by_location[matched_location] = selected.filename
            return str(image_path)
        else:
            logger.warning(f"이미지 파일 없음: {image_path}")
            return None

    def _match_location(self, location_text: str) -> Optional[str]:
        """장소 텍스트를 템플릿 ID로 매칭"""
        candidates = self._expand_location_candidates(location_text)
        template_key_map = {
            str(loc_id).lower(): loc_id
            for loc_id in self.config.location_templates.keys()
        }
        for candidate in candidates:
            direct = template_key_map.get(str(candidate).lower())
            if direct:
                return direct
            for loc_id, template in self.config.location_templates.items():
                if template.matches(candidate):
                    return loc_id

        # 부분 일치 시도
        for candidate in candidates:
            location_lower = candidate.lower()
            for loc_id, template in self.config.location_templates.items():
                if template.name_ko in location_lower or template.name_en in location_lower:
                    return loc_id

        return None

    def _public_target_base_path(self) -> str:
        """Return a relative publishable background root for request manifests."""
        configured = str(getattr(self.config, "library_path", "") or "").strip()
        if configured and not Path(configured).is_absolute():
            return Path(configured).as_posix()
        return (Path("assets") / "backgrounds" / self.pack_id).as_posix()

    def _target_location_templates(self, locations: Optional[List[str]]) -> Dict[str, LocationTemplate]:
        if not locations:
            return dict(self.config.location_templates)

        selected: Dict[str, LocationTemplate] = {}
        for raw_location in locations:
            matched = self._match_location(raw_location)
            if matched and matched in self.config.location_templates:
                selected[matched] = self.config.location_templates[matched]
        return selected

    def _request_times(self, times: Optional[List[str]], time_variants: bool) -> List[str]:
        clean_times = [str(time).strip() for time in (times or []) if str(time).strip()]
        if clean_times:
            return clean_times
        if not time_variants:
            return ["any"]

        configured_times = [
            str(time).strip()
            for time in self.config.time_modifiers.keys()
            if str(time).strip()
        ]
        return configured_times[:2] if configured_times else ["any"]

    def _stable_request_seed(self, location_id: str, time: str, index: int) -> int:
        return int(hashlib.md5(f"{self.pack_id}_{location_id}_{time}_{index}".encode()).hexdigest()[:8], 16)

    def build_asset_request_manifest(
        self,
        locations: Optional[List[str]] = None,
        images_per_location: Optional[int] = None,
        times: Optional[List[str]] = None,
        time_variants: bool = True,
    ) -> Dict[str, Any]:
        """Build public-safe background plate generation requests without generating images."""
        target_locations = self._target_location_templates(locations)
        request_times = self._request_times(times, time_variants)
        count_per_location = int(images_per_location or self.config.images_per_location or 1)
        if count_per_location < 1:
            count_per_location = 1

        requests: List[Dict[str, Any]] = []
        manifest_locations: List[Dict[str, Any]] = []

        for location_id, template in target_locations.items():
            manifest_locations.append(
                {
                    "location_id": location_id,
                    "template_id": template.id,
                    "name_ko": template.name_ko,
                    "name_en": template.name_en,
                    "keywords": list(template.keywords),
                }
            )
            for time in request_times:
                prompt = self._compose_background_prompt(template, time)
                negative_prompt = self._compose_negative_prompt(template)
                for index in range(count_per_location):
                    filename = f"{location_id}_{time}_{index:02d}.png"
                    requests.append(
                        {
                            "request_id": f"{self.pack_id}__background_plate__{location_id}__{time}__{index:02d}",
                            "request_type": "background_plate",
                            "pack_id": self.pack_id,
                            "genre": self.genre,
                            "location_id": location_id,
                            "location_template_id": template.id,
                            "location_name_ko": template.name_ko,
                            "location_name_en": template.name_en,
                            "time": time,
                            "index": index,
                            "target_relative_path": filename,
                            "prompt": prompt,
                            "negative_prompt": negative_prompt,
                            "seed": self._stable_request_seed(location_id, time, index),
                            "width": 1024,
                            "height": 576,
                            "public_safe": True,
                        }
                    )

        return {
            "schema": "reverie.background_library.asset_requests.v1",
            "pack_id": self.pack_id,
            "genre": self.genre,
            "target_base_path": self._public_target_base_path(),
            "location_count": len(manifest_locations),
            "locations": manifest_locations,
            "times": request_times,
            "images_per_location": count_per_location,
            "request_count": len(requests),
            "requests": requests,
            "public_release_boundary": {
                "contains_generated_media": False,
                "contains_voice_samples": False,
                "contains_model_weights": False,
                "contains_private_paths": False,
            },
        }

    def build_asset_coverage_report(
        self,
        request_manifest: Dict[str, Any],
        base_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Report which requested background plates exist locally."""
        if request_manifest.get("schema") != "reverie.background_library.asset_requests.v1":
            raise ValueError("background asset request manifest schema must be reverie.background_library.asset_requests.v1")

        root = Path(base_path) if base_path else self.base_path
        requests = list(request_manifest.get("requests", []) or [])
        assets: List[Dict[str, Any]] = []
        missing_assets: List[str] = []

        for request in requests:
            target_relative_path = str(request.get("target_relative_path") or "").strip()
            exists = bool(target_relative_path and (root / target_relative_path).exists())
            if not exists and target_relative_path:
                missing_assets.append(target_relative_path)
            assets.append(
                {
                    "request_id": str(request.get("request_id") or ""),
                    "request_type": str(request.get("request_type") or ""),
                    "location_id": str(request.get("location_id") or ""),
                    "time": str(request.get("time") or ""),
                    "target_relative_path": target_relative_path,
                    "exists": exists,
                }
            )

        expected_count = len(assets)
        existing_count = sum(1 for asset in assets if asset["exists"])
        missing_count = expected_count - existing_count
        coverage_ratio = round(existing_count / expected_count, 4) if expected_count else 0.0

        return {
            "schema": "reverie.background_library.asset_coverage.v1",
            "pack_id": str(request_manifest.get("pack_id") or self.pack_id),
            "genre": str(request_manifest.get("genre") or self.genre),
            "target_base_path": str(request_manifest.get("target_base_path") or self._public_target_base_path()),
            "expected_count": expected_count,
            "existing_count": existing_count,
            "missing_count": missing_count,
            "coverage_ratio": coverage_ratio,
            "ready_for_render": expected_count > 0 and missing_count == 0,
            "missing_assets": missing_assets,
            "assets": assets,
            "public_release_boundary": {
                "contains_generated_media": False,
                "contains_voice_samples": False,
                "contains_model_weights": False,
                "contains_private_paths": False,
            },
        }

    def _match_manifest_location(self, request_manifest: Dict[str, Any], location_text: str) -> str:
        raw = str(location_text or "").strip()
        if not raw:
            return ""
        matched = self._match_location(raw)
        if matched:
            return matched

        lowered = raw.lower()
        for location in request_manifest.get("locations", []) or []:
            if not isinstance(location, dict):
                continue
            location_id = str(location.get("location_id") or "").strip()
            candidates = [
                location_id,
                str(location.get("template_id") or ""),
                str(location.get("name_ko") or ""),
                str(location.get("name_en") or ""),
            ]
            candidates.extend(str(keyword) for keyword in (location.get("keywords") or []))
            for candidate in candidates:
                clean = str(candidate or "").strip()
                if clean and (clean.lower() == lowered or clean.lower() in lowered or lowered in clean.lower()):
                    return location_id

        for request in request_manifest.get("requests", []) or []:
            location_id = str(request.get("location_id") or "").strip()
            if location_id and (location_id.lower() == lowered or location_id.lower() in lowered):
                return location_id
        return ""

    def _scene_background_location(self, scene: Dict[str, Any]) -> str:
        for key in ("background_id", "background_location", "location", "place", "setting"):
            value = str(scene.get(key) or "").strip()
            if value:
                return value
        return ""

    def _scene_background_time(self, scene: Dict[str, Any]) -> str:
        for key in ("background_time", "time", "time_of_day"):
            value = str(scene.get(key) or "").strip()
            if value:
                return value
        return "any"

    def _select_background_request(
        self,
        request_manifest: Dict[str, Any],
        *,
        location_id: str,
        time: str,
    ) -> Dict[str, Any]:
        requests = [
            request
            for request in (request_manifest.get("requests", []) or [])
            if isinstance(request, dict) and str(request.get("location_id") or "") == location_id
        ]
        if not requests:
            return {}
        for request in requests:
            if str(request.get("time") or "") == time:
                return request
        for request in requests:
            if str(request.get("time") or "") == "any":
                return request
        return requests[0]

    def build_episode_asset_request_manifest(
        self,
        episode: Dict[str, Any],
        images_per_location: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Build background requests for only the location/time pairs used by one episode."""
        if not isinstance(episode, dict):
            raise ValueError("episode must contain a JSON object")

        scenes = episode.get("scenes") or []
        if not isinstance(scenes, list):
            scenes = []
        count_per_location = int(images_per_location or 1)
        if count_per_location < 1:
            count_per_location = 1

        requests: List[Dict[str, Any]] = []
        source_scenes: List[Dict[str, Any]] = []
        errors: List[str] = []
        requested_pairs = set()

        for index, scene in enumerate(scenes):
            if not isinstance(scene, dict):
                continue
            scene_id = str(scene.get("scene_id") or f"scene_{index + 1:04d}")
            raw_location = self._scene_background_location(scene)
            time = self._scene_background_time(scene)
            location_id = self._match_location(raw_location)
            source_scenes.append(
                {
                    "scene_id": scene_id,
                    "raw_location": raw_location,
                    "location_id": location_id or "",
                    "time": time,
                }
            )
            if not location_id or location_id not in self.config.location_templates:
                errors.append(f"scene {scene_id} background location is not in background templates")
                continue

            pair = (location_id, time)
            if pair in requested_pairs:
                continue
            requested_pairs.add(pair)
            template = self.config.location_templates[location_id]
            prompt = self._compose_background_prompt(template, time)
            negative_prompt = self._compose_negative_prompt(template)
            for request_index in range(count_per_location):
                filename = f"{location_id}_{time}_{request_index:02d}.png"
                requests.append(
                    {
                        "request_id": (
                            f"{self.pack_id}__episode_background_plate__"
                            f"{location_id}__{time}__{request_index:02d}"
                        ),
                        "request_type": "background_plate",
                        "pack_id": self.pack_id,
                        "genre": self.genre,
                        "location_id": location_id,
                        "location_template_id": template.id,
                        "location_name_ko": template.name_ko,
                        "location_name_en": template.name_en,
                        "time": time,
                        "index": request_index,
                        "target_relative_path": filename,
                        "prompt": prompt,
                        "negative_prompt": negative_prompt,
                        "seed": self._stable_request_seed(location_id, time, request_index),
                        "width": 1024,
                        "height": 576,
                        "public_safe": True,
                    }
                )

        return {
            "schema": "reverie.background_library.episode_asset_requests.v1",
            "pack_id": self.pack_id,
            "genre": self.genre,
            "episode_id": str(episode.get("episode_id") or ""),
            "target_base_path": self._public_target_base_path(),
            "scene_count": len(scenes),
            "source_scenes": source_scenes,
            "images_per_location": count_per_location,
            "request_count": len(requests),
            "requests": requests,
            "errors": errors,
            "public_release_boundary": {
                "contains_generated_media": False,
                "contains_voice_samples": False,
                "contains_model_weights": False,
                "contains_private_paths": False,
            },
        }

    def build_episode_asset_coverage_report(
        self,
        request_manifest: Dict[str, Any],
        episode: Dict[str, Any],
        base_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Report only the background plates required by one episode."""
        if request_manifest.get("schema") not in {
            "reverie.background_library.asset_requests.v1",
            "reverie.background_library.episode_asset_requests.v1",
        }:
            raise ValueError(
                "background asset request manifest schema must be "
                "reverie.background_library.asset_requests.v1 or "
                "reverie.background_library.episode_asset_requests.v1"
            )
        if not isinstance(episode, dict):
            raise ValueError("episode must contain a JSON object")

        root = Path(base_path) if base_path else self.base_path
        scenes = episode.get("scenes") or []
        if not isinstance(scenes, list):
            scenes = []

        scene_backgrounds: List[Dict[str, Any]] = []
        missing_assets: List[str] = []
        errors: List[str] = []
        existing_count = 0

        for index, scene in enumerate(scenes):
            if not isinstance(scene, dict):
                continue
            scene_id = str(scene.get("scene_id") or f"scene_{index + 1:04d}")
            raw_location = self._scene_background_location(scene)
            location_id = self._match_manifest_location(request_manifest, raw_location)
            time = self._scene_background_time(scene)
            request = self._select_background_request(request_manifest, location_id=location_id, time=time)
            target_relative_path = str(request.get("target_relative_path") or "").strip()
            exists = bool(target_relative_path and (root / target_relative_path).exists())
            if exists:
                existing_count += 1
            else:
                missing_ref = f"{scene_id}:{target_relative_path or raw_location or '<missing-background>'}"
                missing_assets.append(missing_ref)
            if not location_id:
                errors.append(f"scene {scene_id} background location is not in request manifest")

            scene_backgrounds.append(
                {
                    "scene_id": scene_id,
                    "raw_location": raw_location,
                    "location_id": location_id,
                    "time": time,
                    "request_id": str(request.get("request_id") or ""),
                    "target_relative_path": target_relative_path,
                    "exists": exists,
                }
            )

        expected_count = len(scene_backgrounds)
        missing_count = expected_count - existing_count
        coverage_ratio = round(existing_count / expected_count, 4) if expected_count else 0.0
        return {
            "schema": "reverie.background_library.episode_asset_coverage.v1",
            "pack_id": str(request_manifest.get("pack_id") or self.pack_id),
            "genre": str(request_manifest.get("genre") or self.genre),
            "episode_id": str(episode.get("episode_id") or ""),
            "target_base_path": str(request_manifest.get("target_base_path") or self._public_target_base_path()),
            "scene_count": len(scenes),
            "expected_count": expected_count,
            "existing_count": existing_count,
            "missing_count": missing_count,
            "coverage_ratio": coverage_ratio,
            "ready_for_render": expected_count > 0 and missing_count == 0 and not errors,
            "errors": errors,
            "missing_assets": missing_assets,
            "scene_backgrounds": scene_backgrounds,
            "public_release_boundary": {
                "contains_generated_media": False,
                "contains_voice_samples": False,
                "contains_model_weights": False,
                "contains_private_paths": False,
            },
        }

    # ========================================================================
    # 배경 이미지 생성
    # ========================================================================

    def generate_background_library(
        self,
        sd_api: Any,
        locations: Optional[List[str]] = None,
        images_per_location: int = 5,
        time_variants: bool = True,
        progress_callback: Optional[callable] = None
    ) -> Dict[str, List[str]]:
        """
        배경 이미지 라이브러리 자동 생성

        Args:
            sd_api: SD WebUI API 인스턴스
            locations: 생성할 장소 목록 (None이면 모든 템플릿)
            images_per_location: 장소당 이미지 수
            time_variants: 시간대 변형 생성 여부
            progress_callback: 진행 콜백 (current, total, message)

        Returns:
            {location: [image_paths]}
        """
        self.base_path.mkdir(parents=True, exist_ok=True)

        # 생성할 장소 목록
        if locations:
            normalized_location_ids = []
            for location in locations:
                matched = self._match_location(location)
                if matched:
                    normalized_location_ids.append(matched)
            target_locations = {
                k: v for k, v in self.config.location_templates.items()
                if k in locations or v.name_ko in locations or k in normalized_location_ids
            }
        else:
            target_locations = self.config.location_templates

        if not target_locations:
            logger.warning("생성할 장소 템플릿 없음")
            return {}

        # 시간대 변형
        time_variants_list = ["낮", "밤"] if time_variants else ["any"]

        total_images = len(target_locations) * images_per_location * len(time_variants_list)
        current = 0

        results = {}

        for loc_id, template in target_locations.items():
            results[loc_id] = []

            for time in time_variants_list:
                for i in range(images_per_location // len(time_variants_list) + 1):
                    if len(results[loc_id]) >= images_per_location:
                        break

                    current += 1
                    if progress_callback:
                        progress_callback(current, total_images, f"배경 생성: {template.name_ko} ({time})")

                    # 프롬프트 조합
                    prompt = self._compose_background_prompt(template, time)
                    negative = self._compose_negative_prompt(template)

                    # 시드 생성 (재현 가능)
                    seed_base = int(hashlib.md5(
                        f"{self.pack_id}_{loc_id}_{time}_{i}".encode()
                    ).hexdigest()[:8], 16)

                    try:
                        # SD WebUI API 호출
                        image_path = self._generate_single_background(
                            sd_api=sd_api,
                            prompt=prompt,
                            negative_prompt=negative,
                            seed=seed_base,
                            location=loc_id,
                            time=time,
                            index=i
                        )

                        if image_path:
                            results[loc_id].append(image_path)
                            logger.info(f"배경 생성 완료: {image_path}")

                    except Exception as e:
                        logger.error(f"배경 생성 실패 ({loc_id}): {e}")

        # 라이브러리 저장
        self._save_library()

        return results

    def _compose_background_prompt(
        self,
        template: LocationTemplate,
        time: str = "any",
        weather: str = "any",
        mood: str = "any"
    ) -> str:
        """배경 SD 프롬프트 조합"""
        parts = [
            "masterpiece, best quality, highly detailed background",
            self.config.style_prompt,
            template.base_prompt
        ]

        # 시간대 modifier
        if time != "any" and time in self.config.time_modifiers:
            parts.append(self.config.time_modifiers[time])

        # 날씨 modifier
        if weather != "any" and weather in self.config.weather_modifiers:
            parts.append(self.config.weather_modifiers[weather])

        # 분위기 modifier
        if mood != "any" and mood in self.config.mood_modifiers:
            parts.append(self.config.mood_modifiers[mood])

        # Background plates are composited under character sprites, so they must stay empty.
        parts.append(
            "(empty environment:1.4), (architectural background plate:1.3), "
            "background only, no people, no characters, no figure, no face, no body, "
            "no portrait, no mascot, no mannequin, no statue, 16:9 aspect ratio"
        )

        return ", ".join(filter(None, parts))

    def _compose_negative_prompt(self, template: LocationTemplate) -> str:
        """네거티브 프롬프트 조합"""
        parts = [
            "lowres, bad anatomy, bad hands, text, error, missing fingers",
            "cropped, worst quality, low quality, jpeg artifacts",
            "watermark, signature, blurry",
            "(person:1.7), (human:1.7), (character:1.7), (face:1.7), (body:1.6)",
            "(girl:1.7), (woman:1.7), (man:1.7), (child:1.6), (portrait:1.6)",
            "anime girl, lying person, full body, close-up face, eyes, hair, skin, hands, legs",
            self.config.negative_prompt,
            template.negative_prompt
        ]

        return ", ".join(filter(None, parts))

    def _generate_single_background(
        self,
        sd_api: Any,
        prompt: str,
        negative_prompt: str,
        seed: int,
        location: str,
        time: str,
        index: int
    ) -> Optional[str]:
        """단일 배경 이미지 생성"""

        # 파일명 생성
        filename = f"{location}_{time}_{index:02d}.png"
        output_path = self.base_path / filename

        # SD WebUI API 호출
        try:
            # API 파라미터
            params = {
                "prompt": prompt,
                "negative_prompt": negative_prompt,
                "seed": seed,
                "width": 1024,
                "height": 576,  # 16:9
                "steps": 15,
                "cfg_scale": 7.0,
                "sampler_name": "DPM++ 2M Karras"
            }

            # SD WebUI txt2img 호출
            if hasattr(sd_api, 'txt2img'):
                result = sd_api.txt2img(**params)
            elif hasattr(sd_api, 'generate'):
                result = sd_api.generate(**params)
            else:
                # 간단한 API 래퍼
                import requests
                import base64
                from PIL import Image
                from io import BytesIO

                # SD WebUI API URL (기본값)
                api_url = getattr(sd_api, 'base_url', 'http://127.0.0.1:7860')

                response = requests.post(
                    f"{api_url}/sdapi/v1/txt2img",
                    json=params,
                    timeout=120
                )

                if response.status_code != 200:
                    logger.error(f"SD API 오류: {response.status_code}")
                    return None

                result_data = response.json()
                if not result_data.get("images"):
                    return None

                # 이미지 저장
                image_data = base64.b64decode(result_data["images"][0])
                image = Image.open(BytesIO(image_data))
                image.save(str(output_path))

                result = {"images": [str(output_path)]}

            # 결과 처리
            image_path = str(output_path)
            if isinstance(result, dict) and result.get("images"):
                first_image = result["images"][0]
                if isinstance(first_image, str):
                    if Path(first_image).exists():
                        image_path = first_image
                    else:
                        import base64
                        from io import BytesIO
                        from PIL import Image

                        image_data = base64.b64decode(first_image)
                        image = Image.open(BytesIO(image_data))
                        image.save(str(output_path))
                        image_path = str(output_path)
                else:
                    image_path = str(output_path)

            # 라이브러리에 추가
            bg_image = BackgroundImage(
                filename=filename,
                location=location,
                time=time,
                prompt_used=prompt,
                seed=seed,
                quality_score=1.0
            )

            if location not in self.images:
                self.images[location] = []
            self.images[location] = [
                img for img in self.images[location]
                if getattr(img, "filename", "") != filename
            ]
            self.images[location].append(bg_image)

            return image_path

        except Exception as e:
            logger.error(f"배경 이미지 생성 실패: {e}")
            return None

    # ========================================================================
    # 프리셋 관리
    # ========================================================================

    def add_preset_image(
        self,
        image_path: str,
        location: str,
        time: str = "any",
        weather: str = "any",
        mood: str = "neutral"
    ) -> bool:
        """
        프리셋 이미지 추가

        Args:
            image_path: 원본 이미지 경로
            location: 장소 ID
            time: 시간대
            weather: 날씨
            mood: 분위기

        Returns:
            성공 여부
        """
        try:
            src_path = Path(image_path)
            if not src_path.exists():
                logger.error(f"이미지 파일 없음: {image_path}")
                return False

            # 대상 경로
            self.base_path.mkdir(parents=True, exist_ok=True)
            dest_filename = f"{location}_{time}_preset_{len(self.images.get(location, [])):02d}{src_path.suffix}"
            dest_path = self.base_path / dest_filename

            # 복사
            import shutil
            shutil.copy2(src_path, dest_path)

            # 인덱스에 추가
            bg_image = BackgroundImage(
                filename=dest_filename,
                location=location,
                time=time,
                weather=weather,
                mood=mood,
                quality_score=1.0
            )

            if location not in self.images:
                self.images[location] = []
            self.images[location].append(bg_image)

            self._save_library()

            logger.info(f"프리셋 추가 완료: {dest_path}")
            return True

        except Exception as e:
            logger.error(f"프리셋 추가 실패: {e}")
            return False

    def get_available_locations(self) -> List[str]:
        """사용 가능한 장소 목록"""
        return list(self.config.location_templates.keys())

    def get_location_stats(self) -> Dict[str, int]:
        """장소별 이미지 수 통계"""
        return {loc: len(imgs) for loc, imgs in self.images.items()}

    def to_dict(self) -> Dict[str, Any]:
        """직렬화"""
        return {
            "pack_id": self.pack_id,
            "genre": self.genre,
            "base_path": str(self.base_path),
            "total_images": self._count_images(),
            "locations": self.get_location_stats(),
            "templates": list(self.config.location_templates.keys())
        }


def _load_json_object(path: Path | str, label: str) -> Dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return data


def _infer_pack_id(settings_path: Path | str, pack_id: Optional[str]) -> str:
    clean_pack_id = str(pack_id or "").strip()
    if clean_pack_id:
        return clean_pack_id
    return Path(settings_path).resolve().parent.name


def _background_base_paths(
    pack_id: str,
    *,
    background_root: Optional[str] = None,
    repo_root: Optional[str] = None,
) -> Tuple[Path, str]:
    raw_root = Path(background_root) if background_root else Path("assets") / "backgrounds"
    target_base_path = (
        (Path("assets") / "backgrounds" / pack_id).as_posix()
        if raw_root.is_absolute()
        else (raw_root / pack_id).as_posix()
    )
    if raw_root.is_absolute():
        base_path = raw_root / pack_id
    else:
        base_path = ((Path(repo_root).resolve() if repo_root else Path.cwd()) / raw_root / pack_id).resolve()
    return base_path, target_base_path


def build_background_asset_request_manifest(
    settings_path: Path | str,
    *,
    pack_id: Optional[str] = None,
    genre: Optional[str] = None,
    repo_root: Optional[str] = None,
    background_root: Optional[str] = None,
    locations: Optional[List[str]] = None,
    images_per_location: Optional[int] = None,
    times: Optional[List[str]] = None,
) -> Dict[str, Any]:
    settings = _load_json_object(settings_path, "settings")
    resolved_pack_id = _infer_pack_id(settings_path, pack_id)
    resolved_genre = str(genre or resolved_pack_id or "daily_life_toon")
    base_path, target_base_path = _background_base_paths(
        resolved_pack_id,
        background_root=background_root,
        repo_root=repo_root,
    )
    raw_config = settings.get("background_library", {}) or {}
    if not isinstance(raw_config, dict):
        raise ValueError("settings.background_library must be an object")
    config = build_background_library_config(
        genre=resolved_genre,
        config_data=raw_config,
        library_path=target_base_path,
    )
    library = BackgroundLibrary(
        pack_id=resolved_pack_id,
        genre=resolved_genre,
        config=config,
        base_path=str(base_path),
    )
    return library.build_asset_request_manifest(
        locations=locations,
        images_per_location=images_per_location,
        times=times,
    )


def write_background_asset_request_manifest(
    settings_path: Path | str,
    output_path: Path | str,
    *,
    pack_id: Optional[str] = None,
    genre: Optional[str] = None,
    repo_root: Optional[str] = None,
    background_root: Optional[str] = None,
    locations: Optional[List[str]] = None,
    images_per_location: Optional[int] = None,
    times: Optional[List[str]] = None,
) -> Path:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = build_background_asset_request_manifest(
        settings_path,
        pack_id=pack_id,
        genre=genre,
        repo_root=repo_root,
        background_root=background_root,
        locations=locations,
        images_per_location=images_per_location,
        times=times,
    )
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def build_background_episode_asset_request_manifest(
    settings_path: Path | str,
    episode: Dict[str, Any] | Path | str,
    *,
    pack_id: Optional[str] = None,
    genre: Optional[str] = None,
    repo_root: Optional[str] = None,
    background_root: Optional[str] = None,
    images_per_location: Optional[int] = None,
) -> Dict[str, Any]:
    settings = _load_json_object(settings_path, "settings")
    episode_data = _load_json_object(episode, "episode") if isinstance(episode, (str, Path)) else episode
    resolved_pack_id = _infer_pack_id(settings_path, pack_id)
    resolved_genre = str(genre or resolved_pack_id or "daily_life_toon")
    base_path, target_base_path = _background_base_paths(
        resolved_pack_id,
        background_root=background_root,
        repo_root=repo_root,
    )
    raw_config = settings.get("background_library", {}) or {}
    if not isinstance(raw_config, dict):
        raise ValueError("settings.background_library must be an object")
    config = build_background_library_config(
        genre=resolved_genre,
        config_data=raw_config,
        library_path=target_base_path,
    )
    library = BackgroundLibrary(
        pack_id=resolved_pack_id,
        genre=resolved_genre,
        config=config,
        base_path=str(base_path),
    )
    return library.build_episode_asset_request_manifest(
        episode_data,
        images_per_location=images_per_location,
    )


def write_background_episode_asset_request_manifest(
    settings_path: Path | str,
    episode_path: Path | str,
    output_path: Path | str,
    *,
    pack_id: Optional[str] = None,
    genre: Optional[str] = None,
    repo_root: Optional[str] = None,
    background_root: Optional[str] = None,
    images_per_location: Optional[int] = None,
) -> Path:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = build_background_episode_asset_request_manifest(
        settings_path,
        episode_path,
        pack_id=pack_id,
        genre=genre,
        repo_root=repo_root,
        background_root=background_root,
        images_per_location=images_per_location,
    )
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def build_background_asset_coverage_report(
    request_manifest: Dict[str, Any] | Path | str,
    *,
    repo_root: Optional[str] = None,
    background_root: Optional[str] = None,
) -> Dict[str, Any]:
    manifest = (
        _load_json_object(request_manifest, "background asset request manifest")
        if isinstance(request_manifest, (str, Path))
        else request_manifest
    )
    pack_id = str(manifest.get("pack_id") or "").strip()
    if not pack_id:
        raise ValueError("background asset request manifest pack_id is required")
    genre = str(manifest.get("genre") or pack_id)
    if background_root:
        base_path, target_base_path = _background_base_paths(
            pack_id,
            background_root=background_root,
            repo_root=repo_root,
        )
    else:
        target_base_path = str(manifest.get("target_base_path") or (Path("assets") / "backgrounds" / pack_id).as_posix())
        raw_target = Path(target_base_path)
        base_path = (
            raw_target
            if raw_target.is_absolute()
            else ((Path(repo_root).resolve() if repo_root else Path.cwd()) / raw_target).resolve()
        )
    config = BackgroundLibraryConfig(library_path=target_base_path)
    library = BackgroundLibrary(pack_id=pack_id, genre=genre, config=config, base_path=str(base_path))
    return library.build_asset_coverage_report(manifest)


def write_background_asset_coverage_report(
    request_manifest_path: Path | str,
    output_path: Path | str,
    *,
    repo_root: Optional[str] = None,
    background_root: Optional[str] = None,
) -> Path:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    report = build_background_asset_coverage_report(
        request_manifest_path,
        repo_root=repo_root,
        background_root=background_root,
    )
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def build_background_episode_asset_coverage_report(
    request_manifest: Dict[str, Any] | Path | str,
    episode: Dict[str, Any] | Path | str,
    *,
    repo_root: Optional[str] = None,
    background_root: Optional[str] = None,
) -> Dict[str, Any]:
    manifest = (
        _load_json_object(request_manifest, "background asset request manifest")
        if isinstance(request_manifest, (str, Path))
        else request_manifest
    )
    episode_data = _load_json_object(episode, "episode") if isinstance(episode, (str, Path)) else episode
    pack_id = str(manifest.get("pack_id") or "").strip()
    if not pack_id:
        raise ValueError("background asset request manifest pack_id is required")
    genre = str(manifest.get("genre") or pack_id)
    if background_root:
        base_path, target_base_path = _background_base_paths(
            pack_id,
            background_root=background_root,
            repo_root=repo_root,
        )
    else:
        target_base_path = str(manifest.get("target_base_path") or (Path("assets") / "backgrounds" / pack_id).as_posix())
        raw_target = Path(target_base_path)
        base_path = (
            raw_target
            if raw_target.is_absolute()
            else ((Path(repo_root).resolve() if repo_root else Path.cwd()) / raw_target).resolve()
        )
    config = BackgroundLibraryConfig(library_path=target_base_path)
    library = BackgroundLibrary(pack_id=pack_id, genre=genre, config=config, base_path=str(base_path))
    return library.build_episode_asset_coverage_report(manifest, episode_data)


def write_background_episode_asset_coverage_report(
    request_manifest_path: Path | str,
    episode_path: Path | str,
    output_path: Path | str,
    *,
    repo_root: Optional[str] = None,
    background_root: Optional[str] = None,
) -> Path:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    report = build_background_episode_asset_coverage_report(
        request_manifest_path,
        episode_path,
        repo_root=repo_root,
        background_root=background_root,
    )
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Write public-safe background asset requests and local coverage reports."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    request_parser = subparsers.add_parser(
        "asset-requests",
        help="Build background plate generation requests from a pack settings.json file.",
    )
    request_parser.add_argument("settings_path", help="Path to pack settings.json")
    request_parser.add_argument("--pack-id", default=None, help="Pack id. Defaults to the settings directory name.")
    request_parser.add_argument("--genre", default=None, help="Background profile/genre. Defaults to pack id.")
    request_parser.add_argument("--repo-root", default=None, help="Repository root for resolving relative background roots.")
    request_parser.add_argument("--background-root", default=None, help="Directory that contains per-pack background folders.")
    request_parser.add_argument("--location", action="append", default=None, help="Location text/template id. Can be repeated.")
    request_parser.add_argument("--time", action="append", default=None, help="Requested time variant. Can be repeated.")
    request_parser.add_argument("--images-per-location", type=int, default=None, help="Image count per location and time.")
    request_parser.add_argument("--output", default=None, help="Output JSON path. Prints JSON when omitted.")

    episode_request_parser = subparsers.add_parser(
        "episode-asset-requests",
        help="Build background plate requests only for locations used by an episode JSON file.",
    )
    episode_request_parser.add_argument("settings_path", help="Path to pack settings.json")
    episode_request_parser.add_argument("episode_path", help="Input episode JSON path.")
    episode_request_parser.add_argument("--pack-id", default=None, help="Pack id. Defaults to the settings directory name.")
    episode_request_parser.add_argument("--genre", default=None, help="Background profile/genre. Defaults to pack id.")
    episode_request_parser.add_argument("--repo-root", default=None, help="Repository root for resolving relative background roots.")
    episode_request_parser.add_argument("--background-root", default=None, help="Directory that contains per-pack background folders.")
    episode_request_parser.add_argument("--images-per-location", type=int, default=None, help="Image count per episode location/time.")
    episode_request_parser.add_argument("--output", default=None, help="Output JSON path. Prints JSON when omitted.")

    coverage_parser = subparsers.add_parser(
        "coverage",
        help="Report which requested background plates exist locally.",
    )
    coverage_parser.add_argument("request_manifest_path", help="Input background asset request manifest JSON path.")
    coverage_parser.add_argument("--repo-root", default=None, help="Repository root for resolving relative background roots.")
    coverage_parser.add_argument("--background-root", default=None, help="Directory that contains per-pack background folders.")
    coverage_parser.add_argument("--output", default=None, help="Output JSON path. Prints JSON when omitted.")
    coverage_parser.add_argument("--fail-on-missing", action="store_true", help="Exit 1 when any background is missing.")

    episode_coverage_parser = subparsers.add_parser(
        "episode-coverage",
        help="Report only the requested background plates used by an episode JSON file.",
    )
    episode_coverage_parser.add_argument("request_manifest_path", help="Input background asset request manifest JSON path.")
    episode_coverage_parser.add_argument("episode_path", help="Input episode JSON path.")
    episode_coverage_parser.add_argument("--repo-root", default=None, help="Repository root for resolving relative background roots.")
    episode_coverage_parser.add_argument("--background-root", default=None, help="Directory that contains per-pack background folders.")
    episode_coverage_parser.add_argument("--output", default=None, help="Output JSON path. Prints JSON when omitted.")
    episode_coverage_parser.add_argument("--fail-on-missing", action="store_true", help="Exit 1 when any episode background is missing.")

    args = parser.parse_args(argv)
    if args.command == "asset-requests":
        manifest = build_background_asset_request_manifest(
            args.settings_path,
            pack_id=args.pack_id,
            genre=args.genre,
            repo_root=args.repo_root,
            background_root=args.background_root,
            locations=args.location,
            images_per_location=args.images_per_location,
            times=args.time,
        )
        if args.output:
            output = write_background_asset_request_manifest(
                args.settings_path,
                args.output,
                pack_id=args.pack_id,
                genre=args.genre,
                repo_root=args.repo_root,
                background_root=args.background_root,
                locations=args.location,
                images_per_location=args.images_per_location,
                times=args.time,
            )
            print(f"Wrote background asset requests for {manifest['pack_id']}: {output}")
        else:
            print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return 0
    if args.command == "episode-asset-requests":
        manifest = build_background_episode_asset_request_manifest(
            args.settings_path,
            args.episode_path,
            pack_id=args.pack_id,
            genre=args.genre,
            repo_root=args.repo_root,
            background_root=args.background_root,
            images_per_location=args.images_per_location,
        )
        if args.output:
            output = write_background_episode_asset_request_manifest(
                args.settings_path,
                args.episode_path,
                args.output,
                pack_id=args.pack_id,
                genre=args.genre,
                repo_root=args.repo_root,
                background_root=args.background_root,
                images_per_location=args.images_per_location,
            )
            print(f"Wrote episode background asset requests for {manifest['pack_id']}: {output}")
        else:
            print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return 0
    if args.command == "coverage":
        report = build_background_asset_coverage_report(
            args.request_manifest_path,
            repo_root=args.repo_root,
            background_root=args.background_root,
        )
        if args.output:
            output = write_background_asset_coverage_report(
                args.request_manifest_path,
                args.output,
                repo_root=args.repo_root,
                background_root=args.background_root,
            )
            print(
                f"Wrote background asset coverage for {report['pack_id']}: {output} "
                f"(missing {report['missing_count']}/{report['expected_count']})"
            )
        else:
            print(json.dumps(report, ensure_ascii=False, indent=2))
            print(f"backgrounds missing {report['missing_count']}/{report['expected_count']}")
        if args.fail_on_missing and report["missing_count"]:
            return 1
        return 0
    if args.command == "episode-coverage":
        report = build_background_episode_asset_coverage_report(
            args.request_manifest_path,
            args.episode_path,
            repo_root=args.repo_root,
            background_root=args.background_root,
        )
        if args.output:
            output = write_background_episode_asset_coverage_report(
                args.request_manifest_path,
                args.episode_path,
                args.output,
                repo_root=args.repo_root,
                background_root=args.background_root,
            )
            print(
                f"Wrote episode background asset coverage for {report['pack_id']}: {output} "
                f"(missing {report['missing_count']}/{report['expected_count']})"
            )
        else:
            print(json.dumps(report, ensure_ascii=False, indent=2))
            print(f"episode backgrounds missing {report['missing_count']}/{report['expected_count']}")
        if args.fail_on_missing and report["missing_count"]:
            return 1
        return 0

    parser.error(f"unknown command: {args.command}")
    return 2


# ============================================================================
# 테스트
# ============================================================================

if __name__ == "__main__":
    raise SystemExit(main())

    # 테스트 초기화
    bg_lib = BackgroundLibrary(
        pack_id="horror_test",
        genre="horror"
    )

    print("=== BackgroundLibrary 테스트 ===")
    print(f"장소 템플릿: {bg_lib.get_available_locations()}")
    print(f"현재 이미지 수: {bg_lib._count_images()}")

    # 장소 매칭 테스트
    test_locations = ["어두운 숲 속", "마을 입구", "한옥 방 안", "산속 절"]
    for loc in test_locations:
        matched = bg_lib._match_location(loc)
        print(f"매칭: '{loc}' -> {matched}")

    # 프롬프트 조합 테스트
    template = bg_lib.config.location_templates.get("숲")
    if template:
        prompt = bg_lib._compose_background_prompt(template, "밤", "안개", "horror")
        print(f"\n프롬프트 예시:")
        print(prompt[:200] + "...")

    print("\n=== 테스트 완료 ===")
