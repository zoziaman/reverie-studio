# src/core/sfx_manager.py
"""
v53: Auto-SFX 시스템 - 효과음 관리자

효과음 라이브러리 관리 및 검색
- 카테고리별 효과음 관리
- 태그 기반 검색
- 랜덤 선택 (같은 효과음 반복 방지)

"분위기에 맞는 효과음을 자동으로 찾아준다"
"""
import os
import json
import random
import logging
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
import threading

logger = logging.getLogger(__name__)


class SFXCategory(Enum):
    """효과음 카테고리"""
    # 공포
    HORROR_TENSION = "horror/tension"           # 긴장감
    HORROR_JUMPSCARE = "horror/jump_scare"      # 점프 스케어
    HORROR_AMBIENT = "horror/ambient"           # 배경 분위기
    HORROR_SUPERNATURAL = "horror/supernatural" # 초자연적

    # 감동/로맨스
    EMOTIONAL = "emotional"

    # 공통
    COMMON = "common"
    TRANSITION = "common/transition"            # 장면 전환


class SFXTag(Enum):
    """효과음 태그 (대본 분석 시 사용)"""
    # 긴장/공포
    TENSION = "tension"             # 긴장감 고조
    HEARTBEAT = "heartbeat"         # 심장 박동
    SUSPENSE = "suspense"           # 서스펜스
    BREATHING = "breathing"         # 숨소리

    # 점프 스케어
    JUMPSCARE = "jumpscare"         # 갑작스러운 충격
    SCREAM = "scream"               # 비명
    IMPACT = "impact"               # 충격음

    # 환경/배경
    WIND = "wind"                   # 바람
    RAIN = "rain"                   # 비
    THUNDER = "thunder"             # 천둥
    NIGHT = "night"                 # 밤 분위기

    # 초자연
    WHISPER = "whisper"             # 속삭임
    FOOTSTEPS = "footsteps"         # 발걸음
    DOOR = "door"                   # 문 소리
    GLASS = "glass"                 # 유리

    # 감정
    SAD = "sad"                     # 슬픔
    HAPPY = "happy"                 # 기쁨
    CRYING = "crying"               # 울음
    # v61.1 (#64/VER-5): 확장 감정 태그
    DRAMATIC = "dramatic"           # 극적
    ANGRY = "angry"                 # 분노

    # 전환
    WHOOSH = "whoosh"               # 장면 전환
    NOTIFICATION = "notification"   # 알림


@dataclass
class SFXInfo:
    """효과음 정보"""
    filename: str                       # 파일명
    category: str                       # 카테고리 (폴더 경로)
    tags: List[str] = field(default_factory=list)  # 태그 목록
    duration_ms: int = 0                # 길이 (밀리초)
    volume_adjust: float = 0.0          # 볼륨 조절 (dB)
    description: str = ""               # 설명
    use_count: int = 0                  # 사용 횟수

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> 'SFXInfo':
        return cls(**data)


@dataclass
class SFXCue:
    """효과음 큐 (삽입 지점)"""
    timestamp_ms: int                   # 삽입 시점 (밀리초)
    tag: str                            # 효과음 태그
    intensity: float = 0.7              # 강도 (0.0 ~ 1.0)
    duration_ms: Optional[int] = None   # 지속 시간 (None이면 효과음 전체)
    fade_in_ms: int = 0                 # 페이드 인
    fade_out_ms: int = 0                # 페이드 아웃
    reason: str = ""                    # 삽입 이유

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> 'SFXCue':
        return cls(**data)


class SFXManager:
    """
    효과음 라이브러리 관리자

    - 효과음 등록/검색
    - 태그 기반 매칭
    - 최근 사용 추적 (반복 방지)
    """

    def __init__(self, sfx_dir: str):
        """
        Args:
            sfx_dir: 효과음 폴더 경로 (예: assets/sfx)
        """
        self.sfx_dir = sfx_dir
        self.registry_path = os.path.join(sfx_dir, "sfx_registry.json")

        self._lock = threading.Lock()
        self._registry: Dict[str, SFXInfo] = {}  # filename -> SFXInfo
        self._tag_index: Dict[str, List[str]] = {}  # tag -> [filenames]
        self._recent_used: List[str] = []  # 최근 사용된 파일 (반복 방지)
        self._max_recent = 10

        self._ensure_directories()
        self._load_registry()

    def _ensure_directories(self):
        """폴더 구조 생성"""
        directories = [
            # 공포
            "horror/tension",
            "horror/jump_scare",
            "horror/ambient",
            "horror/supernatural",
            # 감동
            "emotional",
            # 공통
            "common",
            "common/transition",
        ]

        for subdir in directories:
            path = os.path.join(self.sfx_dir, subdir)
            os.makedirs(path, exist_ok=True)

        logger.info(f"효과음 폴더 구조 확인 완료: {self.sfx_dir}")

    def _load_registry(self):
        """레지스트리 로드"""
        if os.path.exists(self.registry_path):
            try:
                with open(self.registry_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for filename, info_dict in data.get('sfx', {}).items():
                        self._registry[filename] = SFXInfo.from_dict(info_dict)
                    self._rebuild_tag_index()
                    logger.info(f"효과음 레지스트리 로드: {len(self._registry)}개")
            except Exception as e:
                logger.error(f"레지스트리 로드 실패: {e}")

    def _save_registry(self):
        """레지스트리 저장"""
        with self._lock:
            data = {
                'version': '1.0.0',
                'updated_at': datetime.now().isoformat(),
                'sfx': {k: v.to_dict() for k, v in self._registry.items()}
            }
            with open(self.registry_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

    def _rebuild_tag_index(self):
        """태그 인덱스 재구성"""
        self._tag_index.clear()
        for filename, info in self._registry.items():
            for tag in info.tags:
                if tag not in self._tag_index:
                    self._tag_index[tag] = []
                self._tag_index[tag].append(filename)

    def scan_directory(self) -> int:
        """
        효과음 폴더 스캔하여 새 파일 등록

        Returns:
            새로 등록된 파일 수
        """
        new_count = 0
        audio_extensions = {'.mp3', '.wav', '.ogg', '.m4a', '.flac'}

        for root, dirs, files in os.walk(self.sfx_dir):
            # sfx_registry.json 제외
            for filename in files:
                ext = os.path.splitext(filename)[1].lower()
                if ext not in audio_extensions:
                    continue

                if filename in self._registry:
                    continue

                # 카테고리 추출 (상대 경로)
                rel_path = os.path.relpath(root, self.sfx_dir)
                category = rel_path if rel_path != '.' else 'common'

                # 태그 추론 (파일명에서)
                tags = self._infer_tags_from_filename(filename)

                # 길이 측정
                duration = self._get_audio_duration(os.path.join(root, filename))

                # 등록
                info = SFXInfo(
                    filename=filename,
                    category=category,
                    tags=tags,
                    duration_ms=duration,
                    description=f"자동 스캔: {filename}"
                )
                self._registry[filename] = info
                new_count += 1
                logger.info(f"새 효과음 등록: {filename} ({category})")

        if new_count > 0:
            self._rebuild_tag_index()
            self._save_registry()

        return new_count

    def _infer_tags_from_filename(self, filename: str) -> List[str]:
        """파일명에서 태그 추론"""
        tags = []
        name_lower = filename.lower()

        # 태그 키워드 매핑
        keyword_tags = {
            'heartbeat': [SFXTag.HEARTBEAT.value, SFXTag.TENSION.value],
            'heart': [SFXTag.HEARTBEAT.value],
            'tension': [SFXTag.TENSION.value],
            'suspense': [SFXTag.SUSPENSE.value, SFXTag.TENSION.value],
            'breath': [SFXTag.BREATHING.value],
            'jump': [SFXTag.JUMPSCARE.value],
            'scare': [SFXTag.JUMPSCARE.value],
            'sudden': [SFXTag.JUMPSCARE.value, SFXTag.IMPACT.value],
            'hit': [SFXTag.IMPACT.value],
            'impact': [SFXTag.IMPACT.value],
            'scream': [SFXTag.SCREAM.value],
            'wind': [SFXTag.WIND.value],
            'rain': [SFXTag.RAIN.value],
            'thunder': [SFXTag.THUNDER.value],
            'storm': [SFXTag.THUNDER.value, SFXTag.RAIN.value],
            'night': [SFXTag.NIGHT.value],
            'cricket': [SFXTag.NIGHT.value],
            'whisper': [SFXTag.WHISPER.value],
            'ghost': [SFXTag.WHISPER.value],
            'footstep': [SFXTag.FOOTSTEPS.value],
            'step': [SFXTag.FOOTSTEPS.value],
            'door': [SFXTag.DOOR.value],
            'creak': [SFXTag.DOOR.value],
            'glass': [SFXTag.GLASS.value],
            'break': [SFXTag.GLASS.value, SFXTag.IMPACT.value],
            'sad': [SFXTag.SAD.value],
            'cry': [SFXTag.CRYING.value],
            'sob': [SFXTag.CRYING.value],
            'happy': [SFXTag.HAPPY.value],
            'whoosh': [SFXTag.WHOOSH.value],
            'transition': [SFXTag.WHOOSH.value],
            'swipe': [SFXTag.WHOOSH.value],
        }

        for keyword, tag_list in keyword_tags.items():
            if keyword in name_lower:
                tags.extend(tag_list)

        # 중복 제거
        return list(set(tags))

    def _get_audio_duration(self, filepath: str) -> int:
        """오디오 길이 측정 (밀리초)"""
        try:
            from pydub import AudioSegment
            audio = AudioSegment.from_file(filepath)
            return len(audio)
        except Exception:
            # pydub 없으면 기본값
            return 2000  # 2초 기본값

    def register_sfx(
        self,
        filename: str,
        category: str,
        tags: List[str],
        duration_ms: int = 0,
        volume_adjust: float = 0.0,
        description: str = ""
    ) -> bool:
        """
        효과음 수동 등록

        Args:
            filename: 파일명
            category: 카테고리 (폴더 경로)
            tags: 태그 목록
            duration_ms: 길이 (밀리초)
            volume_adjust: 볼륨 조절 (dB)
            description: 설명

        Returns:
            성공 여부
        """
        # 파일 존재 확인
        filepath = os.path.join(self.sfx_dir, category, filename)
        if not os.path.exists(filepath):
            logger.error(f"효과음 파일 없음: {filepath}")
            return False

        # 길이 측정
        if duration_ms == 0:
            duration_ms = self._get_audio_duration(filepath)

        info = SFXInfo(
            filename=filename,
            category=category,
            tags=tags,
            duration_ms=duration_ms,
            volume_adjust=volume_adjust,
            description=description
        )

        with self._lock:
            self._registry[filename] = info
            self._rebuild_tag_index()
            self._save_registry()

        logger.info(f"효과음 등록: {filename} (태그: {tags})")
        return True

    def find_by_tag(
        self,
        tag: str,
        category_filter: Optional[str] = None,
        avoid_recent: bool = True
    ) -> Optional[SFXInfo]:
        """
        태그로 효과음 찾기

        Args:
            tag: 효과음 태그
            category_filter: 카테고리 필터 (예: "horror")
            avoid_recent: 최근 사용된 것 피하기

        Returns:
            SFXInfo 또는 None
        """
        candidates = self._tag_index.get(tag, [])

        if not candidates:
            logger.warning(f"태그 '{tag}'에 해당하는 효과음 없음")
            return None

        # 카테고리 필터
        if category_filter:
            candidates = [
                f for f in candidates
                if self._registry[f].category.startswith(category_filter)
            ]

        if not candidates:
            return None

        # 최근 사용 피하기
        if avoid_recent and len(candidates) > 1:
            candidates = [f for f in candidates if f not in self._recent_used]
            if not candidates:
                # 모두 최근 사용됐으면 리스트 초기화
                self._recent_used.clear()
                candidates = self._tag_index.get(tag, [])

        # 랜덤 선택
        selected = random.choice(candidates)

        # 최근 사용 기록
        self._recent_used.append(selected)
        if len(self._recent_used) > self._max_recent:
            self._recent_used.pop(0)

        # 사용 횟수 증가
        self._registry[selected].use_count += 1

        return self._registry[selected]

    def get_sfx_path(self, info: SFXInfo) -> str:
        """효과음 전체 경로 반환"""
        return os.path.join(self.sfx_dir, info.category, info.filename)

    def get_all_sfx(self) -> List[SFXInfo]:
        """모든 효과음 목록"""
        return list(self._registry.values())

    def get_categories(self) -> List[str]:
        """등록된 카테고리 목록"""
        return list(set(info.category for info in self._registry.values()))

    def get_stats(self) -> Dict[str, Any]:
        """통계"""
        categories = {}
        for info in self._registry.values():
            cat = info.category.split('/')[0]
            categories[cat] = categories.get(cat, 0) + 1

        return {
            'total_sfx': len(self._registry),
            'total_tags': len(self._tag_index),
            'categories': categories,
            'most_used': sorted(
                self._registry.values(),
                key=lambda x: x.use_count,
                reverse=True
            )[:5]
        }


# 싱글톤
_sfx_manager: Optional[SFXManager] = None
_sfx_manager_lock = threading.Lock()


def get_sfx_manager(sfx_dir: str = None) -> SFXManager:
    """SFXManager 싱글톤 인스턴스 (Thread-safe)"""
    global _sfx_manager

    if _sfx_manager is None:
        with _sfx_manager_lock:
            if _sfx_manager is None:  # Double-check locking
                if sfx_dir is None:
                    sfx_dir = "assets/sfx"
                _sfx_manager = SFXManager(sfx_dir)

    return _sfx_manager
