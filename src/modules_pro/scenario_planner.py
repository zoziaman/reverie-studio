# src/modules_pro/scenario_planner.py
# ============================================================
# Reverie Automation - Scenario Planner (v32.1 - Enhanced)
# v56.1: 유틸리티/분석 클래스 외부 모듈로 분리
# ============================================================

import os
import sys
import json
import time
import re
import random
import string
import logging
from datetime import datetime
from typing import Dict, List, Any, Tuple, Callable, Optional
from functools import wraps
import warnings

# google.generativeai deprecated 경고 억제 (기능은 정상 작동)
with warnings.catch_warnings():
    warnings.filterwarnings("ignore", category=FutureWarning)
    try:
        import google.generativeai as genai
        _GENAI_OLD_AVAILABLE = True
    except ImportError:
        _GENAI_OLD_AVAILABLE = False
        genai = None


# v59.5.5: GenerationConfig 호환 래퍼 (script_writers.py와 동일)
class _GenerationConfigCompat:
    """GeminiWrapper.generate_content()에서 자동 변환됨"""
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)
        self._kwargs = kwargs
    def to_dict(self):
        return dict(self._kwargs)


def _make_generation_config(**kwargs):
    """v59.5.17: 무한 재귀 버그 수정 — genai.GenerationConfig 직접 호출"""
    if _GENAI_OLD_AVAILABLE and genai is not None:
        try:
            return genai.GenerationConfig(**kwargs)
        except Exception as e:
            logging.getLogger(__name__).debug(f"genai.GenerationConfig 생성 실패, 호환 객체 사용: {e}")
    return _GenerationConfigCompat(**kwargs)

from config.settings import config

# v57.7.0: 팩 기반 프롬프트 시스템
# v58: 시나리오 풀, safe_templates 등도 팩에서 로드
try:
    from config.pack_config import (
        ACTIVE_PACK, load_pack, load_pack_by_id, load_default_pack,
        get_prompt, get_content_settings, get_topic_templates,
        get_scenario_pools, get_safe_templates, get_motiontoon_config  # v58 추가
    )
    PACK_CONFIG_AVAILABLE = True
except ImportError:
    PACK_CONFIG_AVAILABLE = False

# ✅ v31: Visual Guard 연결
from modules_pro.visual_director import visual_director

# ============================================================
# v56.1: 분리된 모듈 import
# ============================================================
from modules_pro.script_utils import (
    APIRetryHelper,
    ProgressCallback,
    DiversityMemory,
    progress_callback,
    safe_print,
    _safe_strip,
    _first_line,
)
from modules_pro.script_analyzer import ScriptAnalyzer, ScriptEditor
from modules_pro.script_writers import ScriptWriter, EnhancedScriptWriter, PromptMode
from modules_pro.plan_output import build_final_plan, resolve_part_instructions
from core.script_quality_gate import assert_script_quality, ScriptQualityError
from utils.motiontoon import build_motiontoon_plan
from utils.shorts_manager import normalize_shorts_plan
from utils.story_research import build_market_research_context, score_story_freshness

# ============================================================
# v57.0: PDCA Evaluator import
# ============================================================
try:
    from core.evaluators import StoryCritic, EvaluationResult, get_story_critic
    PDCA_AVAILABLE = True
except ImportError:
    PDCA_AVAILABLE = False
    StoryCritic = None

# ✅ v32.1: 로거 설정
try:
    from utils.logger import get_logger
    logger = get_logger("scenario_planner")
except ImportError:
    # 로거가 없으면 기본 로깅 사용
    logger = logging.getLogger("scenario_planner")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter('[%(levelname)s] %(name)s: %(message)s'))
        logger.addHandler(handler)

# ============================================================
# v56.1: safe_print는 script_utils.py에서 import
# ============================================================

# ============================================================
# v32.1: 지수 백오프 API 재시도 데코레이터 (로컬 유지 - 데코레이터라 분리 복잡)
# ============================================================
def retry_with_backoff(
    max_retries: int = 5,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    jitter: bool = True,
    exceptions: tuple = (Exception,)
):
    """
    지수 백오프를 적용한 재시도 데코레이터

    Args:
        max_retries: 최대 재시도 횟수
        base_delay: 기본 대기 시간 (초)
        max_delay: 최대 대기 시간 (초)
        exponential_base: 지수 증가 배수
        jitter: 무작위 지터 추가 여부
        exceptions: 재시도할 예외 타입들
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None

            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e

                    if attempt == max_retries - 1:
                        logger.error(f"[{func.__name__}] 최대 재시도 횟수({max_retries}) 도달. 마지막 에러: {e}")
                        raise

                    # 지수 백오프 계산
                    delay = min(base_delay * (exponential_base ** attempt), max_delay)

                    # 지터 추가 (0.5 ~ 1.5 배)
                    if jitter:
                        delay = delay * (0.5 + random.random())

                    logger.warning(f"[{func.__name__}] 재시도 {attempt + 1}/{max_retries}, "
                                   f"{delay:.1f}초 후 재시도. 에러: {type(e).__name__}: {str(e)[:100]}")
                    time.sleep(delay)

            raise last_exception
        return wrapper
    return decorator


# ============================================================
# v56.1: APIRetryHelper, ProgressCallback, progress_callback
#        → script_utils.py에서 import (상단 참조)
# ============================================================


# ============================================================
# v56.1: ScriptAnalyzer, ScriptEditor
#        → script_analyzer.py에서 import (상단 참조)
# ============================================================


# ============================================================
# 공통 유틸
# v56.1: _safe_strip, _first_line → script_utils.py에서 import (상단 참조)
# ============================================================
def _extract_json_block(text: str, want: str = "object") -> str:
    if not text:
        return ""
    t = text.replace("```json", "").replace("```", "").strip()

    if want == "object":
        s = t.find("{")
        e = t.rfind("}") + 1
        if 0 <= s < e:
            return t[s:e]
        return ""
    else:
        s = t.find("[")
        e = t.rfind("]") + 1
        if 0 <= s < e:
            return t[s:e]
        return ""


def _safe_json_loads(text: str, default):
    """v62.21 M-3: 잘린 JSON 복구 시도 추가"""
    try:
        return json.loads(text)
    except Exception:
        pass
    # v62.21 M-3: Gemini 8K 출력 토큰 한도로 잘린 JSON 복구 시도
    # 닫히지 않은 중괄호/대괄호를 역순으로 보완
    if text and isinstance(text, str):
        trimmed = text.rstrip()
        for _ in range(10):  # 최대 10번 보완
            opens = trimmed.count("{") - trimmed.count("}")
            open_brackets = trimmed.count("[") - trimmed.count("]")
            if opens <= 0 and open_brackets <= 0:
                break
            if opens > 0:
                trimmed += "}"
            elif open_brackets > 0:
                trimmed += "]"
        try:
            return json.loads(trimmed)
        except Exception:
            pass
    return default


def _korean_keywords(topic: str, n: int = 8) -> List[str]:
    words = re.findall(r"[가-힣]{2,}", topic or "")
    out: List[str] = []
    for w in words:
        if w not in out:
            out.append(w)
        if len(out) >= n:
            break
    return out


# v60.1.0: _sanitize_for_path를 pipeline_utils 정식 버전으로 통합
from utils.runtime_utils import sanitize_for_path as _sanitize_for_path


def _now_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _sanitize_sample_text(text: str) -> str:
    """
    package_content()에서 대본 샘플을 모델에 넣기 전 금칙어 제거
    """
    t = _safe_strip(text)
    
    bad_words = [
        "nude", "naked", "bikini", "lingerie", "nsfw", "sex", "erotic",
        "blood", "gore", "corpse", "wound", "kill", "murder",
        "rape", "assault", "violence", "weapon", "knife", "gun"
    ]
    
    for bad in bad_words:
        t = re.sub(rf'\b{bad}\b', '***', t, flags=re.IGNORECASE)
    
    return t


class FallbackScriptError(RuntimeError):
    """LLM 생성 실패로 비상 템플릿 대본이 감지된 경우."""

    def __init__(self, label: str, turn_count: int):
        self.label = label
        self.turn_count = turn_count
        super().__init__(f"{label} generated fallback script ({turn_count} turns)")


def _generate_nonce() -> str:
    """
    6자리 랜덤 코드 + 랜덤 키워드 2개
    """
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    
    keywords_pool = [
        "구름", "철길", "등대", "골목길", "라디오", "손수건", "우산", "시계",
        "편지", "사진", "거울", "창문", "계단", "문고리", "전화기", "열쇠",
        "나무", "강", "바다", "산", "달", "별", "비", "눈", "안개"
    ]
    kw1, kw2 = random.sample(keywords_pool, 2)
    
    return f"{code} | {kw1}, {kw2}"

def _strip_emoji(s: str) -> str:
    if not s:
        return ""
    # 이모지/기호가 들어가는 높은 유니코드 영역 제거
    s = re.sub(r"[\U00010000-\U0010FFFF]", "", s)
    # 자잘한 장식 기호 추가 제거
    s = re.sub(r"[★☆✓✔✅❌⭕️◯●■□▲△▼▽◆◇]", "", s)
    # 공백 정리
    s = re.sub(r"\s{2,}", " ", s).strip()
    # 한글, 영문, 숫자, 공백만 남김 (문장부호도 제거!)
    s = re.sub(r"[^0-9a-zA-Z가-힣\s]", "", s)
    return s


_WEAK_HOOK_EXACT = {
    "",
    "이야기가 시작됩니다",
    "모든 것은 시작됐다",
    "모든 것이 시작됐다",
    "그날 밤이었다",
    "그날 밤이었다.",
}
_WEAK_HOOK_PREFIXES = (
    "이 이야기는",
    "이제부터",
    "지금부터",
    "그날 밤",
    "모든 것은",
    "모든 게",
    "이야기가",
)
_WEAK_HOOK_SUBSTRINGS = (
    "이야기가 시작",
    "몇 년 전",
    "며칠 전으로",
    "거슬러 올라",
    "지금부터 시작",
)
_HOOK_TRIGGER_TOKENS = (
    "왜",
    "누구",
    "뭐야",
    "뭔데",
    "거짓말",
    "비밀",
    "정체",
    "살려",
    "안 돼",
    "오지 마",
    "문 열",
    "들어와",
    "기억",
    "죽",
    "피",
    "숨",
    "들켰",
    "봤어",
    "없어",
    "있어",
    "여기",
)
_HOOK_EMOTION_WEIGHTS = {
    "desperate": 12,
    "scared": 11,
    "terrified": 11,
    "angry": 9,
    "crying": 8,
    "shocked": 8,
    "surprised": 6,
    "sad": 4,
    "worried": 4,
    "tense": 4,
    "whisper": 4,
}


def _normalize_hook_candidate(text: str) -> str:
    text = _safe_strip(text or "")
    if not text:
        return ""
    text = text.replace("\n", " ")
    text = re.sub(r"\s+", " ", text).strip()
    text = text.strip("\"'“”‘’")
    text = re.sub(r"^[\-–—:]+", "", text).strip()
    return text


def _topic_overlap_ratio_for_hook(topic: str, text: str) -> float:
    topic_keywords = set(_korean_keywords(topic or "", n=6))
    if not topic_keywords:
        return 0.0
    normalized = _normalize_hook_candidate(text)
    matched = sum(1 for kw in topic_keywords if kw and kw in normalized)
    return matched / max(len(topic_keywords), 1)


def _is_weak_hook_candidate(text: str, topic: str = "") -> bool:
    normalized = _normalize_hook_candidate(text)
    if not normalized:
        return True
    normalized_no_punct = re.sub(r"[?!.,…\"'“”‘’]", "", normalized).strip()
    if normalized_no_punct in _WEAK_HOOK_EXACT:
        return True
    if any(normalized.startswith(prefix) for prefix in _WEAK_HOOK_PREFIXES):
        return True
    if any(token in normalized for token in _WEAK_HOOK_SUBSTRINGS):
        return True
    if len(normalized) < 6 or len(normalized) > 42:
        return True
    if normalized in {"...", ".."} or re.fullmatch(r"\.+", normalized):
        return True
    if topic:
        topic_norm = _normalize_hook_candidate(topic)
        if normalized == topic_norm:
            return True
        if len(topic_norm) >= 10 and normalized in topic_norm:
            return True
        if _topic_overlap_ratio_for_hook(topic_norm, normalized) >= 0.85:
            return True
    return False


def _score_hook_turn(turn: Dict[str, Any], index: int, total_turns: int, topic: str = "") -> int:
    role = _normalize_hook_candidate(turn.get("role", ""))
    character = _normalize_hook_candidate(turn.get("character", "")) or role
    text = _normalize_hook_candidate(turn.get("text", ""))
    emotion = _normalize_hook_candidate(turn.get("emotion", "")).lower()

    if not text:
        return -999
    if role in {"나레이션", "narrator"} or character in {"나레이션", "narrator"}:
        return -999
    if len(text) < 8 or len(text) > 90:
        return -999

    score = _HOOK_EMOTION_WEIGHTS.get(emotion, 0)

    if any(token in text for token in _HOOK_TRIGGER_TOKENS):
        score += 6
    if "?" in text or "!" in text:
        score += 4
    if any(mark in text for mark in ("왜", "누구", "어디", "뭐", "설마")):
        score += 3
    if len(text) <= 26:
        score += 3
    elif len(text) <= 40:
        score += 1

    position_ratio = index / max(total_turns - 1, 1)
    if 0.55 <= position_ratio <= 0.92:
        score += 5
    elif 0.35 <= position_ratio < 0.55:
        score += 3
    elif position_ratio > 0.92:
        score += 1

    if _is_weak_hook_candidate(text, topic=topic):
        score -= 8

    return score


# ============================================================
# v56.1: DiversityMemory → script_utils.py에서 import (상단 참조)
# ============================================================


# ============================================================
# v61: 공용 유틸리티 (클래스 간 공유)
# ============================================================
def _build_pool_context(pools) -> str:
    """v60: 팩의 시나리오 풀에서 랜덤 선택하여 컨텍스트 문자열 생성"""
    if not pools:
        return ""
    parts = []
    if pools.tone_pool:
        parts.append(f"[Tone]: {random.choice(pools.tone_pool)}")
    if pools.relationship_pool:
        parts.append(f"[Relationship]: {random.choice(pools.relationship_pool)}")
    if pools.place_pool:
        parts.append(f"[Setting]: {random.choice(pools.place_pool)}")
    if pools.twist_pool:
        parts.append(f"[Twist]: {random.choice(pools.twist_pool)}")
    if pools.arc_pool:
        parts.append(f"[Arc]: {random.choice(pools.arc_pool)}")
    if pools.trigger_pool:
        parts.append(f"[Trigger]: {random.choice(pools.trigger_pool)}")
    if pools.conflict_pool:
        parts.append(f"[Conflict]: {random.choice(pools.conflict_pool)}")
    if pools.mystery_types:
        parts.append(f"[Mystery Type]: {random.choice(pools.mystery_types)}")
    if pools.evidence_pool:
        parts.append(f"[Evidence]: {random.choice(pools.evidence_pool)}")
    return "\n".join(parts)


def _attach_motion_beats_to_visual_scenes(
    visual_scenes: List[Any],
    motiontoon_plan: Optional[Dict[str, Any]],
) -> List[Any]:
    """Keep legacy string prompts intact while enriching dict scenes with motion metadata."""
    if not visual_scenes or not motiontoon_plan or not motiontoon_plan.get("scenes"):
        return visual_scenes

    enriched: List[Any] = []
    beats = motiontoon_plan.get("scenes", [])
    for idx, scene in enumerate(visual_scenes):
        beat = beats[idx] if idx < len(beats) else None
        if not beat or not isinstance(scene, dict):
            enriched.append(scene)
            continue

        scene_copy = dict(scene)
        scene_copy["motion"] = {
            "scene_type": beat.get("scene_type", ""),
            "dominant_emotion": beat.get("dominant_emotion", ""),
            "motion_priority": beat.get("motion_priority", "low"),
            "primitives": beat.get("primitives", []),
            "shorts_candidate": beat.get("shorts_candidate", False),
        }
        enriched.append(scene_copy)
    return enriched


def _build_market_research_prompt_section(category: str, mode: str = "", topic_seed: str = "") -> str:
    """Return a compact trend/research prompt section without blocking production."""
    try:
        bundle = build_market_research_context(
            category=category,
            mode=mode,
            topic_seed=topic_seed,
            max_cards=2,
        )
        if bundle.context:
            freshness = score_story_freshness(topic_seed, context=bundle.context, cards=bundle.cards) if topic_seed else None
            freshness_label = f", freshness={freshness.score}" if freshness else ""
            safe_print(f"   🔎 [시장조사] 트렌드 카드 {len(bundle.cards)}개 주입 (score={bundle.quality_score}{freshness_label})")
            return bundle.context
    except Exception as e:
        logger.warning(f"[시장조사] 컨텍스트 생성 실패 (무시): {e}")
    return ""


def _append_market_research_to_bible(bible: str, market_context: str) -> str:
    if not market_context:
        return bible
    if "[Market Research Context]" in (bible or ""):
        return bible
    return f"{bible}\n\n{market_context}"


# ============================================================
# 총괄 PD
# ============================================================
class ChiefProducer:
    def __init__(self, model, memory: DiversityMemory):
        self.model = model
        self.memory = memory

    @staticmethod
    def _build_pool_context(pools) -> str:
        """v61: 모듈 레벨 함수로 위임 (ScenarioPlanner와 공유)"""
        return _build_pool_context(pools)

    def create_topic(self, category: str, mode: str = "") -> str:
        safe_print(f"\n🎲 [총괄 PD] '{category}:{mode}' 대박 날 아이템 회의 중...")

        nonce = _generate_nonce()
        market_context = _build_market_research_prompt_section(category, mode)

        # v57.7.0: 팩 기반 토픽 생성
        if PACK_CONFIG_AVAILABLE and ACTIVE_PACK.is_loaded:
            topic_templates = get_topic_templates()
            if topic_templates:
                # 팩의 토픽 템플릿 중 하나를 기반으로 변형
                base_topic = random.choice(topic_templates)
                pd_prompt = get_prompt("pd_system", category)

                prompt = f"""
You are the head producer (PD) of the "{ACTIVE_PACK.pack_name}" content brand.
Create ONE new topic sentence inspired by the reference below.

[Brand Style Guide]
{pd_prompt[:500]}

[Reference Topic] {base_topic}

{market_context}

[Requirements]
- Maintain a similar tone and mood to the reference
- The content must be entirely original — no paraphrasing the reference
- Use the market research only as motifs, props, and human conflict. 그대로 복사하지 말고 창작 재구성으로 변환
- No explicit sexual content, hate speech, discrimination, or graphic violence

**Unique Seed (Nonce): {nonce}**

Output: Exactly ONE sentence in Korean. No additional explanation.
"""
                gen_config = _make_generation_config(temperature=1.0, top_p=0.95, top_k=50)

                for attempt in range(5):
                    try:
                        res = self.model.generate_content(prompt, generation_config=gen_config)
                        topic = _first_line((getattr(res, "text", "") or ""))
                        if len(topic) >= 6:
                            logger.info(f"[총괄 PD] 팩 기반 주제 생성: {topic[:50]}...")
                            safe_print(f"   💡 결정된 아이템: {topic} (Pack: {ACTIVE_PACK.pack_name})")
                            return topic
                    except Exception as e:
                        delay = min(1.0 * (2 ** attempt), 30.0) * (0.5 + random.random())
                        if attempt < 4:
                            time.sleep(delay)

                # 실패 시 템플릿 그대로 반환
                return base_topic

        # v60: 팩에서 토픽 생성 프롬프트 로딩 (장르 분기 제거)
        topic_prompt_template = get_prompt("topic_generation") if PACK_CONFIG_AVAILABLE else ""
        scenario_pools = get_scenario_pools() if PACK_CONFIG_AVAILABLE and ACTIVE_PACK.is_loaded else None
        pool_context = self._build_pool_context(scenario_pools)
        # v60: 모든 팩에서 반복 회피 적용 (장르 분기 제거)
        bans = self.memory.get_bans_for_senior() if hasattr(self.memory, 'get_bans_for_senior') else ""

        if topic_prompt_template:
            # v60: 팩 프롬프트 사용 — 장르 무관
            prompt = f"""{topic_prompt_template}

{market_context}
{pool_context}
{("- Also avoid these recent topics: " + bans) if bans else ""}

**Episode Unique Seed (Nonce): {nonce}**
Use this seed to generate an unconventional, non-cliche topic.

Output: Exactly ONE sentence in Korean. No additional explanation.
"""
        else:
            # 폴백: 팩 미로딩 시 최소한의 범용 프롬프트
            prompt = f"""
You are a content creator for YouTube. Create ONE original topic sentence.
{market_context}
{pool_context}
{("- Also avoid these recent topics: " + bans) if bans else ""}

**Episode Unique Seed (Nonce): {nonce}**
Output: Exactly ONE sentence in Korean. No additional explanation.
"""

        gen_config = _make_generation_config(
            temperature=1.0,
            top_p=0.95,
            top_k=50,
        )

        # v32.1: 지수 백오프 재시도 적용
        for attempt in range(5):
            try:
                res = self.model.generate_content(prompt, generation_config=gen_config)
                topic = _first_line((getattr(res, "text", "") or ""))
                if len(topic) < 6:
                    topic = "알 수 없는 이야기"
                logger.info(f"[총괄 PD] 주제 생성 완료: {topic[:50]}...")
                safe_print(f"   💡 결정된 아이템: {topic} (Nonce: {nonce})")
                return topic
            except Exception as e:
                delay = min(1.0 * (2 ** attempt), 30.0) * (0.5 + random.random())
                logger.warning(f"[총괄 PD] 주제 생성 재시도 {attempt+1}/5, {delay:.1f}초 대기. 에러: {e}")
                if attempt < 4:
                    time.sleep(delay)
                else:
                    logger.error(f"[총괄 PD] 주제 생성 최종 실패: {e}")

        return "알 수 없는 이야기"

    def create_powerful_hook(self, topic: str, category: str, mode: str = "") -> str:
        safe_print("   🪝 [총괄 PD] 오프닝 후킹 멘트 작성 중...")

        # v60: 팩에서 훅 생성 프롬프트 로딩 (장르 분기 제거)
        hook_template = get_prompt("hook_generation") if PACK_CONFIG_AVAILABLE else ""
        if hook_template:
            prompt = f"""{hook_template}

[Topic] "{topic}"

Output: ONE hook sentence in Korean only. No explanation.
"""
        else:
            prompt = f"""
You are a drama cold-open specialist.
Write one Korean opening line that feels like a scene from a film or TV drama.

[Topic] "{topic}"

[Rules]
- Write spoken dialogue or an urgent line, not bland narration
- The line must create immediate danger, accusation, reveal, or mystery
- Keep it short and punchy (8-24 Korean characters preferred)
- Questions or exclamations are effective
- Avoid generic openings like "그날 밤", "모든 것은", "이야기가 시작됩니다"
- No profanity, hate speech, or explicit sexual expressions

Output: ONE hook sentence in Korean only. No explanation.
"""
        gen_config = _make_generation_config(
            temperature=0.7,
            top_p=0.9,
        )

        # v32.1: 지수 백오프 재시도 적용
        for attempt in range(5):
            try:
                res = self.model.generate_content(prompt, generation_config=gen_config)
                hook = _normalize_hook_candidate(_first_line((getattr(res, "text", "") or "")))
                if hook and not _is_weak_hook_candidate(hook, topic=topic):
                    logger.info(f"[총괄 PD] 후킹 멘트 생성 완료: {hook[:30]}...")
                    return hook
            except Exception as e:
                delay = min(1.0 * (2 ** attempt), 30.0) * (0.5 + random.random())
                logger.warning(f"[총괄 PD] 후킹 멘트 재시도 {attempt+1}/5, {delay:.1f}초 대기. 에러: {e}")
                if attempt < 4:
                    time.sleep(delay)
                else:
                    logger.error(f"[총괄 PD] 후킹 멘트 최종 실패: {e}")

        return ""

    def package_content(self, topic: str, full_script: List[Dict[str, Any]], category: str, mode: str = "") -> Dict[str, Any]:
        safe_print("   🎁 [총괄 PD] 유튜브 업로드용 메타데이터 작성 중...")

        sample = full_script[:: max(1, len(full_script) // 12)] if full_script else []
        
        sample_txt = " / ".join([
            f"{s.get('role','')}: {_sanitize_sample_text(s.get('text',''))}" 
            for s in sample
        ])[:2500]

        # v60: 팩에서 썸네일 스타일 가이드 로딩 (장르 분기 제거)
        thumb_style_guide = get_prompt("thumbnail_style_guide") if PACK_CONFIG_AVAILABLE else ""
        if not thumb_style_guide:
            thumb_style_guide = "- Keep it short and impactful (2-4 Korean word phrases)"

        # v62.40: 제목 문형 8종 랜덤 선택 (플랫폼 감지 리스크 완화)
        TITLE_TYPES = [
            ("질문형",      "의문문으로 호기심을 자극. 예: '그는 왜 그날 밤 사라졌을까?'"),
            ("선언형",      "단정적 문장으로 충격 전달. 예: '아무도 몰랐던 그 집의 비밀'"),
            ("숫자형",      "숫자로 구체성 강조. 예: '3일 만에 밝혀진 30년의 거짓말'"),
            ("대비형",      "대조로 긴장감 조성. 예: '평범한 아버지, 그러나 감춰진 또 다른 얼굴'"),
            ("반전형",      "예상 뒤집기. 예: '착한 이웃이었던 그가 진짜 범인이었다'"),
            ("인용형",      "극중 대사 직접 인용. 예: '\"당신만 몰랐어요\" — 그 한마디가 모든 걸 바꿨다'"),
            ("상황극형",    "현장감 있는 상황 묘사. 예: '새벽 3시, 문이 열렸다'"),
            ("체크리스트형","나열로 궁금증 유발. 예: '이상한 냄새, 잠긴 방, 그리고 실종된 아내'"),
        ]
        title_type_name, title_type_guide = random.choice(TITLE_TYPES)
        title_type_instruction = f"제목 문형: [{title_type_name}] — {title_type_guide}"
        logger.info(f"[총괄 PD] 제목 문형 선택: {title_type_name}")

        # v61: 팩에서 metadata_generation 프롬프트 로딩
        metadata_template = get_prompt("metadata_generation") if PACK_CONFIG_AVAILABLE else ""
        genre_label = ACTIVE_PACK.pack_id if (PACK_CONFIG_AVAILABLE and ACTIVE_PACK.is_loaded) else category

        if metadata_template:
            # 팩의 메타데이터 생성 프롬프트 사용 (플레이스홀더 치환)
            # v61: 팩 프롬프트는 {{...}} 이중 중괄호 사용 (f-string 안전)
            prompt = metadata_template.replace("{{topic}}", str(topic))
            prompt = prompt.replace("{{genre}}", str(genre_label))
            prompt = prompt.replace("{{sample_txt}}", str(sample_txt))
            prompt = prompt.replace("{{thumb_style_guide}}", str(thumb_style_guide))
            prompt = prompt.replace("{{title_type}}", str(title_type_instruction))  # v62.40
            # v62.40b: 팩 템플릿에 {{title_type}} 플레이스홀더가 없는 경우 (horror 암호화 팩 등)
            # → title_type_instruction이 prompt에 없으면 항상 말미에 추가 보장
            if title_type_instruction not in prompt:
                prompt = prompt.rstrip() + f"\n\n[TITLE FORMAT REQUIREMENT - 필수]\n{title_type_instruction}\n"
            # JSON 출력 포맷이 팩에 없을 수 있으므로 보장
            if "thumbnail_title" not in prompt:
                prompt += f"""

Output JSON ONLY:
{{"title":"","thumbnail_title":"","description":"","tags":"","thumbnail_text":""}}
"""
        else:
            prompt = f"""
You are the chief editor of a 1-million-subscriber YouTube channel.
Create click-worthy metadata based on the information below.
ALL output values must be in Korean.

[Topic] {topic}
[Genre] {genre_label}
[Script Sample] {sample_txt}

[Requirements]
1) title: May include emoji, max 40 Korean characters
   {title_type_instruction}

2) thumbnail_title: ★ CRITICAL — this is the main text overlaid on the thumbnail image ★
   - Absolutely NO emoji
   - 12-18 Korean characters (too long = unreadable on mobile)
   - 2-4 short phrases for visual impact
   - Must capture the story's core mystery or shock point
   {thumb_style_guide}

3) thumbnail_text: Max 8 Korean characters, genre-tag style (e.g., "공포드라마", "감동드라마")
4) tags: 20 high-search-volume Korean keywords, comma-separated
5) description: 3-line Korean summary of the story

Output JSON ONLY:
{{"title":"","thumbnail_title":"","description":"","tags":"","thumbnail_text":""}}
"""
        gen_config = _make_generation_config(
            temperature=0.4,
            top_p=0.85,
        )

        # v32.1: 지수 백오프 재시도 적용
        meta = {}
        for attempt in range(5):
            try:
                res = self.model.generate_content(prompt, generation_config=gen_config)
                raw = _extract_json_block((getattr(res, "text", "") or ""), want="object")
                meta = _safe_json_loads(raw, {})
                if meta:
                    logger.info(f"[총괄 PD] 메타데이터 생성 완료")
                    break
            except Exception as e:
                delay = min(1.0 * (2 ** attempt), 30.0) * (0.5 + random.random())
                logger.warning(f"[총괄 PD] 메타데이터 재시도 {attempt+1}/5, {delay:.1f}초 대기. 에러: {e}")
                if attempt < 4:
                    time.sleep(delay)
                else:
                    logger.error(f"[총괄 PD] 메타데이터 최종 실패: {e}")

        # tags 보정
        if not meta.get("tags"):
            kws = _korean_keywords(topic, 8)
            meta["tags"] = ",".join(kws) if kws else ""

        # title 보정 (유튜브 제목: 이모지 허용)    
        if not meta.get("title"):
            meta["title"] = topic[:38] + ("…" if len(topic) > 38 else "")

        # v50: thumbnail_title 품질 보정 (썸네일 메인 글씨: 이모지 금지)
        raw_tt = meta.get("thumbnail_title") or ""
        raw_tt = _strip_emoji(raw_tt).strip()

        # v58.1: 품질 검증 - 자극적/궁금증 유발 제목인지 판단
        def _is_weak_title(t: str) -> bool:
            """약한 제목인지 판단 (v58.1: 유튜브 최적화)"""
            if len(t) < 4:
                return True
            # 너무 일반적인 제목 패턴
            weak_patterns = ["제목", "이야기", "사연", "내용", "스토리", "영상", "드라마"]
            if any(p in t for p in weak_patterns) and len(t) < 8:
                return True
            # v61.1 (#54): 공포+시니어 공통 강력한 제목 키워드
            strong_keywords = [
                # 공포 계열
                "비밀", "진실", "충격", "배신", "거짓", "정체", "숨겨", "드러나",
                # 시니어/감동 계열
                "눈물", "용서", "고백", "이별", "재회", "약속", "유언", "마지막",
                "아들", "딸", "어머니", "아버지", "가족", "효도", "그리움",
            ]
            return not any(k in t for k in strong_keywords)

        # v60: 자극적 제목 공식 — 팩에서 title_hooks 우선 로드
        def _make_compelling_title(base: str, category: str, mode: str) -> str:
            """궁금증 유발 제목 생성 (v60: 팩 기반)"""
            import random
            # v60.1.0: 팩의 thumbnail.title_hooks에서 로드 (raw_settings 제거)
            title_hooks = []
            if PACK_CONFIG_AVAILABLE and ACTIVE_PACK.is_loaded:
                hooks_raw = getattr(ACTIVE_PACK.thumbnail, 'title_hooks', []) or []
                if hooks_raw:
                    title_hooks = hooks_raw
            # 폴백: 범용 후크
            if not title_hooks:
                title_hooks = ["숨겨온 비밀", "충격의 진실", "드러난 정체", "마지막 고백", "눈물의 진실"]

            if len(base) <= 8:
                return random.choice(title_hooks)
            else:
                return base[:12] + "..."

        if _is_weak_title(raw_tt):
            # v58.1: 강력한 제목으로 변환
            title_clean = _strip_emoji(meta.get("title") or topic)
            raw_tt = _make_compelling_title(title_clean, category, mode)

        # 최종 길이 제한 (v58.1: 12자 권장, 최대 16자)
        if len(raw_tt) > 16:
            # 자연스럽게 끊기 (공백 기준)
            if " " in raw_tt[:16]:
                last_space = raw_tt[:16].rfind(" ")
                if last_space > 8:
                    raw_tt = raw_tt[:last_space]
                else:
                    raw_tt = raw_tt[:12] + "..."
            else:
                raw_tt = raw_tt[:12] + "..."

        meta["thumbnail_title"] = raw_tt.strip()
        logger.info(f"[총괄 PD] 썸네일 제목: '{meta['thumbnail_title']}' ({len(meta['thumbnail_title'])}자)")

        # v58.1: thumbnail_text 보정 (상단 노란 글씨: 자극적으로)
        raw_text = meta.get("thumbnail_text") or ""
        raw_text = _strip_emoji(raw_text).strip()

        if not raw_text or len(raw_text) < 2:
            # v60.1.0: 팩의 thumbnail.text_default 사용 (raw_settings 제거)
            if PACK_CONFIG_AVAILABLE and ACTIVE_PACK.is_loaded:
                raw_text = getattr(ACTIVE_PACK.thumbnail, 'text_default', '') or "실화"
            else:
                raw_text = "실화"

        # 8자 제한
        if len(raw_text) > 8:
            raw_text = raw_text[:8].rstrip()

        meta["thumbnail_text"] = raw_text

        # v61.1 (#55): description 보정 - 장르 중립 폴백 (시니어 하드코딩 제거)
        if not meta.get("description"):
            meta["description"] = (
                f"{meta.get('title', topic)}\n\n"
                f"끝까지 보셔야 합니다.\n\n"
                f"#드라마 #이야기 #숏드라마 #실화"
            )

        return meta


# ============================================================
# v56.1: ScriptWriter → script_writers.py에서 import (상단 참조)
# ============================================================


# ============================================================
# ✅ 미술 감독 (v31.1: 공포 템플릿 30개 확장)
# ============================================================
class ArtDirector:
    """
    v31.1: 공포 템플릿 15개 → 30개 확장
    v58: pack_config에서 safe_templates 우선 로드
    v60: 팩 기반 통합 safe_templates 로딩
    """

    @staticmethod
    def _get_safe_templates() -> List[str]:
        """v60: 팩에서 safe_templates 로딩 (장르 분기 없는 통합 메서드)"""
        if PACK_CONFIG_AVAILABLE and ACTIVE_PACK.is_loaded:
            templates = get_safe_templates()
            if templates:
                return templates
        # 범용 폴백
        return [
            "empty room, dim lighting, atmospheric, cinematic composition",
            "abstract background, soft colors, minimal detail",
            "dark corridor with distant light, atmospheric, no people",
            "rainy window with droplets, blurry view outside",
            "old wooden desk with scattered papers, warm lamp light",
        ]

    @staticmethod
    def _senior_safe_templates(mode: str) -> List[str]:
        # v58: 팩에서 safe_templates 우선 로드
        if PACK_CONFIG_AVAILABLE and ACTIVE_PACK.is_loaded:
            templates = get_safe_templates()
            if templates:
                return templates

        # v60: 장르 분기 제거 — 팩 없을 때 범용 폴백
        return [
            "empty room, dim lighting, atmospheric, cinematic composition",
            "old handwritten letter on weathered wooden table, warm afternoon sunlight",
            "vintage transistor radio on wooden shelf, soft golden hour light",
            "rainy bus stop shelter at dusk, empty wooden bench, gentle rain",
            "aged photo album open on table, sepia-toned photographs visible",
            "steaming tea cup on windowsill, rain droplets on glass pane",
            "empty train station platform at sunset, orange sky glow",
            "old music box on dresser, soft bedroom lighting",
            "abstract background, soft colors, minimal detail",
        ]

    @staticmethod
    def _horror_safe_templates() -> List[str]:
        # v58: 팩에서 safe_templates 우선 로드
        if PACK_CONFIG_AVAILABLE and ACTIVE_PACK.is_loaded:
            templates = get_safe_templates()
            if templates:
                return templates

        # v50: 30개 → 80개 확장 (반복 방지) - 하드코딩 폴백
        return [
            # === 실내 공간 (25개) ===
            "abandoned hallway with flickering fluorescent lights, peeling wallpaper, water stains on ceiling",
            "empty hospital corridor at night, wheelchair near wall, dim emergency lighting",
            "old mansion staircase, dusty handrail, cobwebs in corners, faint candlelight below",
            "cracked mirror on wall, dim room, furniture covered in dusty white sheets",
            "abandoned classroom, overturned desks, chalk dust in air, mysterious scratches on blackboard",
            "dark basement stairs descending, single lightbulb swinging, damp stone walls",
            "empty theater auditorium, torn velvet curtains, single spotlight on empty stage",
            "old library interior, dusty bookshelves, single reading lamp casting long shadows",
            "abandoned hospital room, rusty bed frame, broken IV stand, moonlight through cracked window",
            "old elevator with exposed cables, flickering emergency light, scratched metal walls",
            "empty motel room, buzzing neon sign outside, stained wallpaper, suitcase left behind",
            "bathroom with cracked mirror, dripping faucet, harsh fluorescent light flickering",
            "long corridor with slightly open door, light leaking from underneath, eerie silence",
            "abandoned living room, furniture covered with sheets, moonlight through broken blinds",
            "old rotary phone on small table, receiver off-hook, coiled cord dangling",
            "messy desk with scattered papers, burnt-out candle, heavy shadow on cracked wall",
            "door with chain lock hanging loose, scratch marks on wood, dim hallway beyond",
            "window with heavy rain outside, blurred city lights, empty dark interior",
            "abandoned office building lobby, broken chandelier, marble floor cracked",
            "empty school hallway at night, lockers slightly open, flickering exit sign",
            "old apartment kitchen, rusty sink, cabinet doors hanging open, expired food",
            "dusty attic with covered mirrors, old trunk open, faded photographs scattered",
            "abandoned church interior, broken pews, stained glass casting eerie colors",
            "empty warehouse with hanging chains, distant dripping water, concrete pillars",
            "old psychiatric ward, padded room visible, rusted door frame, dim light",

            # === 실외 공간 (25개) ===
            "dark forest path, twisted tree branches reaching, thick fog rolling in",
            "deserted subway platform at 3am, single bench, mysterious graffiti on tiles",
            "foggy cemetery path, weathered gravestones, bare trees silhouette",
            "derelict factory exterior, rusted machinery, broken windows reflecting moonlight",
            "narrow alley at night, brick walls, fire escape ladder shadow, wet pavement",
            "rainy night street, broken streetlamp sparking, puddles reflecting distant lights",
            "dark forest clearing, abandoned tent, scattered belongings, campfire smoke remains",
            "lonely street lamp in thick fog, empty wet road, film grain atmosphere",
            "abandoned train station platform, fog rolling across tracks, rusted signals",
            "empty parking garage at midnight, single flickering light, concrete pillars",
            "overgrown playground at dusk, rusted swing moving slightly, abandoned toys",
            "foggy pier extending into darkness, rotting wooden planks, distant foghorn",
            "abandoned amusement park, ferris wheel silhouette, peeling paint, overgrown weeds",
            "empty highway rest stop, broken vending machines, single car in lot",
            "dark tunnel entrance, water dripping from ceiling, graffiti covered walls",
            "abandoned gas station at night, flickering price sign, empty pumps",
            "foggy bridge over dark river, rusted railings, distant city lights blurred",
            "empty schoolyard at night, swings moving in wind, basketball left on court",
            "forest road with fallen leaves, car headlights cutting through fog",
            "abandoned construction site, crane silhouette, scattered building materials",
            "rooftop at night, water towers, city skyline hazy, pigeons scattered",
            "backyard with dead garden, rusted lawn chair, broken fence slats",
            "empty drive-in theater, torn screen, rows of speaker posts",
            "lakeside dock at midnight, fog on water, small boat tied to post",
            "mountain road tunnel entrance, darkness within, warning signs faded",

            # === 클로즈업/디테일 (20개) ===
            "close-up of old rusty key on dusty floor, long eerie shadow, keyhole nearby",
            "close-up of cracked picture frame, torn photograph with faces scratched out",
            "close-up of spilled ink on handwritten letter, broken wax seal, aged paper",
            "old cassette tape unspooled on floor, broken walkman nearby, dust particles",
            "vintage clock stopped at 3:33, cracked face, cobweb in corner",
            "bundle of dried flowers in dusty vase, petals scattered on table",
            "old diary open to cryptic entry, faded ink, coffee stain on page",
            "broken spectacles on wooden floor, lens cracked, leather case nearby",
            "antique music box open, tiny ballerina frozen, mechanism visible",
            "stack of yellowed newspapers, headline partially visible, rubber band broken",
            "old medicine bottles arranged on shelf, labels faded, one tipped over",
            "vintage typewriter with paper stuck, keys jammed, ribbon faded",
            "children's drawing on wall, crayon colors faded, paper edges curled",
            "dusty snow globe with crack, water level low, figure inside tilted",
            "old television showing static, antenna bent, console cabinet dusty",
            "candle melted to pool of wax, wick smoking, matches scattered",
            "vintage camera on tripod, lens dusty, film canister open beside it",
            "rocking horse in corner, paint chipped, one eye missing",
            "old gramophone with cracked record, needle arm broken, dust on horn",
            "porcelain doll on shelf, one eye closed, dress yellowed with age",

            # === 분위기/추상 (10개) ===
            "shadow of tree branches on wall, wind moving them, moonlight source",
            "light beam through dusty air, particles floating, source from above",
            "rain droplets trailing down glass, blurred lights beyond, condensation",
            "frost pattern on window, breath visible, cold interior",
            "cobweb in corner catching light, dew drops, dust particles floating",
            "reflections in puddle at night, distorted streetlights, ripples spreading",
            "steam rising from storm drain, night street, red brake lights reflecting",
            "candle flame flicker in draft, wax dripping, shadow dancing on wall",
            "dust motes in single light beam, darkness around, floating slowly",
            "fog rolling across floor, low angle, furniture legs barely visible",
        ]

    @staticmethod
    def _filter_bad_words(text: str) -> str:
        """LLM 생성 프롬프트에서 금칙어 발견 시 안전 폴백"""
        bad_words = [
            "nude", "naked", "bikini", "lingerie", "underwear", "nsfw", "sex", "erotic",
            "blood", "bloody", "gore", "gory", "viscera", "organs",
            "corpse", "dead body", "decapitation", "dismemberment",
            "rape", "assault", "violence", "torture", "weapon"
        ]

        t = text.lower()
        for bad in bad_words:
            if bad in t:
                # v61.1 (#58): 장르 중립 폴백 (공포 전용 → 범용)
                return "empty room, dim lighting, atmospheric, cinematic composition"

        return text

    def __init__(self, model):
        self.model = model

    def create_scenes(
        self,
        topic: str,
        category: str,
        mode: str,
        full_script: List[Dict[str, Any]],
        num_images: int = 40,
    ) -> List[str]:
        safe_print(f"   🎨 [미술 감독] 대본 기반 이미지 프롬프트 {num_images}장 구상 중...")

        # v50: 캐릭터 형체 시스템 사용 여부 확인
        if visual_director.is_character_system_enabled():
            safe_print(f"      🎭 [캐릭터 모드] 대본 기반 캐릭터 형체 이미지 생성")
            return self._create_character_based_scenes(topic, category, mode, full_script, num_images)

        # v60: 팩에 image_llm_prompt가 있으면 LLM 기반, 없으면 하이브리드
        image_llm_prompt = get_prompt("image_llm_prompt") if PACK_CONFIG_AVAILABLE else ""
        if image_llm_prompt:
            safe_print(f"      🛡️ [스토리 연동 모드] 스크립트 기반 이미지")
            return self._create_story_based_scenes(topic, mode, full_script, num_images, image_llm_prompt)
        else:
            safe_print(f"      🎨 [하이브리드 모드] 템플릿 60% + LLM 40%")
            return self._create_horror_scenes_hybrid(topic, mode, full_script, num_images)

    def _create_horror_scenes_hybrid(self, topic: str, mode: str, full_script: List[Dict], num_images: int) -> List[str]:
        # v60: 팩에서 image_style 로딩 (장르 분기 제거)
        style = get_prompt("image_style") if PACK_CONFIG_AVAILABLE else ""
        if not style:
            style = "horror manga style, black and white ink drawing, eerie atmosphere, high contrast"

        # 1) 템플릿 60%
        template_count = int(num_images * 0.6)
        templates = self._get_safe_templates()
        template_scenes = []
        for i in range(template_count):
            t = templates[i % len(templates)]
            
            # ✅ v31: 관문 통과
            raw = f"{t}, {style}"
            pos, neg = visual_director.finalize(raw_prompt=raw)
            template_scenes.append(f"{pos}|||{neg}")

        # 2) LLM 40% - v54: 개선된 스크립트 컨텍스트
        llm_count = num_images - template_count

        # v54: 1/20 → 1/5 샘플링 (4배 더 많은 컨텍스트)
        sample_interval = max(1, len(full_script) // (llm_count * 3)) if full_script else 1
        sampled_turns = full_script[::sample_interval][:llm_count * 3] if full_script else []

        # 각 턴에서 감정/역할/텍스트 추출 (7000자로 확대)
        turn_details = []
        for turn in sampled_turns:
            role = turn.get('role', '화자')
            text = turn.get('text', '')[:150]
            emotion = turn.get('emotion', '')
            if emotion:
                turn_details.append(f"[{role}/{emotion}] {text}")
            else:
                turn_details.append(f"[{role}] {text}")
        sample_txt = "\n".join(turn_details)[:7000]

        prompt = f"""You are a horror manga art director creating images for a Korean horror story.
Create {llm_count} background image prompts that DIRECTLY VISUALIZE scenes from this story.

[STORY TOPIC] {topic}
[STYLE] {style}

[STORY CONTEXT - Key moments]
{sample_txt}

[CRITICAL RULES]
- Each prompt MUST represent a SPECIFIC scene/moment from the story above
- Focus on LOCATIONS, OBJECTS, ATMOSPHERE that appear in the story
- Examples:
  * Story mentions abandoned school → "abandoned classroom at night, overturned desks, chalk dust, moonlight through broken window"
  * Story mentions strange phone call → "old telephone on desk, dim room, flickering lamp, ominous shadows on wall"
  * Story mentions forest → "dense foggy forest path, gnarled trees, mysterious shadows between trunks"
- Characters OK: manga-style characters with expressions and poses are encouraged for storytelling
- Characters must be: fully clothed, manga/manhwa art style
- NO: nsfw, nude, naked, revealing clothes, gore, excessive blood, graphic violence
- NO: photorealistic faces, 3d rendered humans, photograph-style people
- NO: generic horror backgrounds unrelated to this specific story

Output JSON array of {llm_count} prompts:
["prompt1", "prompt2", ...]
"""
        gen_config = _make_generation_config(
            temperature=0.75,
            top_p=0.9,
        )

        llm_scenes = []
        max_attempts = 5
        for attempt in range(max_attempts):
            try:
                res = self.model.generate_content(prompt, generation_config=gen_config)
                raw = _extract_json_block((getattr(res, "text", "") or ""), want="list")
                arr = _safe_json_loads(raw, [])

                if isinstance(arr, list) and len(arr) >= int(llm_count * 0.7):
                    for s in arr[:llm_count]:
                        s = _safe_strip(str(s))
                        s = self._filter_bad_words(s)

                        # ✅ v31: 관문 통과
                        raw_prompt = f"{s}, {style}"
                        pos, neg = visual_director.finalize(raw_prompt=raw_prompt)
                        llm_scenes.append(f"{pos}|||{neg}")
                    logger.info(f"[아트 디렉터] LLM 이미지 프롬프트 {len(llm_scenes)}개 생성 성공")
                    break
                else:
                    logger.warning(f"[아트 디렉터] LLM 응답 불충분 (받음: {len(arr) if isinstance(arr, list) else 0}, 필요: {int(llm_count * 0.7)})")
            except Exception as e:
                delay = min(1.0 * (2 ** attempt), 30.0) * (0.5 + random.random())
                logger.warning(f"[아트 디렉터] API 오류. 재시도 {attempt+1}/{max_attempts}, {delay:.1f}초 대기. 에러: {type(e).__name__}: {str(e)[:100]}")
                if attempt < max_attempts - 1:
                    time.sleep(delay)

        # 폴백
        while len(llm_scenes) < llm_count:
            backup = random.choice(templates)
            raw = f"{backup}, {style}"
            pos, neg = visual_director.finalize(raw_prompt=raw)
            llm_scenes.append(f"{pos}|||{neg}")

        # 3) 섞기
        all_scenes = template_scenes + llm_scenes
        random.shuffle(all_scenes)

        safe_print(f"      ✅ 공포 이미지 {len(all_scenes)}장 (템플릿 {template_count} + LLM {len(llm_scenes)}) 완료")
        return all_scenes[:num_images]

    # =========================================================
    # v54: 시니어 채널 스토리 기반 이미지 생성
    # =========================================================
    def _create_story_based_scenes(
        self,
        topic: str,
        mode: str,
        full_script: List[Dict[str, Any]],
        num_images: int,
        image_llm_prompt: str = ""
    ) -> List[str]:
        """
        v60: 스토리 맥락을 반영한 이미지 생성 (장르 범용)

        개선점:
        1. 스크립트에서 감정/상황 키워드 추출
        2. Gemini에게 스토리 맥락 전달하여 관련 배경 생성
        3. 템플릿은 폴백으로만 사용
        """
        safe_print(f"      📖 [스토리 분석] 대본에서 핵심 장면 {num_images}개 추출 중...")

        # v60: 팩에서 image_style 로딩 (장르 분기 제거)
        style = get_prompt("image_style") if PACK_CONFIG_AVAILABLE else ""
        if not style:
            style = "cinematic composition, professional quality, 2d illustration"

        scenes: List[str] = []
        templates = self._get_safe_templates()

        # 스크립트가 없으면 템플릿 폴백
        if not full_script:
            safe_print(f"      ⚠️ 대본 없음 - 템플릿 폴백")
            for i in range(num_images):
                raw = f"{templates[i % len(templates)]}, {style}"
                pos, neg = visual_director.finalize(raw_prompt=raw)
                scenes.append(f"{pos}|||{neg}")
            return scenes

        # 1. 스크립트에서 핵심 턴 균등 샘플링 (1/5 = 20% 사용, 기존 1/20에서 개선)
        sample_interval = max(1, len(full_script) // (num_images * 2))
        sampled_turns = full_script[::sample_interval][:num_images * 2]

        # 2. 각 턴에서 감정/상황 추출
        turn_summaries = []
        for turn in sampled_turns[:min(30, len(sampled_turns))]:  # 최대 30턴
            role = turn.get("role", "화자")
            text = turn.get("text", "")[:200]  # 각 턴 200자 제한
            emotion = turn.get("emotion", "calm")
            turn_summaries.append(f"[{role}/{emotion}] {text}")

        context_text = "\n".join(turn_summaries)

        # 3. Gemini에게 스토리 맥락 전달하여 이미지 프롬프트 생성
        # v61: image_llm_prompt가 있으면 팩의 규칙 사용, 없으면 기본 규칙
        if image_llm_prompt:
            # 팩의 image_llm_prompt를 시스템 프롬프트로, 스토리 정보를 유저 프롬프트로
            prompt = f"""{image_llm_prompt}

[STORY TOPIC] {topic}

[STORY CONTEXT - Key scenes from the script]
{context_text}

[STYLE] {style}

Create {num_images} Stable Diffusion prompts as a JSON array:
["prompt1", "prompt2", ...]
"""
        else:
            prompt = f"""You are an art director for Korean drama YouTube shorts.
Create {num_images} background image prompts for Stable Diffusion that DIRECTLY RELATE to this story.

[STORY TOPIC] {topic}

[STORY CONTEXT - Key scenes from the script]
{context_text}

[STYLE] {style}

[CRITICAL RULES]
- Each prompt MUST visualize a specific moment/emotion from the story
- Include manga/illustration style characters when the story scene involves people
- Match the emotional tone of the art style described above
- Characters must be: fully clothed, illustration/manhwa art style
- NO: nsfw, nude, naked, revealing clothes, photorealistic faces, 3d rendered humans
- NO: generic backgrounds unrelated to the story

Output JSON array of {num_images} prompts:
["prompt1", "prompt2", ...]
"""
        gen_config = _make_generation_config(
            temperature=0.7,
            top_p=0.9,
        )

        # Gemini 호출
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                res = self.model.generate_content(prompt, generation_config=gen_config)
                raw_text = (getattr(res, "text", "") or "")
                arr = _safe_json_loads(_extract_json_block(raw_text, want="list"), [])

                if isinstance(arr, list) and len(arr) >= int(num_images * 0.7):
                    safe_print(f"      ✅ Gemini가 {len(arr)}개 스토리 기반 프롬프트 생성")
                    for s in arr[:num_images]:
                        s = _safe_strip(str(s))
                        s = self._filter_bad_words(s)
                        raw_prompt = f"{s}, {style}"
                        pos, neg = visual_director.finalize(raw_prompt=raw_prompt)
                        scenes.append(f"{pos}|||{neg}")
                    break
                else:
                    logger.warning(f"[시니어 아트] LLM 응답 부족: {len(arr) if isinstance(arr, list) else 0}개")
            except Exception as e:
                delay = min(1.0 * (2 ** attempt), 10.0)
                logger.warning(f"[시니어 아트] API 오류 {attempt+1}/{max_attempts}: {str(e)[:100]}")
                if attempt < max_attempts - 1:
                    time.sleep(delay)

        # 4. 부족한 만큼 템플릿으로 채우기
        while len(scenes) < num_images:
            backup = templates[len(scenes) % len(templates)]
            raw = f"{backup}, {style}"
            pos, neg = visual_director.finalize(raw_prompt=raw)
            scenes.append(f"{pos}|||{neg}")

        safe_print(f"      ✅ 시니어 스토리 이미지 {len(scenes)}장 완료 (Gemini: {min(len(scenes), num_images - len(templates))}, 폴백: {max(0, len(scenes) - num_images + len(templates))})")
        return scenes[:num_images]

    # =========================================================
    # v50: 캐릭터 형체 기반 씬 생성 (세월정거장/포시즌 전용)
    # =========================================================
    def _create_character_based_scenes(
        self,
        topic: str,
        category: str,
        mode: str,
        full_script: List[Dict[str, Any]],
        num_images: int
    ) -> List[str]:
        """
        대본의 role/emotion/text를 분석해서 캐릭터 형체 + 배경 프롬프트 생성

        흐름:
        1. 대본에서 주요 턴 샘플링 (num_images개)
        2. 각 턴의 role, emotion 추출
        3. visual_director.build_character_prompt() 호출
        4. 결과 프롬프트 반환
        """
        # v60: 채널 타입 — 팩 ID에서 결정 (장르 분기 제거)
        channel_type = ACTIVE_PACK.pack_id if (PACK_CONFIG_AVAILABLE and ACTIVE_PACK.is_loaded) else f"{category}_{mode}"

        safe_print(f"      🎭 [캐릭터 시스템] {channel_type} 스타일로 {num_images}장 생성")

        scenes: List[str] = []

        # 대본에서 균등 샘플링
        if not full_script:
            # 폴백: 템플릿 기반
            safe_print(f"      ⚠️ 대본 없음 - 템플릿 폴백")
            # v60: 팩에서 safe_templates 로딩 → 통합 폴백
            templates = self._get_safe_templates()
            for i in range(num_images):
                t = templates[i % len(templates)]
                pos, neg = visual_director.finalize(raw_prompt=t, channel_type=channel_type)
                scenes.append(f"{pos}|||{neg}")
            return scenes

        # 샘플링 간격 계산
        step = max(1, len(full_script) // num_images)
        sampled_turns = []
        for i in range(0, len(full_script), step):
            if len(sampled_turns) >= num_images:
                break
            sampled_turns.append(full_script[i])

        # 부족하면 마지막 턴 반복
        while len(sampled_turns) < num_images:
            sampled_turns.append(full_script[-1])

        # 각 턴에서 캐릭터 프롬프트 생성
        for i, turn in enumerate(sampled_turns[:num_images]):
            role = turn.get("role", "narrator").lower()
            emotion = turn.get("emotion", "calm").lower()
            text = turn.get("text", "")

            # 동작 추측 (텍스트 기반)
            action = self._guess_action_from_text(text, emotion)

            # v60: 배경 선택 — 팩 ID 기반 (장르 분기 제거)
            bg_pool = visual_director.THUMBNAIL_POOLS.get(
                channel_type,
                visual_director.SAFE_FALLBACKS
            )
            background = random.choice(bg_pool) if bg_pool else None

            # 캐릭터 프롬프트 생성
            pos, neg = visual_director.build_character_prompt(
                channel_type=channel_type,
                role=role,
                emotion=emotion,
                action=action,
                background=background
            )

            scenes.append(f"{pos}|||{neg}")

            if (i + 1) % 10 == 0:
                safe_print(f"      🎭 캐릭터 프롬프트 진행... [{i+1}/{num_images}]")

        safe_print(f"      ✅ 캐릭터 기반 이미지 {len(scenes)}장 프롬프트 완료")
        return scenes

    def _guess_action_from_text(self, text: str, emotion: str) -> str:
        """텍스트에서 동작 추측"""
        text_lower = text.lower() if text else ""

        # 키워드 기반 동작 추측
        action_keywords = {
            "울": "crying",
            "눈물": "crying",
            "흐느": "crying",
            "웃": "laughing",
            "미소": "smiling",
            "달려": "running",
            "뛰": "running",
            "걸": "walking",
            "앉": "sitting",
            "서": "standing",
            "누워": "sleeping",
            "기도": "praying",
            "안아": "hugging",
            "포옹": "hugging",
            "싸우": "arguing",
            "화내": "arguing",
            "생각": "thinking",
            "고민": "thinking",
            "요리": "cooking",
            "일하": "working",
        }

        for keyword, action in action_keywords.items():
            if keyword in text_lower:
                return action

        # 감정 기반 폴백
        emotion_action_map = {
            "sad": "sitting",
            "crying": "crying",
            "angry": "standing",
            "happy": "standing",
            "scared": "standing",
            "calm": "sitting",
        }

        return emotion_action_map.get(emotion, "standing")


# ============================================================
# v37: Enhanced(개선) 프롬프트 시스템
# ============================================================
class EnhancedChiefProducer(ChiefProducer):
    """
    v37: 개선된 총괄 PD - 더 강력한 어그로/후킹 생성
    """

    def create_topic(self, category: str, mode: str = "") -> str:
        safe_print(f"\n🎲 [총괄 PD Enhanced] '{category}:{mode}' 바이럴 킬러 아이템 기획 중...")

        nonce = _generate_nonce()
        market_context = _build_market_research_prompt_section(category, mode)

        # v60: 팩에서 Enhanced 토픽 프롬프트 로딩 (장르 분기 제거)
        topic_enhanced_template = get_prompt("topic_enhanced") if PACK_CONFIG_AVAILABLE else ""
        scenario_pools = get_scenario_pools() if PACK_CONFIG_AVAILABLE and ACTIVE_PACK.is_loaded else None
        pool_context = self._build_pool_context(scenario_pools)
        # v60: 모든 팩에서 반복 회피 적용 (장르 분기 제거)
        bans = self.memory.get_bans_for_senior() if hasattr(self.memory, 'get_bans_for_senior') else ""

        if topic_enhanced_template:
            prompt = f"""{topic_enhanced_template}

{market_context}
{pool_context}
{("- Also avoid these recent topics: " + bans) if bans else ""}

**Nonce: {nonce}** — Use this seed to ensure a completely fresh angle

Output: ONE curiosity-sparking sentence in Korean. No elaboration.
"""
        else:
            # 폴백: 팩 미로딩 시 범용 프롬프트
            prompt = f"""
You are a content director for a YouTube channel. Create a viral topic.
{market_context}
{pool_context}
{("- Also avoid these recent topics: " + bans) if bans else ""}

**Nonce: {nonce}**
Output: ONE sentence in Korean. No elaboration.
"""

        gen_config = _make_generation_config(
            temperature=1.0,
            top_p=0.95,
            top_k=50,
        )

        for attempt in range(5):
            try:
                res = self.model.generate_content(prompt, generation_config=gen_config)
                topic = _first_line((getattr(res, "text", "") or ""))
                if len(topic) < 6:
                    topic = "알 수 없는 이야기"
                logger.info(f"[총괄 PD Enhanced] 주제 생성 완료: {topic[:50]}...")
                safe_print(f"   💡 결정된 아이템: {topic} (Nonce: {nonce})")
                return topic
            except Exception as e:
                delay = min(1.0 * (2 ** attempt), 30.0) * (0.5 + random.random())
                logger.warning(f"[총괄 PD Enhanced] 재시도 {attempt+1}/5")
                if attempt < 4:
                    time.sleep(delay)

        return "알 수 없는 이야기"

    def create_powerful_hook(self, topic: str, category: str, mode: str = "") -> str:
        safe_print("   🪝 [총괄 PD Enhanced] 킬러 훅 작성 중...")

        # v60: 팩에서 Enhanced 훅 프롬프트 로딩 (장르 분기 제거)
        hook_enhanced_template = get_prompt("hook_enhanced") if PACK_CONFIG_AVAILABLE else ""
        if hook_enhanced_template:
            prompt = f"""{hook_enhanced_template}

[Topic] "{topic}"

Output: ONE hook sentence in Korean only. No explanation.
"""
        else:
            prompt = f"""
You are a premium drama cold-open writer.
Write one Korean opening line that sounds like the most dangerous moment of the story.

[Topic] "{topic}"

[Rules]
- Spoken dialogue only or an urgent direct line
- The line must imply betrayal, danger, exposure, or a shocking truth
- Maximum 24 Korean characters — impact over length
- Avoid generic openings like "그날 밤", "모든 것은", "이야기가 시작됩니다"
- No profanity, hate speech, or explicit content

Output: ONE hook sentence in Korean only. No explanation.
"""
        gen_config = _make_generation_config(
            temperature=0.8,
            top_p=0.9,
        )

        for attempt in range(5):
            try:
                res = self.model.generate_content(prompt, generation_config=gen_config)
                hook = _normalize_hook_candidate(_first_line((getattr(res, "text", "") or "")))
                if hook and not _is_weak_hook_candidate(hook, topic=topic):
                    logger.info(f"[총괄 PD Enhanced] 훅 생성 완료: {hook[:30]}...")
                    return hook
            except Exception as e:
                if attempt < 4:
                    time.sleep(min(1.0 * (2 ** attempt), 30.0) * (0.5 + random.random()))

        return ""


# ============================================================
# v56.1: EnhancedScriptWriter, PromptMode
#        → script_writers.py에서 import (상단 참조)
# ============================================================


# ============================================================
# 통합 관리자
# ============================================================
class ScenarioPlanner:
    def __init__(
        self,
        progress_cb: Callable[[str, int, int, str], None] = None,
        prompt_mode: str = PromptMode.ENHANCED
    ):
        """
        ScenarioPlanner 초기화

        Args:
            progress_cb: 진행률 콜백 함수 (단계명, 현재단계, 총단계, 상세메시지) -> None
            prompt_mode: 프롬프트 모드 ("enhanced" - 기본값)
        """
        # v32: 진행률 콜백 설정
        if progress_cb:
            progress_callback.set_callback(progress_cb)

        # v37: 프롬프트 모드 저장
        self.prompt_mode = prompt_mode

        self.model = self._setup_model()
        mode_label = "Enhanced" if prompt_mode == PromptMode.ENHANCED else "Classic"
        safe_print(
            f"[LLM] ScenarioPlanner provider: {config.STORY_LLM_PROVIDER} / "
            f"model: {getattr(self.model, 'model_name', 'unknown')} / prompt: {mode_label}"
        )

        self.memory = DiversityMemory(config.DATA_DIR, keep=40)
        self._configure_story_team()

        # v32: 분석/편집 도구
        self.analyzer = ScriptAnalyzer()
        self.editor = ScriptEditor()

    def set_prompt_mode(self, mode: str):
        """
        v37: 프롬프트 모드 변경

        Args:
            mode: "classic" or "enhanced"
        """
        if mode == self.prompt_mode:
            return

        self.prompt_mode = mode
        mode_label = "Enhanced" if mode == PromptMode.ENHANCED else "Classic"
        safe_print(f"🔄 [ScenarioPlanner] 프롬프트 모드 변경: {mode_label}")
        self._configure_story_team()

    def _uses_single_writer_mode(self) -> bool:
        provider = (getattr(config, "STORY_LLM_PROVIDER", "") or "").strip().lower()
        return provider in {"claude", "claude_cli"}

    def _make_story_writer(self, role_name: str):
        if self.prompt_mode == PromptMode.ENHANCED:
            return EnhancedScriptWriter(self.model, role_name)
        return ScriptWriter(self.model, role_name)

    def _configure_story_team(self):
        if self.prompt_mode == PromptMode.ENHANCED:
            self.pd = EnhancedChiefProducer(self.model, self.memory)
        else:
            self.pd = ChiefProducer(self.model, self.memory)

        self.visual_director = ArtDirector(self.model)
        self.single_writer_mode = self._uses_single_writer_mode()

        if self.single_writer_mode:
            self.story_writer = self._make_story_writer("통합작가")
            self.writer1 = self.story_writer
            self.writer2 = self.story_writer
            self.writer3 = self.story_writer
            safe_print("🧠 [Story Team] Claude 단일 작가 모드 활성화 (PD + Writer 1명)")
        else:
            self.story_writer = None
            self.writer1 = self._make_story_writer("작가1(빌드업)")
            self.writer2 = self._make_story_writer("작가2(위기)")
            self.writer3 = self._make_story_writer("작가3(결말)")

    def _write_story_part(self, writer, role_name: str, topic: str, category: str, mode: str,
                          target_turns: int, story_bible: str, prev_context: str,
                          instruction: str, forbidden: str):
        original_role = getattr(writer, "role_name", role_name)
        writer.role_name = role_name
        try:
            return writer.write_part(
                topic, category, mode, target_turns, story_bible, prev_context, instruction, forbidden
            )
        finally:
            writer.role_name = original_role

    def _setup_model(self):
        from llm.factory import create_story_llm

        model = create_story_llm()
        logger.info(
            f"[ScenarioPlanner] Story LLM 초기화: provider={config.STORY_LLM_PROVIDER}, "
            f"model={getattr(model, 'model_name', 'unknown')}"
        )
        return model

    def _ensure_active_pack(self, category: str, mode: str) -> None:
        """생성 시작 전 category/mode에 맞는 팩을 강제 로드한다."""
        if not PACK_CONFIG_AVAILABLE:
            return

        candidates: List[str] = []
        normalized_category = (category or "").strip()
        normalized_mode = (mode or "").strip()

        if normalized_category == "senior" and normalized_mode:
            if normalized_mode.startswith("senior_"):
                candidates.append(normalized_mode)
            else:
                candidates.append(f"senior_{normalized_mode}")
                candidates.append(normalized_mode)
        elif normalized_mode:
            candidates.append(normalized_mode)

        if normalized_category:
            candidates.append(normalized_category)

        seen = set()
        candidates = [candidate for candidate in candidates if candidate and not (candidate in seen or seen.add(candidate))]

        active_ids = {
            getattr(ACTIVE_PACK, "pack_id", ""),
            getattr(ACTIVE_PACK, "channel_type", ""),
        }
        if any(candidate in active_ids for candidate in candidates):
            return

        for candidate in candidates:
            try:
                if load_pack_by_id(candidate):
                    logger.info("[ScenarioPlanner] active pack routed: %s -> %s", candidate, ACTIVE_PACK.pack_id)
                    return
            except Exception as exc:
                logger.warning("[ScenarioPlanner] pack load failed for %s: %s", candidate, exc)

        load_default_pack(normalized_category or "horror")

    # v62: _summarize_story 삭제 — _format_script_as_context()로 대체 (원문 전달, API 0회)

    def _build_story_bible(self, topic: str, category: str, mode: str) -> str:
        # v60: 팩에서 스토리 바이블 프롬프트 로딩 (장르 분기 제거)
        bible_template = get_prompt("story_bible") if PACK_CONFIG_AVAILABLE else ""
        # v60: 모든 팩에서 반복 회피 적용 (장르 분기 제거)
        bans = self.memory.get_bans_for_senior() if hasattr(self.memory, 'get_bans_for_senior') else ""
        ban_line = f"\n[최근 반복 회피]\n{bans}\n" if bans else ""
        market_context = _build_market_research_prompt_section(category, mode, topic)

        # 시나리오 풀에서 flavor 추출
        pool_context = ""
        if PACK_CONFIG_AVAILABLE and ACTIVE_PACK.is_loaded:
            pools = get_scenario_pools()
            pool_context = _build_pool_context(pools) if pools else ""

        if bible_template:
            prompt = f"""{bible_template}
{ban_line}
{market_context}
{pool_context}

주제: {topic}

출력은 한국어로, 번호 붙여서 간결하게.
"""
        else:
            prompt = f"""
너는 베테랑 드라마 PD다. 주제에 맞춰 '스토리 바이블'을 만들어라.
- 세계관/배경(1)
- 주요 인물 4명(각 1줄, 관계 포함) (2)
- 핵심 갈등 2개(3)
- 반전/비밀 1개(결말 스포일러 금지, 떡밥 형태) (4)
- 톤 가이드(5)
{ban_line}
{market_context}

주제: {topic}

출력은 한국어로, 번호 붙여서 간결하게.
"""

        gen_config = _make_generation_config(
            temperature=0.95,
            top_p=0.95,
            top_k=50,
        )

        try:
            res = self.model.generate_content(prompt, generation_config=gen_config)
            bible = _safe_strip((getattr(res, "text", "") or ""))
            if not bible:
                pack_id = ACTIVE_PACK.pack_id if (PACK_CONFIG_AVAILABLE and ACTIVE_PACK.is_loaded) else "unknown"
                bible = f"팩:{pack_id} / 주제:{topic}"
        except Exception:
            pack_id = ACTIVE_PACK.pack_id if (PACK_CONFIG_AVAILABLE and ACTIVE_PACK.is_loaded) else "unknown"
            bible = f"팩:{pack_id} / 주제:{topic}"

        # v60: 모든 팩에서 유사도 체크 (장르 분기 제거)
        if self.memory.is_similar(topic + " " + bible):
            try:
                res2 = self.model.generate_content(
                    prompt + "\n[RETRY]\n- 최근 에피소드와 유사하니, 인물/장소/갈등/회상 요소를 완전히 다르게 구성하라.",
                    generation_config=gen_config
                )
                bible2 = _safe_strip((getattr(res2, "text", "") or ""))
                if bible2:
                    bible = bible2
            except Exception as e:
                logger.debug(f"[ScenarioPlanner] 스토리 바이블 개선 시도 실패 (원본 유지): {e}")

        return _append_market_research_to_bible(bible, market_context)

    # v62: 바이블+아웃라인 통합 생성 (1회 API 호출)
    def _build_story_blueprint(self, topic: str, category: str, mode: str) -> Tuple[str, Dict]:
        """v62: 스토리 블루프린트 — 바이블+아웃라인을 1회 API 호출로 통합 생성.

        Returns:
            (story_bible_with_outline: str, outline_dict: Dict)
            - story_bible_with_outline: 3명의 작가에게 전달할 전체 컨텍스트 텍스트
            - outline_dict: 구조 아웃라인 딕셔너리 (파트별 instruction 생성용)
        """
        # 1. 팩에서 통합 프롬프트 로딩
        blueprint_template = get_prompt("story_blueprint") if PACK_CONFIG_AVAILABLE else ""

        # 2. 폴백: 기존 story_bible + structural_outline 합치기
        if not blueprint_template:
            bible_t = get_prompt("story_bible") if PACK_CONFIG_AVAILABLE else ""
            outline_t = get_prompt("structural_outline") if PACK_CONFIG_AVAILABLE else ""
            if bible_t or outline_t:
                blueprint_template = f"{bible_t}\n\n---\n\n{outline_t}" if outline_t else bible_t
            else:
                # 최종 폴백: 기존 _build_story_bible + _generate_horror_outline 개별 호출
                logger.warning("[v62] story_blueprint/story_bible/structural_outline 모두 없음 → 레거시 폴백")
                bible = self._build_story_bible(topic, category, mode)
                outline = self._generate_horror_outline_legacy(topic)
                if outline:
                    outline_section = self._format_outline_for_bible(outline)
                    bible = bible + outline_section
                return bible, outline

        # 3. ban + pool 컨텍스트
        bans = self.memory.get_bans_for_senior() if hasattr(self.memory, 'get_bans_for_senior') else ""
        ban_line = f"\n[최근 반복 회피]\n{bans}" if bans else ""
        market_context = _build_market_research_prompt_section(category, mode, topic)

        pool_context = ""
        if PACK_CONFIG_AVAILABLE and ACTIVE_PACK.is_loaded:
            pools = get_scenario_pools()
            pool_context = _build_pool_context(pools) if pools else ""

        # 4. {{topic}}, {{ban_line}} 치환
        prompt = blueprint_template
        prompt = prompt.replace("{{topic}}", topic)
        prompt = prompt.replace("{{ban_line}}", ban_line)

        # flavor 치환 (Flavor Pool에서 랜덤 선택은 팩 프롬프트 자체에 내장)
        if market_context:
            prompt = prompt + f"\n\n{market_context}"
        if pool_context:
            prompt = prompt + f"\n\n{pool_context}"

        prompt = prompt + f"\n\n주제: {topic}\n\n반드시 JSON만 출력. 설명/마크다운 금지."

        gen_config = _make_generation_config(
            temperature=0.9,
            top_p=0.92,
            top_k=50,
            max_output_tokens=4096,
        )

        # 5. Gemini 호출 (최대 3회 시도)
        for attempt in range(3):
            try:
                res = self.model.generate_content(prompt, generation_config=gen_config)
                text = _safe_strip((getattr(res, "text", "") or ""))

                if not text:
                    logger.warning(f"[v62 Blueprint] 빈 응답 (시도 {attempt+1})")
                    continue

                # JSON 추출
                raw = _extract_json_block(text, want="object")
                data = _safe_json_loads(raw, {})

                # 검증: bible + outline 둘 다 있어야 함
                bible_data = data.get("bible", {})
                outline_data = data.get("outline", {})

                if bible_data and outline_data.get("title"):
                    # bible 텍스트 변환 (작가에게 전달)
                    bible_text = self._blueprint_bible_to_text(bible_data)
                    # outline 섹션 주입
                    outline_section = self._format_outline_for_bible(outline_data)
                    full_bible = _append_market_research_to_bible(bible_text, market_context) + outline_section

                    safe_print(f"   [v62 블루프린트] 생성 완료: \"{outline_data.get('title', '?')}\"")
                    safe_print(f"      캐릭터: {len(bible_data.get('characters', []))}명")
                    if outline_data.get('twist_reveal'):
                        safe_print(f"      반전: {outline_data.get('twist_reveal', '?')[:40]}")
                    if outline_data.get('last_line'):
                        safe_print(f"      마지막: [{outline_data.get('last_speaker', '?')}] \"{outline_data.get('last_line', '?')}\"")

                    # 유사도 체크
                    if self.memory.is_similar(topic + " " + full_bible):
                        logger.info("[v62 Blueprint] 유사도 높음 - 1회 추가 시도")
                        prompt_retry = prompt + "\n[RETRY] 최근 에피소드와 유사합니다. 인물/장소/갈등을 완전히 다르게 구성하라."
                        try:
                            res2 = self.model.generate_content(prompt_retry, generation_config=gen_config)
                            text2 = _safe_strip((getattr(res2, "text", "") or ""))
                            raw2 = _extract_json_block(text2, want="object")
                            data2 = _safe_json_loads(raw2, {})
                            if data2.get("bible") and data2.get("outline", {}).get("title"):
                                bible_text2 = self._blueprint_bible_to_text(data2["bible"])
                                outline_section2 = self._format_outline_for_bible(data2["outline"])
                                return _append_market_research_to_bible(bible_text2, market_context) + outline_section2, data2["outline"]
                        except Exception as e:
                            logger.debug(f"[v62 Blueprint] 유사도 재시도 실패 (원본 유지): {e}")

                    return full_bible, outline_data

                logger.warning(f"[v62 Blueprint] JSON 구조 불완전 (시도 {attempt+1}): bible={bool(bible_data)}, outline.title={outline_data.get('title')}")

            except Exception as e:
                logger.warning(f"[v62 Blueprint] API 오류 (시도 {attempt+1}): {e}")
                time.sleep(2)

        # 6. 최종 폴백: 기존 방식 (개별 호출)
        safe_print(f"   [v62 블루프린트] 통합 생성 실패 → 레거시 개별 호출 폴백")
        bible = self._build_story_bible(topic, category, mode)
        outline = self._generate_horror_outline_legacy(topic)
        if outline:
            outline_section = self._format_outline_for_bible(outline)
            bible = bible + outline_section
        return bible, outline

    def _blueprint_bible_to_text(self, bible_data: Dict) -> str:
        """v62: blueprint JSON의 bible 섹션을 작가에게 전달할 텍스트로 변환"""
        lines = ["[스토리 바이블]"]
        if bible_data.get("setting"):
            lines.append(f"1. 배경: {bible_data['setting']}")
        chars = bible_data.get("characters", [])
        if chars:
            lines.append("2. 등장인물:")
            for i, ch in enumerate(chars, 1):
                name = ch.get("name", "?")
                vt = ch.get("voice_type", "?")
                desc = ch.get("desc", "?")
                lines.append(f"   {i}) {name} ({vt}): {desc}")
        conflicts = bible_data.get("conflicts", [])
        if conflicts:
            lines.append("3. 핵심 갈등:")
            for i, c in enumerate(conflicts, 1):
                lines.append(f"   {i}) {c}")
        flashbacks = bible_data.get("flashbacks", [])
        if flashbacks:
            lines.append("4. 회상 장면:")
            for i, fb in enumerate(flashbacks, 1):
                lines.append(f"   {i}) {fb}")
        if bible_data.get("tone"):
            lines.append(f"5. 톤: {bible_data['tone']}")
        return "\n".join(lines)

    def _format_outline_for_bible(self, outline: Dict) -> str:
        """v62: 아웃라인 딕셔너리를 story_bible에 주입할 텍스트 섹션으로 변환"""
        parts = ["\n\n[★ STRUCTURAL OUTLINE — PD가 설계한 구조. 이 구조를 반드시 따르세요! ★]"]
        if outline.get("twist_type"):
            parts.append(f"- 반전 유형: {outline['twist_type']}")
        if outline.get("twist_setup"):
            parts.append(f"- 반전 설정(독자가 믿을 것): {outline['twist_setup']}")
        if outline.get("twist_reveal"):
            parts.append(f"- 반전 공개(실제 진실): {outline['twist_reveal']}")
        if outline.get("twist_why_scary"):
            parts.append(f"- 왜 무서운가: {outline['twist_why_scary']}")
        # 복선 (horror용)
        if outline.get("hint1"):
            parts.append(f"- 복선1: {outline['hint1']} → 회수: {outline.get('payoff1', '?')}")
        if outline.get("hint2"):
            parts.append(f"- 복선2: {outline['hint2']} → 회수: {outline.get('payoff2', '?')}")
        # 감정 씨앗 (touching용)
        if outline.get("emotional_seed1"):
            parts.append(f"- 감정 씨앗1: {outline['emotional_seed1']}")
        if outline.get("emotional_seed2"):
            parts.append(f"- 감정 씨앗2: {outline['emotional_seed2']}")
        # 막장용 필드
        if outline.get("core_secret"):
            parts.append(f"- 핵심 비밀: {outline['core_secret']}")
        if outline.get("misdirection"):
            parts.append(f"- 미스디렉션: {outline['misdirection']}")
        if outline.get("betrayal_axis"):
            parts.append(f"- 배신 축: {outline['betrayal_axis']}")
        if outline.get("evidence"):
            parts.append(f"- 결정적 증거: {outline['evidence']}")
        if outline.get("catharsis_moment"):
            parts.append(f"- 카타르시스 순간: {outline['catharsis_moment']}")
        # 파트별 목표
        if outline.get("p1_goal"):
            parts.append(f"- P1 목표: {outline['p1_goal']}")
        if outline.get("p2_goal"):
            parts.append(f"- P2 목표: {outline['p2_goal']}")
        if outline.get("p3_goal"):
            parts.append(f"- P3 목표: {outline['p3_goal']}")
        # 마지막 대사
        if outline.get("last_line"):
            parts.append(f"- 마지막 대사: [{outline.get('last_speaker', '?')}] \"{outline['last_line']}\"")
        if outline.get("open_question"):
            parts.append(f"- 독자에게 남기는 의문: {outline['open_question']}")
        if outline.get("resolution_type"):
            parts.append(f"- 응징 방식: {outline['resolution_type']}")
        return "\n".join(parts) + "\n"

    # v62: _format_script_as_context — 원문 턴 리스트를 다음 작가용 컨텍스트 문자열로 변환
    def _format_script_as_context(
        self,
        script: List[Dict],
        compact: bool = False,
        max_key_turns: int = 22,
        edge_turns: int = 3,
    ) -> str:
        """v62: 원문 턴 리스트를 다음 작가용 컨텍스트 문자열로 변환.
        v62.2: compact=True면 핵심 턴만 원문, 나머지 1줄 요약 (P3용 압축).

        Args:
            script: 턴 리스트 [{role, text, emotion, ...}, ...]
            compact: True면 압축 모드 (P3에 P1+P2 전달 시 사용)
            max_key_turns: 압축 모드에서 원문으로 유지할 최대 핵심 턴 수
            edge_turns: 항상 보존할 앞/뒤 턴 수
        """
        if not script:
            return "없음(시작)"

        if not compact:
            # 원문 전체 전달 (P1→P2 등)
            lines = []
            for i, turn in enumerate(script, 1):
                role = turn.get("role", "?")
                text = turn.get("text", "")
                emotion = turn.get("emotion", "")
                lines.append(f"[{i}] ({emotion}) {role}: {text}")
            return "\n".join(lines)

        # === v62.2: compact 모드 — P3용 압축 ===
        # 목표: 70턴(14K~28K chars) → ~25줄(3K~5K chars)
        # 전략: 핵심 턴 원문 보존 + 중간 턴 1줄 요약
        total = len(script)
        max_key_turns = max(8, int(max_key_turns or 0))
        edge_turns = max(2, int(edge_turns or 0))
        if total <= max(20, edge_turns * 4):
            # 20턴 이하면 압축 불필요 — 원문 전체
            lines = []
            for i, turn in enumerate(script, 1):
                role = turn.get("role", "?")
                text = turn.get("text", "")
                emotion = turn.get("emotion", "")
                lines.append(f"[{i}] ({emotion}) {role}: {text}")
            return "\n".join(lines)

        # 핵심 턴 인덱스 선별
        key_indices = set()

        # 1) 필수: 첫 3턴 + 마지막 3턴 (도입부/클라이맥스) — 항상 보존
        protected = set()
        for i in range(min(edge_turns, total)):
            key_indices.add(i)
            protected.add(i)
        for i in range(max(0, total - edge_turns), total):
            key_indices.add(i)
            protected.add(i)

        # 2) 필수: silence beats ("..." 턴) — 항상 보존
        for i, turn in enumerate(script):
            text = (turn.get("text") or "").strip()
            if text in ("...", "\u2026"):
                key_indices.add(i)
                protected.add(i)

        # 3) 필수: Part 경계 (P1 끝 / P2 시작 근처)
        mid1 = total // 3
        for i in range(max(0, mid1 - 1), min(total, mid1 + 2)):
            key_indices.add(i)
            protected.add(i)

        # 4) 강한 감정 턴 — 균등 샘플링 (전부가 아닌 대표만)
        strong_emotions = {"scared", "desperate", "angry", "whisper"}
        strong_indices = []
        for i, turn in enumerate(script):
            em = (turn.get("emotion") or "calm").strip().lower()
            if em in strong_emotions and i not in key_indices:
                strong_indices.append(i)

        # 남은 슬롯 수 계산 후 균등 샘플링
        remaining_slots = max_key_turns - len(key_indices)
        if remaining_slots > 0 and strong_indices:
            # 균등 간격으로 선택 (앞/중/뒤 골고루)
            step = max(1, len(strong_indices) // remaining_slots)
            sampled = strong_indices[::step][:remaining_slots]
            for idx in sampled:
                key_indices.add(idx)

        # 5) 최종 상한 체크 — 보호된 턴 외 제거
        if len(key_indices) > max_key_turns:
            removable = sorted(key_indices - protected)
            while len(key_indices) > max_key_turns and removable:
                key_indices.discard(removable.pop())

        # 출력 생성
        lines = []
        lines.append(f"[이전 파트 요약 — 총 {total}턴, 핵심 장면만 발췌]")
        prev_key_idx = -1
        sorted_indices = sorted(key_indices)

        for idx in sorted_indices:
            turn = script[idx]
            role = turn.get("role", "?")
            text = turn.get("text", "")
            emotion = turn.get("emotion", "")

            # 건너뛴 턴들 1줄 요약
            skipped = idx - prev_key_idx - 1
            if skipped > 0:
                skip_start = prev_key_idx + 1
                skip_end = idx - 1
                # 건너뛴 구간의 감정 분포
                skip_emotions = []
                for si in range(skip_start, idx):
                    se = (script[si].get("emotion") or "calm").strip().lower()
                    if se not in skip_emotions:
                        skip_emotions.append(se)
                skip_roles = []
                for si in range(skip_start, idx):
                    sr = script[si].get("role", "?")
                    if sr not in skip_roles:
                        skip_roles.append(sr)
                lines.append(f"  ... ({skipped}턴 생략: {'/'.join(skip_roles[:3])} 대화, 감정: {'/'.join(skip_emotions[:3])})")

            lines.append(f"[{idx+1}] ({emotion}) {role}: {text}")
            prev_key_idx = idx

        # 마지막 이후 남은 턴
        remaining = total - 1 - prev_key_idx
        if remaining > 0:
            lines.append(f"  ... (이후 {remaining}턴 생략)")

        return "\n".join(lines)

    # v62: 로컬 검증 (API 호출 없음)
    def _local_validate(self, full_script: List[Dict], story_outline: Dict) -> Tuple[List[str], bool]:
        """v62: API 호출 없는 로컬 검증.

        Returns:
            (warnings: List[str], critical: bool)
            critical=True면 P3 1회 재시도 권장 (마지막턴 나레이션 등 심각한 문제)
        """
        warnings = []
        critical = False
        total = len(full_script)
        part_size = max(1, total // 3)

        # 1. Act2 대화비율 체크 (70%+)
        act2_start = part_size
        act2_end = part_size * 2
        act2 = full_script[act2_start:act2_end]
        if act2:
            dialogue_count = sum(1 for t in act2
                                 if t.get("role") not in ("나레이션", "narrator", "narration"))
            ratio = dialogue_count / len(act2)
            if ratio < 0.70:
                warnings.append(f"act2_dialogue={ratio:.0%} (목표 70%+)")

        # 2. 마지막 2턴 나레이션 체크 → critical
        last_2 = full_script[-2:] if total >= 2 else []
        last_is_narration = any(
            t.get("role") in ("나레이션", "narrator", "narration") for t in last_2
        )
        if last_is_narration and story_outline:
            # 아웃라인이 있는 팩만 critical (아웃라인 없는 팩은 경고만)
            warnings.append("last_turn_is_narrator (아웃라인 팩: critical)")
            critical = True

        # 3. 감정 다양성 체크 (3종 이상)
        emotions = [t.get("emotion", "calm") for t in full_script]
        unique = set(emotions)
        if len(unique) < 3:
            warnings.append(f"low_emotion_variety={len(unique)}")

        # 4. 총 턴수 체크
        min_total = max(60, part_size * 3 * 0.5)
        if total < min_total:
            warnings.append(f"low_total_turns={total} (min={int(min_total)})")

        if warnings:
            logger.warning(f"[v62 LOCAL_VALIDATE] {warnings} critical={critical}")
            safe_print(f"   [v62 검증 경고] {warnings}")
        else:
            safe_print(f"   [v62 검증] 통과 ({total}턴, {len(unique)}감정)")

        return warnings, critical

    # v60: 구조적 아웃라인 생성 (팩 프롬프트 기반, 범용화)
    # v62: _generate_horror_outline_legacy로 리네임 (blueprint 폴백용으로만 유지)
    def _generate_horror_outline_legacy(self, topic: str) -> Dict[str, Any]:
        """
        v59.5: 4-Pass 구조의 핵심.
        대본의 뼈대(반전, 복선, 마지막 대사)를 먼저 설계.
        v60: structural_outline 팩 프롬프트 사용.
        """
        outline_template = get_prompt("structural_outline") if PACK_CONFIG_AVAILABLE else ""
        if outline_template:
            # v61: 팩 프롬프트 + JSON 출력 형식 강제 (팩이 자유형식 프롬프트라도 JSON 응답 보장)
            outline_prompt = f"""{outline_template}

토픽: {topic}

반드시 JSON만 출력하세요. 설명이나 마크다운 사용 금지:
{{"title":"제목(10자이내)","chars":[{{"n":"이름","v":"man/woman/young_man/young_woman/grandma/grandpa","desc":"역할(10자)"}}],"hint1":"복선1(15자)","plant1":"심는위치(파트1)","payoff1":"회수내용(15자)","payoff1_at":"회수위치(파트3)","hint2":"복선2(15자)","plant2":"심는위치(파트1)","payoff2":"회수내용(15자)","payoff2_at":"회수위치(파트3)","twist_type":"반전유형","twist_setup":"독자가 믿을것(20자)","twist_reveal":"실제진실(20자)","p1_goal":"파트1목표(20자)","p2_goal":"파트2목표(20자)","p3_goal":"파트3목표(20자)","last_line":"마지막대사원문(20자)","last_speaker":"마지막대사 화자이름","open_question":"미해결 의문(15자)"}}
"""
        else:
            # v61.1 (#59): 동적 total_turns (150턴 하드코딩 제거)
            _outline_total = 135  # 기본값 (45턴 × 3파트)
            if PACK_CONFIG_AVAILABLE:
                try:
                    _cs = get_content_settings()
                    if _cs and hasattr(_cs, 'min_turns') and _cs.min_turns:
                        _outline_total = _cs.min_turns * 3
                except Exception:
                    pass
            outline_prompt = f"""드라마 {_outline_total}턴 구조를 설계하세요. 각 값은 짧게!

토픽: {topic}

JSON만 출력:
{{"title":"제목(10자이내)","chars":[{{"n":"이름","v":"man/woman/young_man/young_woman/grandma/grandpa","desc":"역할(10자)"}}],"hint1":"복선1(15자)","plant1":"심는위치(파트1)","payoff1":"회수내용(15자)","payoff1_at":"회수위치(파트3)","hint2":"복선2(15자)","plant2":"심는위치(파트1)","payoff2":"회수내용(15자)","payoff2_at":"회수위치(파트3)","twist_type":"반전유형","twist_setup":"독자가 믿을것(20자)","twist_reveal":"실제진실(20자)","p1_goal":"파트1목표(20자)","p2_goal":"파트2목표(20자)","p3_goal":"파트3목표(20자)","last_line":"마지막대사원문(20자)","last_speaker":"마지막대사 화자이름","open_question":"미해결 의문(15자)"}}
"""

        gen_config = _make_generation_config(
            temperature=0.8,
            top_p=0.9,
            max_output_tokens=4096,
        )

        for attempt in range(3):
            try:
                res = self.model.generate_content(outline_prompt, generation_config=gen_config)
                text = _safe_strip((getattr(res, "text", "") or ""))

                # JSON 추출 (코드블록 제거)
                if text.startswith('```'):
                    lines = text.split('\n')
                    text = '\n'.join(lines[1:])
                    if text.endswith('```'):
                        text = text[:-3].strip()

                # JSON 파싱 시도
                raw = _extract_json_block(text, want="object")
                outline = _safe_json_loads(raw, {})

                if outline and outline.get("title"):
                    safe_print(f"   [공포 아웃라인] 생성 완료: \"{outline.get('title')}\"")
                    safe_print(f"      반전: {outline.get('twist_type', '?')} → {outline.get('twist_reveal', '?')[:40]}")
                    safe_print(f"      마지막: [{outline.get('last_speaker', '?')}] \"{outline.get('last_line', '?')}\"")
                    return outline

                logger.warning(f"[공포 아웃라인] 파싱 실패 (시도 {attempt+1}): {text[:200]}")
            except Exception as e:
                logger.warning(f"[공포 아웃라인] API 오류 (시도 {attempt+1}): {e}")
                time.sleep(2)

        # 실패 시 최소 아웃라인
        safe_print(f"   [공포 아웃라인] 생성 실패, 기본 아웃라인 사용")
        return {
            "title": "공포 이야기",
            "twist_type": "인물정체",
            "twist_setup": "주인공이 피해자라고 믿게 함",
            "twist_reveal": "주인공이 사실은 가해자/유령",
            "twist_why_scary": "내가 공포의 원인이라는 자각",
            "hint1": "주인공이 기억하지 못하는 시간대",
            "payoff1": "그 시간에 주인공이 한 일이 밝혀짐",
            "hint2": "주변 인물의 미묘한 회피 반응",
            "payoff2": "회피가 아니라 공포였음이 드러남",
            "open_question": "주인공은 아직도 그곳에 있는가",
            "last_line": "...이제 갈 수 있어?",
            "last_speaker": "주인공",
            # v62: p1/p2/p3_goal 추가 (inst 생성 시 기본값 대신 사용)
            "p1_goal": "배경 제시, 주인공 일상, 첫 이상 징후 발견",
            "p2_goal": "공포 고조, 진실에 접근, 탈출 시도 실패",
            "p3_goal": "반전 공개, 주인공 정체 드러남, 소름 엔딩",
        }

    def _pick_neighboring_cold_open_turn(
        self,
        script: List[Dict[str, Any]],
        anchor_index: int,
        topic: str = "",
    ) -> Optional[Dict[str, Any]]:
        total_turns = len(script)
        best_neighbor = None
        best_score = 0

        for offset in (-1, 1):
            idx = anchor_index + offset
            if idx < 0 or idx >= total_turns:
                continue
            turn = script[idx]
            score = _score_hook_turn(turn, idx, total_turns, topic=topic)
            if score > best_score:
                best_neighbor = turn
                best_score = score

        return best_neighbor if best_score >= 7 else None

    def _select_hook_text(
        self,
        topic: str,
        category: str,
        mode: str,
        cold_open: List[Dict[str, Any]],
        script_list: List[Dict[str, Any]],
    ) -> str:
        dramatic_turns = [turn for turn in (cold_open or []) if not turn.get("_is_bridge")]
        for turn in dramatic_turns:
            text = _normalize_hook_candidate(turn.get("text", ""))
            if text and not _is_weak_hook_candidate(text, topic=topic):
                return text

        scored_candidates = []
        for index, turn in enumerate(script_list or []):
            score = _score_hook_turn(turn, index, len(script_list or []), topic=topic)
            if score > 0:
                scored_candidates.append((score, turn))

        scored_candidates.sort(key=lambda item: item[0], reverse=True)
        for _, turn in scored_candidates[:5]:
            text = _normalize_hook_candidate(turn.get("text", ""))
            if text and not _is_weak_hook_candidate(text, topic=topic):
                return text

        generated_hook = _normalize_hook_candidate(self.pd.create_powerful_hook(topic, category, mode))
        if generated_hook and not _is_weak_hook_candidate(generated_hook, topic=topic):
            return generated_hook

        if scored_candidates:
            return _normalize_hook_candidate(scored_candidates[0][1].get("text", ""))

        return generated_hook or topic

    @staticmethod
    def _sanitize_cold_open_bridge(text: str) -> str:
        raw = _safe_strip(text or "")
        if not raw:
            return ""

        lowered = raw.lower()
        instruction_markers = (
            "write one", "rules:", "output:", "one korean sentence",
            "no markdown", "no quotes", "no numbering",
        )
        if any(marker in lowered for marker in instruction_markers):
            return ""

        lines = [line.strip().strip("-*•").strip() for line in raw.splitlines() if line.strip()]
        if not lines:
            return ""

        candidate = lines[0].strip("\"'[]() ")
        if not candidate or len(candidate) > 36:
            return ""
        if re.search(r"[A-Za-z]{4,}", candidate):
            return ""
        if candidate.endswith(":"):
            return ""
        return candidate

    def _resolve_cold_open_bridge_text(self, topic: str, cold_open_turns: List[Dict[str, Any]]) -> str:
        fallback_lines = [
            "모든 것은 그날로 거슬러 올라갑니다.",
            "진실은 생각보다 더 가까이에 있었습니다.",
            "그 순간의 대가는 오래 남아 있었습니다.",
            "그날의 선택은 아직 끝나지 않았습니다.",
        ]
        fallback = fallback_lines[abs(hash(topic or "reverie")) % len(fallback_lines)]

        prompt_template = get_prompt("cold_open_bridge") if PACK_CONFIG_AVAILABLE else ""
        direct_bridge = self._sanitize_cold_open_bridge(prompt_template)
        if direct_bridge:
            return direct_bridge

        prompt_template = _safe_strip(prompt_template)
        if not prompt_template:
            return fallback

        dramatic_lines = []
        for turn in cold_open_turns[:2]:
            role = turn.get("character", "") or turn.get("role", "대화")
            text = _normalize_hook_candidate(turn.get("text", ""))
            if text:
                dramatic_lines.append(f"- {role}: {text}")

        bridge_prompt = (
            f"{prompt_template}\n\n"
            f"주제: {topic}\n"
            f"콜드 오프닝 대사:\n{chr(10).join(dramatic_lines) or '- 없음'}\n"
        )

        try:
            gen_config = _make_generation_config(temperature=0.5, max_output_tokens=80)
            res = self.model.generate_content(bridge_prompt, timeout=45, generation_config=gen_config)
            candidate = self._sanitize_cold_open_bridge(getattr(res, "text", "") or "")
            if candidate:
                return candidate
        except Exception as exc:
            logger.warning(f"[콜드 오프닝] 브릿지 생성 실패, 기본 문장 사용: {exc}")

        return fallback

    def _extract_cold_open(self, script_list: List[Dict[str, Any]], topic: str = "") -> List[Dict[str, Any]]:
        """v61.1: 콜드 오프닝 추출 - 전체 대본에서 극적인 장면을 뽑아 영상 시작에 배치

        YouTube 콜드 오프닝 기법:
        - 영상 시작 5초 안에 클라이맥스 장면을 보여줌
        - "모든 것은 며칠 전으로 거슬러 올라갑니다" 브릿지 후 본편 시작
        - 시청자의 궁금증을 유발하여 이탈률 감소

        Args:
            script_list: 전체 대본 리스트 [{role, character, text, emotion}, ...]

        Returns:
            콜드 오프닝 턴 리스트 (1-2개 극적 대사 + 브릿지 나레이션)
            추출 실패 시 빈 리스트 반환
        """
        if not script_list or len(script_list) < 8:
            logger.warning("[콜드 오프닝] 대본이 너무 짧아 추출 불가")
            return []

        candidates = []
        total_turns = len(script_list)
        for i, turn in enumerate(script_list):
            score = _score_hook_turn(turn, i, total_turns, topic=topic)
            if score > 0:
                candidates.append((score, i, turn))

        if not candidates:
            logger.warning("[콜드 오프닝] 적합한 대사를 찾지 못함")
            return []

        candidates.sort(key=lambda x: x[0], reverse=True)
        cold_open_turns = []
        best = candidates[0]
        best_neighbor = self._pick_neighboring_cold_open_turn(script_list, best[1], topic=topic)

        if best_neighbor is not None:
            first_index = best[1] - 1 if script_list[best[1] - 1] is best_neighbor else best[1]
            ordered_turns = [script_list[first_index]]
            if first_index != best[1]:
                ordered_turns.append(best[2])
            else:
                ordered_turns.append(best_neighbor)
            for turn in ordered_turns[:2]:
                cold_open_turns.append({
                    "role": turn.get("role", "대화"),
                    "character": turn.get("character", "") or turn.get("role", "대화"),
                    "text": _normalize_hook_candidate(turn.get("text", "")),
                    "emotion": turn.get("emotion", ""),
                })
        else:
            cold_open_turns.append({
                "role": best[2].get("role", "대화"),
                "character": best[2].get("character", "") or best[2].get("role", "대화"),
                "text": _normalize_hook_candidate(best[2].get("text", "")),
                "emotion": best[2].get("emotion", ""),
            })

        cold_open_turns = [turn for turn in cold_open_turns if turn.get("text")]
        if not cold_open_turns:
            return []

        primary_text = cold_open_turns[0].get("text", "")
        if _is_weak_hook_candidate(primary_text, topic=topic) and len(candidates) > 1:
            alternate = candidates[1][2]
            cold_open_turns[0] = {
                "role": alternate.get("role", "대화"),
                "character": alternate.get("character", "") or alternate.get("role", "대화"),
                "text": _normalize_hook_candidate(alternate.get("text", "")),
                "emotion": alternate.get("emotion", ""),
            }

        bridge_text = self._resolve_cold_open_bridge_text(topic, cold_open_turns)
        cold_open_turns.append({
            "role": "나레이션",
            "character": "narrator",
            "text": bridge_text,
            "emotion": "calm",
            "_is_bridge": True,  # downstream에서 브릿지임을 식별
        })

        safe_print(f"   [콜드 오프닝] {len(cold_open_turns) - 1}개 극적 대사 + 브릿지 추출 완료")
        for ct in cold_open_turns:
            if not ct.get("_is_bridge"):
                safe_print(f"      [{ct['character']}] ({ct['emotion']}) \"{ct['text'][:30]}...\"")

        return cold_open_turns

    def get_auto_topic(self, category: str, mode: str = "") -> str:
        """v60: 모든 팩에서 유사도 체크 (장르 분기 제거)"""
        topic = "알 수 없는 이야기"
        for _ in range(3):
            topic = self.pd.create_topic(category, mode)
            if not self.memory.is_similar(topic):
                return topic
        return topic

    # v62: _validate_horror_script 삭제 — _local_validate()로 대체 (API 0회)

    def create_plan(self, category: str, mode: str, topic: str) -> Tuple[Dict[str, Any], str]:
        """v62: create_plan을 _execute_plan_with_bible의 래퍼로 축약.
        바이블+아웃라인을 통합 생성 후 _execute_plan_with_bible에 위임."""
        # v62: 진행률은 _execute_plan_with_bible에서 초기화 (이중 리셋 방지)
        self._ensure_active_pack(category, mode)

        # v62: 바이블+아웃라인 통합 생성 (1회 API)
        safe_print(f"   [v62] 스토리 블루프린트 생성 중... 주제: {topic[:30]}...")
        story_bible, story_outline = self._build_story_blueprint(topic, category, mode)

        # _execute_plan_with_bible에 위임 (코드 중복 제거)
        return self._execute_plan_with_bible(category, mode, topic, story_bible, story_outline)

    def create_horror_plan(self, topic: str):
        return self.create_plan("horror", "horror", topic)

    def create_senior_plan(self, topic: str, mode: str = "touching"):
        return self.create_plan("senior", mode, topic)

    # ============================================================
    # v57.0: PDCA 사이클 기반 대본 생성
    # ============================================================

    def create_plan_pdca(
        self,
        category: str,
        mode: str,
        topic: str,
        max_iterations: int = 3,
        quality_threshold: int = 80
    ) -> Tuple[Dict[str, Any], str]:
        """
        PDCA 사이클 기반 대본 생성

        bkit 스타일 E-O(Evaluator-Optimizer) 패턴 적용:
        1. Plan: 스토리바이블(설계 문서) 생성
        2. Do: 대본 작성
        3. Check: StoryCritic으로 품질 평가
        4. Act: 기준 미달 시 개선 후 재생성

        Args:
            category: 카테고리 ("horror", "senior")
            mode: 모드 ("horror", "touching", "makjang")
            topic: 주제
            max_iterations: 최대 반복 횟수 (기본 3회)
            quality_threshold: 합격 기준 점수 (기본 80점)

        Returns:
            (final_plan, json_path) 튜플
        """
        if not PDCA_AVAILABLE:
            safe_print("[PDCA] StoryCritic 미설치, 기존 create_plan 사용")
            return self.create_plan(category, mode, topic)

        safe_print(f"\n{'='*60}")
        safe_print(f"🔄 [PDCA] 품질 검증 모드 시작")
        safe_print(f"   주제: {topic}")
        safe_print(f"   최대 반복: {max_iterations}회 / 합격 기준: {quality_threshold}점")
        safe_print(f"{'='*60}\n")

        # StoryCritic 초기화
        critic = get_story_critic(threshold=quality_threshold)

        if not critic.is_available:
            safe_print("[PDCA] StoryCritic 사용 불가, 기존 방식 사용")
            return self.create_plan(category, mode, topic)

        # ========================================
        # Phase 1: Plan - 스토리바이블 생성 + 평가 루프
        # ========================================
        safe_print("📋 [Phase 1] Plan - 스토리바이블 생성 및 검증")

        story_bible = None
        story_outline = None  # v62: blueprint에서 생성된 아웃라인
        bible_score = 0
        last_evaluation = None  # v62.21 M-6: UnboundLocalError 방지

        for iteration in range(1, max_iterations + 1):
            safe_print(f"\n   [반복 {iteration}/{max_iterations}]")

            # v62: 스토리 블루프린트(바이블+아웃라인) 통합 생성 (또는 피드백 개선)
            if story_bible is None:
                story_bible, story_outline = self._build_story_blueprint(topic, category, mode)
                safe_print(f"   ✍️  스토리 블루프린트 생성 완료")
            else:
                # 이전 피드백 기반 개선 (blueprint 텍스트 전체 개선)
                # v62.21 M-6: last_evaluation None 가드
                feedback = last_evaluation.feedback if last_evaluation else "전반적으로 개선 필요"
                story_bible = self._improve_story_bible(
                    story_bible,
                    feedback,
                    category,
                    mode
                )
                safe_print(f"   🔧 스토리바이블 개선 완료")

            # 평가
            safe_print(f"   🔍 StoryCritic 평가 중...")
            last_evaluation = critic.evaluate_story_bible(story_bible, category)
            bible_score = last_evaluation.score

            safe_print(f"   📊 평가 결과: {bible_score}점 {'✅ 합격' if last_evaluation.passed else '❌ 미달'}")

            if last_evaluation.passed:
                safe_print(f"   🎉 스토리바이블 품질 검증 통과!")
                break

            if iteration < max_iterations:
                safe_print(f"   💡 피드백: {last_evaluation.feedback[:100]}...")

        # ========================================
        # Phase 2: Do - 대본 생성
        # ========================================
        safe_print(f"\n📝 [Phase 2] Do - 대본 생성")
        safe_print(f"   스토리바이블 점수: {bible_score}점")

        # v62: 기존 create_plan 로직 재사용 (스토리바이블+아웃라인 이미 생성됨)
        final_plan, json_path = self._execute_plan_with_bible(
            category, mode, topic, story_bible, story_outline
        )

        # ========================================
        # Phase 3: Check - 대본 품질 평가
        # ========================================
        safe_print(f"\n🔍 [Phase 3] Check - 최종 대본 평가")

        script_evaluation = critic.evaluate_script(
            final_plan.get("script_list", []),
            category
        )

        safe_print(f"   📊 대본 점수: {script_evaluation.score}점")
        if script_evaluation.details:
            for key, value in script_evaluation.details.items():
                if isinstance(value, (int, float)):
                    safe_print(f"      - {key}: {value}점")

        # ========================================
        # Phase 4: Act - PDCA 로그 저장
        # ========================================
        pdca_log = {
            "version": "v57.0",
            "topic": topic,
            "category": category,
            "mode": mode,
            "story_bible": {
                "iterations": iteration,
                "final_score": bible_score,
                "passed": last_evaluation.passed
            },
            "script": {
                "score": script_evaluation.score,
                "passed": script_evaluation.passed,
                "details": script_evaluation.details
            },
            "timestamp": datetime.now().isoformat()
        }

        # PDCA 로그를 plan에 추가
        final_plan["pdca_log"] = pdca_log

        # JSON 다시 저장
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(final_plan, f, ensure_ascii=False, indent=4)

        safe_print(f"\n{'='*60}")
        safe_print(f"✅ [PDCA] 완료")
        safe_print(f"   스토리바이블: {bible_score}점 ({iteration}회 반복)")
        safe_print(f"   최종 대본: {script_evaluation.score}점")
        safe_print(f"{'='*60}\n")

        return final_plan, json_path

    def _improve_story_bible(
        self,
        bible: str,
        feedback: str,
        category: str,
        mode: str
    ) -> str:
        """
        피드백 기반 스토리바이블 개선

        Args:
            bible: 기존 스토리바이블
            feedback: 평가 피드백
            category: 카테고리
            mode: 모드

        Returns:
            개선된 스토리바이블
        """
        # v60: 팩에서 story_bible_improve 프롬프트 로딩 (장르 분기 제거)
        improve_template = get_prompt("story_bible_improve") if PACK_CONFIG_AVAILABLE else ""

        if improve_template:
            # 팩 프롬프트에 {bible}과 {feedback} 플레이스홀더 치환
            prompt = improve_template
            # v61: 팩 프롬프트는 {{...}} 이중 중괄호 사용 (f-string 안전)
            prompt = prompt.replace("{{bible}}", bible).replace("{{feedback}}", feedback)
        else:
            # 폴백: 범용 프롬프트 (장르명 없이)
            prompt = f"""
You are a veteran drama producer with 20+ years of experience.
Improve the story bible below based on the provided feedback.

[Current Story Bible]
{bible}

[Feedback]
{feedback}

[Instructions]
- Fix the specific issues raised in the feedback
- Preserve the existing overall structure — only strengthen the weak points
- Output as a numbered list, concise and actionable
- Write the improved story bible in Korean
"""

        gen_config = _make_generation_config(
            temperature=0.85,
            top_p=0.92,
        )

        try:
            res = self.model.generate_content(prompt, generation_config=gen_config)
            improved = _safe_strip((getattr(res, "text", "") or ""))
            if improved:
                return improved
        except Exception as e:
            safe_print(f"   ⚠️ 개선 실패: {e}")

        return bible  # 실패 시 원본 반환

    def _execute_plan_with_bible(
        self,
        category: str,
        mode: str,
        topic: str,
        story_bible: str,
        story_outline: Dict = None
    ) -> Tuple[Dict[str, Any], str]:
        """
        v62: 이미 생성된 스토리바이블+아웃라인으로 대본 생성

        Args:
            category: 카테고리
            mode: 모드
            topic: 주제
            story_bible: 검증된 스토리바이블 (blueprint에서 생성)
            story_outline: 구조 아웃라인 dict (blueprint에서 생성, None이면 레거시 경로)

        Returns:
            (final_plan, json_path) 튜플
        """
        # v32: 진행률 초기화 (총 10단계)
        progress_callback.set_total_steps(10)
        progress_callback.reset()

        # v50: 테스트 모드
        is_test_mode = config.TEST_MODE
        if is_test_mode:
            safe_print(f"\n[TEST MODE] 테스트 모드 활성화")
            turns_per_part = config.TEST_TURNS_PER_PART
            num_images = config.TEST_IMAGE_COUNT
        else:
            # v61.1 (#61): get_content_settings()에서 turns_per_part 로딩 (하드코딩 제거)
            turns_per_part = 45  # 기본값
            if PACK_CONFIG_AVAILABLE:
                try:
                    _cs = get_content_settings()
                    if _cs and hasattr(_cs, 'min_turns') and _cs.min_turns and _cs.min_turns > 0:
                        turns_per_part = _cs.min_turns
                except Exception:
                    pass
            total_turns = turns_per_part * 3
            num_images = max(30, min(60, total_turns // 2))

        # v62: story_outline이 없으면 레거시 폴백 (아웃라인 별도 생성)
        if story_outline is None:
            structural_outline_prompt = get_prompt("structural_outline") if PACK_CONFIG_AVAILABLE else ""
            if structural_outline_prompt:
                progress_callback.update("구조 아웃라인 설계 (레거시)", "반전/복선/구조 설계 중")
                story_outline = self._generate_horror_outline_legacy(topic)
                if story_outline:
                    outline_str = json.dumps(story_outline, ensure_ascii=False)
                    story_bible = f"{story_bible}\n\n[구조 아웃라인]\n{outline_str}"

        forbid_common = """
- 이전 파트에 이미 있는 사건을 '처음부터 다시' 설명하지 마라.
- 이미 해결된 갈등을 다시 같은 방식으로 반복하지 마라.
- 뜬금없는 새 주인공/새 세계관을 추가하지 마라.
- 작가1/2는 결말(완전 해결/화해/용서/응징 확정)을 내지 마라.
- 선정적 묘사/노출/폭력/유혈/혐오/차별은 금지.
"""

        t1, t2, t3 = turns_per_part, turns_per_part, turns_per_part

        inst1, inst2, inst3 = resolve_part_instructions(story_outline)

        # v59.5.17: fallback 감지
        def _is_fallback_script(part: list) -> bool:
            if not part:
                return True
            fb_count = sum(1 for t in part if t.get("_is_fallback"))
            return fb_count > len(part) * 0.5

        # 비상 템플릿은 계획 생성 단계에서 즉시 차단한다.
        def _write_with_retry(writer, label, target_t, prev_context, inst, forbidden):
            role_name_map = {
                "Part 1": "작가1(빌드업)",
                "Part 2": "작가2(위기)",
                "Part 3": "작가3(결말)",
                "Part 3 retry": "작가3(결말)",
            }
            role_name = role_name_map.get(label, getattr(writer, "role_name", label))
            progress_callback.update(f"대본 {label} 집필", f"{role_name} 집필 중")
            result = self._write_story_part(
                writer, role_name, topic, category, mode, target_t, story_bible, prev_context, inst, forbidden
            )
            if _is_fallback_script(result):
                turn_count = len(result) if isinstance(result, list) else 0
                logger.error(f"[v62][{label}] 비상 템플릿 감지 — 계획 생성 중단 ({turn_count}턴)")
                safe_print(f"   ❌ [{label}] 비상 템플릿 감지 — 계획 생성 중단")
                raise FallbackScriptError(label, turn_count)
            return result

        # === Part 1 ===
        p1 = _write_with_retry(
            self.writer1, "Part 1", t1,
            "없음(시작)", inst1,
            forbid_common + "\n- '완전한 마무리' 같은 문장 금지.\n"
        )

        # Claude 단일 작가 모드는 컨텍스트를 압축해 토큰 비용과 timeout 리스크를 줄인다.
        p1_context = self._format_script_as_context(
            p1,
            compact=self.single_writer_mode,
            max_key_turns=30 if self.single_writer_mode else 22,
        )

        # === Part 2 ===
        p2 = _write_with_retry(
            self.writer2, "Part 2", t2,
            p1_context, inst2,
            forbid_common + "\n- 위기를 '해결'하지 말고, 해결 직전까지 몰아가라.\n"
        )

        # v62.2: P1+P2를 P3에 압축 전달 — JSON 잘림 방지 (API 0회)
        # compact=True: 핵심 턴만 원문, 나머지 1줄 요약 (70턴→~25줄, 14K→4K chars)
        p1p2_context = self._format_script_as_context(
            p1 + p2,
            compact=True,
            max_key_turns=26 if self.single_writer_mode else 22,
        )

        # === Part 3 ===
        p3 = _write_with_retry(
            self.writer3, "Part 3", t3,
            p1p2_context, inst3,
            "- 뜬금없는 설정 추가 금지.\n- 결말에서만 반전을 확정.\n"
        )

        # v59.5.17: _is_fallback 마킹 제거
        full_script = []
        for turn in (p1 + p2 + p3):
            clean = {k: v for k, v in turn.items() if k != "_is_fallback"}
            full_script.append(clean)

        # v62: 로컬 검증 (API 0회) — _validate_horror_script 대체
        _p1p2_size = len(p1) + len(p2)
        warnings, critical = self._local_validate(full_script, story_outline)
        if warnings:
            for w in warnings:
                safe_print(f"   ⚠️ [로컬 검증] {w}")

        # v62: critical이면 P3만 1회 재시도
        if critical:
            safe_print(f"   🔄 [로컬 검증] 치명적 위반 — P3 1회 재시도")
            retry_p3 = self._write_story_part(
                self.writer3, "작가3(결말)", topic, category, mode, t3, story_bible, p1p2_context, inst3,
                "- 뜬금없는 설정 추가 금지.\n- 결말에서만 반전을 확정.\n"
            )
            if retry_p3 and not _is_fallback_script(retry_p3):
                # 재시도 P3로 교체
                full_script = []
                for turn in (p1 + p2 + retry_p3):
                    clean = {k: v for k, v in turn.items() if k != "_is_fallback"}
                    full_script.append(clean)
                p3 = retry_p3
                safe_print(f"   ✅ P3 재시도 성공 ({len(retry_p3)}턴)")
            else:
                retry_turns = len(retry_p3) if isinstance(retry_p3, list) else 0
                safe_print(f"   ❌ P3 재시도 실패 — 비상 템플릿/무효 결과 감지")
                raise FallbackScriptError("Part 3 retry", retry_turns)

        # v61.1 (#52): 콜드 오프닝 — 검증 후 full_script에서 p3 재추출
        validated_p3 = full_script[_p1p2_size:] if len(full_script) > _p1p2_size else []

        try:
            quality_report = assert_script_quality(topic, full_script, category=category, mode=mode)
            safe_print(f"   ✅ [품질 게이트] 통과 (score={quality_report.score})")
        except ScriptQualityError as e:
            quality_report = e.report
            if config.TEST_MODE:
                safe_print(f"   ⚠️ [품질 게이트] 테스트 모드 경고 — {quality_report.summary()}")
            else:
                safe_print(f"   ❌ [품질 게이트] 실패 — {quality_report.summary()}")
                raise

        # BUG-C 방어: 비상 템플릿 p3에서는 콜드 오프닝 추출 스킵
        p3_is_fallback = any(t.get("_is_fallback") for t in p3) if p3 else False
        cold_open = []
        if p3_is_fallback:
            safe_print(f"   [콜드 오프닝] Part 3이 비상 템플릿 - 추출 스킵")
        else:
            progress_callback.update("콜드 오프닝 추출", "클라이맥스 장면 선별 중")
            cold_open = self._extract_cold_open(full_script, topic=topic)
            if cold_open:
                safe_print(f"   [콜드 오프닝] {len(cold_open)}턴 추출 성공")
            else:
                safe_print(f"   [콜드 오프닝] 추출 실패 - 대본 기반 훅으로 대체")

        hook_msg = self._select_hook_text(topic, category, mode, cold_open, full_script)

        progress_callback.update("메타데이터 생성", "제목/태그/설명 작성 중")
        meta = self.pd.package_content(topic, full_script, category, mode)
        shorts_plan = normalize_shorts_plan(
            meta.get("shorts"),
            topic=topic,
            hook=hook_msg,
            cold_open=cold_open,
            tags=meta.get("tags", []),
        )
        motiontoon_plan = None
        try:
            motiontoon_config = get_motiontoon_config() if PACK_CONFIG_AVAILABLE else {}
            motiontoon_plan = build_motiontoon_plan(
                full_script,
                cold_open=cold_open,
                config=motiontoon_config,
            )
        except Exception as e:
            logger.warning(f"[ScenarioPlanner] motiontoon_plan 생성 실패 (무시): {e}")
            motiontoon_plan = None

        progress_callback.update("이미지 프롬프트 생성", f"{num_images}장 이미지 구상 중")
        visual_scenes = self.visual_director.create_scenes(
            topic, category, mode, full_script, num_images=num_images
        )
        visual_scenes = _attach_motion_beats_to_visual_scenes(visual_scenes, motiontoon_plan)

        # v57.7.6: mode에 슬래시 등 특수문자가 있을 수 있어 sanitize 적용
        safe_mode = _sanitize_for_path(mode)
        project_name = f"{category.capitalize()}_{safe_mode}_{_now_id()}"
        final_plan = build_final_plan(
            project_name=project_name,
            category=category,
            mode=mode,
            topic=topic,
            story_bible=story_bible,
            meta=meta,
            hook=hook_msg,
            cold_open=cold_open,
            script_list=full_script,
            visual_scenes=visual_scenes,
            quality_gate=quality_report.to_dict(),
            story_outline=story_outline,
            shorts_plan=shorts_plan,
            motiontoon_plan=motiontoon_plan,
        )

        try:
            self.memory.push(topic, story_bible)
        except Exception as e:
            logger.warning(f"[ScenarioPlanner] 메모리 push 실패 (무시): {e}")

        progress_callback.update("완료", f"대본 {len(full_script)}턴, 이미지 {len(visual_scenes)}장")
        return final_plan, self._save_to_json(final_plan)

    def create_horror_plan_pdca(self, topic: str, max_iterations: int = 3) -> Tuple[Dict[str, Any], str]:
        """PDCA 기반 공포 대본 생성"""
        return self.create_plan_pdca("horror", "horror", topic, max_iterations)

    def create_senior_plan_pdca(self, topic: str, mode: str = "touching", max_iterations: int = 3) -> Tuple[Dict[str, Any], str]:
        """PDCA 기반 시니어 대본 생성"""
        return self.create_plan_pdca("senior", mode, topic, max_iterations)

    def _save_to_json(self, data: Dict[str, Any]) -> str:
        path = os.path.join(config.DATA_DIR, "scripts", f"{data['project_name']}.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        return path

    # ============================================================
    # v32: 대본 분석/미리보기/수정 기능
    # ============================================================

    def analyze_script(self, script_list: List[Dict[str, Any]] = None, plan_path: str = None) -> Dict[str, Any]:
        """
        대본 분석 및 통계 반환

        Args:
            script_list: 대본 리스트 (직접 전달)
            plan_path: JSON 파일 경로 (파일에서 로드)

        Returns:
            분석 결과 딕셔너리
        """
        if plan_path:
            with open(plan_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            script_list = data.get("script_list", [])

        if not script_list:
            return {"error": "대본을 제공하세요."}

        return self.analyzer.analyze(script_list)

    def preview_script(self, script_list: List[Dict[str, Any]] = None, plan_path: str = None,
                       start: int = 0, count: int = 20) -> str:
        """
        대본 미리보기 (포맷팅된 문자열 반환)

        Args:
            script_list: 대본 리스트
            plan_path: JSON 파일 경로
            start: 시작 인덱스
            count: 가져올 개수

        Returns:
            포맷팅된 대본 문자열
        """
        if plan_path:
            with open(plan_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            script_list = data.get("script_list", [])

        if not script_list:
            return "대본이 비어있습니다."

        preview = self.analyzer.get_preview(script_list, start, count)
        return self.analyzer.format_for_display(preview)

    def edit_script_turn(self, plan_path: str, index: int,
                         text: str = None, role: str = None, emotion: str = None) -> str:
        """
        대본의 특정 턴 수정 후 저장

        Args:
            plan_path: JSON 파일 경로
            index: 수정할 인덱스
            text: 새 텍스트
            role: 새 역할
            emotion: 새 감정

        Returns:
            수정된 파일 경로
        """
        with open(plan_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        script_list = data.get("script_list", [])
        script_list = self.editor.edit_turn(script_list, index, text, role, emotion)
        data["script_list"] = script_list

        with open(plan_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

        return plan_path

    def insert_script_turn(self, plan_path: str, index: int,
                           text: str, role: str = "narrator", emotion: str = "calm") -> str:
        """
        대본에 새 턴 삽입 후 저장

        Args:
            plan_path: JSON 파일 경로
            index: 삽입할 위치
            text: 텍스트
            role: 역할
            emotion: 감정

        Returns:
            수정된 파일 경로
        """
        with open(plan_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        script_list = data.get("script_list", [])
        script_list = self.editor.insert_turn(script_list, index, text, role, emotion)
        data["script_list"] = script_list

        with open(plan_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

        return plan_path

    def delete_script_turn(self, plan_path: str, index: int) -> str:
        """
        대본의 특정 턴 삭제 후 저장

        Args:
            plan_path: JSON 파일 경로
            index: 삭제할 인덱스

        Returns:
            수정된 파일 경로
        """
        with open(plan_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        script_list = data.get("script_list", [])
        script_list = self.editor.delete_turn(script_list, index)
        data["script_list"] = script_list

        with open(plan_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

        return plan_path

    def regenerate_part(self, plan_path: str, part: int = 3) -> str:
        """
        대본의 특정 파트만 재생성

        Args:
            plan_path: JSON 파일 경로
            part: 재생성할 파트 (1, 2, 3)

        Returns:
            수정된 파일 경로
        """
        with open(plan_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        topic = data.get("topic", "")
        category = data.get("category", "horror")
        mode = data.get("mode", "")
        story_bible = data.get("story_bible", "")
        script_list = data.get("script_list", [])

        # v61.1 (#51): 동적 파트 크기 — 실제 대본 길이 기반 (50턴 하드코딩 제거)
        total_len = len(script_list)
        part_size = max(1, total_len // 3) if total_len > 0 else 45
        p1 = script_list[:part_size]
        p2 = script_list[part_size:part_size*2]
        p3 = script_list[part_size*2:]

        forbid_common = """
- 이전 요약에 이미 있는 사건을 '처음부터 다시' 설명하지 마라.
- 선정적 묘사/노출/폭력/유혈/혐오/차별은 금지.
"""

        if part == 1:
            progress_callback.set_total_steps(1)
            progress_callback.reset()
            progress_callback.update("Part 1 재생성", "작가1(빌드업) 재집필 중")
            p1 = self._write_story_part(
                self.writer1, "작가1(빌드업)", topic, category, mode, part_size, story_bible, "없음(시작)",
                "이야기 시작. 배경/인물/초기 갈등 제시.",
                forbid_common
            )
        elif part == 2:
            # v62: 요약 대신 원문 컨텍스트 전달
            p1_ctx = self._format_script_as_context(p1)
            progress_callback.set_total_steps(1)
            progress_callback.reset()
            progress_callback.update("Part 2 재생성", "작가2(위기) 재집필 중")
            p2 = self._write_story_part(
                self.writer2, "작가2(위기)", topic, category, mode, part_size, story_bible, p1_ctx,
                "사건 본격화. 갈등/공포 폭발. 위기 고조.",
                forbid_common
            )
        elif part == 3:
            # v62.2: P3에는 압축 컨텍스트 전달 (JSON 잘림 방지)
            p1p2_ctx = self._format_script_as_context(p1 + p2, compact=True)
            progress_callback.set_total_steps(1)
            progress_callback.reset()
            progress_callback.update("Part 3 재생성", "작가3(결말) 재집필 중")
            p3 = self._write_story_part(
                self.writer3, "작가3(결말)", topic, category, mode, part_size, story_bible, p1p2_ctx,
                "반전과 결말. 떡밥 회수.",
                forbid_common
            )

        data["script_list"] = p1 + p2 + p3

        with open(plan_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

        return plan_path

    def get_analysis_summary(self, plan_path: str) -> str:
        """
        분석 결과를 사람이 읽기 쉬운 문자열로 반환

        Args:
            plan_path: JSON 파일 경로

        Returns:
            분석 요약 문자열
        """
        analysis = self.analyze_script(plan_path=plan_path)

        if "error" in analysis:
            return f"오류: {analysis['error']}"

        summary = analysis.get("summary", {})
        roles = analysis.get("role_distribution", {})
        emotions = analysis.get("emotion_distribution", {})
        quality = analysis.get("quality_checks", {})

        lines = [
            "=" * 50,
            "📊 대본 분석 결과",
            "=" * 50,
            "",
            "📝 기본 정보:",
            f"   - 총 턴 수: {summary.get('total_turns', 0)}턴",
            f"   - 총 글자 수: {summary.get('total_characters', 0):,}자",
            f"   - 예상 영상 길이: {summary.get('estimated_duration_min', 0)}분",
            f"   - 평균 대사 길이: {summary.get('avg_text_length', 0)}자",
            "",
            "👥 역할 분포:",
        ]

        for role, pct in roles.get("percentages", {}).items():
            emoji = {"narrator": "📖", "grandma": "👵", "grandpa": "👴", "man": "👨", "woman": "👩"}.get(role, "👤")
            lines.append(f"   {emoji} {role}: {pct}%")

        lines.append("")
        lines.append("😊 감정 분포:")

        for emotion, pct in emotions.get("percentages", {}).items():
            # v56.8: Qwen3-TTS 7가지 감정 이모지
            emoji = {
                "calm": "😐", "happy": "😊", "sad": "😢", "angry": "😠",
                "scared": "😨", "excited": "🤩", "whisper": "🤫"
            }.get(emotion, "😐")
            lines.append(f"   {emoji} {emotion}: {pct}%")

        lines.append("")
        lines.append(f"📈 감정 흐름: {' → '.join(emotions.get('flow', []))}")

        lines.append("")
        if quality.get("is_healthy"):
            lines.append("✅ 품질 상태: 양호")
        else:
            lines.append("⚠️ 품질 상태: 개선 필요")

        if quality.get("warnings"):
            lines.append("")
            lines.append("⚠️ 경고:")
            for w in quality["warnings"]:
                lines.append(f"   - {w}")

        lines.append("")
        lines.append("=" * 50)

        return "\n".join(lines)
