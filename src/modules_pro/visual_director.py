import os
import re
import random
import logging
from pathlib import Path
from typing import Tuple, Dict, Optional, List, Any

try:
    from utils.logger import get_logger
    logger = get_logger("visual_director")
except ImportError:
    logger = logging.getLogger(__name__)


def _project_output_path(*parts: str) -> str:
    """Resolve paths under the configured project root when available."""
    try:
        from config.settings import config as app_config

        return os.path.join(app_config.BASE_DIR, *parts)
    except Exception:
        return os.path.join(*parts)

# v59: 지연 import를 위한 플래그
_V59_MODULES_LOADED = False
_V59_LOADED_PACK_PATH = ""  # v59.5.6: 팩 전환 감지용
_scene_analyzer = None
_prompt_composer = None


class VisualDirector:
    """
    [Reverie Visual Guard v50 - Character Silhouette System]
    - SD로 가는 모든 프롬프트를 정제/검열/폴백하는 관문
    - v50 신규: 채널별 캐릭터 형체(실루엣) 시스템 (옵션)
      - 공포: 검은 형체 + 붉은 눈 점
      - 시니어: 색깔 형체 + 미니멀 이모티콘 스타일
    - 정책: 실사 인물 금지, 추상화된 형체만 허용
    - 스타일: Kurzgesagt / Headspace 스타일의 프로페셔널 미니멀

    [배포 모드 vs 세월정거장 모드]
    - 기본(배포): 풍경/배경만 생성 (기존 방식)
    - 세월정거장: 캐릭터 형체 시스템 활성화
    """

    # =========================================================
    # v50: 캐릭터 형체 시스템 활성화 여부
    # - True: 캐릭터 형체 사용 (포시즌공포이야기, 세월정거장)
    # - False: 배포용 - 풍경/배경만
    #
    # 향후: 채널 브랜딩 설정에서 ON/OFF 가능하도록 확장 예정
    # =========================================================
    # v53: 캐릭터 시스템 비활성화 - 모든 장면에 인물이 나오는 문제 해결
    # 스토리와 어울리지 않는 인물이 계속 나와서 비활성화
    # v58: pack_config에서 로드 (아래는 폴백용)
    CHARACTER_SYSTEM_ENABLED = False  # 비활성화: 배경/사물 위주로 생성

    # =========================================================
    # v50: 채널별 캐릭터 형체 정의 (세월정거장 전용)
    # v58: pack_config.ACTIVE_PACK.characters에서 우선 로드, 없으면 여기서 폴백
    # =========================================================
    # v59.5.7: 만화 스타일 캐릭터 (실루엣 → 표정 있는 캐릭터)
    CHANNEL_CHARACTERS = {
        "daily_life_toon": {
            "narrator": {
                "base": "premium Korean webtoon narrator, warm everyday styling, clean foreground cutout, expressive face, fully clothed",
                "style": "layered video-toon, crisp line art, soft daily-life lighting",
            },
            "grandma": {
                "base": "Sunja, elderly Korean grandmother, short gray hair, cardigan and apron, kind but sharp eyes, fully clothed",
                "style": "consistent premium Korean webtoon character, foreground cutout",
            },
            "grandpa": {
                "base": "Deokbae, elderly Korean grandfather, silver hair, vest over shirt, stubborn warm expression, fully clothed",
                "style": "consistent premium Korean webtoon character, foreground cutout",
            },
            "woman": {
                "base": "Korean woman, practical everyday outfit, expressive skeptical eyes, clean webtoon foreground, fully clothed",
                "style": "consistent premium Korean webtoon character, foreground cutout",
            },
            "man": {
                "base": "Korean man, neat everyday outfit, tired but sincere expression, clean webtoon foreground, fully clothed",
                "style": "consistent premium Korean webtoon character, foreground cutout",
            },
            "_default": {
                "base": "Korean daily-life webtoon character, everyday outfit, expressive face, fully clothed",
                "style": "layered video-toon, clean foreground cutout, crisp line art",
            },
        },

        "mystery_toon": {
            "narrator": {
                "base": "premium Korean mystery webtoon narrator, composed expression, dark casual jacket, clean foreground cutout, fully clothed",
                "style": "layered video-toon, restrained shadows, crisp line art",
            },
            "observer": {
                "base": "Nari, Korean young woman, alert decisive eyes, modern casual outfit, clean foreground cutout, fully clothed",
                "style": "consistent Korean mystery webtoon character, restrained lighting",
            },
            "suspect": {
                "base": "middle-aged Korean building manager, ambiguous smile, neat jacket, clean foreground cutout, fully clothed",
                "style": "consistent Korean mystery webtoon character, restrained lighting",
            },
            "woman": {
                "base": "Korean woman, observant expression, practical outfit, clean mystery webtoon foreground, fully clothed",
                "style": "consistent premium Korean webtoon character, controlled shadow",
            },
            "man": {
                "base": "Korean man, quiet suspicious expression, casual jacket, clean mystery webtoon foreground, fully clothed",
                "style": "consistent premium Korean webtoon character, controlled shadow",
            },
            "_default": {
                "base": "Korean mystery webtoon character, expressive eyes, grounded outfit, fully clothed",
                "style": "layered video-toon, clean foreground cutout, restrained shadows",
            },
        },

        # === 공포 채널 ===
        "horror": {
            "ghost": {
                "base": "manga style ghostly figure, long black hair covering face, white dress, eerie floating pose, horror manga character",
                "style": "monochrome manga, ink lineart, high contrast, dramatic shadows",
            },
            "antagonist": {
                "base": "manga style sinister man, sharp features, dark coat, menacing expression, fully clothed",
                "style": "monochrome manga, heavy ink shadows, dramatic noir lighting",
            },
            "protagonist": {
                "base": "manga style young woman, shoulder-length dark hair, casual clothes, expressive face, fully clothed",
                "style": "monochrome manga, clean lineart, detailed expressions",
            },
            "narrator": {
                "base": "manga style middle-aged man, short hair, glasses, serious expression, neat clothing, fully clothed",
                "style": "monochrome manga, clean lines, calm composition",
            },
            "man": {
                "base": "manga style adult man, short dark hair, casual outfit, expressive face, fully clothed",
                "style": "monochrome manga, ink lineart, dramatic shadows",
            },
            "woman": {
                "base": "manga style adult woman, long dark hair, modest clothing, expressive face, fully clothed",
                "style": "monochrome manga, ink lineart, dramatic shadows",
            },
            "_default": {
                "base": "manga style person, dark hair, expressive face, casual clothes, fully clothed",
                "style": "monochrome manga, ink lineart, high contrast",
            },
        },

        # === 시니어 채널 (감동) ===
        "senior_touching": {
            "narrator": {
                "base": "watercolor illustration style warm woman narrator, gentle smile, soft pastel colored clothes, fully clothed",
                "style": "soft watercolor, warm pastel colors, gentle lighting",
            },
            "grandma": {
                "base": "watercolor illustration style elderly grandmother, warm wrinkled smile, grey hair in bun, traditional hanbok, fully clothed",
                "style": "soft watercolor, warm coral tones, heartwarming mood",
            },
            "grandpa": {
                "base": "watercolor illustration style elderly grandfather, gentle wrinkled face, white hair, warm sweater, fully clothed",
                "style": "soft watercolor, earthy warm tones, comforting presence",
            },
            "man": {
                "base": "watercolor illustration style adult man, neat appearance, warm-toned clothes, kind expression, fully clothed",
                "style": "soft watercolor, cool pastel tones, clean composition",
            },
            "woman": {
                "base": "watercolor illustration style adult woman, gentle expression, warm-toned modest dress, fully clothed",
                "style": "soft watercolor, warm pastel tones, elegant simplicity",
            },
            "child": {
                "base": "watercolor illustration style young child, bright curious eyes, school uniform, cheerful expression, fully clothed",
                "style": "soft watercolor, cheerful pastel, playful warmth",
            },
            "_default": {
                "base": "watercolor illustration style person, gentle expression, warm-toned clothes, fully clothed",
                "style": "soft watercolor, pastel colors, warm atmosphere",
            },
        },

        # === 시니어 채널 (막장) ===
        "senior_makjang": {
            "narrator": {
                "base": "webtoon illustration style female narrator, composed expression, professional attire, fully clothed",
                "style": "dramatic webtoon art, muted dramatic tones, cinematic lighting",
            },
            "grandma": {
                "base": "webtoon illustration style elderly grandmother, stern or tearful expression, traditional hanbok, fully clothed",
                "style": "dramatic webtoon art, emotional weight, intense lighting",
            },
            "grandpa": {
                "base": "webtoon illustration style elderly grandfather, stern expression, traditional vest, fully clothed",
                "style": "dramatic webtoon art, somber tones, dramatic mood",
            },
            "man": {
                "base": "webtoon illustration style adult man, sharp features, business suit, tense expression, fully clothed",
                "style": "dramatic webtoon art, high contrast, sharp shadows",
            },
            "woman": {
                "base": "webtoon illustration style adult woman, emotional expression, modest dress, fully clothed",
                "style": "dramatic webtoon art, dramatic pastel tones, cinematic feel",
            },
            "antagonist": {
                "base": "webtoon illustration style scheming person, cold smirk, dark clothing, imposing posture, fully clothed",
                "style": "dramatic webtoon art, high contrast, dramatic shadows",
            },
            "_default": {
                "base": "webtoon illustration style person, expressive face, formal clothing, fully clothed",
                "style": "dramatic webtoon art, dramatic tones, webtoon aesthetic",
            },
        },
    }

    # =========================================================
    # v59.1.5: DEPRECATED - 팩 JSON으로 이동됨
    # 팩 파일의 visual.forced_style에서 설정
    # 이 변수는 참조용으로만 남김 (사용되지 않음)
    # =========================================================
    # v59.5.7: DEPRECATED & UNUSED — 팩 JSON의 visual.forced_style로 완전 이동
    # 폴백으로도 사용되지 않으나, 참조용으로 유지 (인물 차단 키워드 제거 완료)
    CHANNEL_FORCED_STYLES_DEPRECATED = {
        "horror": {
            "force_positive": "monochrome manga, black and white ink drawing, high contrast, dramatic shadows, clean lineart",
            "force_negative": "photorealistic, photograph, 3d render, nsfw, nude, naked, revealing clothes",
        },
        "senior_touching": {
            "force_positive": "warm watercolor illustration, soft pastel colors, gentle gradients, warm lighting, heartwarming mood",
            "force_negative": "scary, dark, horror, photograph, 3d render, photorealistic, nsfw, nude",
        },
        "senior_makjang": {
            "force_positive": "dramatic webtoon illustration, dramatic pastel tones, webtoon aesthetic, cinematic composition",
            "force_negative": "photograph, 3d render, photorealistic, gore, blood, nsfw, nude, naked",
        },
    }

    # =========================================================
    # v50: 감정별 표정 힌트 (SD 프롬프트용)
    # =========================================================
    EMOTION_EXPRESSION_HINTS = {
        # 긍정적 감정
        "happy": "simple curved smile line, upturned dot eyes",
        "joy": "wide curved smile, bright dot eyes",
        "grateful": "gentle smile curve, soft dot eyes",
        "hopeful": "slight upward smile, looking up pose",
        "relieved": "relaxed smile curve, shoulders down",

        # 부정적 감정
        "sad": "downturned curve mouth, drooping dot eyes",
        "crying": "downturned mouth, dot eyes with small tear drop shapes below",
        "angry": "straight line mouth, angled dot eyes",
        "frustrated": "wavy line mouth, furrowed brow lines",
        "scared": "small o-shaped mouth, wide dot eyes",
        "anxious": "wobbly line mouth, uneven dot eyes",
        "shocked": "open circle mouth, very wide dot eyes",

        # 중립/기타
        "calm": "neutral straight line mouth, relaxed dot eyes",
        "thinking": "slight curve mouth to side, one dot eye larger",
        "neutral": "simple straight line, basic dot eyes",
        "surprised": "small open mouth, raised dot eyes",
    }

    # =========================================================
    # v50: 동작/포즈 힌트
    # =========================================================
    ACTION_POSE_HINTS = {
        "standing": "upright standing pose",
        "sitting": "seated pose on chair or floor",
        "walking": "mid-stride walking pose",
        "running": "dynamic running pose",
        "talking": "gesturing hand near chest, speaking pose",
        "listening": "head slightly tilted, attentive pose",
        "crying": "hunched shoulders, head down",
        "laughing": "head tilted back slightly, open posture",
        "thinking": "hand near chin, contemplative pose",
        "hugging": "arms extended or wrapped around",
        "arguing": "animated hand gestures, tense posture",
        "praying": "hands together, head bowed",
        "sleeping": "lying down pose, peaceful",
        "working": "seated at desk pose",
        "cooking": "standing near counter, hands active",
    }

    # =========================================================
    # v59.7.0: NSFW/폭력/품질만 차단 (인물 허용)
    # 기존 HUMAN_BAN_CSV에서 person/face/body 관련 ~50개 키워드 제거
    # =========================================================
    SAFETY_BAN_CSV = """
        nude, nudity, naked, bare skin, exposed, revealing,
        bikini, swimsuit, underwear, lingerie, bra, panties, thong,
        cleavage, nipple, nipples, areola, genital, genitals, penis, vagina,
        nsfw, explicit, sexual, erotic, sexy, seductive, provocative,
        blood, bloody, gore, gory, wound, injury, cut, bruise, scar,
        corpse, dead body, skeleton, skull, bones, organs, viscera,
        violence, violent, murder, kill, weapon, knife, gun, sword,
        deformed, disfigured, mutated, malformed, distorted,
        realistic photo, photorealistic, photo-realistic, photography, photograph,
        3d render, 3d model, CGI, real person, real human
    """.replace("\n", " ").strip()

    TEXT_ARTIFACT_BAN = (
        "text, letters, typography, watermark, logo, signature, "
        "caption, subtitle, signage"
    )

    # =========================================================
    # v59.7.0: 인물 허용으로 암시적 치환 불필요 (빈 dict)
    # 기존: "set for two" → "empty table" 등 인간 암시→무인 치환
    # =========================================================
    IMPLICIT_REPLACEMENTS = {}

    # =========================================================
    # ✅ 본편/비상용 폴백
    # v58: pack_config.ACTIVE_PACK.visual.safe_fallbacks에서 우선 로드
    # =========================================================
    SAFE_FALLBACKS = [
        "empty old room, dusty furniture, dim lamp light, cinematic atmosphere",
        "rainy window with droplets, blurry city lights, melancholic mood, empty interior",
        "abandoned hallway, peeling wallpaper, flickering light, eerie quiet",
        "messy desk with scattered papers, coffee cup, noir lighting, no people",
        "empty train station platform at dusk, long perspective, solitude",
        "foggy alley at night, wet pavement reflections, mysterious mood, no people",
        "empty hospital corridor, cold fluorescent light, sterile atmosphere",
        "lonely chair beside small table, soft light, still life composition",
    ]

    # =========================================================
    # ⭐ 썸네일 전용 배경 풀 (카테고리/모드별)
    # =========================================================
    # ⭐ 썸네일 전용 풀 (카테고리/모드별로 완전 분리)
    THUMBNAIL_POOLS = {
        "daily_life_toon": [
            "Korean apartment living room, warm afternoon light, clean webtoon background, no people",
            "small neighborhood cafe, rainy window, two empty chairs, clean webtoon background, no people",
            "quiet convenience store exterior at night, soft fluorescent glow, clean webtoon background, no people",
            "apartment rooftop laundry line at sunset, city apartments behind, clean webtoon background, no people",
        ],
        "mystery_toon": [
            "old Korean apartment hallway at night, dim fluorescent light, clean mystery webtoon background, no people",
            "narrow Korean alley after rain, wet pavement, distant convenience store glow, clean webtoon background, no people",
            "empty rooftop with water tank at blue dusk, restrained shadows, clean mystery webtoon background, no people",
            "small storage room with boxes and old umbrella stand, dim light, clean mystery webtoon background, no people",
        ],
        # =========================
        # HORROR
        # =========================
        "horror_horror": [
            "abandoned hallway, flickering fluorescent light, peeling wallpaper, wet floor reflections, no people, cinematic",
            "empty hospital corridor at night, wheelchair near wall, cold light, eerie silence, no people",
            "dark staircase down to basement, single swinging bulb, damp concrete walls, no people",
            "old library aisle, dusty bookshelves, one desk lamp, long shadows, no people",
            "rainy night street seen through window, water droplets on glass, dim neon glow, no people",
            "abandoned classroom, overturned chair, chalk dust, faint light from window, no people",
            "empty subway platform, broken sign, puddles, fog, no people",
            "narrow alley, wet pavement, fire escape ladder, distant streetlight, no people",
            "attic with stacked boxes, dust particles in light beam, small window, no people",
            "empty theater auditorium, torn curtain, spotlight on stage, no people",
            "foggy cemetery path, old gravestones, bare trees, no people",
            "derelict factory interior, rusted machinery, broken windows, no people",
            "old motel room, buzzing lamp, stained wallpaper, suitcase left behind, no people",
            "bathroom with cracked mirror, dripping faucet, harsh light, no people",
            "corridor with slightly open door, light leaking underneath, no people",
            "abandoned living room, furniture covered with sheets, moonlight, no people",
            "dark forest path, twisted branches, thick fog, no people",
            "lonely street lamp in fog, empty road, film grain mood, no people",
            "old phone on small table, off-hook, dim room, no people",
            "messy desk, scattered papers, burnt candle, heavy shadow, no people",
            "door chain lock hanging, scratch marks on door, dim hallway, no people",
            "window with heavy rain, blurred city lights, empty interior, no people",
            "close-up: old key on dusty floor, long shadow, no people",
            "close-up: cracked picture frame, torn photo missing faces, no people",
            "close-up: spilled ink on letter, wax seal broken, no people",
            "abandoned train station platform at night, fog, empty bench, no people",
            "empty parking garage, harsh overhead light, long perspective, no people",
            "storage room, plastic covers, single flashlight beam, no people",
            "elevator lobby, floor indicator stuck, mirror reflections, no people",
            "kitchen table, cold leftover meal, single chair pushed back, no people",
        ],

        # =========================
        # SENIOR - TOUCHING
        # =========================
        "senior_touching": [
            "rainy bus stop at dusk, empty wooden bench, warm streetlight, no people, gentle mood",
            "old handwritten letter on wooden table, warm sunlight, teacup steam, no people",
            "vintage transistor radio on shelf, soft golden hour light, no people",
            "steam tea cup on windowsill, rain droplets on glass, cozy interior, no people",
            "open photo album on table, sepia photos, soft light, no people",
            "empty train station platform at sunset, orange sky glow, no people",
            "knitted blanket draped over rocking chair, fireplace glow, no people",
            "old music box on dresser, soft bedroom light, no people",
            "postcard with handwritten message, stamp visible, desk lamp, no people",
            "pocket watch on wooden surface, chain coiled, warm light, no people",
            "pair of slippers by the door, gentle morning light, no people",
            "umbrella left near doorway, raincoat hanging, quiet home, no people",
            "small bouquet in vase, wilted petals, soft sunbeam, no people",
            "kitchen table, simple meal set, one chair, calm light, no people",
            "library desk, open book, reading glasses, sunbeam, no people",
            "old calendar with circled date, red pen, warm wall light, no people",
            "empty seaside bench at dawn, soft pastel sky, no people",
            "narrow alley in small town, wet stones after rain, no people",
            "market street early morning, shutters closed, calm mood, no people",
            "old suitcase in corner, dust, gentle light, no people",
            "handwritten recipe card beside mixing bowl, morning light, no people",
            "window lace curtain, rain outside, warm lamp inside, no people",
            "telephone on small table, note beside it, warm mood, no people",
            "train ticket on table, tea stain, soft sunlight, no people",
            "wooden drawer open, old photographs inside, no people",
            "pair of gloves on chair, quiet room, no people",
            "old scarf hanging on coat rack, warm hallway light, no people",
            "garden gate slightly open, flower path, golden light, no people",
            "laundry line with white cloth, breeze, calm yard, no people",
            "small shrine corner with candle, gentle glow, no people",
        ],

        # =========================
        # SENIOR - MAKJANG
        # =========================
        "senior_makjang": [
            "torn contract papers on desk, harsh overhead light, rain on window, no people, dramatic",
            "broken picture frame on floor, scattered documents, sharp shadows, no people",
            "sealed legal envelope with red stamp on desk, desk lamp glow, no people",
            "smartphone screen with unread messages, dark bedroom, blue glow, no people",
            "wedding ring on table, cracked wine glass, city lights reflection, no people",
            "bank statement papers spread out, calculator, tense lighting, no people",
            "kitchen counter, car keys, abandoned luggage near door, no people",
            "empty courthouse hallway, fluorescent lights, long corridor, no people",
            "closed wooden door, light beam underneath, empty corridor, no people",
            "dining table with untouched meal, spilled wine stain, one chair pushed back, no people",
            "makeup items scattered on bathroom tile, broken mirror shards, no people",
            "calendar with many dates crossed out, red marker, cold light, no people",
            "empty meeting room, chairs aligned, single file folder on table, no people",
            "opened drawer with documents peeking out, dusty attic light, no people",
            "parking lot at night, one car door ajar, streetlight, no people",
            "stairwell landing, echoing light, dropped glove, no people",
            "apartment hallway, door number plate, harsh shadows, no people",
            "desk with resignation letter, pen, coffee stain, no people",
            "kitchen sink with overflowing water, dim light, no people",
            "phone receiver off-hook, silent room, no people",
            "laptop open to email screen (blurred), dark room, no people",
            "trash bin with shredded papers, office corner, no people",
            "curtain slightly open, streetlight stripes on wall, no people",
            "high heel shoe left behind near sofa, dramatic shadow, no people",
            "jewelry box open, empty slot, cold light, no people",
            "messy bed, folded suit on chair, tense mood, no people",
            "door chain lock broken, scratch marks, hallway light, no people",
            "kitchen table, two cups, one overturned, no people",
            "elevator lobby mirror reflections, empty space, no people",
            "staircase with torn photo pieces on steps, no people",
        ],

        # 기본 키
        "horror": [],
        "senior": [],
    }

    def __init__(self):
        self.ban_list = [w.strip() for w in self.SAFETY_BAN_CSV.split(",") if w.strip()]
        # v58: pack_config 캐시 (동적 로드)
        self._pack_config = None

    def _get_pack_config(self):
        """v58: pack_config 지연 로드 (순환 import 방지)"""
        if self._pack_config is None:
            try:
                from config import pack_config
                self._pack_config = pack_config
            except ImportError:
                logger.warning("[VisualDirector] pack_config import 실패, 하드코딩 폴백 사용")
                self._pack_config = False
        return self._pack_config if self._pack_config else None

    def _get_safe_fallbacks(self) -> List[str]:
        """v58: 팩에서 safe_fallbacks 가져오기 (없으면 하드코딩 폴백)"""
        pc = self._get_pack_config()
        if pc and pc.ACTIVE_PACK.is_loaded:
            fallbacks = pc.ACTIVE_PACK.visual.safe_fallbacks
            if fallbacks:
                return fallbacks
        return self.SAFE_FALLBACKS

    def _get_forced_style(self, channel_type: str) -> Dict[str, str]:
        """v59.1.5: 팩에서만 forced_style 가져오기 (하드코딩 폴백 제거)"""
        pc = self._get_pack_config()
        if pc and pc.ACTIVE_PACK.is_loaded:
            forced = pc.ACTIVE_PACK.visual.forced_style
            if forced:
                return forced
        # v59.1.5: 하드코딩 폴백 제거 - 팩에 forced_style이 없으면 빈 dict 반환
        return {}

    def _get_thumbnail_backgrounds(self) -> List[str]:
        """v58: 팩에서 thumbnail_backgrounds 가져오기"""
        pc = self._get_pack_config()
        if pc and pc.ACTIVE_PACK.is_loaded:
            bgs = pc.ACTIVE_PACK.visual.thumbnail_backgrounds
            if bgs:
                return bgs
        return []

    def _get_characters(self, channel_type: str) -> Dict:
        """v58: 팩에서 characters 가져오기"""
        pc = self._get_pack_config()
        if pc and pc.ACTIVE_PACK.is_loaded:
            chars = pc.ACTIVE_PACK.characters
            if chars:
                return chars
        return self.CHANNEL_CHARACTERS.get(channel_type, {})

    def _is_character_system_enabled(self) -> bool:
        """v58: 팩에서 character_system_enabled 가져오기"""
        pc = self._get_pack_config()
        if pc and pc.ACTIVE_PACK.is_loaded:
            return pc.ACTIVE_PACK.visual.character_system_enabled
        return self.CHARACTER_SYSTEM_ENABLED

    # =========================================================
    # v59: Visual Storytelling 시스템
    # =========================================================
    def _is_visual_storytelling_enabled(self) -> bool:
        """v59: Visual Storytelling 활성화 여부 확인

        우선순위:
        1. GUI 체크박스 (config.VISUAL_STORYTELLING_OVERRIDE)
        2. 팩 설정 (visual_storytelling.enabled)
        3. 기본값 (False)
        """
        # v59.1.2: GUI 오버라이드 지원
        from config.settings_v2 import config  # v61.1: 인스턴스 import
        if hasattr(config, 'VISUAL_STORYTELLING_OVERRIDE') and config.VISUAL_STORYTELLING_OVERRIDE is not None:
            return config.VISUAL_STORYTELLING_OVERRIDE

        # 팩 설정 확인
        pc = self._get_pack_config()
        if pc and pc.ACTIVE_PACK.is_loaded:
            vs = pc.ACTIVE_PACK.visual_storytelling
            # v59.5.16: dict/dataclass 양쪽 안전 접근
            if isinstance(vs, dict):
                return vs.get('enabled', False)
            return vs.enabled
        return False

    def _get_visual_storytelling_config(self) -> Optional[Any]:
        """v59: Visual Storytelling 설정 가져오기"""
        pc = self._get_pack_config()
        if pc and pc.ACTIVE_PACK.is_loaded:
            return pc.ACTIVE_PACK.visual_storytelling
        return None

    def _load_v59_modules(self):
        """v59: SceneAnalyzer, PromptComposer 지연 로드"""
        global _V59_MODULES_LOADED, _V59_LOADED_PACK_PATH, _scene_analyzer, _prompt_composer

        # v59.5.6: 팩 전환 감지 — 다른 팩이면 재로드
        current_pack_path = ""
        try:
            _pc = self._get_pack_config()
            if _pc and _pc.ACTIVE_PACK and _pc.ACTIVE_PACK.is_loaded:
                current_pack_path = _pc.ACTIVE_PACK.source_path
        except Exception as e:
            logger.debug(f"[VisualDirector] 팩 경로 조회 실패 (무시): {e}")

        if _V59_MODULES_LOADED and current_pack_path == _V59_LOADED_PACK_PATH:
            return _scene_analyzer, _prompt_composer
        elif _V59_MODULES_LOADED and current_pack_path != _V59_LOADED_PACK_PATH:
            logger.info(f"[VisualDirector] 팩 전환 감지! {_V59_LOADED_PACK_PATH} -> {current_pack_path} - 모듈 재로드")
            _V59_MODULES_LOADED = False

        try:
            from modules_pro.scene_analyzer import SceneAnalyzer
            from modules_pro.prompt_composer import PromptComposer

            vs_config = self._get_visual_storytelling_config()
            if vs_config:
                # v59.1.6: dict/object 양쪽 안전 접근
                if isinstance(vs_config, dict):
                    char_defs = vs_config.get('characters', {})
                    sd_model_cfg = vs_config.get('sd_model', None)
                else:
                    char_defs = getattr(vs_config, 'characters', {})
                    sd_model_cfg = getattr(vs_config, 'sd_model', None)

                # v59.5.6: 팩에서 art_style_config 로드
                _art_style_cfg = None
                try:
                    _pc = self._get_pack_config()
                    if _pc and _pc.ACTIVE_PACK and _pc.ACTIVE_PACK.is_loaded:
                        _art_style_cfg = _pc.ACTIVE_PACK.scene_analyzer or None
                except Exception as e:
                    logger.debug(f"[VisualDirector] art_style_config 로드 실패 (무시): {e}")

                # SceneAnalyzer: character_definitions + art_style_config 파라미터 사용
                _scene_analyzer = SceneAnalyzer(
                    gemini_client=None,  # 폴백 분석 사용
                    character_definitions=char_defs,
                    art_style_config=_art_style_cfg
                )
                # v59.1.5: 팩의 forced_style에서 base_positive/negative 가져오기
                pc = self._get_pack_config()
                channel_type = pc.ACTIVE_PACK.channel_type if pc and pc.ACTIVE_PACK.is_loaded else "daily_life_toon"
                forced_style = self._get_forced_style(channel_type)
                base_pos = forced_style.get('force_positive', '')
                base_neg = forced_style.get('force_negative', '')
                logger.info(f"[VisualDirector] forced_style 적용: pos={base_pos[:50]}..., neg={base_neg[:50]}...")

                # PromptComposer: character_definitions, sd_model_config, forced_style 적용
                _prompt_composer = PromptComposer(
                    character_definitions=char_defs,
                    sd_model_config=sd_model_cfg,
                    base_positive=base_pos,
                    base_negative=base_neg
                )
                _V59_MODULES_LOADED = True
                _V59_LOADED_PACK_PATH = current_pack_path
                logger.info(f"[VisualDirector] v59 모듈 로드 완료: SceneAnalyzer, PromptComposer (pack: {current_pack_path})")
            else:
                logger.warning("[VisualDirector] v59 설정 없음, 모듈 로드 건너뜀")

        except ImportError as e:
            logger.error(f"[VisualDirector] v59 모듈 import 실패: {e}")
            _scene_analyzer = None
            _prompt_composer = None

        return _scene_analyzer, _prompt_composer

    def generate_prompt_v59(
        self,
        dialogue: str,
        speaker: str = "나레이터",
        dialogue_index: int = 0,
        context_dialogues: Optional[List[str]] = None,
    ) -> Tuple[str, str, Dict]:
        """
        v59: Visual Storytelling 모드 프롬프트 생성

        대사를 분석하여 장면 컨텍스트를 추출하고,
        캐릭터/배경/분위기를 반영한 SD 프롬프트 생성

        Args:
            dialogue: 현재 대사 텍스트
            speaker: 화자 (기본값: 나레이터)
            dialogue_index: 대사 인덱스
            context_dialogues: 이전 대사들 (컨텍스트)

        Returns:
            (positive_prompt, negative_prompt, scene_context_dict)
        """
        if not self._is_visual_storytelling_enabled():
            # v59 비활성화 → 기존 배경 전용 로직
            fallbacks = self._get_safe_fallbacks()
            bg = random.choice(fallbacks)
            pos, neg = self.finalize(bg)
            return pos, neg, {}

        scene_analyzer, prompt_composer = self._load_v59_modules()

        if not scene_analyzer or not prompt_composer:
            # 모듈 로드 실패 → 폴백
            logger.warning("[VisualDirector] v59 모듈 없음, 배경 전용 폴백")
            fallbacks = self._get_safe_fallbacks()
            bg = random.choice(fallbacks)
            pos, neg = self.finalize(bg)
            return pos, neg, {}

        try:
            # 1. 장면 분석 (SceneAnalyzer.analyze_dialogue 시그니처에 맞춤)
            scene_result = scene_analyzer.analyze_dialogue(
                dialogue=dialogue,
                speaker=speaker,
                index=dialogue_index,
                context_dialogues=context_dialogues
            )

            # 2. SD 프롬프트 생성 (compose_prompt는 ComposedPrompt 반환)
            composed = prompt_composer.compose_prompt(scene_result)

            # ComposedPrompt에서 positive, negative 추출
            positive = composed.positive
            negative = composed.negative

            # 3. v59.1.6: 인간 금지어 제거하지 않는 v59 전용 sanitize 사용
            positive = self.sanitize_positive_v59(positive)
            negative = self.build_negative_v59(negative)

            logger.debug(f"[VisualDirector] v59 프롬프트 생성: {positive[:100]}...")

            # scene_result를 dict로 변환 (SceneAnalysisResult.to_dict() 사용)
            if hasattr(scene_result, 'to_dict'):
                context_dict = scene_result.to_dict()
            elif hasattr(scene_result, '__dict__'):
                context_dict = {
                    'characters': getattr(scene_result, 'characters', []),
                    'location': getattr(scene_result, 'location', ''),
                    'time_of_day': getattr(scene_result, 'time_of_day', ''),
                    'weather': getattr(scene_result, 'weather', ''),
                    'atmosphere': getattr(scene_result, 'atmosphere', ''),
                    'image_action': getattr(scene_result, 'image_action', 'new'),
                }
            else:
                context_dict = {}

            return positive, negative, context_dict

        except Exception as e:
            logger.error(f"[VisualDirector] v59 프롬프트 생성 실패: {e}")
            # 에러 시 폴백
            fallbacks = self._get_safe_fallbacks()
            bg = random.choice(fallbacks)
            pos, neg = self.finalize(bg)
            return pos, neg, {}

    def get_visual_effects_config(self) -> Dict[str, Any]:
        """
        v59: Remotion용 시각 효과 설정 반환

        Returns:
            RemotionAssembler.set_visual_effects()에 전달할 딕셔너리
        """
        vs_config = self._get_visual_storytelling_config()

        if not vs_config:
            return {}

        # v59.5.16: dict/dataclass 양쪽 안전 접근 (main_window._load_package_to_active_pack 경로에서 dict 가능)
        if isinstance(vs_config, dict):
            if not vs_config.get('enabled', False):
                return {}
            ve_data = vs_config.get('visual_effects', {})
            # v59.5.16: transitions는 visual_effects 내부 또는 visual_storytelling 직접 자식 둘 다 탐색
            trans_data = ve_data.get('transitions', {}) if ve_data else {}
            if not trans_data:
                trans_data = vs_config.get('transitions', {})
            if not ve_data:
                return {}
            # dict에서 직접 camelCase 변환
            vignette_data = ve_data.get('vignette', {})
            color_data = ve_data.get('color_filter', {})
            return {
                'vignette': {
                    'enabled': vignette_data.get('enabled', True) if isinstance(vignette_data, dict) else ve_data.get('vignette_enabled', True),
                    'intensity': vignette_data.get('intensity', 0.3) if isinstance(vignette_data, dict) else ve_data.get('vignette_intensity', 0.3),
                    'color': vignette_data.get('color', '#000000') if isinstance(vignette_data, dict) else ve_data.get('vignette_color', '#000000'),
                },
                'colorFilter': {
                    'enabled': ('type' in color_data) if isinstance(color_data, dict) else ve_data.get('color_filter_enabled', False),
                    'type': color_data.get('type', '') if isinstance(color_data, dict) else ve_data.get('color_filter', ''),
                    'intensity': color_data.get('saturation', color_data.get('intensity', 0.5)) if isinstance(color_data, dict) else ve_data.get('color_filter_intensity', 0.5),
                },
                'kenBurns': {
                    'enabled': ve_data.get('ken_burns_enabled', True),
                    'zoomRange': ve_data.get('ken_burns_zoom_range', [1.0, 1.15]),
                    'panEnabled': ve_data.get('ken_burns_pan_enabled', True),
                },
                'transition': {
                    'default': trans_data.get('default_transition', trans_data.get('default', 'crossfade')) if isinstance(trans_data, dict) else 'crossfade',
                    'duration': trans_data.get('transition_duration', trans_data.get('duration', 0.5)) if isinstance(trans_data, dict) else 0.5,
                },
            }

        if not vs_config.enabled:
            return {}

        ve = vs_config.visual_effects
        trans = vs_config.transitions  # v59.5.15b: TransitionStyle 전달

        return {
            'vignette': {
                'enabled': ve.vignette_enabled,
                'intensity': ve.vignette_intensity,
                'color': ve.vignette_color,
            },
            'colorFilter': {
                'enabled': ve.color_filter_enabled,
                'type': ve.color_filter,
                'intensity': ve.color_filter_intensity,
            },
            'kenBurns': {
                'enabled': ve.ken_burns_enabled,
                'zoomRange': ve.ken_burns_zoom_range,
                'panEnabled': ve.ken_burns_pan_enabled,
            },
            'transition': {  # v59.5.15b: 팩 전환 스타일 → Remotion 전달
                'default': trans.default_transition,
                'duration': trans.transition_duration,
            },
        }

    def get_subtitle_style_config(self) -> Dict[str, Any]:
        """
        v59: Remotion용 자막 스타일 설정 반환

        Returns:
            RemotionAssembler.set_subtitle_style()에 전달할 딕셔너리
        """
        vs_config = self._get_visual_storytelling_config()

        if not vs_config:
            return {}

        # v59.5.16: dict/dataclass 양쪽 안전 접근
        if isinstance(vs_config, dict):
            if not vs_config.get('enabled', False):
                return {}
            ss = vs_config.get('subtitle_style', {})
            if not ss:
                return {}
            return {
                'fontFamily': ss.get('font_family', 'Noto Sans KR'),
                'fontSize': ss.get('font_size', 48),
                'fontWeight': ss.get('font_weight', 'bold'),
                'textColor': ss.get('text_color', '#FFFFFF'),
                'strokeColor': ss.get('stroke_color', '#000000'),
                'strokeWidth': ss.get('stroke_width', 3),
                'shadowColor': ss.get('shadow_color', 'rgba(0,0,0,0.8)'),
                'shadowBlur': ss.get('shadow_blur', 8),
                'backgroundEnabled': ss.get('background_enabled', False),
                'backgroundColor': ss.get('background_color', 'rgba(0,0,0,0.6)'),
                'backgroundPadding': ss.get('background_padding', 16),
                'backgroundRadius': ss.get('background_radius', 8),
                'position': ss.get('position', 'bottom'),
                'marginBottom': ss.get('margin_bottom', 80),
                'textAlign': ss.get('text_align', 'center'),
                'animationIn': ss.get('animation_in', 'fadeIn'),
                'animationOut': ss.get('animation_out', 'fadeOut'),
                'animationDuration': ss.get('animation_duration', 0.3),
                'speakerColors': ss.get('speaker_colors', {}),
            }

        if not vs_config.enabled:
            return {}

        ss = vs_config.subtitle_style
        return {
            'fontFamily': ss.font_family,
            'fontSize': ss.font_size,
            'fontWeight': ss.font_weight,
            'textColor': ss.text_color,
            'strokeColor': ss.stroke_color,
            'strokeWidth': ss.stroke_width,
            'shadowColor': ss.shadow_color,
            'shadowBlur': ss.shadow_blur,
            'backgroundEnabled': ss.background_enabled,
            'backgroundColor': ss.background_color,
            'backgroundPadding': ss.background_padding,
            'backgroundRadius': ss.background_radius,
            'position': ss.position,
            'marginBottom': ss.margin_bottom,
            'textAlign': ss.text_align,
            'animationIn': ss.animation_in,
            'animationOut': ss.animation_out,
            'animationDuration': ss.animation_duration,
            'speakerColors': ss.speaker_colors if hasattr(ss, 'speaker_colors') else {},  # v59.5.15
        }

    # =========================================================
    # 공통 유틸
    # =========================================================
    @staticmethod
    def split_prompt(p: str) -> Tuple[str, str]:
        if not p:
            return "", ""
        if "|||" in p:
            a, b = p.split("|||", 1)
            return a.strip(), b.strip()
        return p.strip(), ""

    def _apply_implicit(self, text: str) -> str:
        t = text or ""
        low = t.lower()
        for danger, safe in self.IMPLICIT_REPLACEMENTS.items():
            pattern = r"\b" + re.escape(danger) + r"\b"
            if re.search(pattern, low):
                t = re.sub(pattern, safe, t, flags=re.IGNORECASE)
                low = t.lower()
        return t

    def _remove_banned_tokens(self, text: str) -> str:
        if not text:
            return ""
        t = text
        for ban in self.ban_list:
            pattern = r"\b" + re.escape(ban) + r"\b"
            t = re.sub(pattern, "", t, flags=re.IGNORECASE)
        t = re.sub(r",\s*,+", ", ", t)
        t = re.sub(r"\s{2,}", " ", t)
        return t.strip(" ,")

    # =========================================================
    # 본편 이미지용 API
    # =========================================================
    def sanitize_positive(self, positive: str) -> str:
        p = (positive or "").strip()
        p = self._apply_implicit(p)
        p = self._remove_banned_tokens(p)
        if len(p) < 5:
            # v58: 팩에서 safe_fallbacks 우선 로드
            fallbacks = self._get_safe_fallbacks()
            p = random.choice(fallbacks)
        return p

    def sanitize_positive_v59(self, positive: str) -> str:
        """
        v59.1.6: Visual Storytelling 전용 positive sanitize

        SAFETY_BAN_CSV 키워드를 제거하지 않음 - 캐릭터 프롬프트 보존
        텍스트 아티팩트만 제거
        """
        p = (positive or "").strip()
        # v59: implicit replacement는 적용하지 않음 (캐릭터 관련 키워드 보존)
        # 텍스트 아티팩트만 제거
        text_bans = [w.strip() for w in self.TEXT_ARTIFACT_BAN.split(",") if w.strip()]
        for ban in text_bans:
            pattern = r"\b" + re.escape(ban) + r"\b"
            p = re.sub(pattern, "", p, flags=re.IGNORECASE)
        p = re.sub(r",\s*,+", ", ", p)
        p = re.sub(r"\s{2,}", " ", p)
        p = p.strip(" ,")

        if len(p) < 5:
            fallbacks = self._get_safe_fallbacks()
            p = random.choice(fallbacks)
        return p

    def build_negative(self, base_negative: str = "") -> str:
        n = (base_negative or "").strip()
        # v59.7.0: SAFETY_BAN_CSV (인물 키워드 제거됨)
        forced = self.SAFETY_BAN_CSV + ", " + self.TEXT_ARTIFACT_BAN
        return f"{n}, {forced}" if n else forced

    def build_negative_v59(self, base_negative: str = "") -> str:
        """
        v59.1.6: Visual Storytelling 전용 negative 빌더

        SAFETY_BAN_CSV를 추가하지 않음 - 팩의 force_negative만 사용
        v59 팩에서는 사람/캐릭터가 등장해야 하므로 인간 금지 키워드 제외
        """
        n = (base_negative or "").strip()
        # v59: TEXT_ARTIFACT_BAN만 추가 (텍스트/워터마크 금지)
        forced = self.TEXT_ARTIFACT_BAN
        return f"{n}, {forced}" if n else forced

    def finalize(
        self,
        raw_prompt: str,
        extra_positive: str = "",
        extra_negative: str = "",
        channel_type: str = None,  # v50: 채널별 강제 스타일 적용
    ) -> Tuple[str, str]:
        pos, neg = self.split_prompt(raw_prompt)
        pos = self.sanitize_positive(pos)

        if extra_positive:
            pos = f"{pos}, {extra_positive}".strip(" ,")

        # v58: 팩에서 forced_style 우선 로드, 없으면 하드코딩 폴백
        forced = self._get_forced_style(channel_type) if channel_type else {}
        if forced:
            if forced.get('force_positive'):
                pos = f"{pos}, {forced['force_positive']}".strip(" ,")
            if forced.get('force_negative'):
                extra_negative = f"{extra_negative}, {forced['force_negative']}".strip(" ,")

        merged_neg = ", ".join([x for x in [neg, extra_negative] if (x or "").strip()])
        merged_neg = self.build_negative(merged_neg)

        return pos, merged_neg

    # =========================================================
    # v50: 캐릭터 형체 프롬프트 생성 (세월정거장 전용)
    # =========================================================
    def build_character_prompt(
        self,
        channel_type: str,
        role: str,
        emotion: str = "calm",
        action: str = None,
        background: str = None,
    ) -> Tuple[str, str]:
        """
        캐릭터 형체 + 배경을 조합한 프롬프트 생성

        Args:
            channel_type: "horror", "senior_touching", "senior_makjang"
            role: "narrator", "grandma", "grandpa", "man", "woman", "ghost", etc.
            emotion: "happy", "sad", "angry", "scared", etc.
            action: "standing", "sitting", "walking", "crying", etc.
            background: 배경 프롬프트 (없으면 자동 선택)

        Returns:
            (positive_prompt, negative_prompt)
        """
        # v58: 팩에서 캐릭터 시스템 활성화 여부 가져오기
        if not self._is_character_system_enabled():
            fallbacks = self._get_safe_fallbacks()
            bg = background or random.choice(fallbacks)
            return self.finalize(bg, channel_type=channel_type)

        # v58: 팩에서 캐릭터 정의 가져오기
        channel_chars = self._get_characters(channel_type)
        char_data = channel_chars.get(role, channel_chars.get("_default", {}))

        if not char_data:
            # 폴백: 배경만
            fallbacks = self._get_safe_fallbacks()
            bg = background or random.choice(fallbacks)
            return self.finalize(bg, channel_type=channel_type)

        # 캐릭터 베이스 + 스타일
        char_base = char_data.get("base", "abstract silhouette figure")
        char_style = char_data.get("style", "flat vector art, minimalist")

        # 감정 표정 힌트
        expression = self.EMOTION_EXPRESSION_HINTS.get(emotion, "neutral expression")

        # 동작 힌트
        pose = self.ACTION_POSE_HINTS.get(action, "natural pose") if action else "natural pose"

        # 배경
        if not background:
            # v58: 팩에서 thumbnail_backgrounds 우선, 없으면 하드코딩 폴백
            bg_pool = self._get_thumbnail_backgrounds()
            if not bg_pool:
                bg_key = channel_type if channel_type in self.THUMBNAIL_POOLS else "daily_life_toon"
                bg_pool = self.THUMBNAIL_POOLS.get(bg_key, self._get_safe_fallbacks())
            background = random.choice(bg_pool) if bg_pool else random.choice(self._get_safe_fallbacks())

        # 배경만 금지어 필터링 (캐릭터/표정/동작은 그대로)
        clean_background = self._remove_banned_tokens(background)

        # 프롬프트 조합: 캐릭터 + 표정 + 동작 + 배경 + 스타일
        positive = f"{char_base}, {expression}, {pose}, {clean_background}, {char_style}"

        # v58: 팩에서 forced_style 가져오기
        forced = self._get_forced_style(channel_type)
        if forced:
            if forced.get('force_positive'):
                positive = f"{positive}, {forced['force_positive']}"
            negative = forced.get('force_negative', "")
        else:
            negative = ""

        # negative는 그대로 빌드 (실사 인물 금지)
        negative = self.build_negative(negative)

        return positive, negative

    def get_character_for_role(self, channel_type: str, role: str) -> Dict:
        """특정 역할의 캐릭터 설정 가져오기 (v58: 팩 우선)"""
        channel_chars = self._get_characters(channel_type)
        return channel_chars.get(role, channel_chars.get("_default", {}))

    def is_character_system_enabled(self) -> bool:
        """캐릭터 시스템 활성화 여부 확인 (v58: 팩 우선)"""
        return self._is_character_system_enabled()

    # =========================================================
    # ⭐ 썸네일 전용 API (여기만 쓰면 됨)
    # v58: 팩에서 thumbnail_backgrounds 우선 로드
    # =========================================================
    def get_thumbnail_background(self, category: str, mode: str) -> str:
        # v58: 팩에서 thumbnail_backgrounds 우선
        pack_bgs = self._get_thumbnail_backgrounds()
        if pack_bgs:
            return random.choice(pack_bgs)

        # 하드코딩 폴백
        key = f"{category}_{mode}" if mode else category
        pool = self.THUMBNAIL_POOLS.get(key, self._get_safe_fallbacks())
        return random.choice(pool)


    # =========================================================
    # v59: 완전 통합 파이프라인
    # =========================================================

    def init_v59_pipeline(
        self,
        pack_id: str,
        genre: str = "daily_life_toon",
        sd_api: Any = None,
        gemini_client: Any = None,
    ) -> Dict[str, Any]:
        """
        v59: Visual Storytelling 파이프라인 전체 초기화

        Args:
            pack_id: 팩 ID
            genre: 장르 ("horror", "touching", "makjang", "senior")
            sd_api: SD WebUI API 인스턴스 (옵션)
            gemini_client: Gemini API 클라이언트 (옵션)

        Returns:
            초기화된 컴포넌트들 딕셔너리
        """
        components = {}

        try:
            # 1. SD Model Recommender
            from modules_pro.sd_model_recommender import SDModelRecommender
            components['sd_recommender'] = SDModelRecommender()
            components['sd_genre'] = genre  # 장르 저장 (get_recommendations에서 사용)
            logger.info(f"[v59] SDModelRecommender 초기화: {genre}")

            # 2. Character Library Manager
            from modules_pro.character_library_manager import CharacterLibraryManager
            char_library_config = None
            char_library_base_path = None
            try:
                from config.pack_config import ACTIVE_PACK as _ACTIVE_PACK
                char_library_config = getattr(getattr(_ACTIVE_PACK, "visual_storytelling", None), "character_library", None)
                if char_library_config:
                    if isinstance(char_library_config, dict):
                        char_library_base_path = str(char_library_config.get("library_path", "") or "").strip() or None
                    else:
                        char_library_base_path = str(getattr(char_library_config, "library_path", "") or "").strip() or None
            except Exception:
                char_library_config = None
            components['char_library'] = CharacterLibraryManager(
                pack_id=pack_id,
                library_base_path=char_library_base_path,
                config=char_library_config
            )
            logger.info(f"[v59] CharacterLibraryManager 초기화: {pack_id}")

            # 3. Background Library
            from modules_pro.background_library import BackgroundLibrary, build_background_library_config
            background_library_config = None
            try:
                from config.pack_config import ACTIVE_PACK as _ACTIVE_PACK
                raw_bg_config = getattr(_ACTIVE_PACK, "background_library", {}) or {}
                if isinstance(raw_bg_config, dict) and raw_bg_config:
                    background_library_config = build_background_library_config(
                        genre=genre,
                        config_data=raw_bg_config,
                        library_path=str(Path("assets/backgrounds") / pack_id),
                    )
            except Exception as bg_config_error:
                logger.warning(f"[v59] background_library 설정 로드 실패, 기본값 사용: {bg_config_error}")
            components['bg_library'] = BackgroundLibrary(
                pack_id=pack_id,
                genre=genre,
                config=background_library_config,
            )
            logger.info(f"[v59] BackgroundLibrary 초기화: {pack_id}")

            # 4. Quality Control - v59.1.1: Gemini 클라이언트 전달
            # v59.5.20: 팩별 아트 스타일을 QualityControl에 전달
            from modules_pro.quality_control import QualityControl, QualityControlConfig
            _art_style = ""
            try:
                from config.pack_config import ACTIVE_PACK as _AP

                def _get_val(obj, key, default=None):
                    if isinstance(obj, dict):
                        return obj.get(key, default)
                    return getattr(obj, key, default)

                # 우선순위 1: scene_analyzer.art_style_prefix
                _sa = getattr(_AP, 'scene_analyzer', None)
                if _sa:
                    _prefix = _get_val(_sa, 'art_style_prefix', '')
                    if _prefix:
                        _art_style = _prefix.rstrip(',').strip()

                # 우선순위 2: visual.forced_style.force_positive (첫 3개 토큰)
                if not _art_style:
                    _v = getattr(_AP, 'visual', None)
                    if _v:
                        _fs = _get_val(_v, 'forced_style', None)
                        if _fs:
                            _fp = _get_val(_fs, 'force_positive', '')
                            if _fp:
                                _tokens = [t.strip() for t in _fp.split(',')][:3]
                                _art_style = ', '.join(_tokens)

                # 우선순위 3: style.image_style
                if not _art_style:
                    _s = getattr(_AP, 'style', None)
                    if _s:
                        _is = _get_val(_s, 'image_style', '')
                        if _is:
                            _art_style = _is

                if _art_style:
                    logger.info(f"[v59] QualityControl 기대 아트스타일: {_art_style[:60]}...")
            except Exception as e:
                logger.debug(f"[v59] 팩 아트 스타일 추출 실패: {e}")

            qc_config = QualityControlConfig(
                check_uncanny_valley=False,  # v62.12: Gemini Vision QC 비활성화 (비용 절감)
                max_retries=3,
                expected_art_style=_art_style,
                allow_multi_person=True,  # v59.6.0: 다중 인물 허용 (클론만 거부)
            )
            components['quality_control'] = QualityControl(
                config=qc_config,
                gemini_client=None  # v62.12: Gemini 클라이언트 차단 — 비전 API 호출 방지
            )
            components['gemini_client'] = gemini_client  # v59.1.1: 별도 저장 (SceneAnalyzer용)
            logger.info(f"[v59] QualityControl 초기화 (Gemini Vision: 비활성화)")

            # 5. Scene Analyzer (Gemini 기반)
            from modules_pro.scene_analyzer import SceneAnalyzer
            vs_config = self._get_visual_storytelling_config()
            # v59.1.6: dict/object 양쪽 안전 접근
            if isinstance(vs_config, dict):
                char_defs = vs_config.get('characters', {})
                sd_config = vs_config.get('sd_model', None)
            elif vs_config:
                char_defs = getattr(vs_config, 'characters', {})
                sd_config = getattr(vs_config, 'sd_model', None)
            else:
                char_defs = {}
                sd_config = None
            # v59.5.6: 팩에서 art_style_config 로드
            _art_style_cfg2 = None
            try:
                _pc2 = self._get_pack_config()
                if _pc2 and _pc2.ACTIVE_PACK and _pc2.ACTIVE_PACK.is_loaded:
                    _art_style_cfg2 = _pc2.ACTIVE_PACK.scene_analyzer or None
            except Exception as e:
                logger.debug(f"[VisualDirector] SceneAnalyzer art_style_config 로딩 실패 (무시): {e}")

            components['scene_analyzer'] = SceneAnalyzer(
                gemini_client=gemini_client,
                character_definitions=char_defs,
                art_style_config=_art_style_cfg2
            )
            logger.info("[v59] SceneAnalyzer 초기화")

            # 6. Prompt Composer (v59.1.5: forced_style 적용)
            from modules_pro.prompt_composer import PromptComposer
            pc = self._get_pack_config()
            channel_type = pc.ACTIVE_PACK.channel_type if pc and pc.ACTIVE_PACK.is_loaded else "daily_life_toon"
            forced_style = self._get_forced_style(channel_type)
            base_pos = forced_style.get('force_positive', '')
            base_neg = forced_style.get('force_negative', '')
            components['prompt_composer'] = PromptComposer(
                character_definitions=char_defs,
                sd_model_config=sd_config,
                base_positive=base_pos,
                base_negative=base_neg
            )
            if components.get('char_library'):
                components['char_library'].prompt_composer = components['prompt_composer']
                try:
                    cl_config = None
                    if isinstance(vs_config, dict):
                        cl_config = vs_config.get('character_library', None)
                    elif vs_config:
                        cl_config = getattr(vs_config, 'character_library', None)
                    if cl_config:
                        components['char_library'].config = cl_config
                except Exception as e:
                    logger.debug(f"[v59] CharacterLibrary config 연결 실패: {e}")
            logger.info(f"[v59] PromptComposer 초기화 (forced_style: {len(base_pos)} pos, {len(base_neg)} neg chars)")

            # SD API 저장
            components['sd_api'] = sd_api

            # 7. v59.1.3: VisualStorytellingDirector 통합 관리자
            try:
                from modules_pro.visual_storytelling_director import VisualStorytellingDirector

                # vs_config를 적절한 형태로 전달
                config_for_vsd = None
                if vs_config:
                    if hasattr(vs_config, '__dict__'):
                        # 객체인 경우 dict로 변환
                        config_for_vsd = {
                            'enabled': getattr(vs_config, 'enabled', False),
                            'characters': getattr(vs_config, 'characters', {}),
                            'sd_model': getattr(vs_config, 'sd_model', None),
                            'character_library': getattr(vs_config, 'character_library', None),
                            'image_generation': getattr(vs_config, 'image_generation', {}),
                            'max_consecutive_reuse': getattr(vs_config, 'max_consecutive_reuse', 2),
                        }
                    else:
                        config_for_vsd = vs_config  # 이미 dict

                components['storytelling_director'] = VisualStorytellingDirector(
                    config=config_for_vsd,
                    gemini_client=gemini_client,
                    sd_client=sd_api,
                    output_dir=_project_output_path("data", "temp_images", pack_id),
                    char_library_manager=components.get('char_library'),  # v59.1.3: CLM 연동
                    bg_library=components.get('bg_library'),
                )
                logger.info("[v59] VisualStorytellingDirector 초기화 (CLM 연동)")
            except Exception as e:
                logger.warning(f"[v59] VisualStorytellingDirector 초기화 실패 (폴백 사용): {e}")
                components['storytelling_director'] = None

            # 캐시
            self._v59_components = components

            logger.info("[v59] 파이프라인 초기화 완료")
            return components

        except Exception as e:
            logger.error(f"[v59] 파이프라인 초기화 실패: {e}")
            return {}

    def generate_scene_image_v59(
        self,
        dialogue: str,
        speaker: str = "나레이터",
        dialogue_index: int = 0,
        context_dialogues: Optional[List[str]] = None,
        sd_api: Any = None,
        output_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        v59: 단일 씬 이미지 생성 (전체 파이프라인)

        Args:
            dialogue: 대사 텍스트
            speaker: 화자
            dialogue_index: 대사 인덱스
            context_dialogues: 이전 대사들
            sd_api: SD WebUI API
            output_path: 출력 경로 (옵션)

        Returns:
            {
                'image_path': str,
                'prompt': str,
                'scene_context': dict,
                'quality_report': QualityReport,
                'action': str  # 'new', 'reuse', 'expression_swap'
            }
        """
        result = {
            'image_path': None,
            'prompt': '',
            'scene_context': {},
            'quality_report': None,
            'action': 'new'
        }

        if not self._is_visual_storytelling_enabled():
            logger.debug("[v59] Visual Storytelling 비활성화됨")
            return result

        # 컴포넌트 가져오기
        components = getattr(self, '_v59_components', {})
        scene_analyzer = components.get('scene_analyzer')
        prompt_composer = components.get('prompt_composer')
        quality_control = components.get('quality_control')
        char_library = components.get('char_library')
        bg_library = components.get('bg_library')

        sd_api = sd_api or components.get('sd_api')

        if not scene_analyzer or not prompt_composer:
            # 지연 로드 시도
            scene_analyzer, prompt_composer = self._load_v59_modules()

        if not scene_analyzer or not prompt_composer:
            logger.warning("[v59] 필수 모듈 없음")
            return result

        try:
            # 1. 씬 분석
            scene_result = scene_analyzer.analyze_dialogue(
                dialogue=dialogue,
                speaker=speaker,
                index=dialogue_index,
                context_dialogues=context_dialogues
            )

            # 씬 컨텍스트 저장
            if hasattr(scene_result, 'to_dict'):
                result['scene_context'] = scene_result.to_dict()
            else:
                result['scene_context'] = {
                    'characters': getattr(scene_result, 'characters', []),
                    'location': getattr(scene_result, 'location', ''),
                    'time_of_day': getattr(scene_result, 'time_of_day', ''),
                    'weather': getattr(scene_result, 'weather', ''),
                    'atmosphere': getattr(scene_result, 'atmosphere', ''),
                }

            # 2. 이미지 액션 결정
            action = getattr(scene_result, 'image_action', 'new')
            result['action'] = action

            if action == 'reuse':
                logger.debug("[v59] 이전 이미지 재사용")
                return result

            # 3. 프롬프트 생성 (v59.1.6: 인간 금지어 제외)
            composed = prompt_composer.compose_prompt(scene_result)
            positive = self.sanitize_positive_v59(composed.positive)
            negative = self.build_negative_v59(composed.negative)
            result['prompt'] = positive

            # 4. SD 이미지 생성
            if sd_api:
                image_path = self._generate_image_with_sd(
                    sd_api=sd_api,
                    positive=positive,
                    negative=negative,
                    output_path=output_path,
                    seed=getattr(composed, 'seed', -1)
                )
                result['image_path'] = image_path

                # 5. 품질 검증
                if quality_control and image_path:
                    report = quality_control.validate_scene_image(image_path)
                    result['quality_report'] = report

                    # 품질 실패 시 재생성 또는 폴백
                    if not report.passed:
                        logger.warning(f"[v59] 품질 검증 실패: {report.overall_status}")

                        # 캐릭터/배경 라이브러리 폴백
                        if char_library and bg_library:
                            fallback_path = self._get_fallback_image(
                                scene_result, char_library, bg_library
                            )
                            if fallback_path:
                                result['image_path'] = fallback_path
                                result['action'] = 'fallback'

            logger.info(f"[v59] 씬 이미지 생성 완료: {result['image_path']}")
            return result

        except Exception as e:
            logger.error(f"[v59] 씬 이미지 생성 실패: {e}")
            return result

    def _generate_image_with_sd(
        self,
        sd_api: Any,
        positive: str,
        negative: str,
        output_path: Optional[str] = None,
        seed: int = -1,
        width: int = 1024,
        height: int = 576,
    ) -> Optional[str]:
        """SD WebUI API로 이미지 생성"""
        try:
            import requests
            import base64
            from PIL import Image
            from io import BytesIO
            import uuid

            params = {
                "prompt": positive,
                "negative_prompt": negative,
                "seed": seed,
                "width": width,
                "height": height,
                "steps": 15,
                "cfg_scale": 7.0,
                "sampler_name": "DPM++ 2M Karras"
            }

            # API URL
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

            if not output_path:
                output_path = _project_output_path("data", "scenes", f"{uuid.uuid4().hex[:8]}.png")

            from pathlib import Path
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            image.save(output_path)

            return output_path

        except Exception as e:
            logger.error(f"SD 이미지 생성 실패: {e}")
            return None

    def _get_fallback_image(
        self,
        scene_result: Any,
        char_library: Any,
        bg_library: Any,
    ) -> Optional[str]:
        """캐릭터/배경 라이브러리에서 폴백 이미지 조회"""
        try:
            # 캐릭터 이미지 우선 조회
            characters = getattr(scene_result, 'characters', [])
            if characters and char_library:
                for char in characters:
                    emotion = getattr(scene_result, 'atmosphere', 'neutral')
                    char_image = char_library.get_character_image(char, emotion)
                    if char_image:
                        return char_image

            # 배경 이미지 폴백
            if bg_library:
                location = getattr(scene_result, 'location', '')
                time = getattr(scene_result, 'time_of_day', 'any')
                weather = getattr(scene_result, 'weather', 'any')

                bg_image = bg_library.get_background_image(
                    location=location,
                    time=time,
                    weather=weather
                )
                if bg_image:
                    return bg_image

            return None

        except Exception as e:
            logger.error(f"폴백 이미지 조회 실패: {e}")
            return None

    def generate_all_images_v59(
        self,
        script: List[Dict],
        sd_api: Any = None,
        output_dir: str = "",
        progress_callback: Optional[callable] = None,
    ) -> List[Dict[str, Any]]:
        """
        v59: 전체 스크립트 이미지 생성

        Args:
            script: [{'speaker': str, 'text': str}, ...]
            sd_api: SD WebUI API
            output_dir: 출력 디렉토리
            progress_callback: 진행 콜백 (current, total, message)

        Returns:
            [{'index': int, 'image_path': str, ...}, ...]
        """
        if not output_dir:
            output_dir = _project_output_path("data", "scenes")

        results = []
        total = len(script)

        # 컨텍스트 대사 수집
        context_dialogues = []

        for i, item in enumerate(script):
            speaker = item.get('speaker', '나레이터')
            text = item.get('text', '')

            if progress_callback:
                progress_callback(i + 1, total, f"씬 {i+1}/{total} 생성 중...")

            # 출력 경로
            output_path = f"{output_dir}/scene_{i:04d}.png"

            # 씬 이미지 생성
            result = self.generate_scene_image_v59(
                dialogue=text,
                speaker=speaker,
                dialogue_index=i,
                context_dialogues=context_dialogues[-5:],  # 최근 5개 컨텍스트
                sd_api=sd_api,
                output_path=output_path
            )

            result['index'] = i
            result['speaker'] = speaker
            result['text'] = text
            results.append(result)

            # 컨텍스트 추가
            context_dialogues.append(f"{speaker}: {text}")

        logger.info(f"[v59] 전체 이미지 생성 완료: {len(results)}개")
        return results

    def prepare_pack_v59(
        self,
        pack_id: str,
        genre: str,
        characters: List[Dict],
        sd_api: Any = None,
        progress_callback: Optional[callable] = None,
    ) -> Dict[str, Any]:
        """
        v59: 팩 생성 시 사전 준비 (캐릭터/배경 라이브러리 생성)

        Args:
            pack_id: 팩 ID
            genre: 장르
            characters: 캐릭터 정의 목록
            sd_api: SD WebUI API
            progress_callback: 진행 콜백

        Returns:
            {
                'character_library': {...},
                'background_library': {...},
                'sd_recommendations': {...}
            }
        """
        result = {}

        try:
            # 1. SD 모델 추천
            from modules_pro.sd_model_recommender import SDModelRecommender
            recommender = SDModelRecommender()
            result['sd_recommendations'] = recommender.get_recommendations(genre)
            logger.info(f"[v59] SD 모델 추천 완료: {genre}")

            # 2. 캐릭터 라이브러리 생성
            from modules_pro.character_library_manager import CharacterLibraryManager
            char_library_config = None
            try:
                from config.pack_config import ACTIVE_PACK as _ACTIVE_PACK
                char_library_config = getattr(getattr(_ACTIVE_PACK, "visual_storytelling", None), "character_library", None)
            except Exception:
                char_library_config = None
            char_lib = CharacterLibraryManager(pack_id=pack_id, config=char_library_config)

            if sd_api and characters:
                for char_def in characters:
                    char_lib.add_character_from_dict(char_def)

                # 캐릭터 이미지 생성
                char_results = char_lib.generate_all_characters(
                    sd_api=sd_api,
                    progress_callback=progress_callback
                )
                result['character_library'] = char_results
                logger.info(f"[v59] 캐릭터 라이브러리 생성 완료: {len(characters)}개 캐릭터")

            # 3. 배경 라이브러리 생성
            from modules_pro.background_library import BackgroundLibrary, build_background_library_config
            bg_library_config = None
            try:
                from config.pack_config import ACTIVE_PACK as _ACTIVE_PACK
                raw_bg_config = getattr(_ACTIVE_PACK, "background_library", {}) or {}
                if isinstance(raw_bg_config, dict) and raw_bg_config:
                    bg_library_config = build_background_library_config(
                        genre=genre,
                        config_data=raw_bg_config,
                        library_path=str(Path("assets/backgrounds") / pack_id),
                    )
            except Exception as bg_config_error:
                logger.warning(f"[v59] background_library 설정 로드 실패, 기본값 사용: {bg_config_error}")
            bg_lib = BackgroundLibrary(pack_id=pack_id, genre=genre, config=bg_library_config)

            if sd_api:
                bg_results = bg_lib.generate_background_library(
                    sd_api=sd_api,
                    progress_callback=progress_callback
                )
                result['background_library'] = bg_results
                logger.info(f"[v59] 배경 라이브러리 생성 완료")

            return result

        except Exception as e:
            logger.error(f"[v59] 팩 준비 실패: {e}")
            return result

    def get_v59_status(self) -> Dict[str, Any]:
        """v59 시스템 상태 조회"""
        return {
            'visual_storytelling_enabled': self._is_visual_storytelling_enabled(),
            'character_system_enabled': self._is_character_system_enabled(),
            'v59_modules_loaded': _V59_MODULES_LOADED,
            'components_initialized': hasattr(self, '_v59_components') and bool(self._v59_components),
        }


# 싱글톤
visual_director = VisualDirector()
