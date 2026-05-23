# src/modules_pro/script_writers.py
# ============================================================
# v56.1: 대본 작성 클래스 모음
# scenario_planner.py에서 분리
# ============================================================
import re
import json
import time
import random
import logging
from typing import Dict, List, Any, Optional, Tuple

from config.settings import config

class _GenerationConfigCompat:
    """
    v59.5.5: genai.GenerationConfig 호환 래퍼
    구 SDK 객체 없이도, model이 GeminiWrapper일 때도 동작
    GeminiWrapper.generate_content()에서 이 객체를 자동 변환함
    """
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)
        self._kwargs = kwargs

    def to_dict(self):
        return dict(self._kwargs)

    def __repr__(self):
        return f"GenerationConfigCompat({self._kwargs})"


def _make_generation_config(**kwargs):
    """
    Gemini 호환 래퍼용 설정 객체 생성.
    """
    return _GenerationConfigCompat(**kwargs)


def _get_story_provider() -> str:
    provider = (getattr(config, "STORY_LLM_PROVIDER", "") or "").strip().lower()
    return "claude_cli" if provider == "claude" else provider


def _resolve_story_timeout(target_turns: int) -> int:
    provider = _get_story_provider()
    configured = int(getattr(config, "STORY_LLM_TIMEOUT_SEC", 600) or 600)
    per_turn_multiplier = 10 if provider == "claude_cli" else 3
    # Claude CLI is still slower than direct API calls, but a flat 15-minute floor
    # makes short script parts look frozen in production.
    provider_floor = 360 if provider == "claude_cli" else 120
    dynamic_timeout = max(provider_floor, target_turns * per_turn_multiplier)
    return max(dynamic_timeout, configured)

# 로거 설정
try:
    from utils.logger import get_logger
    logger = get_logger("script_writers")
except ImportError:
    logger = logging.getLogger("script_writers")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter('[%(levelname)s] %(name)s: %(message)s'))
        logger.addHandler(handler)

# 유틸리티 import
from modules_pro.script_utils import safe_print, _safe_strip

# v57.7.0: 팩 기반 프롬프트 시스템
# v57.7.5: 감정 설정 함수 추가
try:
    from config.pack_config import (
        ACTIVE_PACK, get_prompt, get_character_config,
        get_allowed_emotions, get_emotion_policy, get_emotion_correction_targets,
        get_emergency_sequence,  # v61: 비상 시퀀스 모듈 레벨 import
    )
    PACK_CONFIG_AVAILABLE = True
except ImportError:
    PACK_CONFIG_AVAILABLE = False

# v57.2 Hotfix: TTS 어댑터에서 감정 정규화 함수 재사용 (DRY 원칙)
# v57.3.0: tts_qwen3_adapter import 실패 시 로컬 폴백 사용
try:
    from modules_pro.tts_qwen3_adapter import normalize_emotion
except ImportError:
    # v57.6.2: Qwen3 비활성화 시 로컬 폴백 (10가지 감정 확장, v62.4: warm 추가)
    SUPPORTED_EMOTIONS = {"sad", "angry", "scared", "happy", "calm", "excited", "whisper", "worried", "desperate", "warm"}
    EMOTION_FALLBACK_MAP = {
        "neutral": "calm", "normal": "calm", "default": "calm",
        "fear": "scared", "afraid": "scared", "terrified": "scared",
        "joy": "happy", "joyful": "happy", "cheerful": "happy",
        "anxiety": "worried", "nervous": "worried", "tense": "worried", "uneasy": "worried",
        "quiet": "whisper", "soft": "whisper",
        "pleading": "desperate", "begging": "desperate", "hopeless": "desperate",
        "tender": "warm", "loving": "warm", "affectionate": "warm", "heartwarming": "warm", "gentle": "warm",
    }
    def normalize_emotion(emotion: str) -> str:
        if not emotion:
            return "calm"
        e = emotion.lower().strip()
        if e in SUPPORTED_EMOTIONS:
            return e
        return EMOTION_FALLBACK_MAP.get(e, "calm")


# ============================================================
# JSON 파싱 헬퍼 (scenario_planner.py의 로컬 함수)
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
    try:
        return json.loads(text)
    except Exception:
        pass

    # v61: 불완전 JSON 복구 — Gemini가 target_turns 중간에 끊긴 경우
    # script_list 배열에서 마지막 완전한 객체까지 잘라서 파싱 시도
    if text and '"script_list"' in text:
        try:
            # 마지막 완전한 }를 찾아서 배열 닫기
            last_complete = text.rfind('"sfx_tag"')
            if last_complete == -1:
                last_complete = text.rfind('"emotion"')
            if last_complete > 0:
                # 그 뒤의 첫 번째 }를 찾아서 객체 닫기
                close_obj = text.find("}", last_complete)
                if close_obj > 0:
                    truncated = text[:close_obj + 1] + "]}"
                    result = json.loads(truncated)
                    # v61.1-fix(#14): 마지막 턴 유효성 검증 (불완전 턴 제거)
                    sl = result.get("script_list", [])
                    if sl:
                        last_turn = sl[-1]
                        if not last_turn.get("text") or not last_turn.get("role"):
                            sl.pop()  # 불완전한 마지막 턴 제거
                            result["script_list"] = sl
                    n = len(result.get("script_list", []))
                    logger.warning(f"[JSON복구] 불완전 JSON 복구 성공: {n}턴 (원본 잘림)")
                    return result
        except Exception:
            pass

    return default


# ============================================================
# v62.4: 한국어 이름 → voice_type 추론
# ============================================================
def _infer_voice_type_from_korean_name(name: str) -> str:
    """한국어 캐릭터 이름에서 성별/연령대를 추론하여 voice_type 반환.

    Gemini가 '수진', '미지의 목소리' 같은 창작 이름을 쓸 때,
    hardcoded role_to_voice_type에 없는 이름도 voice_type을 매핑.

    Returns: voice_type str or "" if cannot infer
    """
    if not name:
        return ""

    name = name.strip()

    # 특수 패턴 (나레이션 변형, 미지의 목소리, 불명 등)
    narrator_patterns = ("미지", "목소리", "전화", "방송", "안내", "...")
    for p in narrator_patterns:
        if p in name:
            return "narrator"

    # 관계 키워드로 추론 (이름에 관계가 포함된 경우: "수진 엄마", "철수의 아내")
    # v62.10: man/woman → young_man/young_woman 전면 통일
    # 며느리(20-30대 여성)/사위(20-30대 남성)도 young_man/young_woman이 올바름
    relation_map = {
        "엄마": "middle_woman", "어머니": "middle_woman", "아내": "middle_woman",
        "이모": "middle_woman", "며느리": "young_woman", "아줌마": "middle_woman",
        "아빠": "middle_man", "아버지": "middle_man", "남편": "middle_man",
        "삼촌": "middle_man", "아저씨": "middle_man", "사위": "young_man",
        "할머니": "grandma", "할매": "grandma", "외할머니": "grandma",
        "할아버지": "grandpa", "할배": "grandpa", "외할아버지": "grandpa",
        "아들": "young_man", "딸": "young_woman", "오빠": "young_man", "언니": "young_woman",
        "형": "young_man", "누나": "young_woman", "동생": "young_man",
    }
    for keyword, vt in relation_map.items():
        if keyword in name:
            return vt

    # 한국어 2-3글자 이름에서 끝 글자로 성별 추론
    # 한글만 추출
    hangul_only = re.sub(r'[^가-힣]', '', name)
    if len(hangul_only) < 2:
        return ""

    last_char = hangul_only[-1]

    # 여성 이름에 자주 쓰이는 끝 글자
    female_endings = set("진희은미아영숙순자연정혜선화지현윤서린나")
    # 남성 이름에 자주 쓰이는 끝 글자
    male_endings = set("수철호준혁민석우성태훈규빈환원근")

    # v62.10: man/woman → young_man/young_woman (이름 추론은 창작 캐릭터 = 주로 청년층)
    if last_char in female_endings:
        return "young_woman"
    elif last_char in male_endings:
        return "young_man"

    return ""


# ============================================================
# v37: 프롬프트 모드 Enum
# ============================================================
class PromptMode:
    CLASSIC = "classic"      # 기존 프롬프트
    ENHANCED = "enhanced"    # 개선 프롬프트


# ============================================================
# 대본 작가 클래스
# ============================================================
class ScriptWriter:
    # v62.21 M-2: voice_metadata.json 캐시 (매 호출마다 파일 재읽기 방지)
    _voice_types_cache: Optional[set] = None

    def __init__(self, model, role_name: str):
        self.model = model
        self.role_name = role_name

    @staticmethod
    def _role_rule() -> str:
        # v57.1: role = 캐릭터 이름, voice_type = 음성 타입으로 변경
        # v57.2: 하이브리드 TTS 감정 가이드라인 추가
        # v57.6.5: sfx_tag 추가 (효과음 자동 삽입용)
        # v57.6.7: 캐릭터 이름 규칙 추가 (voice_type 매핑 보장)
        # v57.7.6: 팩의 character_config 기반 캐릭터 강제

        # 팩 캐릭터 설정 로드
        pack_character_rule = ""
        if PACK_CONFIG_AVAILABLE and ACTIVE_PACK.is_loaded:
            char_config = get_character_config()
            if char_config:
                # 팩에 정의된 캐릭터만 사용하도록 강제
                char_list = list(char_config.keys())
                voice_types_used = set(char_config.values())
                pack_character_rule = f"""
[★★★ 팩 캐릭터 강제 규칙 - 반드시 준수! ★★★]
이 팩에서 사용 가능한 캐릭터/역할은 아래 목록으로 제한됩니다:
- {', '.join(char_list)}

★ 위 목록에 없는 캐릭터 이름은 절대 사용 금지! (예: "???" , "괴물", "원혼", "유령" 등 사용 금지)
★ 새로운 캐릭터가 필요하면 위 목록 중 적절한 것을 선택하세요.
★ 귀신/괴물/미지의 존재가 말을 해야 할 때는 "나레이션"으로 처리하세요.
"""
                logger.info(f"[ScriptWriter] 팩 캐릭터 규칙 적용: {char_list}")

        # v59.5.12: middle_man/middle_woman 추가, man/woman을 청년으로 재정의
        base_rule = """
[ROLE & VOICE_TYPE RULE - 중요!]
- role: 캐릭터 이름 또는 "나레이션"
- voice_type: 반드시 아래 9개 중 하나만 사용:
  "narrator"      - 나레이션 전용 (30-40대 남성 나레이터)
  "man"           - 청년 남성 (20-30대)
  "woman"         - 청년 여성 (20-30대)
  "middle_man"    - 중년 남성 (40-50대)
  "middle_woman"  - 중년 여성 (40-50대)
  "grandpa"       - 할아버지 (70대 이상)
  "grandma"       - 할머니 (70대 이상)
  "young_man"     - "man"과 동일 (호환용 별칭)
  "young_woman"   - "woman"과 동일 (호환용 별칭)

★ 나이대 구분이 매우 중요합니다!
  - 20-30대 청년 → man / woman
  - 40-50대 중년 → middle_man / middle_woman
  - 70대+ 노인 → grandpa / grandma

[캐릭터 이름 규칙 - 필수!]
★ 캐릭터 이름은 반드시 성별을 알 수 있는 일반적인 한국 이름을 사용하세요.
★ 지명, 별명, 추상적 이름 금지! (예: "서울", "그림자", "목소리" 등 사용 금지)
★ 괴물, 유령, ???, 원혼 등 비현실적 존재는 role로 사용 금지!

남성 캐릭터 이름 예시:
- 청년 남성(man): 민혁, 지훈, 태준, 성우, 준호, 현우, 도윤, 시우
- 중년 남성(middle_man): 철수, 영수, 민수, 성호, 재호, 동수, 기철, 상철
- 할아버지(grandpa): 할아버지, 영감님, 노인

여성 캐릭터 이름 예시:
- 청년 여성(woman): 지우, 서연, 민지, 하은, 소희, 예린, 유나, 수아
- 중년 여성(middle_woman): 영희, 순자, 미숙, 정숙, 은주, 미선, 수진, 민주
- 할머니(grandma): 할머니, 할매, 노파

- 나레이션의 voice_type은 반드시 "narrator"
- 등장인물의 voice_type은 캐릭터 나이/성별에 맞게 선택

[EMOTION GUIDELINE - v57.7.6 팩 감정 연동]
- narrator(나레이션): 무조건 'calm'으로 고정하십시오. (TTS 품질 최적화)
- 모든 캐릭터: 팩에서 허용된 감정만 사용하십시오.
- 허용되지 않은 감정은 대본 검증에서 자동 변환됩니다.

[SFX TAG RULE - v57.6.5 효과음 자동 삽입]
- sfx_tag: 효과음이 필요한 순간에만 태그를 지정 (선택사항, 없으면 "" 또는 생략)
- 과도한 사용 금지! 전체 대본의 10~15% 턴에만 sfx_tag를 넣으세요.
- 사용 가능한 태그:
  [공포 계열]
  "tension"     - 긴장감 고조 (배경 드론음)
  "heartbeat"   - 심장 박동 (두려움/불안)
  "suspense"    - 서스펜스 (무언가 일어날 것 같을 때)
  "jumpscare"   - 점프 스케어 (갑작스러운 충격) ★영상당 1~2회만!
  "whisper"     - 속삭임/유령 등장
  "footsteps"   - 발자국 소리 (누군가 다가옴)
  "door"        - 문 열림/닫힘 소리
  "thunder"     - 천둥/폭풍
  "wind"        - 으스스한 바람
  "night"       - 밤 분위기 (귀뚜라미)
  [감정 계열]
  "sad"         - 슬픈 피아노
  "crying"      - 울음소리
  "happy"       - 기쁜 순간
  [전환 계열]
  "whoosh"      - 장면 전환
  "impact"      - 충격음
- 예시: 문이 열리는 장면 → "door", 갑자기 귀신 등장 → "jumpscare"
"""
        return pack_character_rule + base_rule

    @staticmethod
    def _emotion_policy(category: str, mode: str) -> Tuple[str, Dict[str, int]]:
        """
        v34: 동적 감정 시스템 - ModelManager에서 감정 목록을 동적으로 가져옴
        v57.7.5: 팩의 감정 정책 우선 적용
        """
        # v57.7.5: 팩의 감정 설정 우선
        if PACK_CONFIG_AVAILABLE and ACTIVE_PACK.is_loaded:
            pack_emotions = ACTIVE_PACK.allowed_emotions
            pack_policy = ACTIVE_PACK.emotion_policy

            if pack_emotions:
                # v57.7.6: 팩 기반 감정 규칙 생성 (강제)
                emotions_str = '", "'.join(pack_emotions)
                rule = f"""
[★★★ EMOTION RULE - PACK: {ACTIVE_PACK.pack_name} ★★★]
- emotion은 반드시 아래 목록에서만 선택 (다른 감정 절대 금지!):
  "{emotions_str}"

★ 위 목록에 없는 감정은 사용 금지!
★ 예: "neutral", "fear", "anxiety" 등은 사용 금지 → 위 목록에서 선택하세요
★ 자연스러운 감정 흐름 유지 (기승전결에 맞춰 변화)
"""
                # v61.1-fix(#9): 감정 폴백 확장 (calm만 → 다양한 감정)
                policy = pack_policy if pack_policy else {"calm": 3, "sad": 2, "worried": 1}
                logger.info(f"[ScriptWriter] 팩 감정 정책 적용 (강제): {list(pack_emotions)}")
                return rule, policy

        # v60: 팩에서 감정 정책 로딩 (장르 분기 제거)
        # v61: 모듈 상단 import 사용 (함수 내 재import → UnboundLocalError 방지)
        try:
            if PACK_CONFIG_AVAILABLE and ACTIVE_PACK.is_loaded:
                channel_id = ACTIVE_PACK.pack_id

                # v60.1.0: 팩에서 emotion_weights 로딩 (raw_settings 제거)
                emotion_weights = {}
                if hasattr(ACTIVE_PACK, 'tts') and hasattr(ACTIVE_PACK.tts, 'emotion_weights'):
                    emotion_weights = ACTIVE_PACK.tts.emotion_weights or {}

                # 감정 정책 (팩에서)
                # v61.1-fix(#9): 감정 폴백 확장
                policy = emotion_weights if emotion_weights else {"calm": 3, "sad": 2, "worried": 1}

                # 동적 감정 프롬프트 생성 시도
                try:
                    from utils.model_manager import get_model_manager
                    mm = get_model_manager()
                    rule = mm.build_emotion_prompt_for_channel(channel_id)
                    return rule, policy
                except ImportError:
                    pass  # model_manager 미설치 — 아래 ACTIVE_PACK 폴백으로 진행
                except Exception as e:
                    logger.debug(f"[ScriptWriters] 동적 감정 프롬프트 생성 실패, 팩 기반 폴백: {e}")

                # v60.1.0: 팩에서 allowed_emotions 로딩 (raw_settings 제거)
                allowed = []
                if hasattr(ACTIVE_PACK, 'tts') and hasattr(ACTIVE_PACK.tts, 'allowed_emotions'):
                    allowed = ACTIVE_PACK.tts.allowed_emotions or []
                if not allowed:
                    allowed = ["sad", "angry", "scared", "happy", "calm", "excited", "whisper"]

                rule = f"""
[EMOTION RULE]
- emotion은 반드시 아래 감정 중 하나만 사용:
  {', '.join(f'"{e}"' for e in allowed)}
- 자연스러운 감정 흐름 유지 (기승전결에 맞춰 변화)
"""
                return rule, policy

        except ImportError:
            pass
        except Exception as e:
            logger.warning(f"[ScriptWriter] 팩 감정 로드 실패, 기본값 사용: {e}")

        # 최종 폴백: 범용 감정 규칙
        rule = """
[EMOTION RULE]
- emotion은 반드시 아래 7가지 중 하나만 사용:
  "sad", "angry", "scared", "happy", "calm", "excited", "whisper"
- 자연스러운 감정 흐름 유지 (기승전결에 맞춰 변화)
"""
        # v61.1-fix(#9): 최종 폴백 감정 정책 확장
        policy = {"calm": 3, "sad": 2, "worried": 1}
        return rule, policy

    @staticmethod
    def _emotion_gate(script_list: List[Dict[str, Any]], min_policy: Dict[str, int],
                      target_turns: int = 35) -> bool:
        """v62.2: 스마트 감정 게이트 — 비율 기반 + tolerance + calm 상한 체크.

        변경사항 (v62.2):
        - tolerance=1: 핵심 감정이 1개 부족해도 경고 후 통과 (재시도 낭비 방지)
        - calm 상한 체크: calm의 min_cnt가 3 이상이면 "상한" 체크로 전환
          (craft_rules.txt "calm 25% 이하"와 정합성 유지)
        - 전체 감정 다양성: 최소 3종류 이상 사용해야 통과
        """
        if not script_list:
            return False

        turn_count = len(script_list)
        # v61.1: 동적 하한선 — target_turns의 절반 미만이면 감정 검증 스킵
        min_threshold = max(15, int(target_turns * 0.5))
        if turn_count < min_threshold:
            safe_print(f"      [감정 게이트] 턴 수 부족({turn_count}턴 < {min_threshold}) - 검증 스킵")
            return True

        em: Dict[str, int] = {}
        for s in script_list:
            k = (s.get("emotion") or "calm").strip().lower()
            em[k] = em.get(k, 0) + 1

        ratio = turn_count / max(float(target_turns), 1.0)
        missing_critical = []  # 심각한 부족 (tolerance 초과)
        missing_warn = []       # 경미한 부족 (tolerance 이내 — 통과)
        missing_optional = []   # min_cnt == 1: 선택 감정

        TOLERANCE = 1  # v62.2: 1개 부족까지 허용

        for k, min_cnt in min_policy.items():
            if min_cnt <= 0:
                continue

            # v62.2: calm 상한 체크 — calm의 min_cnt가 높으면 "상한" 의미
            # 공포에서 calm=5 → "calm이 25% 넘지 않도록" (craft_rules.txt와 일치)
            if k == "calm" and min_cnt >= 3:
                actual_calm = em.get("calm", 0)
                max_calm = max(3, int(turn_count * 0.30))  # 30% 상한 (여유 있게)
                if actual_calm > max_calm:
                    missing_critical.append(f"calm 과다({actual_calm}/{max_calm}상한)")
                continue  # calm은 하한 체크 스킵

            adjusted_min = max(1, int(min_cnt * ratio))
            actual = em.get(k, 0)
            deficit = adjusted_min - actual

            if deficit > 0:
                if min_cnt >= 2:
                    # 핵심 감정
                    if deficit <= TOLERANCE:
                        # v62.2: 1개 부족 — 경고 후 통과
                        missing_warn.append(f"{k}({actual}/{adjusted_min},-{deficit})")
                    else:
                        missing_critical.append(f"{k}({actual}/{adjusted_min},-{deficit})")
                else:
                    missing_optional.append(f"{k}({actual}/{adjusted_min})")

        # v62.2: 감정 다양성 체크 — 최소 3종류 사용
        emotion_variety = len(em)
        if emotion_variety < 3:
            missing_critical.append(f"감정다양성({emotion_variety}종 < 3종)")

        # 로그 출력
        if missing_optional:
            safe_print(f"      [감정 경고] 선택 감정 부족(무시): {', '.join(missing_optional)}")
        if missing_warn:
            safe_print(f"      [감정 경고] 근사치 통과(tolerance={TOLERANCE}): {', '.join(missing_warn)}")
        if missing_critical:
            safe_print(f"      [감정 부족] {', '.join(missing_critical)}")
            return False

        safe_print(f"      [감정 분포] {', '.join([f'{k}:{v}' for k,v in em.items()])}")
        return True

    @staticmethod
    def _emotion_post_correct(script_list: List[Dict[str, Any]], target_turns: int) -> List[Dict[str, Any]]:
        """v62.3: emotion post-correction — calm 초과 나레이션을 위치 기반으로 재라벨링.

        API 재시도 0회로 감정 분포 교정. 규칙:
        1. 나레이션 calm 턴만 대상 (캐릭터 대사는 절대 건드리지 않음)
        2. 전반부(0~33%) calm은 유지 (도입부라 자연스러움)
        3. 중반부(33~66%) calm → worried (긴장 고조)
        4. 후반부(66~100%) calm → scared 또는 whisper (클라이맥스)
        5. 부족 감정 우선 보충: scared > worried > whisper > desperate

        Returns: 교정된 script_list (in-place 수정)
        """
        if not script_list:
            return script_list

        total = len(script_list)

        # 1. 현재 감정 분포 카운트
        em: Dict[str, int] = {}
        for s in script_list:
            k = (s.get("emotion") or "calm").strip().lower()
            em[k] = em.get(k, 0) + 1

        calm_count = em.get("calm", 0)
        max_calm = max(3, int(total * 0.25))  # 25% 상한 (craft_rules 기준)

        # calm이 상한 이하면 교정 불필요
        if calm_count <= max_calm:
            return script_list

        # 2. 부족 감정 파악 — v62.21: 팩 기반 감정 타겟 로딩 (장르별 차등)
        need: Dict[str, int] = {}
        targets: Dict[str, int] = {"worried": 3, "sad": 2}  # 범용 안전 기본값
        if PACK_CONFIG_AVAILABLE:
            try:
                targets = get_emotion_correction_targets()
            except Exception as e:
                logger.debug(f"[ScriptWriter] 감정 보정 타깃 로드 실패, 기본값 사용: {e}")
        for emo, target in targets.items():
            actual = em.get(emo, 0)
            if actual < target:
                need[emo] = target - actual

        # 부족한 게 없으면 단순히 calm→worried로 변환
        if not need:
            need = {"worried": calm_count - max_calm}

        # 3. 나레이션 calm 턴 인덱스 수집 (전반부 제외)
        narr_calm_indices: List[int] = []
        for i, s in enumerate(script_list):
            if (s.get("role", "") == "나레이션" and
                (s.get("emotion") or "calm").strip().lower() == "calm"):
                narr_calm_indices.append(i)

        if not narr_calm_indices:
            return script_list

        # 전반부(0~33%)는 calm이 자연스러운 도입부 → 보호 우선
        # 단, 전반부 calm 보호 상한 = max_calm 절반 (나머지는 변환 대상)
        threshold_early = int(total * 0.33)
        threshold_late = int(total * 0.66)
        early_protect_limit = max(2, max_calm // 2)  # 최소 2개, 최대 max_calm의 절반

        early_narr_calm = [i for i in narr_calm_indices if i < threshold_early]
        mid_narr_calm = [i for i in narr_calm_indices if threshold_early <= i < threshold_late]
        late_narr_calm = [i for i in narr_calm_indices if i >= threshold_late]

        # 전반부: 보호 상한 초과분은 변환 대상에 추가 (뒤쪽 것부터)
        if len(early_narr_calm) > early_protect_limit:
            early_convertible = early_narr_calm[early_protect_limit:]  # 보호 초과분
        else:
            early_convertible = []

        # 변환 대상: 후반부(전부) + 중반부(전부) + 전반부 초과분 (후반부→중반부→전반부 순)
        convertible = late_narr_calm + mid_narr_calm + early_convertible

        if not convertible:
            return script_list

        # 4. 후반부→중반부→전반부 순서로 변환
        late_indices = late_narr_calm
        mid_indices = mid_narr_calm
        early_indices = early_convertible

        # 변환 예산: calm 초과분만큼만 변환
        budget = calm_count - max_calm
        converted = 0
        changes: List[str] = []

        # 4a. 후반부 calm → scared/whisper (부족 감정 우선)
        for idx in late_indices:
            if converted >= budget:
                break
            # scared 부족하면 scared, 아니면 whisper
            if need.get("scared", 0) > 0:
                script_list[idx]["emotion"] = "scared"
                need["scared"] -= 1
                changes.append(f"#{idx}→scared")
            elif need.get("whisper", 0) > 0:
                script_list[idx]["emotion"] = "whisper"
                need["whisper"] -= 1
                changes.append(f"#{idx}→whisper")
            elif need.get("desperate", 0) > 0:
                script_list[idx]["emotion"] = "desperate"
                need["desperate"] -= 1
                changes.append(f"#{idx}→desperate")
            else:
                script_list[idx]["emotion"] = "scared"
                changes.append(f"#{idx}→scared")
            converted += 1

        # 4b. 중반부 calm → worried (부족 감정 우선)
        for idx in mid_indices:
            if converted >= budget:
                break
            if need.get("worried", 0) > 0:
                script_list[idx]["emotion"] = "worried"
                need["worried"] -= 1
                changes.append(f"#{idx}→worried")
            elif need.get("scared", 0) > 0:
                script_list[idx]["emotion"] = "scared"
                need["scared"] -= 1
                changes.append(f"#{idx}→scared")
            elif need.get("whisper", 0) > 0:
                script_list[idx]["emotion"] = "whisper"
                need["whisper"] -= 1
                changes.append(f"#{idx}→whisper")
            else:
                script_list[idx]["emotion"] = "worried"
                changes.append(f"#{idx}→worried")
            converted += 1

        # 4c. 전반부 보호 초과분 calm → worried (도입부에 가까우므로 부드럽게)
        for idx in early_indices:
            if converted >= budget:
                break
            if need.get("worried", 0) > 0:
                script_list[idx]["emotion"] = "worried"
                need["worried"] -= 1
                changes.append(f"#{idx}→worried")
            elif need.get("whisper", 0) > 0:
                script_list[idx]["emotion"] = "whisper"
                need["whisper"] -= 1
                changes.append(f"#{idx}→whisper")
            else:
                script_list[idx]["emotion"] = "worried"
                changes.append(f"#{idx}→worried")
            converted += 1

        if changes:
            safe_print(f"      [감정 교정] calm {calm_count}→{calm_count - converted} ({converted}턴 변환: {', '.join(changes[:8])}{'...' if len(changes) > 8 else ''})")
            logger.info(f"[PostCorrect] calm {calm_count}→{calm_count - converted}, 변환: {changes}")

        return script_list

    @staticmethod
    def _emotion_force_correct(
        script_list: List[Dict[str, Any]],
        min_policy: Dict[str, int],
        target_turns: int,
    ) -> List[Dict[str, Any]]:
        """v62.31: 강제 감정 교정 — 비상 템플릿 투입 방지용 최후 수단.

        _emotion_post_correct(calm 초과 교정)보다 더 공격적:
        - 먼저 calm 초과 교정 (기존 로직 재사용)
        - 그 후 핵심 감정(min_cnt>=2) 결손 → 나레이션 여유 턴 재라벨링
        - 감정 다양성 3종 미달 → 추가 라벨링

        이 함수 호출 후에도 게이트 통과를 보장하지는 않지만,
        적어도 실제 스토리가 살아있는 대본을 반환한다.
        """
        if not script_list:
            return script_list

        # Step 1: 기존 calm 초과 교정 먼저
        result = ScriptWriter._emotion_post_correct(script_list, target_turns)

        total = len(result)
        ratio = total / max(float(target_turns), 1.0)

        # Step 2: 현재 분포 재계산
        em: Dict[str, int] = {}
        for s in result:
            k = (s.get("emotion") or "calm").strip().lower()
            em[k] = em.get(k, 0) + 1

        # Step 3: 핵심 감정(min_cnt>=2) 결손 계산 (calm 상한 체크는 제외)
        deficits: Dict[str, int] = {}
        for k, min_cnt in min_policy.items():
            if min_cnt < 2:
                continue
            if k == "calm" and min_cnt >= 3:
                continue  # calm은 상한 체크, 하한 결손 계산 불필요
            adjusted_min = max(1, int(min_cnt * ratio))
            actual = em.get(k, 0)
            if actual < adjusted_min:
                deficits[k] = adjusted_min - actual

        # 감정 다양성 3종 미달 시 임시 결손 추가
        if len(em) < 3 and not deficits:
            fallback_em = next(
                (k for k in min_policy if k not in em and k != "calm"), "worried"
            )
            deficits[fallback_em] = 1

        if not deficits:
            return result

        # Step 4: 후보 나레이션 턴 수집 (전반부 25% 제외, donor 감정 보유)
        # donor = deficit이 아닌 감정 중 가장 많은 것 (calm 포함)
        donor_emotions = {k for k in em if k not in deficits}
        candidates: List[tuple] = []  # (idx, pos_ratio)
        for i, s in enumerate(result):
            role = s.get("role", "")
            if role not in ("나레이션", "narrator", "narration"):
                continue
            cur_em = (s.get("emotion") or "calm").strip().lower()
            if cur_em not in donor_emotions:
                continue
            pos_ratio = i / max(total - 1, 1)
            if pos_ratio <= 0.25:
                continue  # 전반부 도입부 보호
            candidates.append((i, pos_ratio))

        # 후반부 우선 정렬 (스토리 고조 지점에서 감정 표현이 자연스러움)
        candidates.sort(key=lambda x: -x[1])

        # Step 5: 결손 감정 채우기 (결손 많은 것부터)
        ptr = 0
        changes: List[str] = []
        for target_em, needed in sorted(deficits.items(), key=lambda x: -x[1]):
            filled = 0
            while filled < needed and ptr < len(candidates):
                idx, _ = candidates[ptr]
                old_em = result[idx].get("emotion", "calm")
                result[idx]["emotion"] = target_em
                changes.append(f"#{idx}:{old_em}→{target_em}")
                ptr += 1
                filled += 1

        if changes:
            safe_print(
                f"      [강제 교정] 감정 결손 보충 {len(changes)}턴: "
                f"{', '.join(changes[:8])}{'...' if len(changes) > 8 else ''}"
            )
            logger.info(f"[ForceCorrect] 결손={deficits}, 변환={changes}")

        return result

    @staticmethod
    def _tts_safe_text(text: str) -> str:
        t = _safe_strip(text)
        if not t:
            return ""

        t = t.replace("…", "...")
        t = re.sub(r"\.\s*\.\s*\.", "...", t)
        t = re.sub(r"\.{4,}", "...", t)
        t = re.sub(r",\s*,+", ",", t)
        t = re.sub(r"\s{2,}", " ", t)
        t = re.sub(r",\s*$", "", t)
        t = re.sub(r"([가-힣]{2,4})\s*,\s*\1(야|아)?", r"\1\2", t)
        t = re.sub(r"^([가-힣]{2,4})\s*,\s*\1(야|아)\s*,?\s*$", r"\1\2.", t)

        commas = t.count(",")
        if commas >= 3:
            parts = [p.strip() for p in t.split(",") if p.strip()]
            if len(parts) >= 2:
                t = parts[0] + ". " + " ".join(parts[1:])

        if re.fullmatch(r"\.{3,}", t):
            return "..."

        return t

    @staticmethod
    def _normalize_script(script_list: List[Dict[str, Any]], channel_id: str = None) -> List[Dict[str, Any]]:
        """
        v57.1: role = 캐릭터 이름, voice_type = 음성 타입 체계로 변경
        - role: 캐릭터 이름 그대로 유지 (민우, 지혜, 나레이션 등)
        - voice_type: 7가지 음성 타입 중 하나로 검증
        - 하위 호환성: voice_type 없으면 role에서 추론
        v57.7.3: 팩의 character_config 우선 적용
        """
        # v57.7.3: 팩의 character_config 로드 (최우선 매핑)
        pack_char_map = {}
        if PACK_CONFIG_AVAILABLE and ACTIVE_PACK.is_loaded:
            pack_char_map = get_character_config()
            if pack_char_map:
                logger.info(f"[Script] 팩 character_config 적용: {list(pack_char_map.keys())}")

        # v59.5.12: role → voice_type 추론용 (하위 호환성)
        # media_factory._role_key_normalize()와 동일한 매핑 유지 필수!
        # man/woman = 청년(20-30대), middle_man/middle_woman = 중년(40-50대)
        role_to_voice_type = {
            # 나레이터
            "내레이션": "narrator", "나레이션": "narrator", "narration": "narrator",
            "narrator": "narrator", "해설": "narrator", "내레이터": "narrator",

            # 할머니 (여성 노인 70대+)
            "할머니": "grandma", "grandma": "grandma", "외할머니": "grandma",
            "친할머니": "grandma", "grandmother": "grandma", "할매": "grandma",

            # 할아버지 (남성 노인 70대+)
            "할아버지": "grandpa", "grandpa": "grandpa", "외할아버지": "grandpa",
            "친할아버지": "grandpa", "grandfather": "grandpa", "할배": "grandpa",

            # 중년 남성 (40-50대) - v59.5.12: middle_man으로 분리
            "아빠": "middle_man", "아버지": "middle_man", "father": "middle_man", "dad": "middle_man",
            "남편": "middle_man", "삼촌": "middle_man", "아저씨": "middle_man",
            "중년남자": "middle_man", "중년남성": "middle_man",
            "middle_man": "middle_man",

            # 중년 여성 (40-50대) - v59.5.12: middle_woman으로 분리
            "엄마": "middle_woman", "어머니": "middle_woman", "mother": "middle_woman", "mom": "middle_woman",
            "아내": "middle_woman", "이모": "middle_woman", "아줌마": "middle_woman",
            "중년여자": "middle_woman", "중년여성": "middle_woman",
            "middle_woman": "middle_woman",

            # 청년 남성 (20-30대) - v62.10: young_man으로 통일 (man 구버전 제거)
            "남자": "young_man", "man": "young_man", "청년": "young_man",
            "아들": "young_man", "젊은남자": "young_man", "청년남자": "young_man",
            "오빠": "young_man", "형": "young_man", "남동생": "young_man", "son": "young_man",
            "young_man": "young_man",

            # 청년 여성 (20-30대) - v62.10: young_woman으로 통일 (woman 구버전 제거)
            "여자": "young_woman", "woman": "young_woman", "처녀": "young_woman",
            "딸": "young_woman", "젊은여자": "young_woman", "청년여자": "young_woman",
            "언니": "young_woman", "누나": "young_woman", "여동생": "young_woman", "daughter": "young_woman",
            "young_woman": "young_woman",

            # 임시 child 보이스는 TTS 단계에서 young_woman으로 대체된다.
            "child": "child", "kid": "child", "boy": "child", "girl": "child",
            "아이": "child", "어린이": "child", "손주": "child",
        }
        # v62.10: allowed_voice_types 동적 로딩 — voice_metadata.json 키 기반
        # 새 TTS 음성 추가 시 코드 수정 불필요 (voice_metadata.json + models/ 폴더만 추가)
        # v62.17: 로컬 import 제거 — ACTIVE_PACK/PACK_CONFIG_AVAILABLE은 모듈 레벨(L78~83)에서 이미 import됨
        # v62.21 M-2: 클래스 변수 캐시 사용 (매 호출마다 파일 재읽기 방지)
        if ScriptWriter._voice_types_cache is not None:
            allowed_voice_types = ScriptWriter._voice_types_cache
        else:
            try:
                import json as _json, os as _os
                _meta_path = _os.path.join(
                    _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))),
                    "assets", "models", "voice_metadata.json"
                )
                if _os.path.exists(_meta_path):
                    with open(_meta_path, encoding="utf-8") as _f:
                        _meta = _json.load(_f)
                    # narrator는 runtime에서 narrator_male/female로 분기되는 alias
                    # voice_metadata.json에 없어도 항상 허용해야 함
                    allowed_voice_types = set(_meta.keys()) | {"narrator", "child"}
                    ScriptWriter._voice_types_cache = allowed_voice_types
                    logger.debug(f"[Script] allowed_voice_types 동적 로딩: {sorted(allowed_voice_types)}")
                else:
                    raise FileNotFoundError(_meta_path)
            except Exception as _e:
                # 폴백: 하드코딩 기본값 (voice_metadata.json 없을 때)
                logger.warning(f"[Script] allowed_voice_types 동적 로딩 실패, 기본값 사용: {_e}")
                allowed_voice_types = {
                    "narrator", "narrator_male", "narrator_female",
                    "grandma", "grandpa",
                    "young_man", "young_woman", "middle_man", "middle_woman", "child",
                }
                ScriptWriter._voice_types_cache = allowed_voice_types

        # v34: 동적 감정 로드
        # v57.2.1 Hotfix: fear→scared 통일 (TTS 엔진과 일관성)
        # v57.7.5: 팩의 감정 설정 우선 적용
        # v59.5: CRAFT RULES/후처리와 동일한 9종 기본값 (이전 5종에서 확장)
        allowed_emotions = {"scared", "angry", "sad", "happy", "calm", "excited", "whisper", "worried", "desperate"}  # 기본값

        # 1순위: 팩의 allowed_emotions
        if PACK_CONFIG_AVAILABLE and ACTIVE_PACK.is_loaded and ACTIVE_PACK.allowed_emotions:
            allowed_emotions = set(ACTIVE_PACK.allowed_emotions)
            logger.info(f"[_normalize_script] 팩 감정 설정 적용: {allowed_emotions}")
        # 2순위: ModelManager 동적 로드
        elif channel_id:
            try:
                from utils.model_manager import get_model_manager
                mm = get_model_manager()
                dynamic_emotions = mm.get_all_emotions_for_channel(channel_id)
                if dynamic_emotions:
                    allowed_emotions = set(dynamic_emotions)
                    logger.debug(f"[_normalize_script] 동적 감정 로드 성공: {allowed_emotions}")
            except Exception as e:
                logger.warning(f"[_normalize_script] 동적 감정 로드 실패, 기본값 사용: {e}")

        out: List[Dict[str, Any]] = []
        fallback_count = 0  # v34: 폴백 횟수 추적
        voice_type_fallback_count = 0  # v57.1: voice_type 폴백 횟수
        missing_pack_roles = set()  # v57.7.4: 팩에서 누락된 캐릭터 추적

        for s in script_list:
            # v57.1: role은 캐릭터 이름 그대로 유지
            role = _safe_strip(s.get("role", "나레이션"))

            # v57.1: voice_type 처리 (없으면 role에서 추론)
            # v57.7.3: 팩 character_config → 하드코딩 매핑 → 기본값 순서
            voice_type = _safe_strip(s.get("voice_type", "")).lower()
            if not voice_type or voice_type not in allowed_voice_types:
                # 1순위: 팩의 character_config (대소문자 무시)
                role_lower = role.lower()
                pack_inferred = pack_char_map.get(role_lower) or pack_char_map.get(role)
                if pack_inferred and pack_inferred in allowed_voice_types:
                    voice_type = pack_inferred
                    logger.debug(f"[Script] 팩 매핑 적용: '{role}' → '{voice_type}'")
                else:
                    # 2순위: 하드코딩된 role_to_voice_type
                    inferred = role_to_voice_type.get(role_lower, None)
                    if inferred:
                        voice_type = inferred
                    else:
                        # 2.5순위 v62.4: 한국어 이름 패턴으로 성별 추론
                        # Gemini가 '수진', '미지의 목소리' 등 창작 이름을 쓸 때 대응
                        _kr_inferred = _infer_voice_type_from_korean_name(role)
                        if _kr_inferred:
                            voice_type = _kr_inferred
                            logger.debug(f"[Script] 한국어 이름 추론: '{role}' → '{voice_type}'")
                        else:
                            # 3순위: 기본값
                            if pack_char_map and role_lower not in ("나레이션", "내레이션", "narrator"):
                                missing_pack_roles.add(role)
                            voice_type = "narrator"
                            voice_type_fallback_count += 1
                            logger.warning(f"[Script] voice_type 추론 실패 '{role}' → 'narrator' 폴백")

            # v63.1: 3인칭 나레이션이 캐릭터 역할에 할당된 경우 자동 교정
            _text_content = _safe_strip(s.get("text", ""))
            if voice_type not in ("narrator", "narrator_male", "narrator_female"):
                # 캐릭터가 자기 이름을 3인칭으로 말하는 패턴 감지
                _role_name = role.split("(")[0].strip()  # "채연(여자)" → "채연"
                _third_person_endings = ("했습니다", "있었습니다", "않았습니다", "였습니다", "졌습니다", "했다", "있었다", "않았다", "들었다", "봤다", "갔다", "왔다", "섰다", "앉았다", "멈췄다", "잡았다", "열었다")
                _text_stripped = _text_content.rstrip()
                _has_name_in_text = _role_name and len(_role_name) >= 2 and _role_name in _text_content
                _ends_with_narration = _text_stripped.endswith(_third_person_endings)
                _starts_with_name_particle = False
                if _role_name and len(_role_name) >= 2:
                    for _particle in ("은 ", "는 ", "이 ", "가 "):
                        if (_role_name + _particle) in _text_content:
                            _starts_with_name_particle = True
                            break
                _is_third_person = (
                    (_has_name_in_text and _ends_with_narration)
                    or (_has_name_in_text and _starts_with_name_particle)
                )
                if _is_third_person:
                    logger.warning(f"[Script] 3인칭 나레이션 자동 교정: '{role}'(voice={voice_type}) → 'narrator' | text: {_text_content[:50]}")
                    voice_type = "narrator"

            # v57.2 Hotfix: normalize_emotion으로 동의어 정규화 (fear→scared 등)
            raw_emotion = s.get("emotion", "calm")
            e = normalize_emotion(raw_emotion)

            # v57.7.6: calm 폴백 제거 - 팩 감정만 강제 사용
            # 허용되지 않은 감정은 팩의 첫 번째 감정으로 대체 (calm 대신)
            if e not in allowed_emotions:
                original_e = e
                # 팩에 정의된 감정 중 첫 번째 선택 (calm이 아닌 실제 감정)
                fallback_emotion = next((em for em in allowed_emotions if em != "calm"), "calm")
                e = fallback_emotion
                fallback_count += 1
                logger.warning(f"[Script Fallback] 허용되지 않은 감정 '{original_e}' → '{e}' 폴백 (팩 감정)")

            t = ScriptWriter._tts_safe_text(s.get("text", ""))
            if not t:
                continue

            # v57.6.5: sfx_tag 처리 (효과음 태그)
            sfx_tag = _safe_strip(s.get("sfx_tag", "")).lower()
            # v61.1-fix(#13): _post_process_script의 valid_sfx와 통일 (rain, glass_break, scream 추가)
            allowed_sfx_tags = {
                "tension", "heartbeat", "suspense", "jumpscare", "whisper",
                "footsteps", "door", "thunder", "wind", "night", "rain",
                "glass_break", "scream",
                "sad", "crying", "happy", "whoosh", "impact", ""
            }
            if sfx_tag not in allowed_sfx_tags:
                logger.warning(f"[Script] 허용되지 않은 sfx_tag '{sfx_tag}' → 무시")
                sfx_tag = ""

            # v57.1: voice_type 필드 추가
            # v57.6.5: sfx_tag 필드 추가
            out.append({"role": role, "voice_type": voice_type, "text": t, "emotion": e, "sfx_tag": sfx_tag})

        # v34: 폴백 발생 시 요약 로그
        if fallback_count > 0:
            logger.info(f"[Script Fallback] 총 {fallback_count}개 감정이 기본값(calm)으로 대체됨. "
                       f"허용 감정: {allowed_emotions}")
        if voice_type_fallback_count > 0:
            logger.info(f"[Script] 총 {voice_type_fallback_count}개 voice_type이 기본값(narrator)으로 대체됨.")

        # v57.7.4: 팩에서 누락된 캐릭터 경고
        if missing_pack_roles:
            logger.warning(
                f"[Script] 팩의 character_config에 누락된 캐릭터: {sorted(missing_pack_roles)}\n"
                f"  - 이 캐릭터들은 하드코딩 매핑 또는 기본값(narrator)으로 처리됩니다.\n"
                f"  - 팩에 character_config를 추가하면 정확한 음성 매핑이 가능합니다."
            )

        return out

    # v59.5: 후처리 정규화 — Gemini 출력의 잔여 문제를 코드로 100% 수정
    @staticmethod
    def _post_process_script(
        script_list: List[Dict[str, Any]],
        target_turns: int,
        is_structural_pack: bool = False,
        max_sfx: int = 15,
    ) -> List[Dict[str, Any]]:
        """
        v60: Gemini 출력 후처리 정규화
        - SFX 역할 턴 수정
        - 잘못된 emotion/sfx_tag 정규화
        - 괄호 지문 제거
        - 턴 수 정확히 맞추기
        - SFX 개수 제한
        - 마지막 턴 나레이션 방지 (공포)
        """
        import re as _re

        # 유효값 정의
        valid_emotions = {"calm", "sad", "angry", "scared", "happy", "excited", "whisper", "worried", "desperate"}
        # v59.5: _normalize_script의 allowed_sfx_tags와 통일 (16개 + 빈문자열)
        valid_sfx = {
            "", "wind", "rain", "thunder", "door", "footsteps", "heartbeat",
            "tension", "suspense", "night", "glass_break", "scream",
            "jumpscare", "whisper", "sad", "crying", "happy", "whoosh", "impact",
        }

        # 잘못된 emotion → 가장 가까운 유효 emotion 매핑
        emotion_map = {
            "fear": "scared", "afraid": "scared", "terrified": "scared", "horrified": "scared",
            "nervous": "worried", "anxious": "worried", "uneasy": "worried", "concerned": "worried",
            "confused": "worried", "suspicious": "worried", "doubtful": "worried",
            "frustrated": "angry", "furious": "angry", "irritated": "angry", "annoyed": "angry",
            "shocked": "scared", "surprised": "scared", "startled": "scared",
            "relieved": "calm", "neutral": "calm", "normal": "calm", "confident": "calm",
            "gentle": "calm", "warm": "calm", "serious": "calm", "cold": "calm", "firm": "calm",
            "hopeful": "happy", "grateful": "happy", "joyful": "happy",
            "lonely": "sad", "heartbroken": "sad", "mournful": "sad", "depressed": "sad",
            "trembling": "scared", "panicked": "desperate", "frantic": "desperate",
            "tension": "scared", "suspense": "scared", "eerie": "scared",
            "urgent": "desperate", "pleading": "desperate", "begging": "desperate",
            "hushed": "whisper", "quiet": "whisper", "soft": "whisper", "murmur": "whisper",
        }

        result = []
        # v61.1-fix(#12): 빈 문자열로 초기화 — 첫 턴 나레이션이 불필요하게 수정되지 않도록
        last_char_role = ""

        for s in script_list:
            entry = dict(s)  # 복사

            # ① SFX 역할 → 직전 캐릭터 또는 나레이션으로 변환
            role = entry.get("role", "나레이션").strip()
            if role.upper() in ("SFX", "효과음", "SE", "SOUND", "BGM"):
                entry["role"] = "나레이션"
                entry["voice_type"] = "narrator"
                # text가 효과음 설명이면 나레이션으로 변환
                text = entry.get("text", "").strip()
                if not text or text.startswith("(") or text.startswith("["):
                    continue  # 의미 없는 SFX 턴은 제거

            # ② 잘못된 emotion 정규화
            emotion = entry.get("emotion", "calm").strip().lower()
            if emotion not in valid_emotions:
                mapped = emotion_map.get(emotion, None)
                if mapped:
                    entry["emotion"] = mapped
                else:
                    entry["emotion"] = "calm"
                    logger.debug(f"[PostProcess] 알 수 없는 emotion '{emotion}' → 'calm'")

            # ③ 잘못된 sfx_tag 정규화
            sfx = entry.get("sfx_tag", "").strip().lower()
            if sfx not in valid_sfx:
                # 가까운 sfx_tag 매핑 시도
                sfx_map = {
                    "knock": "door", "knocking": "door", "creak": "door", "slam": "door",
                    "step": "footsteps", "steps": "footsteps", "walking": "footsteps",
                    "heart": "heartbeat", "pulse": "heartbeat",
                    "lightning": "thunder", "storm": "thunder",
                    "breeze": "wind", "howl": "wind",
                    "break": "glass_break", "shatter": "glass_break", "crack": "glass_break",
                    "cry": "scream", "shriek": "scream", "yell": "scream",
                    "dark": "night", "darkness": "night", "silence": "night",
                    "tense": "tension", "intense": "tension",
                    "creepy": "suspense", "eerie": "suspense", "ominous": "suspense",
                    "scared": "tension", "fear": "tension",
                    "drop": "", "drip": "", "water": "rain",
                }
                entry["sfx_tag"] = sfx_map.get(sfx, "")

            # ④ 괄호 지문 제거
            text = entry.get("text", "")
            text = _re.sub(r'\([^)]*\)', '', text).strip()
            text = _re.sub(r'\[[^\]]*\]', '', text).strip()
            if not text:
                continue
            entry["text"] = text

            # 마지막 캐릭터 role 추적 (SFX/나레이션 아닌 것)
            if entry.get("role", "") != "나레이션":
                last_char_role = entry["role"]

            result.append(entry)

        # ⑤ "..." 패딩 턴 정리 (의미 없는 연속 ... 제거)
        # 마지막 의미 있는 턴 찾기
        last_meaningful_idx = len(result) - 1
        while last_meaningful_idx > 0 and result[last_meaningful_idx].get("text", "").strip() == "...":
            last_meaningful_idx -= 1
        # 마지막 의미 있는 턴 뒤의 ... 패딩 제거 (단, 1개는 여운으로 남김)
        if last_meaningful_idx < len(result) - 2:
            result = result[:last_meaningful_idx + 2]  # +2: 의미 있는 턴 + 여운 1턴

        # ⑤-2 턴 수 조정 (초과분만 잘라내기, 부족분은 패딩 안 함)
        # v61.1: "..." 패딩은 영상에 데드에어를 만드므로 제거
        # Gemini가 30턴 줬으면 30턴 영상을 만드는 게 나음
        if len(result) > target_turns:
            result = result[:target_turns]
        elif len(result) < target_turns:
            logger.info(f"[PostProcess] {len(result)}턴 (목표 {target_turns}) - 패딩 없이 그대로 사용")

        # ⑥ SFX 개수 제한 (후반부 것부터 제거)
        sfx_indices = [i for i, s in enumerate(result) if s.get("sfx_tag", "")]
        if len(sfx_indices) > max_sfx:
            # 후반부 초과분의 sfx_tag 제거
            for idx in sfx_indices[max_sfx:]:
                result[idx]["sfx_tag"] = ""
            logger.info(f"[PostProcess] SFX {len(sfx_indices)}개 → {max_sfx}개로 제한")

        # ⑦ 나레이션 3턴 연속 해소 (중간에 짧은 대사 삽입)
        i = 0
        while i < len(result) - 2:
            if (result[i].get("role") == "나레이션" and
                result[i+1].get("role") == "나레이션" and
                result[i+2].get("role") == "나레이션"):
                # 3번째 나레이션을 직전 캐릭터의 짧은 반응으로 변환
                # v61.1-fix(#12 검증): last_char_role이 빈 문자열이면 나레이션 유지
                result[i+2]["role"] = last_char_role if (last_char_role and last_char_role != "나레이션") else "나레이션"
                if result[i+2]["role"] != "나레이션":
                    # v61.1-fix(#4): 나레이션 텍스트를 캐릭터 반응으로 변환
                    # "..." 리터럴 대신 원본 텍스트의 핵심을 짧은 대사로 축약
                    narr_text = result[i+2].get("text", "")
                    if len(narr_text) > 30:
                        # 30자 초과: 앞 25자 + "..." (TTS에서 자연스럽게 읽힘)
                        result[i+2]["text"] = narr_text[:25] + "..."
                    # 30자 이하: 원본 텍스트 그대로 유지 (캐릭터 대사로 충분)
                    result[i+2]["emotion"] = "scared" if is_structural_pack else "calm"
                    # v59.5 L1: voice_type도 캐릭터에 맞게 업데이트 (narrator 유지 방지)
                    # 직전 캐릭터의 voice_type 찾기
                    # v62.10: 기본값 man → young_man (man은 구버전)
                    for j in range(i+1, -1, -1):
                        if result[j].get("role") == last_char_role:
                            result[i+2]["voice_type"] = result[j].get("voice_type", "young_man")
                            break
                    else:
                        result[i+2]["voice_type"] = "young_man"  # 못 찾으면 기본값
                    logger.debug(f"[PostProcess] 나레이션3연속 해소: #{i+2} → {last_char_role}")
            # last_char_role 업데이트
            if result[i].get("role", "") != "나레이션":
                last_char_role = result[i]["role"]
            i += 1

        # ⑦-2 v62.4: 나레이션 비율 간벌 (35% 초과 시 나레이션 턴을 캐릭터 대사로 변환)
        total_turns = len(result)
        if total_turns > 0:
            narr_roles = ("나레이션", "narrator", "narration")
            narr_count = sum(1 for t in result if t.get("role") in narr_roles)
            max_narr = max(3, int(total_turns * 0.35))
            if narr_count > max_narr:
                excess = narr_count - max_narr
                # 변환 대상: 나레이션 턴 중 텍스트가 짧은 것(설명적 나레이션)부터
                # 주변에 캐릭터 대사가 있는 나레이션만 변환 (컨텍스트 유지)
                narr_indices = []
                for idx, t in enumerate(result):
                    if t.get("role") in narr_roles:
                        # 양쪽에 캐릭터가 있는 나레이션만 대상 (독립 씬 나레이션 보호)
                        has_char_neighbor = False
                        if idx > 0 and result[idx-1].get("role") not in narr_roles:
                            has_char_neighbor = True
                        if idx < total_turns - 1 and result[idx+1].get("role") not in narr_roles:
                            has_char_neighbor = True
                        if has_char_neighbor:
                            narr_indices.append((idx, len(t.get("text", ""))))

                # 짧은 나레이션부터 변환 (짧을수록 설명적 → 캐릭터 반응으로 자연스러움)
                narr_indices.sort(key=lambda x: x[1])
                converted = 0
                for idx, _ in narr_indices:
                    if converted >= excess:
                        break
                    # 직전 캐릭터 찾기
                    # v62.10: 기본값 man → young_man (man은 구버전)
                    prev_char = None
                    prev_vt = "young_man"
                    for j in range(idx - 1, -1, -1):
                        if result[j].get("role") not in narr_roles:
                            prev_char = result[j]["role"]
                            prev_vt = result[j].get("voice_type", "young_man")
                            break
                    if prev_char:
                        narr_text = result[idx].get("text", "")
                        if len(narr_text) > 30:
                            narr_text = narr_text[:25] + "..."
                        result[idx]["role"] = prev_char
                        result[idx]["voice_type"] = prev_vt
                        result[idx]["text"] = narr_text
                        # 감정: 나레이션의 원래 감정 유지 (calm이면 worried로 변경)
                        if result[idx].get("emotion") == "calm":
                            result[idx]["emotion"] = "worried"
                        converted += 1
                if converted > 0:
                    logger.info(f"[PostProcess] 나레이션 간벌: {narr_count}→{narr_count-converted}턴 ({converted}개 변환)")

        # v62.4: 모든 팩에서 마지막 턴이 나레이션이면 직전 대사턴과 교체
        # (v60에서는 is_structural_pack만 적용 → P3 재시도 매번 발생 → 전체 적용으로 변경)
        if result and result[-1].get("role") in ("나레이션", "narrator", "narration"):
            # 뒤에서부터 대사 턴 찾기
            for i in range(len(result) - 2, max(len(result) - 6, -1), -1):
                if result[i].get("role") not in ("나레이션", "narrator", "narration"):
                    result[i], result[-1] = result[-1], result[i]
                    logger.info(f"[PostProcess] 마지막 턴 교체: 나레이션 ↔ {result[-1]['role']}")
                    break

        # ⑧ v62.3: emotion post-correction — calm 초과 시 로컬 감정 재라벨링
        # API 재시도 0회로 감정 분포 교정. 나레이션 calm 턴만 대상 (캐릭터 대사는 건드리지 않음)
        result = ScriptWriter._emotion_post_correct(result, target_turns)

        return result

    def _create_fallback_script(self, target_turns: int, category: str, mode: str) -> List[Dict[str, Any]]:
        """
        v59.5.17: 비상 템플릿 대본 — 순차 서사 구조 (랜덤 반복 근절)
        - 팩에서 비상 시퀀스 로딩, 폴백은 12턴 범용 시퀀스 (중복 문장 0개)
        - target_turns > 시퀀스 길이면 cycle로 반복하되 순서 유지
        - _is_fallback 마킹으로 scenario_planner에서 감지 가능
        """
        safe_print(f"      [비상 모드] 안정성 우선 템플릿 대본 생성 중...")
        logger.warning(f"[{self.role_name}] 비상 템플릿 발동 - target={target_turns}턴, {category}/{mode}")

        # v60: 팩에서 비상 시퀀스 로딩 (장르 분기 제거)
        # v61: 모듈 레벨 import 사용 (로컬 import 금지 — UnboundLocalError 방지)
        sequence = []
        if PACK_CONFIG_AVAILABLE:
            pack_sequence = get_emergency_sequence()
            if pack_sequence:
                sequence = [tuple(item) for item in pack_sequence]

        # v61.1-fix(#8): 폴백 비상 시퀀스 — 4턴→12턴 확장 (반복 최소화)
        # v62.10: man/woman → young_man/young_woman (구버전 voice_type 제거)
        if not sequence:
            sequence = [
                ("나레이션", "narrator", "이야기가 시작됩니다.", "calm"),
                ("남자", "young_man", "여기가 어디죠?", "worried"),
                ("여자", "young_woman", "조용히 해요. 누가 올지도 몰라요.", "scared"),
                ("나레이션", "narrator", "두 사람은 서로를 바라보았습니다.", "calm"),
                ("남자", "young_man", "우리가 왜 여기에 있는 거죠?", "worried"),
                ("나레이션", "narrator", "그때, 멀리서 발자국 소리가 들려왔습니다.", "scared"),
                ("여자", "young_woman", "빨리 숨어요!", "desperate"),
                ("남자", "young_man", "저기 뭔가 있어요.", "scared"),
                ("나레이션", "narrator", "어둠 속에서 무언가가 다가오고 있었습니다.", "scared"),
                ("여자", "young_woman", "제발, 이러지 마세요.", "sad"),
                ("남자", "young_man", "걱정 마세요. 제가 지켜줄게요.", "calm"),
                ("나레이션", "narrator", "그렇게 긴 밤이 시작되었습니다.", "calm"),
            ]

        # v59.5.17: 순차 배치 (랜덤 반복 근절) + _is_fallback 마킹
        script: List[Dict[str, Any]] = []
        seq_len = len(sequence)
        for i in range(target_turns):
            role, voice_type, text, emo = sequence[i % seq_len]
            script.append({
                "role": role,
                "voice_type": voice_type,
                "text": ScriptWriter._tts_safe_text(text),
                "emotion": emo,
                "sfx_tag": "",
                "_is_fallback": True,  # v59.5.17: scenario_planner에서 감지용
            })

        script = script[:target_turns]
        safe_print(f"      템플릿 대본 {len(script)}턴 생성 완료 (v59.5.17 순차 서사)")
        return script

    @staticmethod
    def _turn_signature(turn: Dict[str, Any]) -> Tuple[str, str, str, str]:
        return (
            _safe_strip(turn.get("role", "")).lower(),
            _safe_strip(turn.get("voice_type", "")).lower(),
            _safe_strip(turn.get("text", "")),
            _safe_strip(turn.get("emotion", "")).lower(),
        )

    @classmethod
    def _trim_repeated_prefix(cls, existing_script: List[Dict[str, Any]], extra_script: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not existing_script or not extra_script:
            return list(extra_script or [])

        existing_sig = [cls._turn_signature(turn) for turn in existing_script]
        extra_sig = [cls._turn_signature(turn) for turn in extra_script]

        max_overlap = min(8, len(existing_sig), len(extra_sig))
        for overlap in range(max_overlap, 0, -1):
            if existing_sig[-overlap:] == extra_sig[:overlap]:
                return list(extra_script[overlap:])

        search_overlap = min(4, len(existing_sig), len(extra_sig))
        for overlap in range(search_overlap, 0, -1):
            suffix = existing_sig[-overlap:]
            for start in range(0, len(extra_sig) - overlap + 1):
                if extra_sig[start:start + overlap] == suffix:
                    return list(extra_script[start + overlap:])

        if cls._turn_signature(existing_script[-1]) == cls._turn_signature(extra_script[0]):
            return list(extra_script[1:])

        return list(extra_script)

    @staticmethod
    def _build_recovery_context(script: List[Dict[str, Any]], max_turns: int = 18) -> str:
        excerpt = list(script or [])[-max_turns:]
        return json.dumps(excerpt, ensure_ascii=False)

    # v62.41: Gemini 초안 + Claude 리라이트 하이브리드 방식
    def _write_part_hybrid(
        self,
        topic: str,
        category: str,
        mode: str,
        target_turns: int,
        story_bible: str,
        prev_summary: str,
        instruction: str,
        forbidden: str,
        base_prompt: str,
        gen_config,
    ) -> Optional[List[Dict[str, Any]]]:
        """
        v62.41: Gemini Flash가 초안을 빠르게 생성하고,
        Claude CLI가 그 초안을 통째로 리라이트하여 퀄리티를 올린다.

        - Gemini: 구조/플롯/JSON 포맷 → 빠름 (~30초)
        - Claude: 대사 뉘앙스/감정/캐릭터 목소리 → 퀄리티
        - 실패 시 None 반환 → 분할 생성 또는 기존 방식으로 폴백
        """
        role_label = getattr(self, "role_name", "Writer")

        # Step 1: Gemini Flash로 초안 생성
        safe_print(f"      [{role_label}] 하이브리드 모드: Gemini 초안 생성 중...")
        logger.info(f"[{role_label}] hybrid mode: generating Gemini draft")

        try:
            from llm.factory import create_story_llm
            gemini_model = create_story_llm(provider="gemini")
        except Exception as e:
            logger.warning(f"[{role_label}] Gemini 초기화 실패: {e}. 하이브리드 불가.")
            safe_print(f"      [{role_label}] Gemini 사용 불가 → 폴백")
            return None

        # Gemini용 config (빠르게, 안정적으로)
        gemini_gen_config = _make_generation_config(
            temperature=0.75,
            top_p=0.90,
            top_k=40,
            max_output_tokens=16384,
            thinking_budget=0,
        )

        gemini_timeout = max(120, target_turns * 3)
        draft_script = None

        for attempt in range(2):
            try:
                res = gemini_model.generate_content(
                    base_prompt,
                    timeout=gemini_timeout,
                    generation_config=gemini_gen_config,
                )
                full_text = _safe_strip((getattr(res, "text", "") or ""))
                raw = _extract_json_block(full_text, want="object")
                data = _safe_json_loads(raw, {})
                draft_script = data.get("script_list", [])

                # v62.41-fix: 임계값 40% → 70% (P1 — 짧은 대본 성공 반환 방지)
                _min_accept_draft = max(10, int(target_turns * 0.7))
                if isinstance(draft_script, list) and len(draft_script) >= _min_accept_draft:
                    safe_print(
                        f"      [{role_label}] Gemini 초안 완료: {len(draft_script)}턴 "
                        f"(최소 {_min_accept_draft}턴)"
                    )
                    logger.info(f"[{role_label}] Gemini draft: {len(draft_script)} turns (min={_min_accept_draft})")
                    break
                else:
                    n = len(draft_script) if isinstance(draft_script, list) else 0
                    logger.warning(f"[{role_label}] Gemini 초안 분량 미달: {n}/{_min_accept_draft}턴. 재시도 {attempt+1}/2")
                    safe_print(f"      Gemini 초안 미달({n}/{_min_accept_draft}턴). 재시도...")
                    draft_script = None
                    time.sleep(2)

            except Exception as e:
                logger.warning(f"[{role_label}] Gemini 초안 오류: {type(e).__name__}: {str(e)[:150]}")
                safe_print(f"      Gemini 초안 오류. 재시도... ({type(e).__name__})")
                time.sleep(3)

        if not draft_script:
            safe_print(f"      [{role_label}] Gemini 초안 실패 → 폴백")
            return None

        # Step 2: Claude CLI로 리라이트
        safe_print(f"      [{role_label}] Claude 리라이트 시작...")
        logger.info(f"[{role_label}] hybrid mode: Claude rewrite starting")

        draft_json = json.dumps(draft_script, ensure_ascii=False)

        rewrite_prompt = f"""
You are a **veteran Korean drama rewriter**. You've been given a DRAFT script below.
Your job: REWRITE the entire script to dramatically improve quality.

[WHAT TO KEEP]
- Same plot structure, character names, and story progression
- Same number of turns (approximately {len(draft_script)} turns)
- Same JSON format

[WHAT TO IMPROVE]
- Make dialogue more natural, vivid, and emotionally resonant in Korean
- Add subtext — characters don't always say what they mean
- Vary sentence rhythm: tension = short punchy lines, calm = longer flowing sentences
- Deepen emotional shifts — don't just label emotions, SHOW them through word choice
- Make each character's voice distinct (grandma speaks differently from young_woman)
- Add sensory details in narration (sounds, textures, light)
- Ensure dramatic pacing — build tension, release, build again
- Fix any awkward or generic dialogue

[STORY CONTEXT]
Topic: {topic}
Category: {category} / Mode: {mode}

[STORY BIBLE]
{story_bible}

[PREVIOUS PARTS]
{prev_summary}

[DRAFT SCRIPT TO REWRITE]
{draft_json}

[TASK]
{instruction}

[RULES]
- Output ONLY the rewritten JSON. No explanation, no commentary.
- Keep voice_type values exactly as they are (narrator, young_man, grandma, etc.)
- ALL text must be in Korean
- Maintain approximately the same number of turns ({len(draft_script)} ± 5)

Output JSON ONLY:
{{"script_list":[{{"role":"Korean character name","voice_type":"narrator|young_man|young_woman|middle_man|middle_woman|grandma|grandpa|child","text":"Korean dialogue","emotion":"calm|sad|angry|scared|happy|excited|whisper|worried|desperate","sfx_tag":"sfx tag or empty string"}}, ...]}}
"""

        rewrite_timeout = _resolve_story_timeout(target_turns)

        for attempt in range(2):
            try:
                try:
                    res = self.model.generate_content(
                        rewrite_prompt,
                        timeout=rewrite_timeout,
                        generation_config=gen_config,
                    )
                except TypeError:
                    res = self.model.generate_content(
                        rewrite_prompt,
                        generation_config=gen_config,
                    )

                full_text = _safe_strip((getattr(res, "text", "") or ""))
                raw = _extract_json_block(full_text, want="object")
                data = _safe_json_loads(raw, {})
                rewritten = data.get("script_list", [])

                # v62.41-fix: 임계값 40% → 70% (P1 — 짧은 대본 성공 반환 방지)
                _min_accept_rewrite = max(10, int(target_turns * 0.7))
                if isinstance(rewritten, list) and len(rewritten) >= _min_accept_rewrite:
                    safe_print(
                        f"      [{role_label}] Claude 리라이트 완료: {len(rewritten)}턴"
                    )
                    logger.info(f"[{role_label}] Claude rewrite: {len(rewritten)} turns (min={_min_accept_rewrite})")
                    return rewritten
                else:
                    n = len(rewritten) if isinstance(rewritten, list) else 0
                    logger.warning(f"[{role_label}] 리라이트 분량 미달: {n}/{_min_accept_rewrite}턴. 재시도 {attempt+1}/2")
                    safe_print(f"      리라이트 미달({n}/{_min_accept_rewrite}턴). 재시도...")
                    time.sleep(3)

            except Exception as e:
                logger.warning(f"[{role_label}] 리라이트 오류: {type(e).__name__}: {str(e)[:150]}")
                safe_print(f"      리라이트 오류. 재시도... ({type(e).__name__})")
                time.sleep(3)

        # Claude 리라이트 실패 시 Gemini 초안이라도 반환
        safe_print(f"      [{role_label}] 리라이트 실패 → Gemini 초안 사용")
        logger.warning(f"[{role_label}] rewrite failed, using Gemini draft as-is")
        return draft_script

    # v62.41: Claude CLI 서브파트 분할 생성 — 타임아웃 방지 + 안정성 대폭 향상
    def _write_part_chunked(
        self,
        topic: str,
        category: str,
        mode: str,
        target_turns: int,
        story_bible: str,
        prev_summary: str,
        instruction: str,
        forbidden: str,
        base_prompt_builder,  # callable(chunk_instruction, prev_script_json) -> str
        gen_config,
        min_policy: Dict[str, int],
    ) -> Optional[List[Dict[str, Any]]]:
        """
        v62.41: Claude CLI 전용 — target_turns를 chunk_size 단위로 분할 호출.
        각 청크에서 이전 원문을 전달하여 스토리 연속성을 유지한다.
        성공 시 합산된 script_list 반환, 실패 시 None (폴백으로 기존 방식 시도).
        """
        chunk_size = max(12, min(18, target_turns // 3))
        chunks = []
        remaining = target_turns
        while remaining > 0:
            # 마지막 청크가 너무 작으면 이전 청크에 합산
            if remaining <= chunk_size * 0.6 and chunks:
                chunks[-1] += remaining
                remaining = 0
            else:
                sz = min(chunk_size, remaining)
                chunks.append(sz)
                remaining -= sz

        role_label = getattr(self, "role_name", "Writer")
        safe_print(f"      [{role_label}] 분할 생성 모드: {len(chunks)}청크 {chunks} (총 {target_turns}턴)")
        logger.info(f"[{role_label}] chunked write: {len(chunks)} chunks {chunks}, total={target_turns}")

        combined: List[Dict[str, Any]] = []

        for ci, chunk_turns in enumerate(chunks):
            start_turn = sum(chunks[:ci]) + 1
            end_turn = start_turn + chunk_turns - 1
            is_last = (ci == len(chunks) - 1)

            # 이전 서브파트 원문 (요약 아님!)
            prev_script_json = ""
            if combined:
                prev_script_json = json.dumps(combined, ensure_ascii=False)

            # 청크별 지시사항
            if ci == 0:
                chunk_instr = (
                    f"{instruction}\n\n"
                    f"[CHUNK TASK] Write turns {start_turn}–{end_turn} ({chunk_turns} turns). "
                    f"This is the BEGINNING of this part. Start the story for this part."
                )
            elif is_last:
                chunk_instr = (
                    f"{instruction}\n\n"
                    f"[CHUNK TASK] Write turns {start_turn}–{end_turn} ({chunk_turns} turns). "
                    f"This is the FINAL chunk. Bring this part to a powerful conclusion or cliffhanger. "
                    f"The LAST turn MUST be a character's spoken line, NOT narration."
                )
            else:
                chunk_instr = (
                    f"{instruction}\n\n"
                    f"[CHUNK TASK] Write turns {start_turn}–{end_turn} ({chunk_turns} turns). "
                    f"Continue naturally from where the previous chunk ended. "
                    f"Escalate tension, add new developments."
                )

            prompt = base_prompt_builder(chunk_instr, prev_script_json)
            api_timeout = _resolve_story_timeout(chunk_turns)

            success = False
            for attempt in range(2):
                try:
                    try:
                        res = self.model.generate_content(
                            prompt, timeout=api_timeout, generation_config=gen_config
                        )
                    except TypeError:
                        res = self.model.generate_content(
                            prompt, generation_config=gen_config
                        )

                    full_text = _safe_strip((getattr(res, "text", "") or ""))
                    raw = _extract_json_block(full_text, want="object")
                    data = _safe_json_loads(raw, {})
                    script_chunk = data.get("script_list", [])

                    if not isinstance(script_chunk, list) or len(script_chunk) < max(3, chunk_turns // 3):
                        n_got = len(script_chunk) if isinstance(script_chunk, list) else 0
                        logger.warning(
                            f"[{role_label}] chunk {ci+1}/{len(chunks)} 분량 미달 "
                            f"({n_got}/{chunk_turns}턴). 재시도 {attempt+1}/2"
                        )
                        safe_print(f"      청크 {ci+1} 분량 미달({n_got}턴). 재시도...")
                        if n_got == 0:
                            safe_print(f"      [DEBUG] 응답 앞 200자: {full_text[:200]}")
                        time.sleep(2)
                        continue

                    # 중복 턴 제거 (이전 원문과 겹치는 부분)
                    pre_dedup_len = len(script_chunk)
                    if combined:
                        script_chunk = self._trim_repeated_prefix(combined, script_chunk)

                    # v62.41-fix P1: 중복 제거 후 빈약한 청크 재검증
                    if pre_dedup_len > 0 and len(script_chunk) < max(2, pre_dedup_len // 3):
                        logger.warning(
                            f"[{role_label}] chunk {ci+1}: 중복 제거 후 {pre_dedup_len}→{len(script_chunk)}턴 "
                            f"(대부분 반복). 재시도 {attempt+1}/2"
                        )
                        safe_print(f"      청크 {ci+1}: 중복 제거 후 {len(script_chunk)}턴만 남음. 재시도...")
                        time.sleep(2)
                        continue

                    combined.extend(script_chunk)
                    safe_print(
                        f"      [{role_label}] 청크 {ci+1}/{len(chunks)} 완료: "
                        f"+{len(script_chunk)}턴 (누적 {len(combined)}/{target_turns})"
                    )
                    logger.info(
                        f"[{role_label}] chunk {ci+1}/{len(chunks)}: "
                        f"+{len(script_chunk)} turns (cumulative {len(combined)}/{target_turns})"
                    )
                    success = True
                    if len(combined) >= target_turns:
                        logger.info(
                            f"[{role_label}] chunked write reached target after chunk {ci+1}: "
                            f"{len(combined)}/{target_turns}"
                        )
                        break
                    break

                except Exception as e:
                    logger.warning(
                        f"[{role_label}] chunk {ci+1} 오류: {type(e).__name__}: {str(e)[:150]}. "
                        f"재시도 {attempt+1}/2"
                    )
                    safe_print(f"      청크 {ci+1} 오류. 재시도... ({type(e).__name__})")
                    time.sleep(3)

            if not success:
                logger.error(f"[{role_label}] chunk {ci+1} 최종 실패. 분할 생성 중단.")
                safe_print(f"      [{role_label}] 청크 {ci+1} 실패 → 분할 생성 중단")
                return None  # 기존 방식으로 폴백
            if len(combined) >= target_turns:
                break

        # v62.41-fix P1-3: 내부 청크 합산도 70% 기준 적용
        _min_chunked = max(10, int(target_turns * 0.7))
        if len(combined) < _min_chunked:
            logger.warning(f"[{role_label}] 분할 합산 {len(combined)}/{_min_chunked}턴 < 최소 기준. 폴백.")
            safe_print(f"      [{role_label}] 분할 합산 미달: {len(combined)}/{_min_chunked}턴")
            return None

        safe_print(f"      [{role_label}] 분할 생성 완료: 총 {len(combined)}턴")
        logger.info(f"[{role_label}] chunked write complete: {len(combined)} turns total")
        return combined

    # v62.41: Basic ScriptWriter용 분할 생성 래퍼
    def _basic_write_part_chunked(
        self,
        topic: str,
        category: str,
        mode: str,
        target_turns: int,
        story_bible: str,
        prev_summary: str,
        instruction: str,
        forbidden: str,
        role_rule: str,
        emotion_rule: str,
        min_policy: Dict[str, int],
        writer_system: str,
    ) -> Optional[List[Dict[str, Any]]]:
        # 팩 스타일 / 나레이션 전용 / craft_rules / pacing 조립 (write_part와 동일)
        pack_style_section = ""
        if writer_system:
            pack_style_section = f"\n[PACK STYLE GUIDE - 이 채널의 이야기 톤/개성]\n{writer_system}\n"
        if PACK_CONFIG_AVAILABLE and ACTIVE_PACK.is_loaded and getattr(ACTIVE_PACK.tts, "narration_only", False):
            pack_style_section += (
                "\n[NARRATION ONLY MODE — 절대 규칙]\n"
                "- 모든 턴의 role을 \"narrator\"로, voice_type도 \"narrator\"로 설정하십시오.\n"
                "- 1인칭 또는 3인칭 나레이터 시점으로 이야기 전체를 서술하십시오.\n"
            )
        basic_craft = ""
        if PACK_CONFIG_AVAILABLE:
            basic_craft = get_prompt("craft_rules") or ""
        if basic_craft:
            basic_craft = basic_craft.replace("{{target_turns}}", str(target_turns))
            basic_craft = basic_craft.replace("{{min_dialogue}}", str(int(target_turns * 0.65)))
            basic_craft = basic_craft.replace("{{max_narration}}", str(int(target_turns * 0.35)))
        basic_pacing = ""
        if PACK_CONFIG_AVAILABLE:
            part_name = self.role_name
            if "빌드업" in part_name or "1" in part_name:
                basic_pacing = get_prompt("pacing_part1") or ""
            elif "위기" in part_name or "2" in part_name:
                basic_pacing = get_prompt("pacing_part2") or ""
            else:
                basic_pacing = get_prompt("pacing_part3") or ""

        def build_prompt(chunk_instruction: str, prev_script_json: str) -> str:
            prev_block = prev_summary or ""
            if prev_script_json:
                prev_block += f"\n\n[THIS PART — ALREADY WRITTEN TURNS (continue from here)]\n{prev_script_json}"
            return f"""
You are a professional screenwriter specializing in the role of "{self.role_name}".
Write compelling Korean-language drama scripts that keep audiences hooked.

[TOPIC] {topic}
[CATEGORY] {category} / [MODE] {mode}

[STYLE GUIDE]
{role_rule}
{pack_style_section}
{emotion_rule}
{basic_pacing}

[STORY BIBLE - World/Characters/Tone]
{story_bible}

[PREVIOUS PARTS - Full Script So Far]
{prev_block}

Read the above script carefully. Continue the story naturally.
Do NOT repeat events already covered. Continue from where it left off.

[YOUR TASK]
{chunk_instruction}

[FORBIDDEN / DO NOT DO]
{forbidden}

{basic_craft}

Output JSON ONLY:
{{"script_list":[{{"role":"Korean character name","voice_type":"narrator|young_man|young_woman|middle_man|middle_woman|grandma|grandpa|child","text":"Korean dialogue","emotion":"calm|sad|angry|scared|happy|excited|whisper|worried|desperate","sfx_tag":"sfx tag or empty string"}}, ...]}}
"""

        gen_config = _make_generation_config(
            temperature=0.8, top_p=0.92, top_k=50,
            max_output_tokens=16384, thinking_budget=0,
        )

        result = self._write_part_chunked(
            topic, category, mode, target_turns, story_bible, prev_summary,
            instruction, forbidden, build_prompt, gen_config, min_policy,
        )
        if result is None:
            return None

        # 후처리 (기존 write_part와 동일)
        _channel_id = ACTIVE_PACK.pack_id if (PACK_CONFIG_AVAILABLE and ACTIVE_PACK.is_loaded) else f"{category}_{mode}"
        result = self._normalize_script(result, _channel_id)
        result = self._post_process_script(
            result, target_turns, is_structural_pack=False, max_sfx=max(5, target_turns // 4)
        )
        if not self._emotion_gate(result, min_policy, target_turns=target_turns):
            result = self._emotion_force_correct(result, min_policy, target_turns)
        if len(result) > target_turns:
            result = result[:target_turns]
        # v62.41-fix P1-3: 분할 생성도 후처리 후 최소 70% 강제
        _min_final = max(10, int(target_turns * 0.7))
        if len(result) < _min_final:
            safe_print(f"      [{self.role_name}] 분할 생성 후처리 후 분량 미달: {len(result)}/{_min_final}턴 → None 반환")
            logger.warning(f"[{self.role_name}] chunked post-process under minimum: {len(result)}/{_min_final}")
            return None
        safe_print(f"      [{self.role_name}] 분할 생성 최종: {len(result)}턴")
        return result

    def _try_recover_short_script(
        self,
        topic: str,
        category: str,
        mode: str,
        target_turns: int,
        story_bible: str,
        prev_summary: str,
        instruction: str,
        forbidden: str,
        script: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        if _get_story_provider() != "claude_cli":
            return script
        if not isinstance(script, list) or not script or len(script) >= target_turns:
            return script

        combined = list(script)
        recovery_config = _make_generation_config(
            temperature=0.55,
            top_p=0.85,
            top_k=40,
            max_output_tokens=8192,
            thinking_budget=0,
        )
        previous_summary_excerpt = _safe_strip(prev_summary or "")
        if len(previous_summary_excerpt) > 1800:
            previous_summary_excerpt = previous_summary_excerpt[-1800:]

        for _ in range(2):
            missing_turns = target_turns - len(combined)
            if missing_turns <= 0:
                break

            recovery_prompt = f"""
You are repairing an under-length Korean drama script part.
Continue directly from the existing turns below.
Write EXACTLY {missing_turns} NEW turns and return ONLY those new turns.
Do NOT restart the story.
Do NOT summarize or restate earlier turns.
The first new turn must immediately continue from the last existing turn.
Keep character names, voice_type values, tone, pacing, and unresolved conflict consistent.

[ROLE]
{self.role_name}

[TOPIC] {topic}
[CATEGORY] {category} / [MODE] {mode}

[STORY BIBLE]
{story_bible}

[PREVIOUS PARTS SUMMARY]
{previous_summary_excerpt}

[CURRENT PART TASK]
{instruction}

[FORBIDDEN]
{forbidden}

[EXISTING PART - LAST TURNS JSON]
{self._build_recovery_context(combined)}

Output JSON ONLY:
{{"script_list":[{{"role":"Korean character name","voice_type":"narrator|young_man|young_woman|middle_man|middle_woman|grandma|grandpa|child","text":"Korean dialogue","emotion":"calm|sad|angry|scared|happy|excited|whisper|worried|desperate","sfx_tag":"sfx tag or empty string"}}, ...]}}
"""

            try:
                api_timeout = _resolve_story_timeout(missing_turns)
                try:
                    res = self.model.generate_content(
                        recovery_prompt,
                        timeout=api_timeout,
                        generation_config=recovery_config,
                    )
                except TypeError:
                    res = self.model.generate_content(
                        recovery_prompt,
                        generation_config=recovery_config,
                    )

                raw_text = _safe_strip((getattr(res, "text", "") or ""))
                raw_json = _extract_json_block(raw_text, want="object")
                data = _safe_json_loads(raw_json, {})
                extra_script = data.get("script_list", [])
                if not isinstance(extra_script, list) or not extra_script:
                    logger.warning(f"[{self.role_name}] short-script recovery returned no usable turns")
                    break

                extra_script = self._trim_repeated_prefix(combined, extra_script)
                if not extra_script:
                    logger.warning(f"[{self.role_name}] short-script recovery only repeated existing turns")
                    break

                combined.extend(extra_script)
                logger.info(
                    f"[{self.role_name}] short-script recovery +{len(extra_script)} turns "
                    f"({len(combined)}/{target_turns})"
                )
            except Exception as exc:
                logger.warning(f"[{self.role_name}] short-script recovery failed: {type(exc).__name__}: {exc}")
                break

        return combined

    def write_part(
        self,
        topic: str,
        category: str,
        mode: str,
        target_turns: int,
        story_bible: str,
        prev_summary: str,
        instruction: str,
        forbidden: str,
        attempt_limit: int = 3,  # v62: 5→3 (무의미한 재시도 감소)
    ) -> List[Dict[str, Any]]:
        safe_print(f"   [{self.role_name}] 집필 시작 (목표 {target_turns}턴)...")

        role_rule = self._role_rule()
        emotion_rule, min_policy = self._emotion_policy(category, mode)

        # v57.7.0: 팩 기반 작가 프롬프트
        writer_system = ""
        if PACK_CONFIG_AVAILABLE and ACTIVE_PACK.is_loaded:
            writer_system = get_prompt("writer_system", category)
            if writer_system:
                safe_print(f"      [팩 적용] {ACTIVE_PACK.pack_name} 작가 프롬프트 사용")

        # v62.41: Claude CLI 하이브리드/분할 생성 분기
        if _get_story_provider() == "claude_cli" and target_turns > 20:
            # 1순위: Gemini 초안 + Claude 리라이트 (가장 빠르고 퀄리티 높음)
            # base_prompt를 먼저 조립해서 Gemini에 전달
            _ps = ""
            if writer_system:
                _ps = f"\n[PACK STYLE GUIDE]\n{writer_system}\n"
            _hybrid_prompt = f"""
You are a professional screenwriter. Write a Korean drama script.
[TOPIC] {topic}
[CATEGORY] {category} / [MODE] {mode}
{role_rule}
{_ps}
{emotion_rule}
[STORY BIBLE]
{story_bible}
[PREVIOUS PARTS]
{prev_summary}
[YOUR TASK]
{instruction}
[FORBIDDEN]
{forbidden}
Write EXACTLY {target_turns} turns. ALL text in Korean.
Output JSON ONLY:
{{"script_list":[{{"role":"Korean character name","voice_type":"narrator|young_man|young_woman|middle_man|middle_woman|grandma|grandpa|child","text":"Korean dialogue","emotion":"calm|sad|angry|scared|happy|excited|whisper|worried|desperate","sfx_tag":"sfx tag or empty string"}}, ...]}}
"""
            gen_config_basic = _make_generation_config(
                temperature=0.8, top_p=0.92, top_k=50,
                max_output_tokens=16384, thinking_budget=0,
            )
            hybrid_result = self._write_part_hybrid(
                topic, category, mode, target_turns, story_bible, prev_summary,
                instruction, forbidden, _hybrid_prompt, gen_config_basic,
            )
            if hybrid_result is not None:
                # 후처리
                _cid = ACTIVE_PACK.pack_id if (PACK_CONFIG_AVAILABLE and ACTIVE_PACK.is_loaded) else f"{category}_{mode}"
                hybrid_result = self._normalize_script(hybrid_result, _cid)
                hybrid_result = self._post_process_script(
                    hybrid_result, target_turns, is_structural_pack=False, max_sfx=max(5, target_turns // 4)
                )
                if not self._emotion_gate(hybrid_result, min_policy, target_turns=target_turns):
                    hybrid_result = self._emotion_force_correct(hybrid_result, min_policy, target_turns)
                if len(hybrid_result) > target_turns:
                    hybrid_result = hybrid_result[:target_turns]
                # v62.41-fix P1: 후처리 후 최소 턴 수 강제 (target의 70%)
                _min_final = max(10, int(target_turns * 0.7))
                if len(hybrid_result) < _min_final:
                    safe_print(f"      [{self.role_name}] 하이브리드 후처리 후 분량 미달: {len(hybrid_result)}/{_min_final}턴 → 폴백")
                    logger.warning(f"[{self.role_name}] hybrid post-process under minimum: {len(hybrid_result)}/{_min_final}")
                else:
                    safe_print(f"      [{self.role_name}] 하이브리드 최종: {len(hybrid_result)}턴")
                    return hybrid_result

            # 2순위: 분할 생성 (Gemini 불가 시 또는 하이브리드 분량 미달 시)
            safe_print(f"      [{self.role_name}] 하이브리드 실패 → 분할 생성 시도")
            chunked_result = self._basic_write_part_chunked(
                topic, category, mode, target_turns, story_bible, prev_summary,
                instruction, forbidden, role_rule, emotion_rule, min_policy,
                writer_system,
            )
            if chunked_result is not None:
                return chunked_result
            safe_print(f"      [{self.role_name}] 분할 생성도 실패 → 기존 방식으로 폴백")

        # v61.1-fix(#5): role_rule은 항상 포함 + writer_system은 추가 가이드
        # (이전: writer_system이 있으면 role_rule 완전 대체 → 캐릭터 규칙 소실)
        pack_style_section = ""
        if writer_system:
            pack_style_section = f"\n[PACK STYLE GUIDE - 이 채널의 이야기 톤/개성]\n{writer_system}\n"

        # v62.40: 나레이션 전용 모드 — 모든 대사를 narrator 단일 역할로 강제
        if PACK_CONFIG_AVAILABLE and ACTIVE_PACK.is_loaded and getattr(ACTIVE_PACK.tts, "narration_only", False):
            pack_style_section += (
                "\n[NARRATION ONLY MODE — 절대 규칙]\n"
                "[주의] 이 에피소드는 나레이션 전용입니다.\n"
                "- 모든 턴의 role을 \"narrator\"로, voice_type도 \"narrator\"로 설정하십시오.\n"
                "- grandpa, grandma, young_man, young_woman 등 대화 캐릭터는 절대 사용 금지.\n"
                "- 1인칭 또는 3인칭 나레이터 시점으로 이야기 전체를 서술하십시오.\n"
                "- [이 규칙은 CRAFT RULES, STYLE GUIDE 등 모든 하위 규칙보다 우선합니다.]\n"
            )
            logger.info("[ScriptWriters] narration_only 모드 활성화")

        # v61.1-fix(#10): Basic에도 craft_rules + pacing 주입 (Enhanced와 동일)
        basic_craft = ""
        if PACK_CONFIG_AVAILABLE:
            basic_craft = get_prompt("craft_rules") or ""
        if basic_craft:
            basic_craft = basic_craft.replace("{{target_turns}}", str(target_turns))
            basic_craft = basic_craft.replace("{{min_dialogue}}", str(int(target_turns * 0.65)))
            basic_craft = basic_craft.replace("{{max_narration}}", str(int(target_turns * 0.35)))
        else:
            basic_craft = f"""[CRAFT RULES]
1) Write EXACTLY {target_turns} turns — no fewer, no more.
2) Show, Don't Tell: Instead of "she was sad", write "tears rolled down her cheek."
3) Dialogue to narration ratio = 7:3.
4) No repetition: always add new developments.
5) At least 1 emotional shift every 5 turns.
6) Vary sentence length: tension = short, calm = medium, impact = one word.
7) Ellipsis: ONLY "..." allowed. Never ". . ." or Unicode "…".
8) voice_type must match the character's age/gender accurately.
9) sfx_tag only at key dramatic moments (10-15% of total turns).
10) Character names MUST be common Korean names that indicate gender.
ALL dialogue text must be in Korean.
"""

        # v61.1-fix(#10): Basic에도 파트별 페이싱 가이드 주입
        basic_pacing = ""
        if PACK_CONFIG_AVAILABLE:
            part_name = self.role_name  # "파트1: 빌드업" 등
            if "빌드업" in part_name or "1" in part_name:
                basic_pacing = get_prompt("pacing_part1") or ""
            elif "위기" in part_name or "2" in part_name:
                basic_pacing = get_prompt("pacing_part2") or ""
            else:
                basic_pacing = get_prompt("pacing_part3") or ""

        base_prompt = f"""
You are a professional screenwriter specializing in the role of "{self.role_name}".
Write compelling Korean-language drama scripts that keep audiences hooked.

[TOPIC] {topic}
[CATEGORY] {category} / [MODE] {mode}

[STYLE GUIDE]
{role_rule}
{pack_style_section}
{emotion_rule}
{basic_pacing}

[STORY BIBLE - World/Characters/Tone]
{story_bible}

[PREVIOUS PARTS - Full Script So Far]
{prev_summary}

Read the above script carefully. Continue the story naturally.
Do NOT repeat events already covered. Continue from where it left off.

[YOUR TASK]
{instruction}

[FORBIDDEN / DO NOT DO]
{forbidden}

{basic_craft}

Output JSON ONLY:
{{"script_list":[{{"role":"Korean character name","voice_type":"narrator|young_man|young_woman|middle_man|middle_woman|grandma|grandpa|child","text":"Korean dialogue","emotion":"calm|sad|angry|scared|happy|excited|whisper|worried|desperate","sfx_tag":"sfx tag or empty string"}}, ...]}}
"""

        # v62.3: thinking_budget=0 — Gemini 2.5 Flash의 thinking 비활성화
        # thinking이 켜져있으면 16K 중 10~15K를 thinking에 소비 → 실제 출력 1~6K → 8턴만 생성
        # 대본은 "규칙 기반 창작"이므로 thinking 불필요, 16K 전부 출력에 사용
        gen_config = _make_generation_config(
            temperature=0.8,
            top_p=0.92,
            top_k=50,
            max_output_tokens=16384,
            thinking_budget=0,
        )

        # v32.1: 지수 백오프 적용 재시도
        # v62.31: best_script 추적 — 모든 재시도 실패해도 비상 템플릿 투입 방지
        best_script: Optional[List[Dict[str, Any]]] = None

        for attempt in range(attempt_limit):
            try:
                tweak = ""
                if attempt >= 1:
                    emotion_guide = ", ".join([f"{k}: at least {v}" for k, v in min_policy.items()])
                    tweak += f"\n[RETRY NOTE - Emotion distribution required]\nYou MUST include: {emotion_guide}\n"
                if attempt >= 2:
                    tweak += "\n[EXAMPLE]\n- Calm scenes: calm\n- Conflict/Crisis: angry or sad\n- Catharsis: happy (touching) or angry (makjang)\n"
                # v62: attempt 3/4 tweak 삭제 (attempt_limit=3이므로 도달 불가)

                # v61.1: target_turns 기반 timeout (35턴 기준 ~105초)
                api_timeout = _resolve_story_timeout(target_turns)
                # v62.39: hasattr(_client) 방식 오판 수정 → try/except TypeError 방식
                # raw genai.GenerativeModel도 내부 _client 보유 → hasattr 항상 True → TypeError 재발
                # try: timeout 시도, except TypeError: timeout 없이 재호출
                try:
                    res = self.model.generate_content(
                        base_prompt + tweak,
                        timeout=api_timeout,
                        generation_config=gen_config
                    )
                except TypeError:
                    res = self.model.generate_content(
                        base_prompt + tweak,
                        generation_config=gen_config
                    )
                full_text = _safe_strip((getattr(res, "text", "") or ""))
                raw = _extract_json_block(full_text, want="object")
                data = _safe_json_loads(raw, {})
                script = data.get("script_list", [])
                if isinstance(script, list) and 0 < len(script) < target_turns:
                    script = self._try_recover_short_script(
                        topic,
                        category,
                        mode,
                        target_turns,
                        story_bible,
                        prev_summary,
                        instruction,
                        forbidden,
                        script,
                    )

                # v61.1: 0.75→0.5 + 최소 20턴 하한선 (BUG-2/6 수정)
                # Gemini 2.5 Flash 8K 토큰 한도로 27~36턴 생성 → threshold 50%
                # 단, 17턴 같은 극단적 미달 방지를 위해 최소 20턴 절대 하한
                min_accept = min(target_turns, max(20, int(target_turns * 0.5)))
                if not isinstance(script, list) or len(script) < min_accept:
                    # v32.1: 지수 백오프 대기
                    delay = min(1.0 * (2 ** attempt), 30.0) * (0.5 + random.random())
                    n_turns = len(script) if isinstance(script, list) else 0
                    logger.warning(f"[{self.role_name}] 분량 미달({n_turns}턴 < {min_accept}). 재시도 {attempt+1}/{attempt_limit}, {delay:.1f}초 대기")
                    safe_print(f"      분량 미달({n_turns}턴 < {min_accept}). 재시도... ({attempt+1}/{attempt_limit})")
                    # v61: 0턴이면 Gemini 응답 디버그 출력
                    if n_turns == 0:
                        safe_print(f"      [DEBUG] Gemini 응답 앞 200자: {full_text[:200] if full_text else '(빈 응답)'}")
                        safe_print(f"      [DEBUG] JSON 추출: {raw[:200] if raw else '(추출 실패)'}")
                    time.sleep(delay)
                    continue

                # v60: 팩 ID 기반 채널 결정 (장르 분기 제거)
                # v61: 모듈 레벨 import 사용 (로컬 import 금지)
                _channel_id = ACTIVE_PACK.pack_id if (PACK_CONFIG_AVAILABLE and ACTIVE_PACK.is_loaded) else f"{category}_{mode}"
                script = self._normalize_script(script, _channel_id)

                # v61.1: 기본 ScriptWriter에도 후처리 적용 (Enhanced와 동일)
                # 괄호 지문 제거, SFX 정규화, 나레이션 3연속 해소, SFX 개수 제한
                script = self._post_process_script(
                    script, target_turns, is_structural_pack=False, max_sfx=max(5, target_turns // 4)
                )

                if not self._emotion_gate(script, min_policy, target_turns=target_turns):
                    # v62.31: gate 실패해도 best_script 저장 (비상 템플릿 투입 방지)
                    if best_script is None or len(script) > len(best_script):
                        best_script = script
                    # v32.1: 지수 백오프 대기
                    delay = min(1.0 * (2 ** attempt), 30.0) * (0.5 + random.random())
                    logger.warning(f"[{self.role_name}] 감정 분포 불량. 재시도 {attempt+1}/{attempt_limit}, {delay:.1f}초 대기")
                    safe_print(f"      감정 분포 불량. 재시도... ({attempt+1}/{attempt_limit})")
                    time.sleep(delay)
                    continue

                # v61.1: 패딩 제거 — 부족분은 그대로 사용 (데드에어 방지)
                if len(script) > target_turns:
                    script = script[:target_turns]

                logger.info(f"[{self.role_name}] 집필 완료: {len(script)}턴")
                safe_print(f"      [{self.role_name}] {len(script)}턴 집필 완료")
                return script

            except Exception as e:
                # v32.1: 지수 백오프 대기 및 상세 에러 로깅
                delay = min(1.0 * (2 ** attempt), 30.0) * (0.5 + random.random())
                logger.warning(f"[{self.role_name}] API 오류. 재시도 {attempt+1}/{attempt_limit}, {delay:.1f}초 대기. 에러: {type(e).__name__}: {str(e)[:100]}")
                safe_print(f"      JSON 형식/응답 오류. 재시도... ({attempt+1}/{attempt_limit})")
                time.sleep(delay)

        # v62.31: best_script 있으면 강제 교정 후 사용 (비상 템플릿 투입 방지)
        if best_script is not None:
            logger.warning(f"[{self.role_name}] 모든 재시도 감정 게이트 실패 → 최선 시도분({len(best_script)}턴) 강제 교정")
            safe_print(f"      [{self.role_name}] 감정 강제 교정 중... (실제 대본 유지)")
            corrected = self._emotion_force_correct(best_script, min_policy, target_turns)
            if len(corrected) > target_turns:
                corrected = corrected[:target_turns]
            return corrected

        logger.error(f"[{self.role_name}] LLM 생성 최종 실패 → 템플릿 대본 투입")
        safe_print(f"      [{self.role_name}] LLM 생성 실패 → 템플릿 대본 투입")
        return self._create_fallback_script(target_turns, category, mode)


# ============================================================
# v37: 개선된 작가 - 더 정교한 스토리텔링
# ============================================================
class EnhancedScriptWriter(ScriptWriter):
    """
    v37: 개선된 작가 - 더 정교한 스토리텔링
    """

    # v62.10: 캐릭터 음성 가이드 — voice_type 체계와 일치 (young_man/young_woman 사용)
    VOICE_GUIDES = {
        "narrator": "객관적이고 차분하게, 상황을 생생하게 묘사. 감정은 절제하되 긴장감은 유지.",
        "grandma": "따뜻하고 회상적인 톤. '~했었지', '그때는 말이야' 같은 노인 특유의 말투. 지혜롭고 포용적.",
        "grandpa": "과묵하지만 깊은 울림. 짧은 문장, 행동으로 보여주는 사랑. '...그랬어', '알겠다' 같은 절제된 표현.",
        "middle_man": "중년 남성 특유의 책임감. 때로는 완고하지만 가족을 위한 희생. '내가 어떻게든 해볼게'.",
        "middle_woman": "따뜻하고 포용적인 중년 여성. 가족을 꿰뚫는 직관. '그래도 우리 가족이잖아'.",
        "young_man": "에너지 있고 충동적. 때로는 다듬어지지 않은 감정. '형, 나도 알아. 근데...'.",
        "young_woman": "감정 표현이 섬세하고 직관적. 상황을 읽는 대사. '이상하지 않아요? 저만 그래요?'.",
        "man": "상황에 따라 강하거나 흔들리는 목소리. 책임감과 고뇌. 직접적인 화법.",
        "woman": "감정 표현이 섬세함. 공감과 직관. 상황을 읽는 대사. 때로는 강하게, 때로는 부드럽게.",
    }

    def _get_enhanced_role_rule(self) -> str:
        # v57.6.5: 기본 _role_rule() + 캐릭터 음성 가이드
        base_rule = self._role_rule()
        voice_guide = "\n".join([f"  - {k}: {v}" for k, v in self.VOICE_GUIDES.items()])
        return f"""{base_rule}

[CHARACTER VOICE GUIDE - 캐릭터별 말투/톤]
{voice_guide}

각 캐릭터의 음성 가이드를 따라 대사를 작성하세요.
같은 role이라도 상황에 따라 톤이 변할 수 있습니다.
"""

    def _get_enhanced_pacing_rule(self, part_name: str, category: str, mode: str, target_turns: int = 35) -> str:
        """v60: 파트별 페이싱 가이드 — 팩에서 로딩 (장르 분기 제거)"""
        # v61: 모듈 레벨 import 사용 (로컬 import 금지 — UnboundLocalError 방지)
        if PACK_CONFIG_AVAILABLE:
            if "빌드업" in part_name or "1" in part_name:
                pacing = get_prompt("pacing_part1")
                if pacing:
                    return pacing
            elif "위기" in part_name or "2" in part_name:
                pacing = get_prompt("pacing_part2")
                if pacing:
                    return pacing
            else:
                pacing = get_prompt("pacing_part3")
                if pacing:
                    return pacing

        # v61.1-fix(#6): 범용 폴백 — target_turns 기반 동적 계산 (50턴 하드코딩 제거)
        # 파트당 target_turns를 기준으로 비율 구간 생성
        t = target_turns  # 파트당 턴 수 (예: 35)
        if "빌드업" in part_name or "1" in part_name:
            return f"""
[PACING GUIDE - Part 1: 빌드업]
- 1~{max(3, t//7)}턴: 일상 속 인물 소개 (대사로 성격 보여주기)
- {max(4, t//7)+1}~{t//3}턴: 관계 설정 + 갈등의 씨앗
- {t//3+1}~{int(t*0.7)}턴: 갈등 본격화 + 미스터리/사건 등장
- {int(t*0.7)+1}~{t-3}턴: 첫 번째 충격 또는 위기
- 마지막 3턴: 클리프행어

[MUST INCLUDE]
- 인물은 대사/행동으로만 소개 (설명 나레이션 금지)
- 복선 2개 이상
- 나레이션 30% 이하
"""
        elif "위기" in part_name or "2" in part_name:
            return f"""
[PACING GUIDE - Part 2: 위기]
- 1~{t//5}턴: Part 1 이어받기 + 텐션 유지
- {t//5+1}~{t//2}턴: 갈등 심화, 새 정보 등장
- {t//2+1}~{int(t*0.8)}턴: 위기의 정점, 잘못된 선택
- {int(t*0.8)+1}~{t}턴: 가장 어두운 순간

[MUST INCLUDE]
- 감정 롤러코스터 (희망→절망→실낱 희망)
- 복선 1개 이상 회수
- 한 단어/짧은 문장 임팩트 턴 2개 이상
- 나레이션 30% 이하
"""
        else:
            return f"""
[PACING GUIDE - Part 3: 결말]
- 1~{t//4}턴: 마지막 결심/시도
- {t//4+1}~{int(t*0.65)}턴: 반전 또는 진실 폭로 + 감정 폭발
- {int(t*0.65)+1}~{t-3}턴: 갈등 해결 (카타르시스)
- {t-2}~{t}턴: 여운 있는 마무리

[MUST INCLUDE]
- 모든 떡밥 회수
- 캐릭터 변화가 보이는 대사
- ★ CRITICAL: 마지막 턴은 반드시 캐릭터 대사 (나레이션 금지). 여운이 남는 한 마디로 끝낼 것.
"""

    # v62.41: Enhanced ScriptWriter용 분할 생성 래퍼
    def _enhanced_write_part_chunked(
        self,
        topic: str,
        category: str,
        mode: str,
        target_turns: int,
        story_bible: str,
        prev_summary: str,
        instruction: str,
        forbidden: str,
        role_rule: str,
        emotion_rule: str,
        min_policy: Dict[str, int],
        pack_style_guide: str,
        pacing_rule: str,
    ) -> Optional[List[Dict[str, Any]]]:
        # 나레이션 전용 모드 (write_part와 동일)
        if PACK_CONFIG_AVAILABLE and ACTIVE_PACK.is_loaded and getattr(ACTIVE_PACK.tts, "narration_only", False):
            pack_style_guide += (
                "\n[NARRATION ONLY MODE — 절대 규칙]\n"
                "- 모든 턴의 role을 \"narrator\"로, voice_type도 \"narrator\"로 설정하십시오.\n"
            )
        # craft_rules
        pack_craft = ""
        if PACK_CONFIG_AVAILABLE:
            pack_craft = get_prompt("craft_rules") or ""
        if pack_craft:
            craft_rules = pack_craft.replace("{{target_turns}}", str(target_turns))
            craft_rules = craft_rules.replace("{{min_dialogue}}", str(int(target_turns * 0.65)))
            craft_rules = craft_rules.replace("{{max_narration}}", str(int(target_turns * 0.35)))
        else:
            craft_rules = f"""[CRAFT RULES]
1) Write EXACTLY {target_turns} turns total for this part.
2) Show, Don't Tell. Dialogue ratio 7:3. No repetition.
3) voice_type must match character age/gender. sfx_tag at key moments only.
ALL dialogue text must be in Korean.
"""

        forbidden_block = (
            f"{forbidden}\n"
            "- No more than 2 consecutive narration turns.\n"
            "- The LAST turn must ALWAYS be character dialogue, NEVER narration."
        )

        def build_prompt(chunk_instruction: str, prev_script_json: str) -> str:
            prev_block = prev_summary or ""
            if prev_script_json:
                prev_block += f"\n\n[THIS PART — ALREADY WRITTEN TURNS (continue from here)]\n{prev_script_json}"
            return f"""
You are a **veteran drama writer** in the role of "{self.role_name}".
Your singular goal: make viewers unable to look away from the screen.
Write all dialogue and narration text in Korean.

[TOPIC] {topic}
[CATEGORY] {category} / [MODE] {mode}

{role_rule}
{pack_style_guide}
{emotion_rule}
{pacing_rule}

[STORY BIBLE - World/Characters/Tone]
{story_bible}

[PREVIOUS PARTS - Full Script So Far]
{prev_block}

Read the above script carefully. Continue the story naturally.
Do NOT repeat events already covered. Continue from where it left off.

[YOUR TASK]
{chunk_instruction}

[FORBIDDEN / DO NOT DO]
{forbidden_block}

{craft_rules}

[CRITICAL REMINDERS]
- voice_type is REQUIRED for every turn.
- Narration turns must be 30% or less. Let characters SPEAK and ACT.

Output JSON ONLY:
{{"script_list":[{{"role":"Korean character name","voice_type":"narrator|young_man|young_woman|middle_man|middle_woman|grandma|grandpa|child","text":"Korean dialogue","emotion":"calm|sad|angry|scared|happy|excited|whisper|worried|desperate","sfx_tag":"sfx tag or empty string"}}, ...]}}
"""

        gen_config = _make_generation_config(
            temperature=0.92, top_p=0.95, top_k=60,
            max_output_tokens=16384, thinking_budget=0,
        )

        result = self._write_part_chunked(
            topic, category, mode, target_turns, story_bible, prev_summary,
            instruction, forbidden, build_prompt, gen_config, min_policy,
        )
        if result is None:
            return None

        # 후처리 (기존 Enhanced write_part와 동일)
        _channel_id = ACTIVE_PACK.pack_id if (PACK_CONFIG_AVAILABLE and ACTIVE_PACK.is_loaded) else f"{category}_{mode}"
        _has_outline = bool(get_prompt("structural_outline")) if PACK_CONFIG_AVAILABLE else False
        result = self._normalize_script(result, _channel_id)
        result = self._post_process_script(
            result, target_turns, is_structural_pack=_has_outline, max_sfx=max(5, target_turns // 4)
        )
        if not self._emotion_gate(result, min_policy, target_turns=target_turns):
            result = self._emotion_force_correct(result, min_policy, target_turns)
        if len(result) > target_turns:
            result = result[:target_turns]
        # v62.41-fix P1-3: 분할 생성도 후처리 후 최소 70% 강제
        _min_final = max(10, int(target_turns * 0.7))
        if len(result) < _min_final:
            safe_print(f"      [{self.role_name} Enhanced] 분할 생성 후처리 후 분량 미달: {len(result)}/{_min_final}턴 → None 반환")
            logger.warning(f"[{self.role_name} Enhanced] chunked post-process under minimum: {len(result)}/{_min_final}")
            return None
        safe_print(f"      [{self.role_name} Enhanced] 분할 생성 최종: {len(result)}턴")
        return result

    def write_part(
        self,
        topic: str,
        category: str,
        mode: str,
        target_turns: int,
        story_bible: str,
        prev_summary: str,
        instruction: str,
        forbidden: str,
        attempt_limit: int = 3,  # v62: 5→3 (무의미한 재시도 감소)
    ) -> List[Dict[str, Any]]:
        safe_print(f"   [{self.role_name} Enhanced] 집필 시작 (목표 {target_turns}턴)...")

        role_rule = self._get_enhanced_role_rule()
        emotion_rule, min_policy = self._emotion_policy(category, mode)
        pacing_rule = self._get_enhanced_pacing_rule(self.role_name, category, mode, target_turns)

        # v59.5.16: 팩의 writer_system을 Enhanced에도 적용 (이야기 개성/톤/세계관)
        pack_style_guide = ""
        if PACK_CONFIG_AVAILABLE and ACTIVE_PACK.is_loaded:
            _ws = get_prompt("writer_system", category)
            if _ws:
                pack_style_guide = f"\n[PACK STYLE GUIDE - 이 채널의 이야기 톤/개성]\n{_ws}\n"
                safe_print(f"      [v59.5.16] 팩 writer_system 적용: {ACTIVE_PACK.pack_name}")

        # v62.41: Claude CLI 하이브리드/분할 생성 분기 (Enhanced)
        if _get_story_provider() == "claude_cli" and target_turns > 20:
            # 나레이션 전용 모드 체크
            _narr_only = ""
            if PACK_CONFIG_AVAILABLE and ACTIVE_PACK.is_loaded and getattr(ACTIVE_PACK.tts, "narration_only", False):
                _narr_only = "\n[NARRATION ONLY MODE] All turns must use role='narrator', voice_type='narrator'.\n"

            # craft_rules 조립
            _craft = ""
            if PACK_CONFIG_AVAILABLE:
                _craft = get_prompt("craft_rules") or ""
            if _craft:
                _craft = _craft.replace("{{target_turns}}", str(target_turns))
                _craft = _craft.replace("{{min_dialogue}}", str(int(target_turns * 0.65)))
                _craft = _craft.replace("{{max_narration}}", str(int(target_turns * 0.35)))

            # 1순위: Gemini 초안 + Claude 리라이트
            _hybrid_prompt = f"""
You are a **veteran drama writer** in the role of "{self.role_name}".
Write all dialogue and narration text in Korean.

[TOPIC] {topic}
[CATEGORY] {category} / [MODE] {mode}

{role_rule}
{pack_style_guide}
{_narr_only}
{emotion_rule}
{pacing_rule}

[STORY BIBLE]
{story_bible}

[PREVIOUS PARTS]
{prev_summary}

[YOUR TASK]
{instruction}

[FORBIDDEN]
{forbidden}
- No more than 2 consecutive narration turns.
- The LAST turn must ALWAYS be character dialogue, NEVER narration.

{_craft}

Write EXACTLY {target_turns} turns. ALL text in Korean.
Output JSON ONLY:
{{"script_list":[{{"role":"Korean character name","voice_type":"narrator|young_man|young_woman|middle_man|middle_woman|grandma|grandpa|child","text":"Korean dialogue","emotion":"calm|sad|angry|scared|happy|excited|whisper|worried|desperate","sfx_tag":"sfx tag or empty string"}}, ...]}}
"""
            gen_config_enh = _make_generation_config(
                temperature=0.92, top_p=0.95, top_k=60,
                max_output_tokens=16384, thinking_budget=0,
            )
            hybrid_result = self._write_part_hybrid(
                topic, category, mode, target_turns, story_bible, prev_summary,
                instruction, forbidden, _hybrid_prompt, gen_config_enh,
            )
            if hybrid_result is not None:
                _cid = ACTIVE_PACK.pack_id if (PACK_CONFIG_AVAILABLE and ACTIVE_PACK.is_loaded) else f"{category}_{mode}"
                _has_ol = bool(get_prompt("structural_outline")) if PACK_CONFIG_AVAILABLE else False
                hybrid_result = self._normalize_script(hybrid_result, _cid)
                hybrid_result = self._post_process_script(
                    hybrid_result, target_turns, is_structural_pack=_has_ol, max_sfx=max(5, target_turns // 4)
                )
                if not self._emotion_gate(hybrid_result, min_policy, target_turns=target_turns):
                    hybrid_result = self._emotion_force_correct(hybrid_result, min_policy, target_turns)
                if len(hybrid_result) > target_turns:
                    hybrid_result = hybrid_result[:target_turns]
                # v62.41-fix P1: 후처리 후 최소 턴 수 강제 (target의 70%)
                _min_final = max(10, int(target_turns * 0.7))
                if len(hybrid_result) < _min_final:
                    safe_print(f"      [{self.role_name} Enhanced] 하이브리드 후처리 후 분량 미달: {len(hybrid_result)}/{_min_final}턴 → 폴백")
                    logger.warning(f"[{self.role_name} Enhanced] hybrid post-process under minimum: {len(hybrid_result)}/{_min_final}")
                else:
                    safe_print(f"      [{self.role_name} Enhanced] 하이브리드 최종: {len(hybrid_result)}턴")
                    return hybrid_result

            # 2순위: 분할 생성 (하이브리드 실패 또는 분량 미달)
            safe_print(f"      [{self.role_name} Enhanced] 하이브리드 실패 → 분할 생성 시도")
            chunked_result = self._enhanced_write_part_chunked(
                topic, category, mode, target_turns, story_bible, prev_summary,
                instruction, forbidden, role_rule, emotion_rule, min_policy,
                pack_style_guide, pacing_rule,
            )
            if chunked_result is not None:
                return chunked_result
            safe_print(f"      [{self.role_name} Enhanced] 분할도 실패 → 기존 방식으로 폴백")

        # v62.40: 나레이션 전용 모드 — Enhanced 경로에도 동일 주입
        if PACK_CONFIG_AVAILABLE and ACTIVE_PACK.is_loaded and getattr(ACTIVE_PACK.tts, "narration_only", False):
            pack_style_guide += (
                "\n[NARRATION ONLY MODE — 절대 규칙]\n"
                "[주의] 이 에피소드는 나레이션 전용입니다.\n"
                "- 모든 턴의 role을 \"narrator\"로, voice_type도 \"narrator\"로 설정하십시오.\n"
                "- grandpa, grandma, young_man, young_woman 등 대화 캐릭터는 절대 사용 금지.\n"
                "- 1인칭 또는 3인칭 나레이터 시점으로 이야기 전체를 서술하십시오.\n"
                "- [이 규칙은 CRAFT RULES, STYLE GUIDE 등 모든 하위 규칙보다 우선합니다.]\n"
            )
            logger.info("[ScriptWriters Enhanced] narration_only 모드 활성화")

        # v59.4: 공포 장르 특화 작법 기술
        # v60: 팩에서 craft_rules 로딩 (장르 분기 제거)
        pack_craft = ""
        # v61: 모듈 레벨 PACK_CONFIG_AVAILABLE 사용 (로컬 import 금지 — UnboundLocalError 방지)
        if PACK_CONFIG_AVAILABLE:
            pack_craft = get_prompt("craft_rules") or ""

        if pack_craft:
            # 팩 craft_rules에 target_turns 플레이스홀더 치환
            # v61: 팩 프롬프트는 {{...}} 이중 중괄호 사용 (f-string 안전)
            craft_rules = pack_craft.replace("{{target_turns}}", str(target_turns))
            craft_rules = craft_rules.replace("{{min_dialogue}}", str(int(target_turns * 0.65)))
            craft_rules = craft_rules.replace("{{max_narration}}", str(int(target_turns * 0.35)))
        else:
            # 범용 폴백 (장르 무관)
            craft_rules = f"""[CRAFT RULES - Writing Techniques]
1) Write EXACTLY {target_turns} turns — no fewer, no more.
2) Show, Don't Tell: Instead of "she was sad", write "tears rolled down her cheek."
3) Dialogue to narration ratio = 7:3. Narration ONLY for scene transitions.
4) No repetition: never re-explain existing information. Always add new developments.
5) At least 1 emotional shift, new information, or tension change every 5 turns.
6) Keep dialogue natural. Minimize exposition dumps.
7) Vary sentence length: tension = short, calm = medium, impact = one word.
8) Ellipsis: ONLY "..." allowed. Never ". . ." — never end sentences with commas.
9) voice_type must match the character's age/gender accurately.
10) sfx_tag only at key dramatic moments (10-15% of total turns).
11) ★ Character names: common Korean names that indicate gender ONLY!

ALL dialogue text must be written in Korean.
"""

        base_prompt = f"""
You are a **veteran drama writer** in the role of "{self.role_name}".
Your singular goal: make viewers unable to look away from the screen.
Write all dialogue and narration text in Korean.

[TOPIC] {topic}
[CATEGORY] {category} / [MODE] {mode}

{role_rule}
{pack_style_guide}
{emotion_rule}
{pacing_rule}

[STORY BIBLE - World/Characters/Tone]
{story_bible}

[PREVIOUS PARTS - Full Script So Far]
{prev_summary}

Read the above script carefully. Continue the story naturally.
Do NOT repeat events already covered. Continue from where it left off.

[YOUR TASK]
{instruction}

[FORBIDDEN / DO NOT DO]
{forbidden}
- No more than 2 consecutive narration turns. After 2 narration turns, the next MUST be character dialogue.
- The LAST turn of the script must ALWAYS be a character's spoken line, NEVER narration.

{craft_rules}

[CRITICAL REMINDERS]
- voice_type is REQUIRED for every turn. Choose from: narrator, young_man, young_woman, middle_man, middle_woman, grandma, grandpa, child.
- Narration turns must be 30% or less of total turns. Let characters SPEAK and ACT.

Output JSON ONLY:
{{"script_list":[{{"role":"Korean character name","voice_type":"narrator|young_man|young_woman|middle_man|middle_woman|grandma|grandpa|child","text":"Korean dialogue","emotion":"calm|sad|angry|scared|happy|excited|whisper|worried|desperate","sfx_tag":"sfx tag or empty string"}}, ...]}}
"""

        # v59.4: temperature 상향 (더 창의적, 덜 기계적)
        # v62.3: thinking_budget=0 — thinking 비활성화 (대본 생성용)
        gen_config = _make_generation_config(
            temperature=0.92,
            top_p=0.95,
            top_k=60,
            max_output_tokens=16384,
            thinking_budget=0,
        )

        # v62.31: best_script 추적 — 모든 재시도 실패해도 비상 템플릿 투입 방지
        best_script: Optional[List[Dict[str, Any]]] = None

        for attempt in range(attempt_limit):
            try:
                tweak = ""
                if attempt >= 1:
                    emotion_guide = ", ".join([f"{k}: at least {v}" for k, v in min_policy.items()])
                    tweak += f"\n[RETRY - Emotion distribution required]\n{emotion_guide}\n"
                if attempt >= 2:
                    tweak += "\n[CHARACTER VOICE EMPHASIS]\nClearly differentiate each character's speech patterns and tone.\n"
                # v62: attempt 3 tweak 삭제 (attempt_limit=3이므로 도달 불가)

                # v61.1: target_turns 기반 timeout (35턴 기준 ~105초)
                api_timeout = _resolve_story_timeout(target_turns)
                # v62.39: hasattr(_client) 방식 오판 수정 → try/except TypeError 방식
                try:
                    res = self.model.generate_content(
                        base_prompt + tweak,
                        timeout=api_timeout,
                        generation_config=gen_config
                    )
                except TypeError:
                    res = self.model.generate_content(
                        base_prompt + tweak,
                        generation_config=gen_config
                    )
                full_text = _safe_strip((getattr(res, "text", "") or ""))
                raw = _extract_json_block(full_text, want="object")
                data = _safe_json_loads(raw, {})
                script = data.get("script_list", [])
                if isinstance(script, list) and 0 < len(script) < target_turns:
                    script = self._try_recover_short_script(
                        topic,
                        category,
                        mode,
                        target_turns,
                        story_bible,
                        prev_summary,
                        instruction,
                        forbidden,
                        script,
                    )

                # v61.1: 0.75→0.5 + 최소 20턴 하한선 (BUG-2/6 수정)
                min_accept = min(target_turns, max(20, int(target_turns * 0.5)))
                if not isinstance(script, list) or len(script) < min_accept:
                    delay = min(1.0 * (2 ** attempt), 30.0) * (0.5 + random.random())
                    # v61: 디버그 - 0턴이면 Gemini 응답 앞부분 출력
                    resp_preview = full_text[:300] if full_text else "(빈 응답)"
                    n_turns_e = len(script) if isinstance(script, list) else 0
                    logger.warning(f"[{self.role_name} Enhanced] 분량 미달({n_turns_e}턴 < {min_accept}). 재시도 {attempt+1}/{attempt_limit}")
                    safe_print(f"      분량 미달({n_turns_e}턴 < {min_accept}). 재시도...")
                    if n_turns_e == 0:
                        safe_print(f"      [DEBUG] Gemini 응답 앞 300자: {resp_preview[:200]}")
                        safe_print(f"      [DEBUG] JSON 추출 결과: {raw[:200] if raw else '(추출 실패)'}")
                    time.sleep(delay)
                    continue

                # v60: 팩 ID 기반 채널 결정 (장르 분기 제거)
                # v61: 모듈 레벨 import 사용 (로컬 import 금지)
                _channel_id2 = ACTIVE_PACK.pack_id if (PACK_CONFIG_AVAILABLE and ACTIVE_PACK.is_loaded) else f"{category}_{mode}"
                _has_outline = bool(get_prompt("structural_outline")) if PACK_CONFIG_AVAILABLE else False
                script = self._normalize_script(script, _channel_id2)

                # v60: 후처리 정규화 (is_structural_pack으로 전환)
                script = self._post_process_script(
                    script, target_turns, is_structural_pack=_has_outline, max_sfx=max(5, target_turns // 4)
                )

                if not self._emotion_gate(script, min_policy, target_turns=target_turns):
                    # v62.31: gate 실패해도 best_script 저장 (비상 템플릿 투입 방지)
                    if best_script is None or len(script) > len(best_script):
                        best_script = script
                    corrected_now = self._emotion_force_correct(script, min_policy, target_turns)
                    if self._emotion_gate(corrected_now, min_policy, target_turns=target_turns):
                        logger.info(f"[{self.role_name} Enhanced] 감정 분포 로컬 강제 교정 성공")
                        safe_print(f"      [{self.role_name} Enhanced] 감정 강제 교정으로 통과")
                        if len(corrected_now) > target_turns:
                            corrected_now = corrected_now[:target_turns]
                        return corrected_now
                    delay = min(1.0 * (2 ** attempt), 30.0) * (0.5 + random.random())
                    logger.warning(f"[{self.role_name} Enhanced] 감정 분포 불량. 재시도")
                    safe_print(f"      감정 분포 불량. 재시도...")
                    time.sleep(delay)
                    continue

                logger.info(f"[{self.role_name} Enhanced] 집필 완료: {len(script)}턴")
                safe_print(f"      [{self.role_name} Enhanced] {len(script)}턴 집필 완료")
                return script

            except Exception as e:
                delay = min(1.0 * (2 ** attempt), 30.0) * (0.5 + random.random())
                logger.warning(f"[{self.role_name} Enhanced] API 오류. 재시도 {attempt+1}/{attempt_limit}, {delay:.1f}초 대기. 에러: {type(e).__name__}: {str(e)[:200]}")
                safe_print(f"      오류 발생. 재시도... ({attempt+1}/{attempt_limit}) — {type(e).__name__}: {str(e)[:100]}")
                time.sleep(delay)

        # v62.31: best_script 있으면 강제 교정 후 사용 (비상 템플릿 투입 방지)
        if best_script is not None:
            logger.warning(f"[{self.role_name} Enhanced] 모든 재시도 감정 게이트 실패 → 최선 시도분({len(best_script)}턴) 강제 교정")
            safe_print(f"      [{self.role_name} Enhanced] 감정 강제 교정 중... (실제 대본 유지)")
            corrected = self._emotion_force_correct(best_script, min_policy, target_turns)
            if len(corrected) > target_turns:
                corrected = corrected[:target_turns]
            return corrected

        logger.error(f"[{self.role_name} Enhanced] 생성 실패 → 템플릿 투입")
        safe_print(f"      [{self.role_name} Enhanced] 생성 실패 → 템플릿 투입")
        return self._create_fallback_script(target_turns, category, mode)
