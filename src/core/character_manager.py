# -*- coding: utf-8 -*-
"""
Character Manager (캐릭터 관리자)

v55.0.0: 캐릭터 일관성을 위한 참조 이미지 관리
- 캐릭터별 참조 이미지 저장/로드
- 시나리오별 캐릭터 매핑
- IP-Adapter/ControlNet 연동 설정

Author: Reverie Studio
"""

import os
import json
import logging
import shutil
import threading
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict, field
from datetime import datetime
from PIL import Image

logger = logging.getLogger(__name__)


@dataclass
class CharacterProfile:
    """캐릭터 프로필"""

    # 기본 정보
    character_id: str               # 고유 ID (예: "horror_ghost_001")
    name: str                       # 캐릭터 이름 (예: "처녀귀신")
    description: str = ""           # 설명

    # 참조 이미지
    reference_images: List[str] = field(default_factory=list)  # 참조 이미지 파일명들
    primary_image: str = ""         # 주 참조 이미지

    # 프롬프트 정보
    base_prompt: str = ""           # 기본 프롬프트 (캐릭터 외형)
    negative_tags: List[str] = field(default_factory=list)  # 제외 태그

    # IP-Adapter 설정
    ip_weight: float = 0.7          # IP-Adapter 가중치
    face_only: bool = True          # 얼굴만 참조 여부

    # 메타데이터
    channel_type: str = ""          # 채널 타입 (horror, emotional 등)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    use_count: int = 0              # 사용 횟수

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CharacterProfile':
        """딕셔너리에서 생성"""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class CharacterManager:
    """
    캐릭터 관리자

    채널별/시나리오별 캐릭터 참조 이미지 관리
    IP-Adapter 연동을 위한 일관성 설정

    v55.0.0: 초기 구현
    """

    def __init__(self, data_dir: str, channel_type: str = "daily_life_toon"):
        """
        초기화

        Args:
            data_dir: 데이터 디렉토리
            channel_type: 채널 타입
        """
        self.data_dir = data_dir
        self.channel_type = channel_type

        # 디렉토리 설정
        self.characters_dir = os.path.join(data_dir, "characters", channel_type)
        self.registry_path = os.path.join(self.characters_dir, "character_registry.json")

        # 캐릭터 캐시
        self._characters: Dict[str, CharacterProfile] = {}
        self._lock = threading.Lock()

        # 초기화
        self._ensure_directories()
        self._load_registry()

        logger.info(f"CharacterManager 초기화: {channel_type}, {len(self._characters)}개 캐릭터")

    def _ensure_directories(self):
        """디렉토리 생성"""
        os.makedirs(self.characters_dir, exist_ok=True)

    def _load_registry(self):
        """레지스트리 로드"""
        if os.path.exists(self.registry_path):
            try:
                with open(self.registry_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                for char_data in data.get("characters", []):
                    try:
                        character = CharacterProfile.from_dict(char_data)
                        self._characters[character.character_id] = character
                    except Exception as e:
                        logger.warning(f"캐릭터 로드 실패: {e}")

            except Exception as e:
                logger.error(f"레지스트리 로드 실패: {e}")

    def _save_registry(self):
        """레지스트리 저장"""
        with self._lock:
            try:
                data = {
                    "version": "55.0.0",
                    "channel_type": self.channel_type,
                    "total_characters": len(self._characters),
                    "updated_at": datetime.now().isoformat(),
                    "characters": [ch.to_dict() for ch in self._characters.values()]
                }

                with open(self.registry_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)

            except Exception as e:
                logger.error(f"레지스트리 저장 실패: {e}")

    # ========== 캐릭터 관리 API ==========

    def create_character(
        self,
        name: str,
        description: str = "",
        base_prompt: str = "",
        ip_weight: float = 0.7,
        face_only: bool = True
    ) -> Optional[CharacterProfile]:
        """
        새 캐릭터 생성

        Args:
            name: 캐릭터 이름
            description: 설명
            base_prompt: 기본 프롬프트
            ip_weight: IP-Adapter 가중치
            face_only: 얼굴만 참조 여부

        Returns:
            CharacterProfile: 생성된 캐릭터 (실패 시 None)
        """
        # ID 생성
        character_id = self._generate_id(name)

        # 캐릭터 폴더 생성
        char_dir = self._get_character_dir(character_id)
        os.makedirs(char_dir, exist_ok=True)

        # 프로필 생성
        character = CharacterProfile(
            character_id=character_id,
            name=name,
            description=description,
            base_prompt=base_prompt,
            ip_weight=ip_weight,
            face_only=face_only,
            channel_type=self.channel_type
        )

        # 등록
        self._characters[character_id] = character
        self._save_registry()

        logger.info(f"캐릭터 생성: {character_id} ({name})")
        return character

    def _generate_id(self, name: str) -> str:
        """캐릭터 ID 생성"""
        import re
        # 한글/영문을 기반으로 ID 생성
        base_id = re.sub(r'[^a-zA-Z0-9가-힣]', '', name)[:10]
        if not base_id:
            base_id = "char"

        # 중복 체크
        idx = 1
        while True:
            character_id = f"{self.channel_type}_{base_id}_{idx:03d}"
            if character_id not in self._characters:
                return character_id
            idx += 1

    def _get_character_dir(self, character_id: str) -> str:
        """캐릭터 폴더 경로"""
        return os.path.join(self.characters_dir, character_id)

    def delete_character(self, character_id: str, delete_files: bool = False) -> bool:
        """
        캐릭터 삭제

        Args:
            character_id: 캐릭터 ID
            delete_files: 파일도 삭제할지 여부

        Returns:
            bool: 성공 여부
        """
        if character_id not in self._characters:
            logger.warning(f"캐릭터 없음: {character_id}")
            return False

        # 삭제
        del self._characters[character_id]
        self._save_registry()

        # 파일 삭제
        if delete_files:
            char_dir = self._get_character_dir(character_id)
            if os.path.exists(char_dir):
                shutil.rmtree(char_dir)
                logger.info(f"캐릭터 폴더 삭제: {char_dir}")

        logger.info(f"캐릭터 삭제: {character_id}")
        return True

    def get_character(self, character_id: str) -> Optional[CharacterProfile]:
        """캐릭터 조회"""
        return self._characters.get(character_id)

    def get_all_characters(self) -> List[CharacterProfile]:
        """모든 캐릭터 목록"""
        return list(self._characters.values())

    def update_character(self, character_id: str, **kwargs) -> bool:
        """
        캐릭터 정보 업데이트

        Args:
            character_id: 캐릭터 ID
            **kwargs: 업데이트할 필드들

        Returns:
            bool: 성공 여부
        """
        if character_id not in self._characters:
            return False

        character = self._characters[character_id]

        for key, value in kwargs.items():
            if hasattr(character, key):
                setattr(character, key, value)

        character.updated_at = datetime.now().isoformat()
        self._save_registry()

        return True

    # ========== 참조 이미지 관리 ==========

    def add_reference_image(
        self,
        character_id: str,
        image_path: str,
        is_primary: bool = False
    ) -> Optional[str]:
        """
        참조 이미지 추가

        Args:
            character_id: 캐릭터 ID
            image_path: 원본 이미지 경로
            is_primary: 주 이미지로 설정

        Returns:
            str: 저장된 이미지 파일명 (실패 시 None)
        """
        if character_id not in self._characters:
            logger.warning(f"캐릭터 없음: {character_id}")
            return None

        if not os.path.exists(image_path):
            logger.warning(f"이미지 파일 없음: {image_path}")
            return None

        character = self._characters[character_id]
        char_dir = self._get_character_dir(character_id)
        os.makedirs(char_dir, exist_ok=True)

        # 이미지 복사 및 처리
        try:
            img = Image.open(image_path)

            # 파일명 생성
            idx = len(character.reference_images) + 1
            filename = f"ref_{idx:03d}.png"
            save_path = os.path.join(char_dir, filename)

            # 크기 조정 (512x512 권장)
            if img.size[0] > 512 or img.size[1] > 512:
                img.thumbnail((512, 512), Image.LANCZOS)

            # 저장
            img.save(save_path, "PNG", quality=95)

            # 등록
            character.reference_images.append(filename)

            if is_primary or not character.primary_image:
                character.primary_image = filename

            character.updated_at = datetime.now().isoformat()
            self._save_registry()

            logger.info(f"참조 이미지 추가: {character_id} -> {filename}")
            return filename

        except Exception as e:
            logger.error(f"참조 이미지 추가 실패: {e}")
            return None

    def get_reference_image_path(
        self,
        character_id: str,
        use_primary: bool = True
    ) -> Optional[str]:
        """
        참조 이미지 경로 가져오기

        Args:
            character_id: 캐릭터 ID
            use_primary: 주 이미지 우선 사용

        Returns:
            str: 이미지 절대 경로 (없으면 None)
        """
        character = self.get_character(character_id)
        if not character:
            return None

        char_dir = self._get_character_dir(character_id)

        # 주 이미지 우선
        if use_primary and character.primary_image:
            path = os.path.join(char_dir, character.primary_image)
            if os.path.exists(path):
                return path

        # 첫 번째 참조 이미지
        if character.reference_images:
            path = os.path.join(char_dir, character.reference_images[0])
            if os.path.exists(path):
                return path

        return None

    def remove_reference_image(self, character_id: str, filename: str) -> bool:
        """
        참조 이미지 제거

        Args:
            character_id: 캐릭터 ID
            filename: 이미지 파일명

        Returns:
            bool: 성공 여부
        """
        if character_id not in self._characters:
            return False

        character = self._characters[character_id]

        if filename not in character.reference_images:
            return False

        # 목록에서 제거
        character.reference_images.remove(filename)

        # 주 이미지였다면 변경
        if character.primary_image == filename:
            character.primary_image = character.reference_images[0] if character.reference_images else ""

        # 파일 삭제
        char_dir = self._get_character_dir(character_id)
        file_path = os.path.join(char_dir, filename)
        if os.path.exists(file_path):
            os.remove(file_path)

        character.updated_at = datetime.now().isoformat()
        self._save_registry()

        return True

    # ========== IP-Adapter 연동 ==========

    def get_ip_adapter_config(self, character_id: str):
        """
        캐릭터용 IP-Adapter 설정 생성

        Args:
            character_id: 캐릭터 ID

        Returns:
            IPAdapterConfig: IP-Adapter 설정 (실패 시 None)
        """
        character = self.get_character(character_id)
        if not character:
            return None

        ref_path = self.get_reference_image_path(character_id)
        if not ref_path:
            logger.warning(f"캐릭터 '{character_id}'에 참조 이미지가 없습니다.")
            return None

        try:
            from core.ip_adapter_bridge import IPAdapterConfig, IPAdapterMode

            mode = IPAdapterMode.FACE if character.face_only else IPAdapterMode.FULL

            return IPAdapterConfig(
                enabled=True,
                mode=mode,
                weight=character.ip_weight,
                reference_images=[ref_path]
            )

        except ImportError:
            logger.error("ip_adapter_bridge 모듈을 찾을 수 없습니다.")
            return None

    def increment_use_count(self, character_id: str) -> bool:
        """사용 횟수 증가"""
        if character_id not in self._characters:
            return False

        self._characters[character_id].use_count += 1
        self._save_registry()
        return True

    # ========== 통계 ==========

    def get_stats(self) -> Dict[str, Any]:
        """통계 조회"""
        total_refs = sum(len(c.reference_images) for c in self._characters.values())
        total_uses = sum(c.use_count for c in self._characters.values())

        return {
            "total_characters": len(self._characters),
            "total_reference_images": total_refs,
            "total_uses": total_uses,
            "channel_type": self.channel_type
        }


# ========== 헬퍼 함수 ==========

_manager_cache: Dict[str, CharacterManager] = {}

def get_character_manager(data_dir: str, channel_type: str = "daily_life_toon") -> CharacterManager:
    """
    CharacterManager 인스턴스 가져오기

    Args:
        data_dir: 데이터 디렉토리
        channel_type: 채널 타입

    Returns:
        CharacterManager: 인스턴스
    """
    key = f"{data_dir}:{channel_type}"

    if key not in _manager_cache:
        _manager_cache[key] = CharacterManager(data_dir, channel_type)

    return _manager_cache[key]
