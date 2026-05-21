# src/modules_pro/visual_storytelling_director.py
# ============================================================
# v59: Visual Storytelling Director
# 비주얼 스토리텔링 전체 파이프라인 관리자
# SceneAnalyzer + PromptComposer + SD API + 캐릭터 라이브러리
# ============================================================

import os
import json
import hashlib
import logging
import time
import threading
from queue import Queue, Empty
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field, asdict
from datetime import datetime
from utils.videotoon_contract import actor_id_from_slot, actor_identity_candidates_from_slot

try:
    from utils.logger import get_logger
    logger = get_logger("visual_storytelling_director")
except ImportError:
    logger = logging.getLogger(__name__)


# ============================================================
# 이미지 생성 결과 데이터 클래스
# ============================================================

@dataclass
class GeneratedImage:
    """생성된 이미지 정보"""
    path: str = ""                    # 이미지 파일 경로
    scene_id: str = ""                # 장면 ID
    dialogue_index: int = 0           # 대사 인덱스

    # 생성 정보
    action: str = "new"               # new, expression, pose, reuse
    prompt_positive: str = ""
    prompt_negative: str = ""

    # 캐릭터 정보 (expression/pose swap 시)
    character_id: str = ""
    expression: str = ""
    pose: str = ""

    # 메타데이터
    seed: int = -1
    generation_time: float = 0.0
    retry_count: int = 0
    parts: Dict[str, str] = field(default_factory=dict)

    # 품질 검증
    passed_quality_check: bool = True
    quality_issues: List[str] = field(default_factory=list)
    safe_image: bool = False              # v59.3.0: CRITICAL 위반 → 안전 이미지 대체 여부

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class StorytellingResult:
    """비주얼 스토리텔링 처리 결과"""
    images: List[GeneratedImage] = field(default_factory=list)

    # 통계
    total_dialogues: int = 0
    new_images: int = 0
    expression_swaps: int = 0
    pose_swaps: int = 0
    reuses: int = 0

    # 시간
    total_time: float = 0.0
    avg_generation_time: float = 0.0

    # 에러
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result['images'] = [img.to_dict() for img in self.images]
        return result


# ============================================================
# VisualStorytellingDirector 클래스
# ============================================================

class VisualStorytellingDirector:
    """
    v59: 비주얼 스토리텔링 통합 관리자

    전체 파이프라인:
    1. 대사 분석 (SceneAnalyzer)
    2. 프롬프트 생성 (PromptComposer)
    3. 이미지 액션 결정 (new/expression/pose/reuse)
    4. SD 이미지 생성 또는 캐릭터 라이브러리에서 선택
    5. 품질 검증 (얼굴/NSFW/블러)
    6. 결과 반환
    """

    def __init__(self,
                 config: Any = None,
                 gemini_client: Any = None,
                 sd_client: Any = None,
                 output_dir: str = "",
                 char_library_manager: Any = None,
                 bg_library: Any = None):
        """
        Args:
            config: VisualStorytellingConfig
            gemini_client: Gemini API 클라이언트
            sd_client: SD WebUI API 클라이언트
            output_dir: 이미지 저장 디렉토리
            char_library_manager: CharacterLibraryManager 인스턴스 (v59.1.3)
        """
        self.config = config
        self.gemini_client = gemini_client
        self.sd_client = sd_client
        self.output_dir = Path(output_dir) if output_dir else Path("temp/images")

        # v59.1.3: CharacterLibraryManager 연동
        self.char_library_manager = char_library_manager
        self.bg_library = bg_library

        # 내부 모듈 초기화
        self.scene_analyzer = None
        self.prompt_composer = None
        self.motiontoon_asset_pipeline = None
        self._init_modules()

        # 이전 이미지 캐시 (reuse용)
        self.previous_images: Dict[str, GeneratedImage] = {}
        self.character_panel_state: Dict[str, Dict[str, Any]] = {}
        self.location_panel_state: Dict[str, Dict[str, Any]] = {}
        self.cut_state_ledger: List[Dict[str, Any]] = []

        # 캐릭터 라이브러리 캐시
        self.character_libraries: Dict[str, Dict[str, str]] = {}

        # 연속 reuse 카운터
        self.consecutive_reuse_count = 0

        # v59.3.0: 마지막 정상 이미지 경로 (safe fallback용)
        self._last_good_image: Optional[str] = None

        logger.info("[VSD] VisualStorytellingDirector 초기화 완료")

    def _init_modules(self):
        """내부 모듈 초기화"""
        try:
            from modules_pro.scene_analyzer import SceneAnalyzer
            from modules_pro.prompt_composer import PromptComposer, char_defs_from_dict

            # v59.3.0: 캐릭터 정의 추출 (공통 유틸 사용)
            characters = []
            if self.config:
                # config가 dict인지 object인지 확인
                if isinstance(self.config, dict):
                    chars_raw = self.config.get('characters', {})
                else:
                    chars_raw = getattr(self.config, 'characters', {})

                # dict인 경우 공통 유틸로 변환
                if isinstance(chars_raw, dict):
                    characters = char_defs_from_dict(
                        chars_raw, include_aliases=True, include_lora=True
                    )
                    logger.info(f"[VSD] 캐릭터 dict → list 변환: {len(characters)}개")
                elif isinstance(chars_raw, list):
                    characters = chars_raw
                else:
                    logger.warning(f"[VSD] 알 수 없는 characters 타입: {type(chars_raw)}")

            # v59.3.0: SD 모델 설정 + positive_base/negative_base 추출 (경로 수정!)
            sd_model = None
            base_positive = ""
            base_negative = ""
            if self.config:
                if isinstance(self.config, dict):
                    sd_model = self.config.get('sd_model', None)
                    # v59.3.0: positive_base는 sd_model 안에 있음!
                    if isinstance(sd_model, dict):
                        base_positive = sd_model.get('positive_base', '')
                        base_negative = sd_model.get('negative_base', '')
                else:
                    sd_model = getattr(self.config, 'sd_model', None)
                    # v59.3.0: sd_model 객체에서 읽기
                    if sd_model:
                        base_positive = getattr(sd_model, 'positive_base', '')
                        base_negative = getattr(sd_model, 'negative_base', '')

            # v59.3.0: forced_style 합치기 (visual.forced_style → base에 통합)
            try:
                from config.pack_config import ACTIVE_PACK
                if ACTIVE_PACK.is_loaded:
                    forced = getattr(ACTIVE_PACK.visual, 'forced_style', {})
                    if isinstance(forced, dict) and forced:
                        force_pos = forced.get('force_positive', '')
                        force_neg = forced.get('force_negative', '')
                        if force_pos:
                            base_positive = f"{force_pos}, {base_positive}" if base_positive else force_pos
                            logger.info(f"[VSD] forced_style positive 적용: {force_pos[:60]}...")
                        if force_neg:
                            base_negative = f"{force_neg}, {base_negative}" if base_negative else force_neg
                            logger.info(f"[VSD] forced_style negative 적용: {force_neg[:60]}...")
            except ImportError:
                logger.debug("[VSD] pack_config import 실패 - forced_style 미적용")

            logger.info(f"[VSD] base_positive: {base_positive[:80]}..." if base_positive else "[VSD] base_positive: (비어있음)")
            logger.info(f"[VSD] base_negative: {base_negative[:80]}..." if base_negative else "[VSD] base_negative: (비어있음)")

            # v59.5.6: 팩에서 art_style_config 로드
            _art_style_cfg = None
            try:
                if ACTIVE_PACK.is_loaded:
                    _art_style_cfg = ACTIVE_PACK.scene_analyzer or None
            except Exception as e:
                logger.debug(f"[VSD] art_style_config 로드 실패 (무시): {e}")

            # SceneAnalyzer 초기화
            self.scene_analyzer = SceneAnalyzer(
                gemini_client=self.gemini_client,
                character_definitions=characters,
                art_style_config=_art_style_cfg
            )

            # PromptComposer 초기화
            if isinstance(self.config, dict):
                prompt_strategy = self.config.get('prompt_strategy', 'panel_card')
                llm_hint_tag_limit = self.config.get('llm_hint_tag_limit', 4)
            else:
                prompt_strategy = getattr(self.config, 'prompt_strategy', 'panel_card') if self.config else 'panel_card'
                llm_hint_tag_limit = getattr(self.config, 'llm_hint_tag_limit', 4) if self.config else 4

            self.prompt_composer = PromptComposer(
                character_definitions=characters,
                sd_model_config=sd_model,
                base_positive=base_positive,
                base_negative=base_negative,
                art_style_config=_art_style_cfg,
                prompt_strategy=prompt_strategy,
                llm_hint_tag_limit=llm_hint_tag_limit,
            )

            if self.char_library_manager:
                self.char_library_manager.prompt_composer = self.prompt_composer
            logger.info("[VSD] SceneAnalyzer, PromptComposer 초기화 완료")

        except ImportError as e:
            logger.error(f"[VSD] 모듈 import 실패: {e}")

    def is_enabled(self) -> bool:
        """비주얼 스토리텔링 활성화 여부"""
        if not self.config:
            return False
        # v59.1.3: dict/object 호환
        if isinstance(self.config, dict):
            return self.config.get('enabled', False)
        return getattr(self.config, 'enabled', False)

    def _build_dynamic_character_mapping(self, dialogues: List[Dict[str, str]]):
        """
        v59.3.3: 대본의 등장인물 이름을 팩 캐릭터 ID에 동적 매핑

        대본에 "서윤", "도진" 같은 고유 이름이 있으면,
        Gemini에게 한 번만 물어서 protagonist/man/woman 등으로 매핑.
        결과를 SceneAnalyzer.alias_to_id에 추가.
        """
        if not self.scene_analyzer:
            return

        self._apply_pack_cast_aliases()
        if self._apply_fixed_cast_role_mapping(dialogues):
            return

        # 1. 대본에서 모든 고유 speaker 추출
        speakers = set()
        for d in dialogues:
            speaker = d.get('speaker', d.get('role', ''))
            if speaker:
                speakers.add(speaker)

        # 2. 이미 매핑된 이름 제거
        unmapped = []
        for speaker in speakers:
            resolved_id = self.scene_analyzer._get_character_id(speaker)
            # _get_character_id는 매핑 없으면 입력값 그대로 반환
            # → 팩에 정의된 ID가 아니면 unmapped
            if resolved_id == speaker.lower() and resolved_id not in [
                c.lower() for c in self.scene_analyzer.alias_to_id.values()
            ]:
                unmapped.append(speaker)

        if not unmapped:
            logger.info("[VSD] 동적 매핑: 모든 캐릭터 이미 매핑됨")
            return

        # 3. 팩에 정의된 캐릭터 ID 목록
        available_ids = list(set(self.scene_analyzer.alias_to_id.values()))
        if not available_ids:
            available_ids = ['narrator', 'protagonist', 'man', 'woman', 'ghost', 'antagonist']

        logger.info(f"[VSD] 동적 매핑 필요: {unmapped} → 후보 ID: {available_ids}")

        # 4. Gemini에게 매핑 요청 (1회)
        # 대본 앞부분에서 맥락 추출
        context_lines = []
        for d in dialogues[:20]:  # 앞 20줄만
            speaker = d.get('speaker', d.get('role', ''))
            text = d.get('text', '')[:60]
            if speaker and text:
                context_lines.append(f"{speaker}: {text}")

        # Gemini 없으면 바로 폴백
        if not self.gemini_client:
            logger.info("[VSD] Gemini 미연결 → 폴백 매핑 사용")
            self._fallback_character_mapping(unmapped, dialogues)
            return

        prompt = f"""Analyze the characters in the following script and map each character to one of the available roles below.

Available character roles (English IDs):
{', '.join(available_ids)}

Characters that need mapping:
{', '.join(unmapped)}

Script excerpt (first 20 lines):
{chr(10).join(context_lines)}

Mapping rules:
1. Protagonist / main speaker → protagonist
2. Narration / narrator / commentary → narrator
3. Male supporting character → man
4. Female supporting character → woman
5. Villain / antagonist → antagonist
6. Ghost / supernatural entity → ghost
7. Elderly male → man (regardless of age)
8. Elderly female → woman (regardless of age)

Output ONLY the JSON below (no explanation):
{{"mappings": {{"Korean character name": "English role ID", ...}}}}"""

        try:
            # v62.18: 명시적 timeout (기본 30초 → 60초, 캐릭터 매핑은 간단하지만 여유 확보)
            response = self.gemini_client.generate_content(prompt, timeout=60)
            response_text = response.text.strip() if hasattr(response, 'text') else str(response).strip()

            # JSON 추출
            json_str = response_text
            if "```json" in json_str:
                json_str = json_str.split("```json")[1].split("```")[0]
            elif "```" in json_str:
                json_str = json_str.split("```")[1].split("```")[0]

            data = json.loads(json_str)
            mappings = data.get('mappings', {})

            # 5. SceneAnalyzer에 매핑 추가
            added = 0
            for name, char_id in mappings.items():
                if char_id.lower() in [aid.lower() for aid in available_ids]:
                    self.scene_analyzer.alias_to_id[name.lower()] = char_id.lower()
                    added += 1
                    logger.info(f"[VSD] 동적 매핑: '{name}' → '{char_id}'")
                else:
                    logger.warning(f"[VSD] 동적 매핑 무시 (유효하지 않은 ID): '{name}' → '{char_id}'")

            logger.info(f"[VSD] 동적 매핑 완료: {added}/{len(unmapped)}개 매핑됨")

        except Exception as e:
            logger.warning(f"[VSD] 동적 매핑 실패 (폴백: speaker 기반 추론): {e}")
            # 폴백: 간단한 규칙 기반 매핑
            self._fallback_character_mapping(unmapped, dialogues)

    def _fallback_character_mapping(self, unmapped: List[str], dialogues: List[Dict[str, str]]):
        """v59.3.3: Gemini 실패 시 규칙 기반 폴백 매핑"""
        if self._apply_fixed_cast_role_mapping(dialogues, only_unmapped=unmapped):
            return
        # speaker별 등장 횟수 카운트
        speaker_count = {}
        for d in dialogues:
            speaker = d.get('speaker', d.get('role', ''))
            if speaker in unmapped:
                speaker_count[speaker] = speaker_count.get(speaker, 0) + 1

        # 가장 많이 나오는 순서대로 역할 배정
        sorted_speakers = sorted(speaker_count.items(), key=lambda x: -x[1])
        role_queue = ['protagonist', 'woman', 'man', 'antagonist']
        role_idx = 0

        for speaker, count in sorted_speakers:
            if speaker.lower() in ['나레이션', '나레이터', 'narrator', '해설']:
                self.scene_analyzer.alias_to_id[speaker.lower()] = 'narrator'
                logger.info(f"[VSD] 폴백 매핑: '{speaker}' → 'narrator' (규칙)")
            elif role_idx < len(role_queue):
                assigned = role_queue[role_idx]
                self.scene_analyzer.alias_to_id[speaker.lower()] = assigned
                logger.info(f"[VSD] 폴백 매핑: '{speaker}' → '{assigned}' (등장횟수 {count}위)")
                role_idx += 1
            else:
                # 남은 캐릭터는 _default로
                self.scene_analyzer.alias_to_id[speaker.lower()] = 'man'
                logger.info(f"[VSD] 폴백 매핑: '{speaker}' → 'man' (기본)")

    def _get_pack_motiontoon_cast_slots(self) -> Dict[str, Dict[str, Any]]:
        try:
            from config.pack_config import get_motiontoon_config

            motiontoon = get_motiontoon_config()
            slots = getattr(motiontoon, "cast_slots", {}) or {}
            if isinstance(slots, dict):
                return slots
        except Exception as e:
            logger.debug(f"[VSD] pack motiontoon cast_slots load failed: {e}")
        return {}

    def _resolve_motiontoon_slot_name(self, char_id: str) -> str:
        normalized_char = str(char_id or "").strip().lower()
        if not normalized_char:
            return ""
        for slot_name, slot_data in self._get_pack_motiontoon_cast_slots().items():
            if not isinstance(slot_data, dict):
                continue
            slot_ids = {
                candidate.strip().lower()
                for candidate in actor_identity_candidates_from_slot(slot_data)
                if candidate.strip()
            }
            if normalized_char in slot_ids:
                return str(slot_name)
        return ""

    def _get_pack_motiontoon_config(self) -> Any:
        try:
            from config.pack_config import get_motiontoon_config

            return get_motiontoon_config()
        except Exception as e:
            logger.debug(f"[VSD] pack motiontoon config load failed: {e}")
            return None

    def _get_pack_motiontoon_puppet_profiles(self) -> Dict[str, Dict[str, Any]]:
        try:
            from config.pack_config import get_motiontoon_config

            motiontoon = get_motiontoon_config()
            profiles = getattr(motiontoon, "puppet_profiles", {}) or {}
            if isinstance(profiles, dict):
                return profiles
        except Exception as e:
            logger.debug(f"[VSD] pack motiontoon puppet_profiles load failed: {e}")
        return {}

    def _get_motiontoon_rig_overrides(self, char_id: str, emotion: str = "", pose: str = "") -> Dict[str, Any]:
        if not char_id:
            return {}

        slots = self._get_pack_motiontoon_cast_slots()
        profiles = self._get_pack_motiontoon_puppet_profiles()
        motiontoon = self._get_pack_motiontoon_config()
        normalized_char = str(char_id).strip().lower()
        slot_name = ""
        for candidate_slot, slot_data in slots.items():
            if not isinstance(slot_data, dict):
                continue
            slot_ids = {
                candidate.strip().lower()
                for candidate in actor_identity_candidates_from_slot(slot_data)
                if candidate.strip()
            }
            if normalized_char in slot_ids:
                slot_name = str(candidate_slot)
                break

        if not slot_name:
            return {}

        profile = profiles.get(slot_name, {}) if isinstance(profiles, dict) else {}
        if not isinstance(profile, dict):
            profile = {}

        rig = {
            "cast_slot": slot_name,
            "character_id_hint": char_id,
            "overlay_theme": str(getattr(motiontoon, "overlay_theme", "") or ""),
            "emotion_hint": str(emotion or "").strip().lower(),
            "pose_hint": str(pose or "").strip().lower(),
            "face_anchor_x": float(profile.get("face_anchor_x", 0.5) or 0.5),
            "face_anchor_y": float(profile.get("face_anchor_y", 0.33) or 0.33),
            "face_scale": float(profile.get("face_scale", 1.0) or 1.0),
            "bob_strength": float(profile.get("bob_strength", 1.0) or 1.0),
            "face_rig_requested": bool(
                getattr(motiontoon, "blink_enabled", False)
                or getattr(motiontoon, "mouth_flap_enabled", False)
            ),
        }

        normalized_emotion = str(emotion or "").strip().lower()
        normalized_pose = str(pose or "").strip().lower()
        if normalized_emotion in {"fear", "sad", "sadness"}:
            rig["face_anchor_y"] = max(0.24, rig["face_anchor_y"] - 0.01)
        if normalized_pose in {"sitting", "kneeling"}:
            rig["bob_strength"] = max(0.45, rig["bob_strength"] * 0.82)
            rig["face_scale"] = max(0.82, rig["face_scale"] * 0.97)

        return rig

    def _get_motiontoon_performance_rig(
        self,
        char_id: str,
        emotion: str = "",
        pose: str = "",
        scene_id: str = "",
        sprite_kind: str = "",
    ) -> Dict[str, Any]:
        """Create deterministic shot blocking so consistency does not become one frozen sprite."""
        if not char_id:
            return {}

        seed_key = f"{char_id}|{emotion}|{pose}|{scene_id}"
        digest = hashlib.sha1(seed_key.encode("utf-8", errors="ignore")).hexdigest()
        seed = int(digest[:8], 16)
        emotion_norm = str(emotion or "neutral").strip().lower()
        pose_norm = str(pose or "standing").strip().lower()
        sprite_kind_norm = str(sprite_kind or "").strip().lower()
        high_emotion = any(
            token in emotion_norm
            for token in ("fear", "worried", "sad", "cry", "shock", "surprise", "angry", "panic")
        )

        if sprite_kind_norm == "expression_portrait" or high_emotion:
            close_profiles = [
                ("close_reaction", 0.48, 0.66, 0.56, -1.4, "reaction_hold"),
                ("close_listen", 0.55, 0.67, 0.58, 1.2, "listening_turn"),
                ("close_emphasis", 0.50, 0.68, 0.60, -0.6, "speaking_emphasis"),
            ]
            shot_size, center_x, center_y, height, lean, acting_pose = close_profiles[seed % len(close_profiles)]
        else:
            medium_profiles = [
                ("medium", 0.50, 0.80, 0.76, 0.0, "grounded_talk"),
                ("medium_left", 0.43, 0.81, 0.74, -1.0, "lean_in"),
                ("medium_right", 0.58, 0.81, 0.74, 1.0, "listening_turn"),
                ("wide", 0.52, 0.84, 0.68, 0.4, "reaction_hold"),
            ]
            shot_size, center_x, center_y, height, lean, acting_pose = medium_profiles[seed % len(medium_profiles)]

        if "sitting" in pose_norm or "kneel" in pose_norm:
            center_y = min(0.90, center_y + 0.04)
            height = max(0.58, height - 0.06)
        if "point" in pose_norm or "gesture" in pose_norm:
            acting_pose = "speaking_emphasis"
            lean += -0.8 if seed % 2 == 0 else 0.8

        return {
            "shot_size": shot_size,
            "acting_pose": acting_pose,
            "sprite_center_x": round(center_x, 4),
            "sprite_center_y": round(center_y, 4),
            "sprite_height_ratio": round(height, 4),
            "sprite_enter_px": 10 + (seed % 14),
            "sprite_parallax_px": 3 + (seed % 5),
            "sprite_lean_deg": round(lean, 3),
            "sprite_breathe_px": 0.8 if high_emotion else 1.2,
            "sprite_focus_scale": 1.015 if high_emotion else 1.0,
            "puppet_bob": False,
            "bob_strength": 0.18,
        }

    def _use_simple_character_sprite_mode(self) -> bool:
        motiontoon = self._get_pack_motiontoon_config()
        mode = str(getattr(motiontoon, "character_layer_mode", "") or "").strip().lower()
        return mode in {"simple_sprite", "character_sprite"}

    def _get_motiontoon_asset_pipeline(self):
        if self.motiontoon_asset_pipeline is None:
            try:
                from modules_pro.motiontoon_asset_pipeline import MotiontoonAssetPipeline

                self.motiontoon_asset_pipeline = MotiontoonAssetPipeline()
            except Exception as e:
                logger.debug(f"[VSD] motiontoon asset pipeline init failed: {e}")
                self.motiontoon_asset_pipeline = False
        return self.motiontoon_asset_pipeline or None

    @staticmethod
    def _merge_prompt_parts(parts: List[str]) -> str:
        merged: List[str] = []
        seen = set()
        for part in parts:
            cleaned = str(part or "").strip().strip(",")
            if not cleaned:
                continue
            key = cleaned.lower()
            if key in seen:
                continue
            seen.add(key)
            merged.append(cleaned)
        return ", ".join(merged)

    @staticmethod
    def _stable_scene_index(scene: Any) -> int:
        scene_id = str(getattr(scene, "scene_id", "") or "")
        try:
            return int(scene_id.split("_")[-1])
        except Exception:
            return 0

    def _get_pack_visual_prompt_pool(self, field_name: str) -> List[str]:
        try:
            from config.pack_config import ACTIVE_PACK

            if getattr(ACTIVE_PACK, "is_loaded", False):
                visual = getattr(ACTIVE_PACK, "visual", None)
                values = getattr(visual, field_name, None) if visual else None
                if isinstance(values, list):
                    return [str(v).strip() for v in values if str(v).strip()]
        except Exception as e:
            logger.debug(f"[VSD] visual prompt pool load failed ({field_name}): {e}")
        return []

    def _pick_background_hint(self, scene: Any) -> str:
        location = str(getattr(scene, "location", "") or "").strip()
        time_of_day = str(getattr(scene, "time_of_day", "") or "").strip()
        key_props = [str(v).strip() for v in (getattr(scene, "key_props", []) or []) if str(v).strip()]
        scene_type = str(getattr(scene, "scene_type", "") or "").strip()

        hint_parts: List[str] = []
        if location:
            hint_parts.append(location)
        if key_props:
            hint_parts.append(", ".join(key_props[:3]))
        if time_of_day:
            hint_parts.append(time_of_day)
        if scene_type in {"memory", "reveal", "prop_reveal"}:
            hint_parts.append("storytelling object focus")

        if hint_parts:
            return ", ".join(hint_parts)

        fallback_pool = self._get_pack_visual_prompt_pool("thumbnail_backgrounds")
        if not fallback_pool:
            fallback_pool = self._get_pack_visual_prompt_pool("safe_fallbacks")
        if fallback_pool:
            return fallback_pool[self._stable_scene_index(scene) % len(fallback_pool)]

        return "empty hanok courtyard, simple wooden door, warm lamp light, no people"

    def _build_background_plate_prompt(self, scene: Any, composed: Any) -> Any:
        """Build a background-only prompt for simple sprite motiontoon scenes."""
        prompt_cls = type(composed)
        background_hint = self._pick_background_hint(scene)
        positive = self._merge_prompt_parts(
            [
                getattr(composed, "style_prompt", ""),
                background_hint,
                "empty background plate, no people, no person, no character, no portrait, no close-up face, environment only, readable layout, stable background for 2d puppet compositing, clean stage-like background, no giant mascot, no floating icon, no cutaway panel",
            ]
        )
        negative = self._merge_prompt_parts(
            [
                getattr(composed, "negative", ""),
                "person, people, man, woman, child, girl, boy, face, portrait, centered subject, solo, standing character, body, hands in foreground, close-up character, 1girl, 1boy, mascot, emoji face, animal mascot, giant floating object, panel border, comic insert, speech bubble",
            ]
        )

        return prompt_cls(
            positive=positive,
            negative=negative,
            scene_id=getattr(composed, "scene_id", ""),
            character_prompts=[],
            scene_prompt=getattr(composed, "scene_prompt", ""),
            style_prompt=getattr(composed, "style_prompt", ""),
            lora_triggers=[],
            continuity_hint=getattr(composed, "continuity_hint", ""),
            camera_shot=getattr(composed, "camera_shot", ""),
            key_props=list(getattr(composed, "key_props", []) or []),
            outfit_hint="",
            width=getattr(composed, "width", 768),
            height=getattr(composed, "height", 432),
            steps=getattr(composed, "steps", 15),
            cfg_scale=getattr(composed, "cfg_scale", 7.0),
            sampler=getattr(composed, "sampler", "DPM++ 2M Karras"),
            seed=getattr(composed, "seed", -1),
            checkpoint=getattr(composed, "checkpoint", ""),
            vae=getattr(composed, "vae", ""),
            clip_skip=getattr(composed, "clip_skip", 0),
            scheduler=getattr(composed, "scheduler", ""),
        )

    @staticmethod
    def _normalize_background_time(value: str) -> str:
        normalized = str(value or "").strip().lower()
        mapping = {
            "morning": "낮",
            "day": "낮",
            "afternoon": "낮",
            "daytime": "낮",
            "evening": "저녁",
            "dusk": "저녁",
            "sunset": "저녁",
            "night": "밤",
            "midnight": "밤",
            "dawn": "새벽",
            "early morning": "새벽",
            "낮": "낮",
            "밤": "밤",
            "새벽": "새벽",
            "저녁": "저녁",
        }
        return mapping.get(normalized, "any")

    def _generate_background_plate_from_library(
        self,
        scene: Any,
        scene_id: str,
        output_path: Path,
    ) -> Optional[str]:
        if not self.bg_library:
            return None

        location = str(getattr(scene, "location", "") or "").strip()
        location_detail = str(getattr(scene, "location_detail", "") or "").strip()
        prompt_hint = str(getattr(scene, "sd_prompt", "") or "").strip()
        location_candidates = [candidate for candidate in [location, location_detail, prompt_hint] if candidate]
        if not location_candidates:
            return None

        time_hint = self._normalize_background_time(getattr(scene, "time_of_day", ""))
        mood_hint = str(getattr(scene, "atmosphere", "") or "").strip() or "any"

        try:
            bg_path = None
            for candidate in location_candidates:
                bg_path = self.bg_library.get_background_image(
                    location=candidate,
                    time=time_hint,
                    mood=mood_hint,
                )
                if bg_path:
                    break
            generation_candidates = []
            if self.sd_client and self.bg_library:
                try:
                    for candidate in location_candidates:
                        matched = self.bg_library._match_location(candidate) if hasattr(self.bg_library, "_match_location") else ""
                        if matched and len(getattr(self.bg_library, "images", {}).get(matched, []) or []) < 3:
                            if matched not in generation_candidates:
                                generation_candidates.append(matched)
                except Exception:
                    generation_candidates = list(location_candidates) if not bg_path else []
            if not bg_path and not generation_candidates:
                generation_candidates = list(location_candidates)
            if generation_candidates and self.sd_client:
                self.bg_library.generate_background_library(
                    sd_api=self.sd_client,
                    locations=generation_candidates,
                    images_per_location=3,
                    time_variants=False,
                )
                for candidate in location_candidates:
                    bg_path = self.bg_library.get_background_image(
                        location=candidate,
                        time="any",
                        mood=mood_hint,
                    )
                    if bg_path:
                        break

            if bg_path and os.path.exists(bg_path):
                import shutil

                shutil.copy(bg_path, str(output_path))
                return str(output_path)
        except Exception as e:
            logger.debug(f"[VSD] background library plate failed ({scene_id}): {e}")

        return None

    def _compose_scene_motiontoon_assets(
        self,
        scene_image_path: str,
        *,
        background_source_path: str,
        sprite_source_path: str = "",
        char_id: str = "",
        emotion: str = "",
        pose: str = "",
    ) -> Dict[str, str]:
        if not self.char_library_manager or not scene_image_path or not os.path.exists(scene_image_path):
            return {}

        if self._use_simple_character_sprite_mode():
            pipeline = self._get_motiontoon_asset_pipeline()
            if not pipeline:
                return {}
            rig_overrides = self._get_motiontoon_rig_overrides(char_id, emotion, pose)
            overlay_kind = str(rig_overrides.get("overlay_kind", "document") or "document")
            layer_part_overrides = {}
            face_part_overrides = {}
            if char_id and self.char_library_manager:
                try:
                    variant = self.char_library_manager.get_character_sheet_variant(
                        char_id,
                        expression=emotion or "neutral",
                        pose=pose or "standing",
                        fallback=True,
                    )
                    if isinstance(variant, dict):
                        layer_part_overrides = {
                            key: value
                            for key, value in dict(variant.get("parts", {}) or {}).items()
                            if value
                        }
                        face_part_overrides = {
                            key: value
                            for key, value in dict(variant.get("face_parts", {}) or {}).items()
                            if value
                        }
                    if hasattr(self.char_library_manager, "get_external_videotoon_sprite_variant"):
                        external_variant = self.char_library_manager.get_external_videotoon_sprite_variant(
                            char_id,
                            expression=emotion or "neutral",
                            pose=pose or "standing",
                        )
                        external_parts = {
                            key: value
                            for key, value in dict(external_variant.get("parts", {}) or {}).items()
                            if value
                        }
                        if external_parts:
                            layer_part_overrides.update(external_parts)
                            face_part_overrides = {
                                key: value
                                for key, value in dict(external_variant.get("face_parts", {}) or {}).items()
                                if value
                            }
                            rig_overrides.update(dict(external_variant.get("rig", {}) or {}))
                except Exception as e:
                    logger.debug(f"[VSD] face part overrides load failed ({char_id}): {e}")
            rig_overrides.update(
                self._get_motiontoon_performance_rig(
                    char_id,
                    emotion,
                    pose,
                    Path(scene_image_path).stem,
                    str(rig_overrides.get("sprite_kind", "") or ""),
                )
            )
            return pipeline.build_scene_assets(
                scene_image_path,
                background_source_path=background_source_path,
                sprite_source_path=sprite_source_path,
                layer_part_overrides=layer_part_overrides,
                face_part_overrides=face_part_overrides,
                rig_overrides=rig_overrides,
                overlay_kind=overlay_kind,
            )

        try:
            from utils.layered_cutout import attach_layered_cutout_assets
        except Exception as e:
            logger.debug(f"[VSD] motiontoon asset compose import failed: {e}")
            return {}

        rig_overrides = self._get_motiontoon_rig_overrides(char_id, emotion, pose)
        overlay_kind = str(rig_overrides.get("overlay_kind", "document") or "document")

        background_assets = {}
        if background_source_path and os.path.exists(background_source_path):
            try:
                background_assets = self.char_library_manager.prime_motiontoon_parts(
                    background_source_path,
                    overlay_kind=overlay_kind,
                )
            except Exception as e:
                logger.debug(f"[VSD] background plate prime failed ({background_source_path}): {e}")

        sprite_assets = {}
        if sprite_source_path and os.path.exists(sprite_source_path):
            try:
                sprite_assets = self.char_library_manager.prime_motiontoon_parts(
                    sprite_source_path,
                    overlay_kind=overlay_kind,
                    rig_overrides=rig_overrides,
                )
            except Exception as e:
                logger.debug(f"[VSD] sprite prime failed ({sprite_source_path}): {e}")

        if not sprite_assets and background_assets:
            if self._use_simple_character_sprite_mode():
                simple_background = {
                    "background_path": str(background_assets.get("background_path", "") or background_source_path),
                }
                attached = attach_layered_cutout_assets(
                    scene_image_path,
                    simple_background,
                    overlay_kind=overlay_kind,
                    strength=0.82,
                    rig_overrides=rig_overrides,
                )
                return attached or simple_background
            return background_assets
        if not background_assets and sprite_assets:
            return sprite_assets
        if not sprite_assets and not background_assets:
            return {}

        combined = {
            "background_path": str(background_assets.get("background_path", "") or background_source_path),
            "foreground_path": str(sprite_assets.get("foreground_path", "") or ""),
            "head_path": str(sprite_assets.get("head_path", "") or ""),
            "body_path": str(sprite_assets.get("body_path", "") or ""),
            "left_arm_path": str(sprite_assets.get("left_arm_path", "") or ""),
            "right_arm_path": str(sprite_assets.get("right_arm_path", "") or ""),
            "eyes_open_path": str(sprite_assets.get("eyes_open_path", "") or ""),
            "eyes_closed_path": str(sprite_assets.get("eyes_closed_path", "") or ""),
            "mouth_closed_path": str(sprite_assets.get("mouth_closed_path", "") or ""),
            "mouth_open_path": str(sprite_assets.get("mouth_open_path", "") or ""),
        }

        attached = attach_layered_cutout_assets(
            scene_image_path,
            combined,
            overlay_kind=overlay_kind,
            strength=0.82,
            rig_overrides=rig_overrides,
        )
        return attached or combined

    def _build_simple_sprite_background_only_parts(
        self,
        image_path: str,
        *,
        char_id: str = "",
        emotion: str = "",
        pose: str = "",
    ) -> Dict[str, str]:
        if not image_path or not os.path.exists(image_path):
            return {}
        if self._use_simple_character_sprite_mode():
            pipeline = self._get_motiontoon_asset_pipeline()
            if not pipeline:
                return {}
            rig_overrides = self._get_motiontoon_rig_overrides(char_id, emotion, pose)
            overlay_kind = str(rig_overrides.get("overlay_kind", "document") or "document")
            return pipeline.build_background_only_assets(
                image_path,
                background_source_path=image_path,
                rig_overrides=rig_overrides,
                overlay_kind=overlay_kind,
            )
        try:
            from utils.layered_cutout import attach_layered_cutout_assets
        except Exception as e:
            logger.debug(f"[VSD] simple sprite fallback import failed: {e}")
            return {}

        rig_overrides = self._get_motiontoon_rig_overrides(char_id, emotion, pose)
        overlay_kind = str(rig_overrides.get("overlay_kind", "document") or "document")
        assets = {"background_path": str(image_path)}
        attached = attach_layered_cutout_assets(
            image_path,
            assets,
            overlay_kind=overlay_kind,
            strength=0.82,
            rig_overrides=rig_overrides,
        )
        return attached or assets

    def _ensure_simple_sprite_library_image(self, char_id: str, emotion: str, pose: str) -> str:
        if not char_id or not self.char_library_manager or not self.prompt_composer:
            return ""

        current = self._get_from_library(char_id, emotion, pose)
        if current and os.path.exists(current):
            return current

        char_map = getattr(self.prompt_composer, "char_map", {}) or {}
        character_def = char_map.get(char_id)
        if not character_def:
            return ""

        try:
            success, _ = self.char_library_manager.generate_character_library(
                character_def=character_def,
                variant_keys=[f"{emotion}_{pose}"],
                images_per_combo=1,
            )
            if success:
                refreshed = self._get_from_library(char_id, emotion, pose)
                if refreshed and os.path.exists(refreshed):
                    logger.info(f"[VSD] simple sprite 라이브러리 생성 완료: {char_id}/{emotion}_{pose}")
                    return refreshed
        except Exception as e:
            logger.warning(f"[VSD] simple sprite 라이브러리 생성 실패 ({char_id}/{emotion}_{pose}): {e}")

        return ""

    def _apply_pack_cast_aliases(self) -> None:
        if not self.scene_analyzer:
            return

        slots = self._get_pack_motiontoon_cast_slots()
        if not slots:
            return

        applied = 0
        for slot_name, slot_data in slots.items():
            if not isinstance(slot_data, dict):
                continue
            actor_id = actor_id_from_slot(slot_data).lower()
            if not actor_id:
                continue
            aliases = [slot_name]
            aliases.extend(slot_data.get("aliases", []) or [])
            for alias in aliases:
                alias_clean = str(alias).strip().lower()
                if not alias_clean:
                    continue
                self.scene_analyzer.alias_to_id[alias_clean] = actor_id
                applied += 1

        if applied:
            logger.info(f"[VSD] pack cast alias applied: {applied} aliases")

    def _get_pack_preferred_character_ids(self) -> List[str]:
        slots = self._get_pack_motiontoon_cast_slots()
        preferred: List[str] = []
        for slot_name in ("protagonist", "deuteragonist", "child", "antagonist", "elder", "support"):
            slot_data = slots.get(slot_name, {})
            if not isinstance(slot_data, dict):
                continue
            actor_id = actor_id_from_slot(slot_data)
            if actor_id and actor_id not in preferred:
                preferred.append(actor_id)
        return preferred

    def _get_pack_slot_order(self) -> List[str]:
        slots = self._get_pack_motiontoon_cast_slots()
        ordered = [slot for slot in ("protagonist", "deuteragonist", "child", "antagonist", "elder", "support") if slot in slots]
        for slot_name in slots.keys():
            slot_name = str(slot_name)
            if slot_name not in ordered:
                ordered.append(slot_name)
        return ordered

    @staticmethod
    def _is_narration_like_speaker(speaker: str) -> bool:
        return str(speaker or "").strip().lower() in {
            "",
            "narrator",
            "narration",
            "나레이션",
            "내레이션",
            "나레이터",
            "해설",
        }

    def _infer_pack_slot_for_speaker(self, speaker: str) -> str:
        speaker_clean = str(speaker or "").strip().lower()
        if not speaker_clean:
            return ""

        slots = self._get_pack_motiontoon_cast_slots()
        partial_matches: List[Tuple[int, str]] = []
        for slot_name, slot_data in slots.items():
            if not isinstance(slot_data, dict):
                continue
            aliases = [slot_name]
            aliases.extend(slot_data.get("aliases", []) or [])
            for alias in aliases:
                alias_clean = str(alias or "").strip().lower()
                if not alias_clean:
                    continue
                if speaker_clean == alias_clean:
                    return str(slot_name)
                if len(alias_clean) >= 2 and (alias_clean in speaker_clean or speaker_clean in alias_clean):
                    partial_matches.append((len(alias_clean), str(slot_name)))

        if partial_matches:
            partial_matches.sort(key=lambda item: (-item[0], item[1]))
            return partial_matches[0][1]

        child_tokens = ("아이", "사내아이", "계집아이", "소년", "소녀", "동자", "돌이", "애기", "어린", "child")
        female_elder_tokens = ("할머니", "할매", "엄마", "어머니", "노파", "노모", "어멈", "grandma")
        male_elder_tokens = ("할아버지", "할배", "아버지", "아빠", "노인", "어르신", "훈장", "grandpa")
        antagonist_tokens = ("범인", "사기꾼", "사장", "팀장", "과장", "점장", "원장", "도둑", "악인")
        support_tokens = ("아이", "소년", "소녀", "학생", "하인", "종", "동무", "친구")

        if any(token in speaker_clean for token in child_tokens) and "child" in slots:
            return "child"
        if any(token in speaker_clean for token in female_elder_tokens) and "elder" in slots:
            return "elder"
        if any(token in speaker_clean for token in male_elder_tokens):
            if "support" in slots:
                support_data = slots.get("support", {})
                support_id = actor_id_from_slot(support_data).lower()
                if support_id in {"grandpa", "middle_man", "young_man", "man"}:
                    return "support"
            if "elder" in slots:
                elder_data = slots.get("elder", {})
                elder_id = actor_id_from_slot(elder_data).lower()
                if elder_id in {"grandpa", "middle_man", "young_man", "man"}:
                    return "elder"
        if any(token in speaker_clean for token in antagonist_tokens) and "antagonist" in slots:
            return "antagonist"
        if any(token in speaker_clean for token in support_tokens):
            if "support" in slots:
                return "support"
            if "deuteragonist" in slots:
                return "deuteragonist"
        return ""

    def _apply_fixed_cast_role_mapping(
        self,
        dialogues: List[Dict[str, str]],
        only_unmapped: Optional[List[str]] = None,
    ) -> bool:
        if not self.scene_analyzer:
            return False

        slots = self._get_pack_motiontoon_cast_slots()
        if not slots:
            return False

        slot_order = self._get_pack_slot_order()
        fixed_ids = {
            actor_id_from_slot(slot_data).lower()
            for slot_data in slots.values()
            if isinstance(slot_data, dict)
        }
        fixed_ids.discard("")
        if not slot_order or not fixed_ids:
            return False

        speaker_counts: Dict[str, int] = {}
        first_seen: Dict[str, int] = {}
        for idx, dialogue in enumerate(dialogues):
            speaker = str(dialogue.get("speaker") or dialogue.get("character") or dialogue.get("role") or "").strip()
            if self._is_narration_like_speaker(speaker):
                continue

            resolved = ""
            try:
                resolved = str(self.scene_analyzer._get_character_id(speaker) or "").strip().lower()
            except Exception:
                resolved = ""

            if resolved in fixed_ids:
                self.scene_analyzer.alias_to_id[speaker.lower()] = resolved
                continue

            if only_unmapped and speaker not in only_unmapped and resolved in fixed_ids:
                self.scene_analyzer.alias_to_id[speaker.lower()] = resolved
                continue

            speaker_counts[speaker] = speaker_counts.get(speaker, 0) + 1
            first_seen.setdefault(speaker, idx)

        if not speaker_counts:
            return False

        slot_assignments: Dict[str, str] = {}
        speaker_assignments: Dict[str, str] = {}

        for speaker in speaker_counts.keys():
            inferred_slot = self._infer_pack_slot_for_speaker(speaker)
            if not inferred_slot:
                continue
            slot_data = slots.get(inferred_slot, {})
            actor_id = actor_id_from_slot(slot_data).lower()
            if not actor_id or inferred_slot in slot_assignments:
                continue
            slot_assignments[inferred_slot] = speaker
            speaker_assignments[speaker] = actor_id

        ranked_speakers = sorted(
            speaker_counts.items(),
            key=lambda item: (-item[1], first_seen[item[0]], item[0]),
        )

        available_slots = [slot for slot in slot_order if slot not in slot_assignments]
        fallback_slot = available_slots[-1] if available_slots else (slot_order[-1] if slot_order else "")
        for speaker, _count in ranked_speakers:
            if speaker in speaker_assignments:
                continue
            slot_name = available_slots.pop(0) if available_slots else fallback_slot
            if not slot_name:
                continue
            slot_data = slots.get(slot_name, {})
            actor_id = actor_id_from_slot(slot_data).lower()
            if not actor_id:
                continue
            slot_assignments.setdefault(slot_name, speaker)
            speaker_assignments[speaker] = actor_id

        applied = 0
        for speaker, actor_id in speaker_assignments.items():
            self.scene_analyzer.alias_to_id[speaker.lower()] = actor_id
            logger.info(f"[VSD] fixed cast mapping: '{speaker}' -> '{actor_id}'")
            applied += 1

        return applied > 0

    def process_dialogues(self, dialogues: List[Dict[str, str]],
                          job_id: str = "",
                          pipeline_mode: bool = True,
                          pre_analyzed_scenes: Optional[Dict] = None,
                          image_callback: Optional[Any] = None) -> StorytellingResult:
        """
        대사 목록을 처리하여 이미지 생성

        v59.2.3: Producer-Consumer 파이프라인 모드 추가
        - SceneAnalyzer 분석 완료 즉시 SD 이미지 생성 시작
        - SD[n+1] 생성 중 QC[n] 검증 동시 진행

        v62.18: pre_analyzed_scenes 캐시 전달 지원
        - orchestrator에서 TTS 병렬로 이미 분석한 결과를 재사용
        - 이중 SceneAnalyzer 호출 방지 (Gemini API 절감)

        Args:
            dialogues: [{"speaker": "...", "text": "..."}, ...]
            job_id: 작업 ID (파일명용)
            pipeline_mode: True면 병렬 파이프라인 (기본값)
            pre_analyzed_scenes: {idx: SceneAnalysisResult} 사전 분석 캐시 (없으면 내부 분석)

        Returns:
            StorytellingResult
        """
        start_time = time.time()
        result = StorytellingResult(total_dialogues=len(dialogues))

        if not self.is_enabled():
            logger.warning("[VSD] 비주얼 스토리텔링 비활성화됨")
            result.errors.append("Visual storytelling is disabled")
            return result

        # v59.3.0: 상태 초기화 (이전 실행 잔류 방지)
        self.consecutive_reuse_count = 0
        self._last_good_image = None
        self.previous_images = {}
        self.character_panel_state = {}
        self.location_panel_state = {}
        self.cut_state_ledger = []
        if self.scene_analyzer:
            self.scene_analyzer.previous_scenes = []

        logger.info(f"[VSD] 처리 시작: {len(dialogues)}개 대사 (파이프라인={pipeline_mode})")

        # v59.3.3: 동적 캐릭터 매핑 — 대본의 인물 이름을 팩 캐릭터 ID에 자동 매핑
        self._build_dynamic_character_mapping(dialogues)
        self._ensure_major_character_references(dialogues)

        # 출력 디렉토리 생성
        output_path = self.output_dir / job_id if job_id else self.output_dir
        output_path.mkdir(parents=True, exist_ok=True)

        if not pipeline_mode or len(dialogues) <= 3:
            return self._process_dialogues_sequential(
                dialogues,
                result,
                output_path,
                start_time,
                pre_analyzed_scenes=pre_analyzed_scenes,
                image_callback=image_callback,
            )

        return self._process_dialogues_pipeline(
            dialogues,
            result,
            output_path,
            start_time,
            pre_analyzed_scenes=pre_analyzed_scenes,
            image_callback=image_callback,
        )

    def _resolve_dialogue_character_id(self, speaker: str) -> str:
        narrator_ids = {"narrator", "narration", "나레이션", "나레이터"}
        speaker_clean = (speaker or "").strip()
        if not speaker_clean or speaker_clean.lower() in narrator_ids:
            return ""

        if self.char_library_manager:
            try:
                resolved = self.char_library_manager.find_character_by_alias(speaker_clean)
                if resolved and resolved.lower() not in narrator_ids:
                    return resolved
            except Exception:
                pass

        if self.scene_analyzer and hasattr(self.scene_analyzer, "_get_character_id"):
            try:
                resolved = self.scene_analyzer._get_character_id(speaker_clean)
                if resolved and resolved.lower() not in narrator_ids:
                    return resolved
            except Exception:
                pass

        return ""

    def _apply_dialogue_visual_hints(self, scene: Any, dialogue: Dict[str, Any]) -> Any:
        """Prefer explicit script-level visual hints over analyzer guesses."""
        if not scene or not dialogue:
            return scene

        location = str(dialogue.get("location", "") or "").strip()
        if location:
            scene.location = location

        location_detail = str(dialogue.get("location_detail", "") or "").strip()
        if location_detail:
            scene.location_detail = location_detail

        time_hint = str(dialogue.get("time_of_day", "") or dialogue.get("time", "") or "").strip()
        if time_hint:
            scene.time_of_day = time_hint

        weather_hint = str(dialogue.get("weather", "") or "").strip()
        if weather_hint:
            scene.weather = weather_hint

        mood_hint = str(dialogue.get("atmosphere", "") or dialogue.get("mood", "") or "").strip()
        if mood_hint:
            scene.atmosphere = mood_hint

        image_prompt = str(dialogue.get("image_prompt", "") or dialogue.get("sd_prompt", "") or "").strip()
        if image_prompt:
            existing = str(getattr(scene, "sd_prompt", "") or "").strip()
            scene.sd_prompt = image_prompt if not existing else f"{existing}, {image_prompt}"

        return scene

    def _get_major_character_ids(self, dialogues: List[Dict[str, str]], limit: int = 3) -> List[str]:
        preferred_ids = self._get_pack_preferred_character_ids()
        if preferred_ids:
            return preferred_ids[:max(limit, len(preferred_ids))]

        counts: Dict[str, int] = {}
        first_seen: Dict[str, int] = {}

        for idx, dialogue in enumerate(dialogues):
            speaker = dialogue.get("speaker") or dialogue.get("character") or dialogue.get("role") or ""
            char_id = self._resolve_dialogue_character_id(speaker)
            if not char_id:
                continue
            counts[char_id] = counts.get(char_id, 0) + 1
            first_seen.setdefault(char_id, idx)

        ranked = sorted(counts.items(), key=lambda item: (-item[1], first_seen[item[0]], item[0]))
        major_ids = [char_id for char_id, count in ranked if count >= 2][:limit]
        preferred_seen_ids = [preferred_id for preferred_id in self._get_pack_preferred_character_ids() if preferred_id in counts]
        for preferred_id in reversed(preferred_seen_ids):
            if preferred_id not in major_ids:
                major_ids.insert(0, preferred_id)
        major_ids = major_ids[:limit]
        if len(major_ids) < min(limit, len(ranked)):
            for char_id, _ in ranked:
                if char_id not in major_ids:
                    major_ids.append(char_id)
                if len(major_ids) >= limit:
                    break
        return major_ids[:limit]

    def _ensure_major_character_references(self, dialogues: List[Dict[str, str]]) -> None:
        if not self.char_library_manager or not getattr(self.char_library_manager, "sd_api_url", None):
            return
        if not self.prompt_composer or not hasattr(self.prompt_composer, "char_map"):
            return

        major_ids = self._get_major_character_ids(dialogues, limit=3)
        if not major_ids:
            return

        cl_cfg = {}
        if isinstance(self.config, dict):
            cl_cfg = self.config.get("character_library", {}) or {}
        elif self.config:
            cl_cfg = getattr(self.config, "character_library", None) or {}

        if isinstance(cl_cfg, dict):
            preferred_expressions = list(cl_cfg.get("preferred_expressions", []) or [])
            preferred_poses = list(cl_cfg.get("preferred_poses", []) or [])
            required_variant_keys = list(cl_cfg.get("required_variant_keys", []) or [])
            required_variant_keys_by_slot = dict(cl_cfg.get("required_variant_keys_by_slot", {}) or {})
        else:
            preferred_expressions = list(getattr(cl_cfg, "preferred_expressions", []) or [])
            preferred_poses = list(getattr(cl_cfg, "preferred_poses", []) or [])
            required_variant_keys = list(getattr(cl_cfg, "required_variant_keys", []) or [])
            required_variant_keys_by_slot = dict(getattr(cl_cfg, "required_variant_keys_by_slot", {}) or {})

        essential_expressions = preferred_expressions or ["neutral", "talking", "fear", "surprise", "sad", "anger"]
        essential_poses = preferred_poses or ["standing", "listening", "sitting", "walking"]

        for rank, char_id in enumerate(major_ids):
            char_def = self.prompt_composer.char_map.get(char_id)
            if not char_def:
                continue

            available_expressions = list(getattr(char_def, "expressions", {}).keys())
            available_poses = list(getattr(char_def, "poses", {}).keys())
            if preferred_expressions:
                expressions = list(dict.fromkeys([expr for expr in essential_expressions if expr]))[:6]
            else:
                expressions = list(dict.fromkeys([
                    expr for expr in (essential_expressions + available_expressions) if expr
                ]))[:6]
            if preferred_poses:
                poses = list(dict.fromkeys([pose for pose in essential_poses if pose]))[:4]
            else:
                poses = list(dict.fromkeys([
                    pose for pose in (essential_poses + available_poses) if pose
                ]))[:4]
            missing_keys: List[str] = []
            slot_name = self._resolve_motiontoon_slot_name(char_id)
            slot_required_variant_keys = []
            if slot_name:
                slot_required_variant_keys = list(required_variant_keys_by_slot.get(slot_name, []) or [])
            effective_required_variant_keys = slot_required_variant_keys or required_variant_keys

            try:
                coverage = self.char_library_manager.get_character_sheet_coverage(
                    char_id,
                    available_expressions=expressions,
                    available_poses=poses,
                    required_variant_keys=effective_required_variant_keys or None,
                )
                if coverage.get("is_complete"):
                    continue
                missing_keys = list(coverage.get("missing_keys", []) or [])
                if missing_keys:
                    missing_expressions: List[str] = []
                    missing_poses: List[str] = []
                    for key in missing_keys:
                        expr_name, pose_name = key.split("_", 1) if "_" in key else (key, "standing")
                        if expr_name not in missing_expressions:
                            missing_expressions.append(expr_name)
                        if pose_name not in missing_poses:
                            missing_poses.append(pose_name)
                    expressions = missing_expressions or expressions
                    poses = missing_poses or poses
            except Exception as e:
                logger.debug(f"[VSD] sheet coverage check failed ({char_id}): {e}")

            images_per_combo = 2 if rank == 0 else 1

            try:
                logger.info(f"[VSD] 주요 캐릭터 reference 생성: {char_id} ({rank + 1}/{len(major_ids)})")
                self.char_library_manager.generate_character_library(
                    character_def=char_def,
                    expressions=expressions,
                    poses=poses,
                    variant_keys=missing_keys or None,
                    images_per_combo=images_per_combo,
                )
            except Exception as e:
                logger.warning(f"[VSD] 주요 캐릭터 reference 생성 실패 ({char_id}): {e}")

    def _process_dialogues_sequential(self, dialogues: List[Dict[str, str]],
                                       result: StorytellingResult,
                                       output_path: Path,
                                       start_time: float,
                                       pre_analyzed_scenes: Optional[Dict] = None,
                                       image_callback: Optional[Any] = None) -> StorytellingResult:
        """v59.2.3: 순차 처리 (기존 로직)"""
        # 1. 장면 분석 — v62.18: 사전 캐시가 있으면 재분석 스킵
        if pre_analyzed_scenes:
            logger.info(f"[VSD] Step 1: 사전 분석 캐시 사용 ({len(pre_analyzed_scenes)}개 씬, SceneAnalyzer 재호출 스킵)")
            scene_results = [pre_analyzed_scenes[i] for i in range(len(dialogues))
                            if i in pre_analyzed_scenes]
            # v62.18: scene_analyzer.previous_scenes 동기화 (캐시 누락 폴백 시 컨텍스트 제공)
            if self.scene_analyzer:
                self.scene_analyzer.previous_scenes = list(scene_results[-10:])
        else:
            logger.info("[VSD] Step 1: 장면 분석 (순차)")
            scene_results = self.scene_analyzer.analyze_scene_batch(dialogues, parallel=False)
            scene_results = [
                self._apply_dialogue_visual_hints(scene, dialogues[idx])
                for idx, scene in enumerate(scene_results)
            ]

        # 2. 각 장면 처리
        logger.info("[VSD] Step 2: 이미지 생성 (순차)")
        for i, scene in enumerate(scene_results):
            try:
                image = self._process_scene(scene, i, output_path)
                result.images.append(image)
                self._update_result_stats(result, image)
                if image_callback and image.path:
                    try:
                        image_callback(i, image.path, len(result.images), len(dialogues))
                    except Exception as e:
                        logger.debug(f"[VSD] image_callback 실패 (scene {i}): {e}")
            except Exception as e:
                logger.error(f"[VSD] 장면 {i} 처리 실패: {e}")
                result.errors.append(f"Scene {i}: {str(e)}")

        self._finalize_result(result, start_time)
        return result

    def _process_dialogues_pipeline(self, dialogues: List[Dict[str, str]],
                                     result: StorytellingResult,
                                     output_path: Path,
                                     start_time: float,
                                     pre_analyzed_scenes: Optional[Dict] = None,
                                     image_callback: Optional[Any] = None) -> StorytellingResult:
        """
        v59.2.3: Producer-Consumer 파이프라인

        구조:
          [SceneAnalyzer 병렬] → Queue → [SD 이미지 생성 + QC 파이프라인]

        v62.18: 사전 분석 캐시가 있으면 SceneAnalyzer 재호출 스킵

        SceneAnalyzer가 분석 완료하면 즉시 Queue에 넣고,
        SD 소비자가 꺼내서 이미지 생성 시작.
        총 대기 시간을 최소화.
        """
        total = len(dialogues)
        scene_queue: Queue = Queue(maxsize=0)  # 무제한 큐
        SENTINEL = None  # 종료 신호

        # ─── Producer: SceneAnalyzer 병렬 분석 → Queue ───
        def producer_thread():
            """SceneAnalyzer 병렬 분석 후 결과를 순서대로 Queue에 push"""
            try:
                # v62.18: 사전 분석 캐시가 있으면 Gemini 재호출 없이 즉시 큐 전달
                if pre_analyzed_scenes:
                    logger.info(f"[VSD] ★ Producer 시작: 사전 분석 캐시 사용 ({len(pre_analyzed_scenes)}개, SceneAnalyzer 스킵)")
                    # v62.18: previous_scenes 동기화 (캐시 누락 폴백 시 컨텍스트 제공)
                    if self.scene_analyzer:
                        cached_list = [pre_analyzed_scenes[i] for i in sorted(pre_analyzed_scenes.keys())]
                        self.scene_analyzer.previous_scenes = cached_list[-10:]
                    for i in range(total):
                        if i in pre_analyzed_scenes:
                            scene_queue.put((i, self._apply_dialogue_visual_hints(pre_analyzed_scenes[i], dialogues[i])))
                            logger.debug(f"[VSD] Producer: 장면 {i} 캐시→큐 전달")
                        else:
                            logger.warning(f"[VSD] Producer: 장면 {i} 캐시 누락 → 개별 분석")
                            single = self.scene_analyzer.analyze_dialogue(
                                dialogue=dialogues[i].get('text', ''),
                                speaker=dialogues[i].get('speaker', '나레이터'))
                            scene_queue.put((i, self._apply_dialogue_visual_hints(single, dialogues[i])))
                else:
                    logger.info("[VSD] ★ Producer 시작: SceneAnalyzer 병렬 분석")
                    # 병렬로 분석 (내부에서 image_action도 순차 결정)
                    scene_results = self.scene_analyzer.analyze_scene_batch(dialogues, parallel=True)

                    # 분석 결과를 순서대로 큐에 전달
                    for i, scene in enumerate(scene_results):
                        scene_queue.put((i, self._apply_dialogue_visual_hints(scene, dialogues[i])))
                        logger.debug(f"[VSD] Producer: 장면 {i} 큐 전달")

            except Exception as e:
                logger.error(f"[VSD] Producer 예외: {e}")
            finally:
                scene_queue.put(SENTINEL)  # 종료 신호
                logger.info("[VSD] ★ Producer 완료")

        # ─── Consumer: SD 이미지 생성 (순차, SD API는 단일 GPU) ───
        image_results: Dict[int, GeneratedImage] = {}
        consumer_errors: List[str] = []

        def consumer_thread():
            """Queue에서 장면을 꺼내 SD 이미지 생성"""
            logger.info("[VSD] ★ Consumer 시작: SD 이미지 생성")
            processed = 0

            while True:
                item = scene_queue.get()

                # 종료 신호
                if item is SENTINEL:
                    logger.info(f"[VSD] ★ Consumer 완료: {processed}개 처리")
                    break

                idx, scene = item
                try:
                    image = self._process_scene(scene, idx, output_path)
                    image_results[idx] = image
                    processed += 1
                    if image_callback and image.path:
                        try:
                            image_callback(idx, image.path, processed, total)
                        except Exception as e:
                            logger.debug(f"[VSD] image_callback 실패 (scene {idx}): {e}")

                    # 진행 로그
                    if processed % max(1, total // 10) == 0 or processed == total:
                        logger.info(f"[VSD] SD 진행: {processed}/{total} ({processed/total*100:.0f}%)")

                except Exception as e:
                    logger.error(f"[VSD] Consumer 장면 {idx} 실패: {e}")
                    consumer_errors.append(f"Scene {idx}: {str(e)}")

        # ─── 실행: Producer와 Consumer 동시 시작 ───
        logger.info(f"[VSD] ★ 파이프라인 시작: {total}개 대사")
        pipeline_start = time.time()

        producer = threading.Thread(target=producer_thread, name="VSD-Producer", daemon=True)
        consumer = threading.Thread(target=consumer_thread, name="VSD-Consumer", daemon=True)

        producer.start()
        consumer.start()

        # 둘 다 완료 대기
        producer.join()
        consumer.join()

        pipeline_elapsed = time.time() - pipeline_start
        logger.info(f"[VSD] ★ 파이프라인 완료: {pipeline_elapsed:.1f}s")

        # ─── 결과 정리 (순서대로) ───
        for i in range(total):
            if i in image_results:
                image = image_results[i]
                result.images.append(image)
                self._update_result_stats(result, image)
            else:
                # 에러로 누락된 장면
                result.errors.append(f"Scene {i}: missing result")

        result.errors.extend(consumer_errors)
        self._finalize_result(result, start_time)
        return result

    @staticmethod
    def _update_result_stats(result: 'StorytellingResult', image: 'GeneratedImage'):
        """v59.2.3: 결과 통계 업데이트 (중복 코드 제거)"""
        if image.action == "new":
            result.new_images += 1
        elif image.action == "expression":
            result.expression_swaps += 1
        elif image.action == "pose":
            result.pose_swaps += 1
        else:
            result.reuses += 1

    @staticmethod
    def _finalize_result(result: 'StorytellingResult', start_time: float):
        """v59.2.3: 최종 통계 계산"""
        result.total_time = time.time() - start_time
        if result.new_images > 0:
            gen_times = [img.generation_time for img in result.images if img.generation_time > 0]
            if gen_times:
                result.avg_generation_time = sum(gen_times) / len(gen_times)

        logger.info(f"[VSD] 처리 완료: {len(result.images)}개 이미지, "
                   f"new={result.new_images}, expr={result.expression_swaps}, "
                   f"pose={result.pose_swaps}, reuse={result.reuses}, "
                   f"시간={result.total_time:.1f}s")

    @staticmethod
    def _extract_scene_identity(scene: Any, index: int) -> Dict[str, str]:
        scene_id = getattr(scene, 'scene_id', f'scene_{index:04d}')
        location = getattr(scene, 'location', '') or ''
        emotion = 'neutral'
        pose = 'standing'
        char_id = ''
        camera_shot = getattr(scene, 'camera_shot', '') or ''
        outfit_hint = getattr(scene, 'outfit_hint', '') or ''
        key_props = list(getattr(scene, 'key_props', []) or [])
        characters = getattr(scene, 'characters', [])
        if characters:
            main_char = characters[0]
            if hasattr(main_char, 'id'):
                char_id = getattr(main_char, 'id', '') or ''
                emotion = getattr(main_char, 'emotion', 'neutral') or 'neutral'
                pose = getattr(main_char, 'action', 'standing') or 'standing'
            elif isinstance(main_char, dict):
                char_id = main_char.get('id', '') or ''
                emotion = main_char.get('emotion', 'neutral') or 'neutral'
                pose = main_char.get('action', 'standing') or 'standing'
        return {
            'scene_id': scene_id,
            'location': location,
            'emotion': emotion,
            'pose': pose,
            'char_id': char_id,
            'camera_shot': camera_shot,
            'outfit_hint': outfit_hint,
            'key_props': key_props,
        }

    def _normalize_scene_variant(self, char_id: str, emotion: str, pose: str) -> Tuple[str, str]:
        normalized_emotion = (emotion or 'neutral').strip().lower() or 'neutral'
        normalized_pose = (pose or 'standing').strip().lower() or 'standing'

        if self.char_library_manager and char_id:
            try:
                normalized_emotion, normalized_pose = self.char_library_manager.resolve_variant(
                    char_id,
                    normalized_emotion,
                    normalized_pose,
                )
            except Exception as e:
                logger.debug(f"[VSD] variant normalize failed ({char_id}/{emotion}/{pose}): {e}")

        return normalized_emotion, normalized_pose

    def _augment_scene_with_cut_state(self, scene: Any, scene_state: Dict[str, str]) -> None:
        char_id = scene_state.get('char_id', '')
        location = scene_state.get('location', '')
        camera_shot = scene_state.get('camera_shot', '')
        char_state = self.character_panel_state.get(char_id) if char_id else None
        location_state = self.location_panel_state.get(location) if location else None

        extra_hints: List[str] = []
        if char_state:
            extra_hints.append("same face, same hairstyle, same outfit as previous cut")
            if not scene_state.get('outfit_hint') and char_state.get('outfit_hint'):
                scene.outfit_hint = char_state.get('outfit_hint')
                scene_state['outfit_hint'] = char_state.get('outfit_hint')
        if char_state and char_state.get('location') == location and location:
            extra_hints.append("same room layout and lighting, vary only panel angle")
        elif location_state:
            extra_hints.append("same background layout as previous cut in this location")

        if not scene_state.get('key_props') and char_state and char_state.get('key_props'):
            scene.key_props = list(char_state.get('key_props', []))
            scene_state['key_props'] = list(char_state.get('key_props', []))
            extra_hints.append("keep the same key prop visible")
        elif not scene_state.get('key_props') and location_state and location_state.get('key_props'):
            scene.key_props = list(location_state.get('key_props', []))
            scene_state['key_props'] = list(location_state.get('key_props', []))
            extra_hints.append("keep the same location prop layout")

        if not camera_shot and char_state and char_state.get('camera_shot'):
            scene.camera_shot = char_state.get('camera_shot')
            scene_state['camera_shot'] = char_state.get('camera_shot')
        elif not camera_shot and location_state and location_state.get('camera_shot'):
            scene.camera_shot = location_state.get('camera_shot')
            scene_state['camera_shot'] = location_state.get('camera_shot')
        elif location_state and camera_shot and camera_shot == location_state.get('camera_shot'):
            extra_hints.append("same location, shift to a slightly different panel angle")

        if extra_hints:
            existing = getattr(scene, 'continuity_hint', '') or ''
            scene.continuity_hint = ", ".join([part for part in [existing] + extra_hints if part])

    def _select_effective_action(self, requested_action: str,
                                 scene_state: Dict[str, str]) -> str:
        char_id = scene_state.get('char_id', '')
        location = scene_state.get('location', '')
        emotion, pose = self._normalize_scene_variant(
            char_id,
            scene_state.get('emotion', 'neutral'),
            scene_state.get('pose', 'standing'),
        )
        scene_state['emotion'] = emotion
        scene_state['pose'] = pose
        key_props = tuple(scene_state.get('key_props', []) or [])
        outfit_hint = scene_state.get('outfit_hint', '')
        camera_shot = scene_state.get('camera_shot', '')

        char_state = self.character_panel_state.get(char_id) if char_id else None
        location_state = self.location_panel_state.get(location) if location else None

        has_char_library = False
        if self.char_library_manager and char_id:
            try:
                if hasattr(self.char_library_manager, "has_character_sheet_variant"):
                    has_char_library = bool(self.char_library_manager.has_character_sheet_variant(
                        character_id=char_id,
                        expression=emotion,
                        pose=pose,
                        fallback=True,
                    ))
                else:
                    has_char_library = bool(self.char_library_manager.get_character_image(
                        character_id=char_id,
                        expression=emotion,
                        pose=pose,
                        fallback=False,
                    ))
            except Exception:
                has_char_library = False

        if char_state:
            same_pose = char_state.get('pose') == pose
            same_emotion = char_state.get('emotion') == emotion
            same_location = char_state.get('location') == location
            same_props = tuple(char_state.get('key_props', []) or []) == key_props
            same_outfit = (not outfit_hint) or (char_state.get('outfit_hint') == outfit_hint)
            same_camera = (not camera_shot) or (char_state.get('camera_shot') == camera_shot)

            if same_location and same_pose and same_emotion and same_props and same_outfit and same_camera:
                return 'reuse'
            if has_char_library and same_location and same_props and same_outfit and not same_emotion and same_pose:
                return 'expression'
            if has_char_library and same_location and same_props and same_outfit and not same_pose:
                return 'pose'
            if same_location and same_props and same_outfit and same_camera and not has_char_library:
                return 'reuse'
            if requested_action in ('expression', 'pose') and same_location and same_props and same_outfit and same_camera and not has_char_library:
                return 'reuse'

        if requested_action == 'reuse' and not (char_state or location_state or self.previous_images):
            return 'new'

        return requested_action

    def _get_reuse_source(self, scene_state: Dict[str, str]) -> Optional[GeneratedImage]:
        char_id = scene_state.get('char_id', '')
        location = scene_state.get('location', '')

        if char_id and char_id in self.character_panel_state:
            return self.character_panel_state[char_id].get('image')
        if location and location in self.location_panel_state:
            return self.location_panel_state[location].get('image')
        if self.previous_images:
            last_key = list(self.previous_images.keys())[-1]
            return self.previous_images[last_key]
        return None

    @staticmethod
    def _resolve_motiontoon_background_source(image: Optional[GeneratedImage], fallback_path: str = "") -> str:
        if image:
            parts = dict(getattr(image, 'parts', {}) or {})
            background_path = str(parts.get('background_path', '') or '')
            if background_path and os.path.exists(background_path):
                return background_path
            image_path = str(getattr(image, 'path', '') or '')
            if image_path and os.path.exists(image_path):
                return image_path
        return fallback_path

    def _register_cut_state(self, image: GeneratedImage, scene_state: Dict[str, str]) -> None:
        scene_id = scene_state.get('scene_id', '')
        char_id = scene_state.get('char_id', '')
        location = scene_state.get('location', '')
        emotion = scene_state.get('emotion', 'neutral')
        pose = scene_state.get('pose', 'standing')
        camera_shot = scene_state.get('camera_shot', '')
        outfit_hint = scene_state.get('outfit_hint', '')
        key_props = list(scene_state.get('key_props', []) or [])

        if scene_id:
            self.previous_images[scene_id] = image

        panel_state = {
            'scene_id': scene_id,
            'char_id': char_id,
            'location': location,
            'emotion': emotion,
            'pose': pose,
            'camera_shot': camera_shot,
            'outfit_hint': outfit_hint,
            'key_props': key_props,
            'image': image,
        }
        if char_id:
            self.character_panel_state[char_id] = panel_state
        if location:
            self.location_panel_state[location] = panel_state

        self.cut_state_ledger.append({
            'scene_id': scene_id,
            'path': image.path,
            'action': image.action,
            'character_id': char_id,
            'location': location,
            'emotion': emotion,
            'pose': pose,
            'camera_shot': camera_shot,
            'outfit_hint': outfit_hint,
            'key_props': key_props,
        })

    def _process_scene(self, scene: Any, index: int, output_path: Path) -> GeneratedImage:
        """단일 장면 처리"""
        scene_state = self._extract_scene_identity(scene, index)
        scene_id = scene_state['scene_id']
        scene_state['emotion'], scene_state['pose'] = self._normalize_scene_variant(
            scene_state.get('char_id', ''),
            scene_state.get('emotion', 'neutral'),
            scene_state.get('pose', 'standing'),
        )
        action = getattr(scene, 'image_action', 'new')
        self._augment_scene_with_cut_state(scene, scene_state)
        action = self._select_effective_action(action, scene_state)

        # 연속 reuse 제한 확인 (v59.1.7: dict/object 안전 접근)
        if self.config:
            if isinstance(self.config, dict):
                max_reuse = self.config.get('max_consecutive_reuse', 2)
            else:
                max_reuse = getattr(self.config, 'max_consecutive_reuse', 2)
        else:
            max_reuse = 2
        if action == "reuse" and self.consecutive_reuse_count >= max_reuse:
            logger.info(f"[VSD] 연속 reuse 제한 ({max_reuse}) 도달 → new로 변경")
            action = "new"

        # 액션별 처리
        if action == "reuse":
            image = self._handle_reuse(scene, index, scene_state, output_path)
        elif action == "expression":
            image = self._handle_expression_swap(scene, index, output_path)
        elif action == "pose":
            image = self._handle_pose_swap(scene, index, output_path)
        else:
            image = self._handle_new_image(scene, index, output_path)

        self._register_cut_state(image, scene_state)
        return image

    def _handle_new_image(self, scene: Any, index: int, output_path: Path) -> GeneratedImage:
        """새 이미지 생성"""
        self.consecutive_reuse_count = 0
        scene_id = getattr(scene, 'scene_id', f'scene_{index:04d}')

        start_time = time.time()

        # v59.1.3: 캐릭터 정보 추출
        char_id = ""
        emotion = "neutral"
        pose = "standing"
        characters = getattr(scene, 'characters', [])
        if characters:
            char = characters[0]
            if hasattr(char, 'id'):
                char_id = char.id
                emotion = getattr(char, 'emotion', 'neutral')
                pose = getattr(char, 'action', 'standing')
            elif isinstance(char, dict):
                char_id = char.get('id', '')
                emotion = char.get('emotion', 'neutral')
                pose = char.get('action', 'standing')

        # v59.1.3: 캐릭터 라이브러리에서 먼저 검색
        library_image = self._get_from_library(char_id, emotion, pose) if char_id else None
        use_simple_sprite_mode = self._use_simple_character_sprite_mode()
        if use_simple_sprite_mode and not char_id:
            preferred_ids = self._get_pack_preferred_character_ids()
            if preferred_ids:
                char_id = preferred_ids[0]
                emotion = "neutral"
                pose = "standing"
        emotion, pose = self._normalize_scene_variant(char_id, emotion, pose)
        if use_simple_sprite_mode and char_id and not library_image:
            library_image = self._get_from_library(char_id, emotion, pose)
        if use_simple_sprite_mode and char_id and not library_image:
            library_image = self._ensure_simple_sprite_library_image(char_id, emotion, pose)
        if library_image:
            logger.info(f"[VSD] 캐릭터 라이브러리에서 이미지 발견: {char_id}/{emotion}")

        # 기존 경로는 유지하고, 최근 두 팩에서만 단순 스프라이트 모드를 탄다.
        if library_image and os.path.exists(library_image) and not use_simple_sprite_mode:
            import shutil
            image_path = output_path / f"{scene_id}.png"
            shutil.copy(library_image, str(image_path))
            gen_time = time.time() - start_time
            parts = {}
            rig_overrides = self._get_motiontoon_rig_overrides(char_id, emotion, pose)
            if self.char_library_manager:
                try:
                    parts = self.char_library_manager.bind_character_sheet_variant(
                        str(image_path),
                        char_id,
                        emotion,
                        pose,
                        fallback=True,
                        rig_overrides=rig_overrides,
                    )
                    if not parts:
                        parts = self.char_library_manager.prime_motiontoon_parts(
                            str(image_path),
                            rig_overrides=rig_overrides,
                        )
                except Exception as e:
                    logger.debug(f"[VSD] library motiontoon part prime failed ({scene_id}): {e}")

            result = GeneratedImage(
                path=str(image_path),
                scene_id=scene_id,
                dialogue_index=index,
                action="library",
                character_id=char_id,
                expression=emotion,
                pose=pose,
                generation_time=gen_time,
                parts=parts,
            )
            self.previous_images[scene_id] = result
            return result

        # 프롬프트 생성
        composed = self.prompt_composer.compose_prompt(scene)
        composed.seed = self._build_scene_seed(scene, char_id, scene_id)
        background_composed = None
        if use_simple_sprite_mode and library_image and os.path.exists(library_image):
            background_composed = self._build_background_plate_prompt(scene, composed)
            background_composed.seed = composed.seed

        # SD 이미지 생성
        image_path = output_path / f"{scene_id}.png"
        seed = -1

        # v59.3.0: _call_sd_api 결과를 별도 변수에 저장 (result 변수 충돌 방지)
        sd_result: Dict[str, Any] = {}

        if self.sd_client:
            try:
                if use_simple_sprite_mode and library_image and self.bg_library:
                    generated_plate = self._generate_background_plate_from_library(
                        scene,
                        scene_id,
                        image_path,
                    )
                    if generated_plate:
                        sd_result = {'seed': -1, 'path': generated_plate, 'retry_count': 0}
                    else:
                        sd_result = self._call_sd_api(background_composed or composed, str(image_path))
                else:
                    # SD API 호출
                    sd_result = self._call_sd_api(background_composed or composed, str(image_path))
                seed = sd_result.get('seed', -1)
            except Exception as e:
                logger.error(f"[VSD] SD 생성 실패: {e}")
                # v59.3.0: BUG-C 수정 - 빈 경로 대신 safe_image 생성
                self._save_safe_image(str(image_path))
                sd_result = {'safe_image': True, 'quality_issues': [f'SD_ERROR: {str(e)[:80]}'], 'retry_count': 0}
        else:
            logger.warning("[VSD] SD 클라이언트 없음 - 폴백: 단색 플레이스홀더 생성")
            # v59.1.7: 실제 파일 생성 (media_factory 필터링에서 누락 방지)
            image_path = output_path / f"{scene_id}_placeholder.png"
            try:
                self._create_placeholder_image(str(image_path))
            except Exception as e:
                logger.error(f"[VSD] 플레이스홀더 생성 실패: {e}")
                image_path = Path("")

        gen_time = time.time() - start_time
        parts = {}
        rig_overrides = self._get_motiontoon_rig_overrides(char_id, emotion, pose)
        if self.char_library_manager and str(image_path):
            try:
                if use_simple_sprite_mode and library_image and os.path.exists(library_image):
                    parts = self._compose_scene_motiontoon_assets(
                        str(image_path),
                        background_source_path=str(image_path),
                        sprite_source_path=library_image,
                        char_id=char_id,
                        emotion=emotion,
                        pose=pose,
                    )
                if not parts and use_simple_sprite_mode:
                    parts = self._build_simple_sprite_background_only_parts(
                        str(image_path),
                        char_id=char_id,
                        emotion=emotion,
                        pose=pose,
                    )
                if not parts:
                    parts = self.char_library_manager.prime_motiontoon_parts(
                        str(image_path),
                        rig_overrides=rig_overrides,
                    )
            except Exception as e:
                logger.debug(f"[VSD] motiontoon part prime failed ({scene_id}): {e}")

        # v59.3.0: sd_result에서 safe_image / quality_issues 추출
        is_safe = sd_result.get('safe_image', False)
        api_quality_issues = sd_result.get('quality_issues', [])
        api_retry_count = sd_result.get('retry_count', 0)

        result = GeneratedImage(
            path=str(image_path),
            scene_id=scene_id,
            dialogue_index=index,
            action="new",
            prompt_positive=(background_composed or composed).positive,
            prompt_negative=(background_composed or composed).negative,
            character_id=char_id,
            expression=emotion,
            pose=pose,
            seed=seed,
            generation_time=gen_time,
            retry_count=api_retry_count,
            parts=parts,
            quality_issues=api_quality_issues,
            passed_quality_check=not bool(api_quality_issues),
            safe_image=is_safe,                   # v59.3.0: CRITICAL 위반 플래그
        )

        # 캐시에 저장
        self.previous_images[scene_id] = result

        # v59.3.0: 정상 이미지만 _last_good_image에 저장 (CRITICAL 위반 이미지 오염 방지)
        if str(image_path) and os.path.exists(str(image_path)) and not is_safe:
            self._last_good_image = str(image_path)

        return result

    def _handle_expression_swap(self, scene: Any, index: int,
                                  output_path: Path) -> GeneratedImage:
        """표정 변경 (캐릭터 라이브러리에서 선택)"""
        self.consecutive_reuse_count = 0
        scene_id = getattr(scene, 'scene_id', f'scene_{index:04d}')
        scene_state = self._extract_scene_identity(scene, index)

        # 캐릭터 정보 추출
        characters = getattr(scene, 'characters', [])
        if not characters:
            return self._handle_new_image(scene, index, output_path)

        char = characters[0]
        if hasattr(char, 'id'):
            char_id = char.id
            emotion = getattr(char, 'emotion', 'neutral')
            action = getattr(char, 'action', 'standing')
        else:
            char_id = char.get('id', '')
            emotion = char.get('emotion', 'neutral')
            action = char.get('action', 'standing')

        # 캐릭터 라이브러리에서 검색 (v59.1.7: expression→emotion 수정, lib_key 수정)
        emotion, action = self._normalize_scene_variant(char_id, emotion, action)
        image_path = self._get_from_library(char_id, emotion, action)

        use_simple_sprite_mode = self._use_simple_character_sprite_mode()
        if image_path:
            import shutil
            scene_image_path = output_path / f"{scene_id}.png"
            reuse_source = self._get_reuse_source(scene_state)
            if use_simple_sprite_mode and not (
                reuse_source and getattr(reuse_source, 'path', '') and os.path.exists(reuse_source.path)
            ):
                return self._handle_new_image(scene, index, output_path)

            background_source = image_path
            if reuse_source:
                background_source = self._resolve_motiontoon_background_source(reuse_source, fallback_path=background_source)
            shutil.copy(background_source, str(scene_image_path))
            parts = {}
            if self.char_library_manager:
                try:
                    if use_simple_sprite_mode:
                        parts = self._compose_scene_motiontoon_assets(
                            str(scene_image_path),
                            background_source_path=background_source,
                            sprite_source_path=image_path,
                            char_id=char_id,
                            emotion=emotion,
                            pose=action,
                        )
                    if not parts:
                        rig_overrides = self._get_motiontoon_rig_overrides(char_id, emotion, action)
                        parts = self.char_library_manager.bind_character_sheet_variant(
                            str(scene_image_path),
                            char_id,
                            emotion,
                            action,
                            fallback=True,
                            rig_overrides=rig_overrides,
                        )
                    if not parts and use_simple_sprite_mode:
                        parts = self._build_simple_sprite_background_only_parts(
                            str(scene_image_path),
                            char_id=char_id,
                            emotion=emotion,
                            pose=action,
                        )
                    if not parts:
                        rig_overrides = self._get_motiontoon_rig_overrides(char_id, emotion, action)
                        parts = self.char_library_manager.prime_motiontoon_parts(
                            str(scene_image_path),
                            rig_overrides=rig_overrides,
                        )
                except Exception as e:
                    logger.debug(f"[VSD] expression motiontoon part lookup failed ({char_id}/{emotion}/{action}): {e}")
            return GeneratedImage(
                path=str(scene_image_path),
                scene_id=scene_id,
                dialogue_index=index,
                action="expression",
                character_id=char_id,
                expression=emotion,
                pose=action,
                parts=parts,
            )
        else:
            # 라이브러리에 없으면 새로 생성
            logger.info(f"[VSD] 라이브러리에 없음 ({char_id}/{emotion}_{action}) → 새로 생성")
            return self._handle_new_image(scene, index, output_path)

    def _handle_pose_swap(self, scene: Any, index: int,
                           output_path: Path) -> GeneratedImage:
        """포즈 변경 (캐릭터 라이브러리에서 선택)"""
        # 표정 변경과 동일한 로직
        result = self._handle_expression_swap(scene, index, output_path)
        result.action = "pose"
        return result

    def _handle_reuse(self, scene: Any, index: int,
                      scene_state: Optional[Dict[str, Any]] = None,
                      output_path: Optional[Path] = None) -> GeneratedImage:
        """이전 이미지 재사용"""
        self.consecutive_reuse_count += 1
        scene_id = getattr(scene, 'scene_id', f'scene_{index:04d}')
        scene_state = scene_state or self._extract_scene_identity(scene, index)

        # 가장 최근 이미지 찾기
        prev_image = self._get_reuse_source(scene_state)
        if prev_image:
            image_path = prev_image.path
            parts = dict(getattr(prev_image, 'parts', {}) or {})
            char_id = scene_state.get('char_id', '')
            emotion, pose = self._normalize_scene_variant(
                char_id,
                scene_state.get('emotion', 'neutral'),
                scene_state.get('pose', 'standing'),
            )
            rig_overrides = self._get_motiontoon_rig_overrides(char_id, emotion, pose)

            if image_path and os.path.exists(image_path):
                try:
                    import shutil
                    source_path = Path(self._resolve_motiontoon_background_source(prev_image, fallback_path=image_path))
                    # Reuse clones must always materialize into the active scene output
                    # directory so later render/probe steps keep a stable scene_id->file map.
                    scene_output_dir = output_path or source_path.parent
                    scene_image_path = scene_output_dir / f"{scene_id}{source_path.suffix}"
                    if str(scene_image_path) != str(source_path):
                        shutil.copy(str(source_path), str(scene_image_path))
                        if self._use_simple_character_sprite_mode():
                            sprite_source_path = ""
                            if self.char_library_manager and char_id:
                                try:
                                    variant = self.char_library_manager.get_character_sheet_variant(
                                        char_id,
                                        expression=emotion,
                                        pose=pose,
                                        fallback=True,
                                    )
                                    candidate_path = str(variant.get('image_path', '') or '') if isinstance(variant, dict) else ''
                                    if candidate_path and os.path.exists(candidate_path):
                                        sprite_source_path = candidate_path
                                except Exception as e:
                                    logger.debug(f"[VSD] reuse sprite source lookup failed ({char_id}/{emotion}/{pose}): {e}")
                            if not sprite_source_path:
                                sprite_source_path = str(parts.get('foreground_path', '') or '')
                            if not sprite_source_path:
                                sprite_source_path = str(getattr(prev_image, 'path', '') or '')
                            parts = self._compose_scene_motiontoon_assets(
                                str(scene_image_path),
                                background_source_path=str(source_path),
                                sprite_source_path=sprite_source_path,
                                char_id=char_id,
                                emotion=emotion,
                                pose=pose,
                            )
                        else:
                            from utils.layered_cutout import clone_layered_cutout_assets

                            cloned_parts = clone_layered_cutout_assets(
                                image_path,
                                str(scene_image_path),
                                rig_overrides=rig_overrides,
                            )
                            if cloned_parts:
                                parts = cloned_parts
                        image_path = str(scene_image_path)
                except Exception as e:
                    logger.debug(f"[VSD] reuse clone failed ({scene_id}): {e}")

            return GeneratedImage(
                path=image_path,
                scene_id=scene_id,
                dialogue_index=index,
                action="reuse",
                character_id=char_id,
                expression=emotion,
                pose=pose,
                parts=parts,
            )

        # 이전 이미지 없으면 기본 이미지
        return GeneratedImage(
            path="",
            scene_id=scene_id,
            dialogue_index=index,
            action="reuse",
            quality_issues=["No previous image available"],
        )

    def _create_placeholder_image(self, path: str, width: int = 768, height: int = 512):
        """v59.1.7: SD 없을 때 단색 플레이스홀더 이미지 생성 (os.path.exists 통과용)"""
        try:
            from PIL import Image
            img = Image.new('RGB', (width, height), color=(30, 30, 30))
            img.save(path, 'PNG')
            logger.debug(f"[VSD] 플레이스홀더 생성: {path}")
        except ImportError:
            # PIL 없으면 최소 PNG 바이너리 직접 작성
            import struct, zlib
            def _minimal_png(w, h):
                raw = b''
                for _ in range(h):
                    raw += b'\x00' + b'\x1e\x1e\x1e' * w
                compressed = zlib.compress(raw)
                def chunk(ctype, data):
                    c = ctype + data
                    return struct.pack('>I', len(data)) + c + struct.pack('>I', zlib.crc32(c) & 0xffffffff)
                return (b'\x89PNG\r\n\x1a\n' +
                        chunk(b'IHDR', struct.pack('>IIBI', w, h, 8, 2) + b'\x00\x00\x00') +
                        chunk(b'IDAT', compressed) +
                        chunk(b'IEND', b''))
            with open(path, 'wb') as f:
                f.write(_minimal_png(width, height))
            logger.debug(f"[VSD] 플레이스홀더 생성 (minimal PNG): {path}")

    def _get_from_library(self, char_id: str, expression: str, pose: str = "standing") -> Optional[str]:
        """캐릭터 라이브러리에서 이미지 경로 가져오기 (v59.1.3: CLM 연동)"""
        if not self.char_library_manager:
            return None

        try:
            expression, pose = self._normalize_scene_variant(char_id, expression, pose)
            if hasattr(self.char_library_manager, "get_character_sheet_variant"):
                variant = self.char_library_manager.get_character_sheet_variant(
                    character_id=char_id,
                    expression=expression,
                    pose=pose,
                    fallback=True,
                )
                image_path = str(variant.get("image_path", "") or "") if isinstance(variant, dict) else ""
                if image_path:
                    return image_path
            return self.char_library_manager.get_character_image(
                character_id=char_id,
                expression=expression,
                pose=pose,
                fallback=True
            )
        except Exception as e:
            logger.debug(f"[VSD] 라이브러리 조회 실패 ({char_id}/{expression}/{pose}): {e}")
            return None

    @staticmethod
    def _stable_seed(*parts: Any) -> int:
        joined = "|".join(str(part).strip().lower() for part in parts if part is not None and str(part).strip())
        digest = hashlib.sha256(joined.encode("utf-8")).digest()
        return (int.from_bytes(digest[:8], "big") % 2147483646) + 1

    @classmethod
    def _variant_seed(cls, base_seed: int, attempt: int) -> int:
        return cls._stable_seed(base_seed, "retry", attempt)

    def _build_scene_seed(self, scene: Any, char_id: str, scene_id: str) -> int:
        location = getattr(scene, "location", "") if scene else ""
        speaker = getattr(scene, "speaker", "") if scene else ""
        narrator_ids = {"narrator", "narration", "나레이션", "나레이터"}
        if char_id and char_id.lower() not in narrator_ids:
            return self._stable_seed("character", char_id)
        if location:
            return self._stable_seed("location", location)
        return self._stable_seed("scene", speaker, scene_id)

    @staticmethod
    def _parse_sd_seed(result: Dict[str, Any]) -> int:
        """v59.2.0: SD WebUI info 필드에서 seed 추출 (info는 JSON 문자열)"""
        info = result.get('info', {})
        if isinstance(info, str):
            try:
                import json as _json
                info = _json.loads(info)
            except (ValueError, TypeError):
                info = {}
        if isinstance(info, dict):
            return info.get('seed', -1)
        return -1

    def _call_sd_api(self, composed: Any, output_path: str, max_retries: int = 3) -> Dict[str, Any]:
        """
        SD WebUI API 호출 + Gemini Vision 품질 검증

        v59.1.0: 불쾌한 골짜기 감지 시 자동 재생성 (최대 3회)
        v59.2.0: SD info JSON 문자열 파싱 수정
        """
        if not self.sd_client:
            return {}

        params = composed.to_api_params()
        base_seed = int(params.get("seed", -1) or -1)
        quality_control = self._get_quality_control()

        for attempt in range(max_retries):
            try:
                result = self.sd_client.txt2img(**params)

                # 이미지 저장
                if result and 'images' in result:
                    import base64
                    img_data = base64.b64decode(result['images'][0])
                    with open(output_path, 'wb') as f:
                        f.write(img_data)

                    # v59.7.0: 로컬 QC 게이트 → 통과 시에만 Gemini 호출
                    if quality_control:
                        # 1단계: 로컬 QC (해상도/블러/아티팩트 — ~0.1초)
                        _saved_uv = quality_control.config.check_uncanny_valley
                        quality_control.config.check_uncanny_valley = False
                        local_report = quality_control.validate_scene_image(output_path)
                        quality_control.config.check_uncanny_valley = _saved_uv

                        if not local_report.passed:
                            _msg = local_report.checks[0].message if local_report.checks else 'unknown'
                            logger.warning(f"[VSD] 로컬 QC 실패 (시도 {attempt + 1}/{max_retries}): {_msg}")
                            if attempt < max_retries - 1:
                                if base_seed > 0:
                                    params['seed'] = self._variant_seed(base_seed, attempt + 1)
                                continue
                            else:
                                # 마지막 시도도 로컬 실패 → 마지막 이미지 사용
                                return {
                                    'seed': self._parse_sd_seed(result),
                                    'path': output_path,
                                    'quality_issues': [f"LOCAL_QC: {_msg}"],
                                    'retry_count': attempt
                                }

                    # v62.12: Gemini Vision QC 제거 (비용 절감 — validate_with_gemini 삭제됨)
                    # 로컬 QC (1단계) 통과 시 바로 이미지 확정
                    return {
                        'seed': self._parse_sd_seed(result),
                        'path': output_path,
                        'retry_count': attempt
                    }

            except Exception as e:
                logger.error(f"[VSD] SD API 호출 실패 (시도 {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(1)
                    continue

        # v59.3.0: BUG-C - 모든 리트라이 실패 시 safe_image 생성 (빈 경로 방지)
        logger.warning(f"[VSD] SD API 최종 실패 - safe_image 생성: {output_path}")
        self._save_safe_image(output_path)
        return {
            'seed': -1,
            'path': output_path,
            'quality_issues': ['SD_API_ALL_RETRIES_FAILED'],
            'retry_count': max_retries,
            'safe_image': True
        }

    def _get_quality_control(self):
        """QualityControl 인스턴스 반환 (lazy init)"""
        if not hasattr(self, '_quality_control'):
            try:
                from modules_pro.quality_control import QualityControl, QualityControlConfig

                # v59.5.20: 팩별 아트 스타일을 QualityControl에 전달
                # 주의: ACTIVE_PACK 속성은 dict 또는 dataclass 모두 가능
                _art_style = ""
                try:
                    from config.pack_config import ACTIVE_PACK

                    def _get_val(obj, key, default=None):
                        """dict/dataclass 모두 대응하는 값 접근 헬퍼"""
                        if isinstance(obj, dict):
                            return obj.get(key, default)
                        return getattr(obj, key, default)

                    # 우선순위 1: scene_analyzer.art_style_prefix
                    _sa = getattr(ACTIVE_PACK, 'scene_analyzer', None)
                    if _sa:
                        _prefix = _get_val(_sa, 'art_style_prefix', '')
                        if _prefix:
                            _art_style = _prefix.rstrip(',').strip()

                    # 우선순위 2: visual.forced_style.force_positive (첫 3개 토큰)
                    if not _art_style:
                        _v = getattr(ACTIVE_PACK, 'visual', None)
                        if _v:
                            _fs = _get_val(_v, 'forced_style', None)
                            if _fs:
                                _fp = _get_val(_fs, 'force_positive', '')
                                if _fp:
                                    _tokens = [t.strip() for t in _fp.split(',')][:3]
                                    _art_style = ', '.join(_tokens)

                    # 우선순위 3: style.image_style
                    if not _art_style:
                        _s = getattr(ACTIVE_PACK, 'style', None)
                        if _s:
                            _is = _get_val(_s, 'image_style', '')
                            if _is:
                                _art_style = _is

                except Exception as e:
                    logger.debug(f"[VSD] 팩 아트 스타일 추출 실패: {e}")

                if _art_style:
                    logger.info(f"[VSD] QualityControl 기대 아트스타일: {_art_style[:60]}...")

                config = QualityControlConfig(
                    check_uncanny_valley=False,  # v62.12: Gemini Vision QC 비활성화 (비용 절감)
                    max_retries=3,
                    expected_art_style=_art_style
                )
                self._quality_control = QualityControl(config=config, gemini_client=None)
                # v62.12: gemini_client=None — 비전 API 호출 완전 차단
                logger.info("[VSD] QualityControl 초기화 완료 (로컬 QC만, Gemini Vision 비활성화)")
            except ImportError as e:
                logger.warning(f"[VSD] QualityControl import 실패: {e}")
                self._quality_control = None

        return self._quality_control

    def _save_safe_image(self, output_path: str):
        """
        v59.3.0: CRITICAL 위반 시 안전 이미지 생성
        우선순위: 1) 이전 정상 이미지 재사용 → 2) 어두운 그라데이션
        """
        # v59.3.0: 이전 정상 이미지가 있으면 재사용
        last_good = getattr(self, '_last_good_image', None)
        if last_good and os.path.exists(last_good):
            try:
                import shutil
                shutil.copy(last_good, output_path)
                logger.info(f"[VSD] 이전 정상 이미지 재사용: {last_good} → {output_path}")
                return
            except Exception as e:
                logger.warning(f"[VSD] 이전 이미지 복사 실패: {e}")

        # 어두운 그라데이션 이미지 (순검정 대신)
        try:
            from PIL import Image, ImageDraw
            img = Image.new('RGB', (1024, 576))
            draw = ImageDraw.Draw(img)
            for y in range(576):
                # 상단 약간 밝고 하단 어두운 그라데이션
                c = int(20 * (1 - y / 576))
                draw.line([(0, y), (1024, y)], fill=(c, c, c + 5))
            img.save(output_path)
            logger.info(f"[VSD] 안전 이미지(그라데이션) 저장: {output_path}")
        except Exception as e:
            logger.error(f"[VSD] 안전 이미지 생성 실패: {e}")
            # 최후 수단: 순검정 PNG
            try:
                from PIL import Image
                img = Image.new('RGB', (1024, 576), color=(10, 10, 15))
                img.save(output_path)
            except Exception as e2:
                logger.error(f"[VSD] 최후 수단 순검정 PNG 생성도 실패: {e2}")

    # =========================================================
    # 캐릭터 라이브러리 생성
    # =========================================================

    def generate_character_library(self, char_id: str,
                                    expressions: List[str] = None,
                                    poses: List[str] = None) -> Dict[str, str]:
        """
        캐릭터 라이브러리 사전 생성

        Args:
            char_id: 캐릭터 ID
            expressions: 표정 목록 (None이면 기본값)
            poses: 포즈 목록 (None이면 기본값)

        Returns:
            {"{expression}_{pose}": "image_path", ...}
        """
        if not expressions:
            expressions = ["neutral", "happy", "sad", "fear", "anger", "surprise"]
        if not poses:
            poses = ["standing", "sitting", "walking"]

        logger.info(f"[VSD] 캐릭터 라이브러리 생성: {char_id} "
                   f"({len(expressions)} expressions x {len(poses)} poses)")

        library = {}
        output_path = self.output_dir / "character_library" / char_id
        output_path.mkdir(parents=True, exist_ok=True)

        for expr in expressions:
            for pose in poses:
                key = f"{expr}_{pose}"
                image_path = output_path / f"{key}.png"

                # 이미 있으면 스킵
                if image_path.exists():
                    library[key] = str(image_path)
                    continue

                # 프롬프트 생성
                composed = self.prompt_composer.compose_character_library_prompt(
                    char_id=char_id,
                    expression=expr,
                    pose=pose
                )

                # SD 생성
                if self.sd_client:
                    try:
                        self._call_sd_api(composed, str(image_path))
                        library[key] = str(image_path)
                        logger.debug(f"[VSD] 생성: {key}")
                    except Exception as e:
                        logger.error(f"[VSD] 생성 실패 ({key}): {e}")
                else:
                    # 테스트 모드
                    library[key] = str(image_path)

        # 캐시에 저장
        self.character_libraries[char_id] = library

        logger.info(f"[VSD] 라이브러리 완료: {char_id} → {len(library)}개 이미지")
        return library

    def generate_all_character_libraries(self) -> Dict[str, Dict[str, str]]:
        """모든 캐릭터 라이브러리 생성"""
        if not self.config:
            return {}

        # v59.3.3: dict/object 양쪽 지원
        if isinstance(self.config, dict):
            characters = self.config.get('characters', [])
        else:
            characters = getattr(self.config, 'characters', [])
        all_libraries = {}

        # characters가 dict(캐릭터ID→정의)인 경우 list로 변환
        if isinstance(characters, dict):
            characters = [
                {**v, 'id': k} if isinstance(v, dict) else v
                for k, v in characters.items()
                if not k.startswith('_')
            ]

        for char in characters:
            # v59.3.3: char가 dict 또는 object일 수 있음
            if isinstance(char, dict):
                char_id = char.get('id', '')
            else:
                char_id = getattr(char, 'id', '')
            if not char_id:
                continue

            # 캐릭터 정의에서 표정/포즈 추출
            if isinstance(char, dict):
                expressions = list(char.get('expressions', {}).keys())
                poses = list(char.get('poses', {}).keys())
            else:
                expressions = list(getattr(char, 'expressions', {}).keys())
                poses = list(getattr(char, 'poses', {}).keys())

            if not expressions:
                expressions = ["neutral", "happy", "sad", "fear"]
            if not poses:
                poses = ["standing", "sitting"]

            library = self.generate_character_library(char_id, expressions, poses)
            all_libraries[char_id] = library

        return all_libraries

    def load_character_library(self, char_id: str, library_path: str) -> bool:
        """저장된 캐릭터 라이브러리 로드"""
        lib_path = Path(library_path)
        if not lib_path.exists():
            return False

        library = {}
        for img_file in lib_path.glob("*.png"):
            key = img_file.stem  # "happy_standing" 등
            library[key] = str(img_file)

        self.character_libraries[char_id] = library
        logger.info(f"[VSD] 라이브러리 로드: {char_id} → {len(library)}개 이미지")
        return True

    # =========================================================
    # 유틸리티
    # =========================================================

    def get_summary(self, result: StorytellingResult) -> str:
        """결과 요약 문자열 생성"""
        return (
            f"Visual Storytelling Summary:\n"
            f"  Total dialogues: {result.total_dialogues}\n"
            f"  Images generated: {len(result.images)}\n"
            f"    - New: {result.new_images}\n"
            f"    - Expression swaps: {result.expression_swaps}\n"
            f"    - Pose swaps: {result.pose_swaps}\n"
            f"    - Reuses: {result.reuses}\n"
            f"  Total time: {result.total_time:.2f}s\n"
            f"  Avg generation time: {result.avg_generation_time:.2f}s\n"
            f"  Errors: {len(result.errors)}"
        )

    def reset(self):
        """상태 초기화"""
        self.previous_images.clear()
        self.character_panel_state.clear()
        self.location_panel_state.clear()
        self.cut_state_ledger.clear()
        self.consecutive_reuse_count = 0
        if self.scene_analyzer:
            self.scene_analyzer.reset_cache()
        logger.info("[VSD] 상태 초기화됨")


# ============================================================
# 팩토리 함수
# ============================================================

def create_visual_storytelling_director(
    pack_config: Any = None,
    gemini_client: Any = None,
    sd_client: Any = None,
    output_dir: str = ""
) -> Optional[VisualStorytellingDirector]:
    """
    VisualStorytellingDirector 생성 팩토리

    Args:
        pack_config: ACTIVE_PACK 또는 pack_config 모듈
        gemini_client: Gemini API 클라이언트
        sd_client: SD WebUI API 클라이언트
        output_dir: 출력 디렉토리

    Returns:
        VisualStorytellingDirector 또는 None (비활성화 시)
    """
    # config에서 visual_storytelling 추출
    vs_config = None

    if pack_config:
        # pack_config 모듈인 경우
        if hasattr(pack_config, 'get_visual_storytelling_config'):
            vs_config = pack_config.get_visual_storytelling_config()
        # ActivePack 인스턴스인 경우
        elif hasattr(pack_config, 'visual_storytelling'):
            vs_config = pack_config.visual_storytelling

    # v59.3.3: dict/object 양쪽 지원
    if not vs_config:
        logger.info("[VSD Factory] 비주얼 스토리텔링 비활성화됨 (config 없음)")
        return None
    if isinstance(vs_config, dict):
        enabled = vs_config.get('enabled', False)
    else:
        enabled = getattr(vs_config, 'enabled', False)
    if not enabled:
        logger.info("[VSD Factory] 비주얼 스토리텔링 비활성화됨")
        return None

    return VisualStorytellingDirector(
        config=vs_config,
        gemini_client=gemini_client,
        sd_client=sd_client,
        output_dir=output_dir
    )


# ============================================================
# 테스트
# ============================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    print("=== VisualStorytellingDirector Test ===\n")

    # Mock 설정
    class MockConfig:
        def __init__(self):
            self.enabled = True
            self.characters = []
            self.sd_model = None
            self.max_consecutive_reuse = 2
            self.images_per_minute = 3

    # Director 생성
    director = VisualStorytellingDirector(
        config=MockConfig(),
        gemini_client=None,
        sd_client=None,
        output_dir="temp/test_vsd"
    )

    print(f"1. Director created: enabled={director.is_enabled()}")

    # 테스트 대사
    test_dialogues = [
        {"speaker": "narrator", "text": "The night was dark."},
        {"speaker": "hero", "text": "I heard something strange..."},
        {"speaker": "narrator", "text": "He walked forward carefully."},
    ]

    # 처리
    print("\n2. Processing dialogues...")
    result = director.process_dialogues(test_dialogues, job_id="test_001")

    print(f"\n3. Result:")
    print(f"   Images: {len(result.images)}")
    print(f"   New: {result.new_images}")
    print(f"   Reuse: {result.reuses}")
    print(f"   Time: {result.total_time:.2f}s")

    print("\n4. Summary:")
    print(director.get_summary(result))

    print("\n[OK] Test completed!")
