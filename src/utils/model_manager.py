# src/utils/model_manager.py
"""
v33: TTS 모델 관리 시스템

커스텀 TTS 모델을 등록, 수정, 삭제하고
채널별 캐릭터-모델 매핑을 관리합니다.
"""
import os
import json
import logging
import shutil
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field, asdict
from glob import glob

logger = logging.getLogger(__name__)

from config.settings import config


# ============================================================
# 모델 정보 스키마
# ============================================================
@dataclass
class EmotionInfo:
    """감정 정보"""
    reference_audio: str  # 참조 음성 파일 (상대 경로)
    reference_text: str   # 참조 텍스트
    description: str = "" # 감정 설명

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> 'EmotionInfo':
        return cls(
            reference_audio=data.get("reference_audio", ""),
            reference_text=data.get("reference_text", ""),
            description=data.get("description", "")
        )


@dataclass
class ModelInfo:
    """TTS 모델 정보"""
    schema_version: str = "1.0"
    name: str = ""
    description: str = ""
    created_at: str = ""
    updated_at: str = ""
    author: str = ""

    # 파일 정보
    gpt_weights: str = "gpt_weights.ckpt"
    sovits_weights: str = "sovits_weights.pth"

    # 감정 매핑
    emotions: Dict[str, EmotionInfo] = field(default_factory=dict)

    # 메타데이터
    default_emotion: str = "calm"
    language: str = "ko"
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "name": self.name,
            "description": self.description,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "author": self.author,
            "files": {
                "gpt_weights": self.gpt_weights,
                "sovits_weights": self.sovits_weights
            },
            "emotions": {k: v.to_dict() for k, v in self.emotions.items()},
            "default_emotion": self.default_emotion,
            "language": self.language,
            "tags": self.tags
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'ModelInfo':
        files = data.get("files", {})
        emotions_data = data.get("emotions", {})
        emotions = {}
        for k, v in emotions_data.items():
            if isinstance(v, dict):
                emotions[k] = EmotionInfo.from_dict(v)
            else:
                # 구버전 호환 (문자열만 있는 경우)
                emotions[k] = EmotionInfo(
                    reference_audio=f"emotions/{k}.wav",
                    reference_text=str(v),
                    description=""
                )

        return cls(
            schema_version=data.get("schema_version", "1.0"),
            name=data.get("name", ""),
            description=data.get("description", ""),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            author=data.get("author", ""),
            gpt_weights=files.get("gpt_weights", "gpt_weights.ckpt"),
            sovits_weights=files.get("sovits_weights", "sovits_weights.pth"),
            emotions=emotions,
            default_emotion=data.get("default_emotion", "calm"),
            language=data.get("language", "ko"),
            tags=data.get("tags", [])
        )

    def save(self, path: str):
        """model_info.json 저장"""
        self.updated_at = datetime.now().isoformat()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, path: str) -> Optional['ModelInfo']:
        """model_info.json 로드"""
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return cls.from_dict(data)
        except Exception as e:
            logger.warning(f"[ModelInfo] 로드 실패: {e}")
            return None


# ============================================================
# 채널별 캐릭터-모델 매핑
# ============================================================
@dataclass
class ChannelMapping:
    """채널별 캐릭터-모델 매핑"""
    channel_id: str
    character_models: Dict[str, str] = field(default_factory=dict)  # 캐릭터 -> 모델 경로

    def to_dict(self) -> dict:
        return {
            "channel_id": self.channel_id,
            "character_models": self.character_models
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'ChannelMapping':
        return cls(
            channel_id=data.get("channel_id", ""),
            character_models=data.get("character_models", {})
        )


# ============================================================
# 모델 관리자 클래스
# ============================================================
class ModelManager:
    """TTS 모델 관리자"""

    # 기본 캐릭터 목록 (채널별)
    DEFAULT_CHARACTERS = {
        "daily_life_toon": ["narrator", "grandma", "grandpa", "middle_woman", "young_man", "young_woman"],
        "mystery_toon": ["narrator", "grandma", "grandpa", "middle_woman", "young_man", "young_woman", "manager"],
    }

    # 기본 감정 목록 (v56.8: Qwen3-TTS 7가지 통일)
    DEFAULT_EMOTIONS = ["calm", "sad", "angry", "happy", "scared", "excited", "whisper"]

    # v56.8: 레거시 감정 → 표준 감정 매핑 (호환성)
    EMOTION_FALLBACK_MAP = {
        "fear": "scared",
        "afraid": "scared",
        "terrified": "scared",
        "neutral": "calm",
        "normal": "calm",
        "joy": "happy",
        "joyful": "happy",
    }

    def __init__(self):
        self.models_dir = os.path.join(config.ASSETS_DIR, "models")
        self.custom_dir = os.path.join(self.models_dir, "custom")
        self.mapping_file = os.path.join(config.DATA_DIR, "channel_model_mapping.json")

        # 폴더 생성
        os.makedirs(self.custom_dir, exist_ok=True)
        os.makedirs(config.DATA_DIR, exist_ok=True)

        # 매핑 로드
        self.channel_mappings: Dict[str, ChannelMapping] = self._load_mappings()

    # ============================================================
    # 모델 목록 조회
    # ============================================================
    def get_all_models(self) -> List[Dict]:
        """
        모든 모델 목록 반환

        Returns:
            [{"id": "senior/grandma", "name": "할머니", "path": "...", "type": "builtin"}, ...]
        """
        models = []

        # 1. 기본 제공 모델 (horror, senior)
        for category in ["horror", "senior"]:
            category_dir = os.path.join(self.models_dir, category)
            if not os.path.isdir(category_dir):
                continue

            for char_name in os.listdir(category_dir):
                char_dir = os.path.join(category_dir, char_name)
                if not os.path.isdir(char_dir):
                    continue

                # 가중치 파일 존재 확인
                gpt_path = os.path.join(char_dir, "gpt_weights.ckpt")
                sov_path = os.path.join(char_dir, "sovits_weights.pth")

                if os.path.exists(gpt_path) and os.path.exists(sov_path):
                    model_info = self._load_or_create_model_info(char_dir, char_name)
                    models.append({
                        "id": f"{category}/{char_name}",
                        "name": model_info.name if model_info.name else char_name,
                        "path": char_dir,
                        "type": "builtin",
                        "category": category,
                        "emotions": list(model_info.emotions.keys()) if model_info else self.DEFAULT_EMOTIONS,
                        "description": model_info.description if model_info else ""
                    })

        # 2. 커스텀 모델
        if os.path.isdir(self.custom_dir):
            for model_name in os.listdir(self.custom_dir):
                model_dir = os.path.join(self.custom_dir, model_name)
                if not os.path.isdir(model_dir):
                    continue

                gpt_path = os.path.join(model_dir, "gpt_weights.ckpt")
                sov_path = os.path.join(model_dir, "sovits_weights.pth")

                if os.path.exists(gpt_path) and os.path.exists(sov_path):
                    model_info = ModelInfo.load(os.path.join(model_dir, "model_info.json"))
                    models.append({
                        "id": f"custom/{model_name}",
                        "name": model_info.name if model_info and model_info.name else model_name,
                        "path": model_dir,
                        "type": "custom",
                        "category": "custom",
                        "emotions": list(model_info.emotions.keys()) if model_info else ["calm"],
                        "description": model_info.description if model_info else ""
                    })

        return models

    def get_model_by_id(self, model_id: str) -> Optional[Dict]:
        """모델 ID로 모델 정보 조회"""
        models = self.get_all_models()
        for m in models:
            if m["id"] == model_id:
                return m
        return None

    def get_model_info(self, model_id: str) -> Optional[ModelInfo]:
        """모델 ID로 ModelInfo 조회"""
        model = self.get_model_by_id(model_id)
        if not model:
            return None

        info_path = os.path.join(model["path"], "model_info.json")
        return ModelInfo.load(info_path)

    def _load_or_create_model_info(self, model_dir: str, default_name: str) -> ModelInfo:
        """model_info.json 로드 또는 기본값 생성"""
        info_path = os.path.join(model_dir, "model_info.json")
        info = ModelInfo.load(info_path)

        if info:
            return info

        # 구버전 호환: voice_metadata.json에서 감정 정보 로드
        metadata_path = os.path.join(os.path.dirname(model_dir), "voice_metadata.json")
        emotions = {}

        if os.path.exists(metadata_path):
            try:
                with open(metadata_path, "r", encoding="utf-8") as f:
                    metadata = json.load(f)
                char_data = metadata.get(default_name, {})
                for emo, text in char_data.items():
                    ref_audio = self._find_emotion_audio(model_dir, emo)
                    emotions[emo] = EmotionInfo(
                        reference_audio=ref_audio,
                        reference_text=text,
                        description=""
                    )
            except Exception as e:
                logger.warning(f"모델 메타데이터 로드/등록 실패: {e}")

        # 기본 감정이 없으면 폴더에서 찾기
        if not emotions:
            for emo in self.DEFAULT_EMOTIONS:
                ref_audio = self._find_emotion_audio(model_dir, emo)
                if ref_audio:
                    emotions[emo] = EmotionInfo(
                        reference_audio=ref_audio,
                        reference_text="안녕하세요.",
                        description=""
                    )

        return ModelInfo(
            name=default_name,
            emotions=emotions,
            created_at=datetime.now().isoformat()
        )

    def _find_emotion_audio(self, model_dir: str, emotion: str) -> str:
        """감정에 해당하는 참조 음성 파일 찾기"""
        candidates = [
            os.path.join(model_dir, f"{emotion}.wav"),
            os.path.join(model_dir, f"{emotion}.mp3"),
            os.path.join(model_dir, "emotions", f"{emotion}.wav"),
            os.path.join(model_dir, "emotions", f"{emotion}.mp3"),
        ]
        for p in candidates:
            if os.path.exists(p):
                return os.path.relpath(p, model_dir)
        return ""

    # ============================================================
    # 커스텀 모델 CRUD
    # ============================================================
    def create_custom_model(
        self,
        name: str,
        gpt_weights_src: str,
        sovits_weights_src: str,
        description: str = "",
        author: str = "",
        emotions: Dict[str, Dict] = None
    ) -> Tuple[bool, str]:
        """
        커스텀 모델 생성

        Args:
            name: 모델 이름 (폴더명으로 사용)
            gpt_weights_src: GPT 가중치 파일 원본 경로
            sovits_weights_src: SoVITS 가중치 파일 원본 경로
            description: 모델 설명
            author: 작성자
            emotions: 감정 정보 {"calm": {"reference_audio": "...", "reference_text": "..."}}

        Returns:
            (성공 여부, 메시지)
        """
        # 이름 검증
        safe_name = self._sanitize_name(name)
        if not safe_name:
            return False, "유효하지 않은 모델 이름입니다."

        model_dir = os.path.join(self.custom_dir, safe_name)

        if os.path.exists(model_dir):
            return False, f"'{safe_name}' 모델이 이미 존재합니다."

        # 원본 파일 확인
        if not os.path.exists(gpt_weights_src):
            return False, f"GPT 가중치 파일을 찾을 수 없습니다: {gpt_weights_src}"
        if not os.path.exists(sovits_weights_src):
            return False, f"SoVITS 가중치 파일을 찾을 수 없습니다: {sovits_weights_src}"

        try:
            # 폴더 생성
            os.makedirs(model_dir, exist_ok=True)
            emotions_dir = os.path.join(model_dir, "emotions")
            os.makedirs(emotions_dir, exist_ok=True)

            # 가중치 파일 복사
            shutil.copy2(gpt_weights_src, os.path.join(model_dir, "gpt_weights.ckpt"))
            shutil.copy2(sovits_weights_src, os.path.join(model_dir, "sovits_weights.pth"))

            # 감정 정보 처리
            emotion_objects = {}
            if emotions:
                for emo_name, emo_data in emotions.items():
                    ref_audio_src = emo_data.get("reference_audio", "")
                    ref_text = emo_data.get("reference_text", "안녕하세요.")
                    desc = emo_data.get("description", "")

                    # 참조 음성 복사
                    if ref_audio_src and os.path.exists(ref_audio_src):
                        ext = os.path.splitext(ref_audio_src)[1]
                        ref_audio_dest = os.path.join(emotions_dir, f"{emo_name}{ext}")
                        shutil.copy2(ref_audio_src, ref_audio_dest)
                        rel_path = f"emotions/{emo_name}{ext}"
                    else:
                        rel_path = ""

                    emotion_objects[emo_name] = EmotionInfo(
                        reference_audio=rel_path,
                        reference_text=ref_text,
                        description=desc
                    )

            # model_info.json 생성
            model_info = ModelInfo(
                name=name,
                description=description,
                author=author,
                created_at=datetime.now().isoformat(),
                updated_at=datetime.now().isoformat(),
                emotions=emotion_objects,
                default_emotion=list(emotion_objects.keys())[0] if emotion_objects else "calm"
            )
            model_info.save(os.path.join(model_dir, "model_info.json"))

            return True, f"모델 '{name}'이(가) 생성되었습니다."

        except Exception as e:
            # 실패 시 폴더 정리
            if os.path.exists(model_dir):
                shutil.rmtree(model_dir)
            return False, f"모델 생성 실패: {e}"

    def update_custom_model(
        self,
        model_id: str,
        name: str = None,
        description: str = None,
        emotions: Dict[str, Dict] = None
    ) -> Tuple[bool, str]:
        """커스텀 모델 정보 수정"""
        if not model_id.startswith("custom/"):
            return False, "기본 제공 모델은 수정할 수 없습니다."

        model = self.get_model_by_id(model_id)
        if not model:
            return False, "모델을 찾을 수 없습니다."

        model_dir = model["path"]
        info_path = os.path.join(model_dir, "model_info.json")

        info = ModelInfo.load(info_path)
        if not info:
            info = ModelInfo()

        if name:
            info.name = name
        if description is not None:
            info.description = description

        # 감정 업데이트
        if emotions:
            emotions_dir = os.path.join(model_dir, "emotions")
            os.makedirs(emotions_dir, exist_ok=True)

            for emo_name, emo_data in emotions.items():
                ref_audio_src = emo_data.get("reference_audio", "")
                ref_text = emo_data.get("reference_text", "")
                desc = emo_data.get("description", "")

                # 새 참조 음성이 있으면 복사
                if ref_audio_src and os.path.exists(ref_audio_src) and not ref_audio_src.startswith(model_dir):
                    ext = os.path.splitext(ref_audio_src)[1]
                    ref_audio_dest = os.path.join(emotions_dir, f"{emo_name}{ext}")
                    shutil.copy2(ref_audio_src, ref_audio_dest)
                    rel_path = f"emotions/{emo_name}{ext}"
                else:
                    rel_path = ref_audio_src

                info.emotions[emo_name] = EmotionInfo(
                    reference_audio=rel_path,
                    reference_text=ref_text,
                    description=desc
                )

        info.save(info_path)
        return True, "모델 정보가 수정되었습니다."

    def delete_custom_model(self, model_id: str) -> Tuple[bool, str]:
        """커스텀 모델 삭제"""
        if not model_id.startswith("custom/"):
            return False, "기본 제공 모델은 삭제할 수 없습니다."

        model = self.get_model_by_id(model_id)
        if not model:
            return False, "모델을 찾을 수 없습니다."

        try:
            shutil.rmtree(model["path"])

            # 매핑에서도 제거
            for channel_id, mapping in self.channel_mappings.items():
                for char, mapped_model in list(mapping.character_models.items()):
                    if mapped_model == model_id:
                        del mapping.character_models[char]
            self._save_mappings()

            return True, "모델이 삭제되었습니다."
        except Exception as e:
            return False, f"삭제 실패: {e}"

    def add_emotion_to_model(
        self,
        model_id: str,
        emotion_name: str,
        reference_audio: str,
        reference_text: str,
        description: str = ""
    ) -> Tuple[bool, str]:
        """모델에 감정 추가"""
        if not model_id.startswith("custom/"):
            return False, "기본 제공 모델에는 감정을 추가할 수 없습니다."

        model = self.get_model_by_id(model_id)
        if not model:
            return False, "모델을 찾을 수 없습니다."

        model_dir = model["path"]
        emotions_dir = os.path.join(model_dir, "emotions")
        os.makedirs(emotions_dir, exist_ok=True)

        # 참조 음성 복사
        if reference_audio and os.path.exists(reference_audio):
            ext = os.path.splitext(reference_audio)[1]
            dest_path = os.path.join(emotions_dir, f"{emotion_name}{ext}")
            shutil.copy2(reference_audio, dest_path)
            rel_path = f"emotions/{emotion_name}{ext}"
        else:
            return False, "참조 음성 파일을 찾을 수 없습니다."

        # model_info.json 업데이트
        info_path = os.path.join(model_dir, "model_info.json")
        info = ModelInfo.load(info_path) or ModelInfo()

        info.emotions[emotion_name] = EmotionInfo(
            reference_audio=rel_path,
            reference_text=reference_text,
            description=description
        )
        info.save(info_path)

        return True, f"감정 '{emotion_name}'이(가) 추가되었습니다."

    def remove_emotion_from_model(self, model_id: str, emotion_name: str) -> Tuple[bool, str]:
        """모델에서 감정 제거"""
        if not model_id.startswith("custom/"):
            return False, "기본 제공 모델의 감정은 제거할 수 없습니다."

        model = self.get_model_by_id(model_id)
        if not model:
            return False, "모델을 찾을 수 없습니다."

        info_path = os.path.join(model["path"], "model_info.json")
        info = ModelInfo.load(info_path)

        if not info or emotion_name not in info.emotions:
            return False, f"감정 '{emotion_name}'을(를) 찾을 수 없습니다."

        # 참조 음성 파일 삭제
        emo_info = info.emotions[emotion_name]
        if emo_info.reference_audio:
            audio_path = os.path.join(model["path"], emo_info.reference_audio)
            if os.path.exists(audio_path):
                os.remove(audio_path)

        del info.emotions[emotion_name]
        info.save(info_path)

        return True, f"감정 '{emotion_name}'이(가) 제거되었습니다."

    # ============================================================
    # 채널-캐릭터-모델 매핑
    # ============================================================
    def get_channel_mapping(self, channel_id: str) -> ChannelMapping:
        """채널의 캐릭터-모델 매핑 조회"""
        if channel_id not in self.channel_mappings:
            self.channel_mappings[channel_id] = ChannelMapping(
                channel_id=channel_id,
                character_models={}
            )
        return self.channel_mappings[channel_id]

    def set_character_model(self, channel_id: str, character: str, model_id: str) -> Tuple[bool, str]:
        """캐릭터에 모델 매핑"""
        # 모델 존재 확인
        model = self.get_model_by_id(model_id)
        if not model:
            return False, f"모델 '{model_id}'을(를) 찾을 수 없습니다."

        mapping = self.get_channel_mapping(channel_id)
        mapping.character_models[character] = model_id
        self._save_mappings()

        return True, f"'{character}'에 '{model['name']}' 모델이 매핑되었습니다."

    def get_character_model(self, channel_id: str, character: str) -> Optional[str]:
        """캐릭터에 매핑된 모델 ID 조회"""
        mapping = self.get_channel_mapping(channel_id)
        return mapping.character_models.get(character)

    def reset_channel_mapping(self, channel_id: str) -> Tuple[bool, str]:
        """채널 매핑 초기화 (기본값으로)"""
        self.channel_mappings[channel_id] = ChannelMapping(
            channel_id=channel_id,
            character_models={}
        )
        self._save_mappings()
        return True, "채널 매핑이 초기화되었습니다."

    def _load_mappings(self) -> Dict[str, ChannelMapping]:
        """매핑 파일 로드"""
        if not os.path.exists(self.mapping_file):
            return {}

        try:
            with open(self.mapping_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            mappings = {}
            for channel_id, mapping_data in data.items():
                mappings[channel_id] = ChannelMapping.from_dict(mapping_data)
            return mappings
        except Exception as e:
            logger.warning(f"[ModelManager] 매핑 로드 실패: {e}")
            return {}

    def _save_mappings(self):
        """매핑 파일 저장"""
        try:
            data = {k: v.to_dict() for k, v in self.channel_mappings.items()}
            with open(self.mapping_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"[ModelManager] 매핑 저장 실패: {e}")

    # ============================================================
    # 헬퍼 메서드
    # ============================================================
    def _sanitize_name(self, name: str) -> str:
        """파일/폴더명으로 사용 가능하게 정리"""
        import re
        # 알파벳, 숫자, 한글, 언더스코어, 하이픈만 허용
        safe = re.sub(r'[^\w\s가-힣-]', '', name)
        safe = safe.strip().replace(' ', '_')
        return safe[:50] if safe else ""

    def resolve_model_for_character(self, channel_id: str, character: str) -> Optional[Dict]:
        """
        캐릭터에 해당하는 모델 정보 반환 (매핑 우선, 없으면 기본값)

        Returns:
            {
                "model_id": "custom/우리할배",
                "path": "...",
                "gpt_weights": "...",
                "sovits_weights": "...",
                "emotions": {...}
            }
        """
        # 1. 커스텀 매핑 확인
        model_id = self.get_character_model(channel_id, character)

        if not model_id:
            # 2. 기본 모델 매핑
            if channel_id == "horror" and character == "narrator":
                model_id = "horror/narrator"
            else:
                # senior 계열은 senior/{character}
                char_key = self._normalize_character_key(character)
                model_id = f"senior/{char_key}"

        # 모델 정보 조회
        model = self.get_model_by_id(model_id)
        if not model:
            return None

        # 전체 경로 포함
        return {
            "model_id": model_id,
            "path": model["path"],
            "gpt_weights": os.path.join(model["path"], "gpt_weights.ckpt"),
            "sovits_weights": os.path.join(model["path"], "sovits_weights.pth"),
            "emotions": model.get("emotions", []),
            "name": model.get("name", "")
        }

    def _normalize_character_key(self, character: str) -> str:
        """캐릭터 이름을 모델 폴더 키로 변환 (v57.6.7: 성별 기반 매핑 추가)"""
        # 직접 매핑 (우선)
        direct_mapping = {
            "할머니": "grandma",
            "할아버지": "grandpa",
            "남자": "man",
            "여자": "woman",
            "내레이터": "narrator",
            "내레이션": "narrator",
            "나레이션": "narrator",
            "나레이터": "narrator",
        }

        char_lower = character.lower().strip()
        if character in direct_mapping:
            return direct_mapping[character]
        if char_lower in direct_mapping:
            return direct_mapping[char_lower]

        # v57.6.7: 한국 이름 성별 추론 매핑
        # 남성 이름 (끝 글자 기반 + 일반적 남성 이름)
        male_endings = ("준", "혁", "민", "훈", "우", "진", "호", "석", "수", "영", "철", "현", "규", "태", "성")
        male_names = ("태준", "민혁", "지훈", "성우", "강민", "동현", "준호", "영수", "철수", "민수",
                      "현우", "지호", "승현", "재민", "도윤", "시우", "주원", "하준", "은우", "건우",
                      "강태준", "서민혁", "박지훈", "김성우", "이동현")

        # 여성 이름 (끝 글자 기반 + 일반적 여성 이름)
        female_endings = ("미", "아", "희", "연", "은", "지", "서", "린", "나", "윤", "빈")
        female_names = ("혜미", "지우", "수아", "민지", "서연", "지은", "유나", "하은", "소희", "예린",
                        "서지우", "김혜미", "박민지", "이서연", "최유나", "정하은", "강소희")

        # 이름으로 직접 매핑
        if character in male_names or char_lower in male_names:
            return "man"
        if character in female_names or char_lower in female_names:
            return "woman"

        # 끝 글자로 추론
        if len(character) >= 2:
            last_char = character[-1]
            if last_char in male_endings:
                return "man"
            if last_char in female_endings:
                return "woman"

        # 기본값: narrator
        return char_lower

    # ============================================================
    # v34: 동적 감정 시스템 API
    # ============================================================
    def get_available_emotions_for_channel(self, channel_id: str) -> Dict[str, List[str]]:
        """
        채널에서 사용 가능한 모든 감정 목록 반환 (캐릭터별)

        Args:
            channel_id: 채널 ID (horror, senior_touching, senior_makjang)

        Returns:
            {
                "narrator": ["calm", "sad", "angry", "happy", "fear"],
                "grandma": ["calm", "소노", "중노", "대노", "서운함"],
                ...
            }
        """
        characters = self.DEFAULT_CHARACTERS.get(channel_id, ["narrator"])
        result = {}

        for char in characters:
            model_info = self.resolve_model_for_character(channel_id, char)
            if model_info:
                full_info = self.get_model_info(model_info["model_id"])
                if full_info and full_info.emotions:
                    result[char] = list(full_info.emotions.keys())
                else:
                    # 기본 감정
                    result[char] = self.DEFAULT_EMOTIONS.copy()
            else:
                result[char] = self.DEFAULT_EMOTIONS.copy()

        return result

    def normalize_emotion(self, emotion: str) -> str:
        """
        레거시 감정을 표준 감정으로 정규화 (v56.8)

        Args:
            emotion: 원본 감정 태그

        Returns:
            정규화된 감정 (Qwen3-TTS 7가지 중 하나)
        """
        if not emotion:
            return "calm"
        emotion_lower = emotion.lower().strip()
        return self.EMOTION_FALLBACK_MAP.get(emotion_lower, emotion_lower)

    def get_all_emotions_for_channel(self, channel_id: str) -> List[str]:
        """
        채널에서 사용 가능한 모든 감정 목록 (중복 제거)

        v56.8: fear → scared 등 레거시 감정 자동 변환

        Args:
            channel_id: 채널 ID

        Returns:
            ["calm", "sad", "angry", "happy", "scared", ...]
        """
        char_emotions = self.get_available_emotions_for_channel(channel_id)
        all_emotions = set()
        for emotions in char_emotions.values():
            # v56.8: 레거시 감정 정규화
            normalized = [self.normalize_emotion(e) for e in emotions]
            all_emotions.update(normalized)
        return sorted(list(all_emotions))

    def get_emotion_descriptions_for_channel(self, channel_id: str) -> Dict[str, str]:
        """
        채널에서 사용 가능한 감정들의 설명 반환 (Gemini 힌트용)

        Args:
            channel_id: 채널 ID

        Returns:
            {
                "calm": "평온한 상태",
                "소노": "약간 화난 상태",
                "중노": "중간 정도로 화난 상태",
                ...
            }
        """
        characters = self.DEFAULT_CHARACTERS.get(channel_id, ["narrator"])
        descriptions = {}

        # 기본 감정 설명 (v56.8: Qwen3-TTS 7가지)
        default_descriptions = {
            "calm": "평온한 상태",
            "sad": "슬픈 상태",
            "angry": "화난 상태",
            "happy": "행복한 상태",
            "scared": "두려운 상태",
            "excited": "흥분한 상태",
            "whisper": "속삭이는 상태",
        }
        descriptions.update(default_descriptions)

        # 커스텀 모델의 감정 설명 추가
        for char in characters:
            model_info = self.resolve_model_for_character(channel_id, char)
            if model_info:
                full_info = self.get_model_info(model_info["model_id"])
                if full_info and full_info.emotions:
                    for emo_name, emo_info in full_info.emotions.items():
                        if emo_info.description and emo_name not in default_descriptions:
                            descriptions[emo_name] = emo_info.description

        return descriptions

    def build_emotion_prompt_for_channel(self, channel_id: str) -> str:
        """
        Gemini 프롬프트용 감정 규칙 문자열 생성

        Args:
            channel_id: 채널 ID

        Returns:
            "[EMOTION RULE]\n- emotion은 반드시 아래 중 하나:\n  calm, sad, angry, ..."
        """
        emotions = self.get_all_emotions_for_channel(channel_id)
        descriptions = self.get_emotion_descriptions_for_channel(channel_id)

        # 감정 목록 문자열
        emotion_list = ", ".join([f'"{e}"' for e in emotions])

        # 감정 설명 문자열
        desc_lines = []
        for emo in emotions:
            desc = descriptions.get(emo, "")
            if desc:
                desc_lines.append(f"  - {emo}: {desc}")
            else:
                desc_lines.append(f"  - {emo}")

        prompt = f"""[EMOTION RULE - DYNAMIC]
- emotion은 반드시 아래 중 하나만 사용:
  {emotion_list}

감정 설명:
{chr(10).join(desc_lines)}

- 자연스러운 감정 흐름 유지 (기승전결에 맞춰 변화)
- calm은 전체의 70%를 넘지 않도록 함
"""
        return prompt


# ============================================================
# 싱글톤 인스턴스
# ============================================================
_model_manager_instance = None

def get_model_manager() -> ModelManager:
    """ModelManager 싱글톤 인스턴스 반환"""
    global _model_manager_instance
    if _model_manager_instance is None:
        _model_manager_instance = ModelManager()
    return _model_manager_instance


# ============================================================
# 테스트
# ============================================================
if __name__ == "__main__":
    mm = get_model_manager()

    print("=" * 60)
    print("모델 목록")
    print("=" * 60)

    for m in mm.get_all_models():
        print(f"  [{m['type']:7}] {m['id']:20} - {m['name']}")
        print(f"           감정: {', '.join(m['emotions'][:5])}{'...' if len(m['emotions']) > 5 else ''}")

    print("\n" + "=" * 60)
