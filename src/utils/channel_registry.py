# -*- coding: utf-8 -*-
"""
채널 레지스트리 (Channel Registry)

v54.8.0: 멀티채널 관리를 위한 채널 등록/조회/삭제 시스템
- 최대 100개 채널 지원 (YouTube 브랜드 채널 한도)
- 채널별 독립 데이터 폴더 관리
- 채널 메타데이터 (이름, 타입, YouTube 채널 ID 등)

v57.0.0: 다국어 지원 추가
- 채널별 target_language 설정 (ko, en, ja 등)
- 지원 언어: 한국어(ko), 영어(en), 일본어(ja), 중국어(zh)

Author: Reverie Studio
"""

import os
import json
import threading
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict, field
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


# 최대 채널 수 (YouTube 브랜드 채널 한도)
MAX_CHANNELS = 100

# v57.0.0: 지원 언어 목록
SUPPORTED_LANGUAGES = {
    "ko": "한국어",
    "en": "English",
    "ja": "日本語",
    "zh": "中文"
}


class TargetLanguage(str, Enum):
    """v57.0.0: 채널 타겟 언어"""
    KOREAN = "ko"
    ENGLISH = "en"
    JAPANESE = "ja"
    CHINESE = "zh"

    @classmethod
    def get_display_name(cls, lang_code: str) -> str:
        """언어 코드의 표시 이름 반환"""
        return SUPPORTED_LANGUAGES.get(lang_code, lang_code)


@dataclass
class ChannelInfo:
    """채널 정보 데이터 클래스"""

    # 필수 필드
    channel_id: str                    # 내부 고유 ID (예: "horror_001")
    channel_type: str                  # 채널 타입 (horror, emotional, romance 등)
    display_name: str                  # 표시 이름 (예: "공포 이야기 1번 채널")

    # YouTube 연동 정보
    youtube_channel_id: Optional[str] = None   # YouTube 채널 ID (UC...)
    youtube_channel_name: Optional[str] = None # YouTube 채널명

    # 상태 정보
    is_active: bool = True             # 활성화 여부
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    # 설정
    priority: int = 50                 # 우선순위 (0-100, 높을수록 우선)
    daily_video_limit: int = 3         # 일일 영상 제한 (기본 3편/일, 월 ~$7)

    # v57.0.0: 다국어 설정
    target_language: str = "ko"        # 타겟 언어 (ko, en, ja, zh)

    # v60.1.0: 일일 생성 제한 추적
    today_video_count: int = 0         # 오늘 생성한 영상 수
    last_reset_date: str = ""          # 마지막 리셋 날짜 (YYYY-MM-DD)

    # 통계 (간단)
    total_videos: int = 0              # 총 업로드 영상 수
    total_views: int = 0               # 총 조회수

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ChannelInfo':
        """딕셔너리에서 생성"""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class ChannelRegistry:
    """
    채널 레지스트리

    모든 채널의 등록/조회/삭제를 관리
    최대 100개 채널 지원

    v54.8.0: 초기 구현
    """

    _instance: Optional['ChannelRegistry'] = None
    _lock = threading.Lock()

    def __new__(cls, data_dir: str = None):
        """싱글톤 패턴"""
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self, data_dir: str = None):
        """
        초기화

        Args:
            data_dir: 기본 데이터 디렉토리
        """
        if self._initialized:
            return

        self._initialized = True
        # v60.1.0: RLock으로 변경 (can_generate_today → _save_registry 중첩 호출 지원)
        self._file_lock = threading.RLock()

        # 데이터 디렉토리 설정
        if data_dir is None:
            try:
                from config.settings import config
                data_dir = config.DATA_DIR
            except Exception:
                data_dir = "data"

        self.data_dir = data_dir
        self.channels_dir = os.path.join(data_dir, "channels")
        self.registry_path = os.path.join(data_dir, "channel_registry.json")

        # 채널 캐시
        self._channels: Dict[str, ChannelInfo] = {}

        # 초기화
        self._ensure_directories()
        self._load_registry()

        logger.info(f"ChannelRegistry 초기화 완료: {len(self._channels)}개 채널 로드")

    def _ensure_directories(self):
        """필요한 디렉토리 생성"""
        os.makedirs(self.channels_dir, exist_ok=True)

    def _load_registry(self):
        """레지스트리 파일 로드"""
        if os.path.exists(self.registry_path):
            try:
                with open(self.registry_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                for channel_data in data.get("channels", []):
                    try:
                        channel = ChannelInfo.from_dict(channel_data)
                        self._channels[channel.channel_id] = channel
                    except Exception as e:
                        logger.warning(f"채널 로드 실패: {e}")

            except Exception as e:
                logger.error(f"레지스트리 로드 실패: {e}")

    def _save_registry(self):
        """레지스트리 파일 저장"""
        with self._file_lock:
            try:
                data = {
                    "version": "57.0.0",  # v57.0.0: 버전 업데이트
                    "max_channels": MAX_CHANNELS,
                    "total_channels": len(self._channels),
                    "updated_at": datetime.now().isoformat(),
                    "channels": [ch.to_dict() for ch in self._channels.values()]
                }

                with open(self.registry_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)

            except Exception as e:
                logger.error(f"레지스트리 저장 실패: {e}")

    # ========== 채널 관리 API ==========

    def register_channel(
        self,
        channel_type: str,
        display_name: str,
        youtube_channel_id: str = None,
        youtube_channel_name: str = None,
        priority: int = 50,
        target_language: str = "ko"  # v57.0.0: 타겟 언어 추가
    ) -> Optional[ChannelInfo]:
        """
        새 채널 등록

        Args:
            channel_type: 채널 타입 (horror, emotional, romance 등)
            display_name: 표시 이름
            youtube_channel_id: YouTube 채널 ID (선택)
            youtube_channel_name: YouTube 채널명 (선택)
            priority: 우선순위 (0-100)
            target_language: 타겟 언어 (ko, en, ja, zh) - v57.0.0

        Returns:
            ChannelInfo: 등록된 채널 정보, 실패 시 None
        """
        # 최대 채널 수 체크
        if len(self._channels) >= MAX_CHANNELS:
            logger.error(f"최대 채널 수({MAX_CHANNELS}) 초과")
            return None

        # v57.0.0: 언어 코드 유효성 검사
        if target_language not in SUPPORTED_LANGUAGES:
            logger.warning(f"지원하지 않는 언어: {target_language}, 기본값(ko) 사용")
            target_language = "ko"

        # 고유 ID 생성
        channel_id = self._generate_channel_id(channel_type)

        # 채널 정보 생성
        channel = ChannelInfo(
            channel_id=channel_id,
            channel_type=channel_type,
            display_name=display_name,
            youtube_channel_id=youtube_channel_id,
            youtube_channel_name=youtube_channel_name,
            priority=priority,
            target_language=target_language  # v57.0.0
        )

        # 채널 데이터 폴더 생성
        channel_data_dir = self.get_channel_data_dir(channel_id)
        os.makedirs(channel_data_dir, exist_ok=True)

        # 등록
        self._channels[channel_id] = channel
        self._save_registry()

        logger.info(f"채널 등록: {channel_id} ({display_name})")
        return channel

    def _generate_channel_id(self, channel_type: str) -> str:
        """고유 채널 ID 생성"""
        # 해당 타입의 기존 채널 수 확인
        existing = [ch for ch in self._channels.values() if ch.channel_type == channel_type]
        next_num = len(existing) + 1

        # 중복 체크
        while True:
            channel_id = f"{channel_type}_{next_num:03d}"
            if channel_id not in self._channels:
                return channel_id
            next_num += 1

    def unregister_channel(self, channel_id: str, delete_data: bool = False) -> bool:
        """
        채널 등록 해제

        Args:
            channel_id: 채널 ID
            delete_data: 데이터 폴더도 삭제할지 여부

        Returns:
            bool: 성공 여부
        """
        if channel_id not in self._channels:
            logger.warning(f"채널 없음: {channel_id}")
            return False

        # 삭제
        del self._channels[channel_id]
        self._save_registry()

        # 데이터 폴더 삭제 (선택)
        if delete_data:
            import shutil
            channel_data_dir = self.get_channel_data_dir(channel_id)
            if os.path.exists(channel_data_dir):
                shutil.rmtree(channel_data_dir)
                logger.info(f"채널 데이터 삭제: {channel_data_dir}")

        logger.info(f"채널 등록 해제: {channel_id}")
        return True

    def get_channel(self, channel_id: str) -> Optional[ChannelInfo]:
        """채널 정보 조회"""
        return self._channels.get(channel_id)

    def get_all_channels(self) -> List[ChannelInfo]:
        """모든 채널 목록"""
        return list(self._channels.values())

    def get_active_channels(self) -> List[ChannelInfo]:
        """활성 채널 목록"""
        return [ch for ch in self._channels.values() if ch.is_active]

    def get_channels_by_type(self, channel_type: str) -> List[ChannelInfo]:
        """타입별 채널 목록"""
        return [ch for ch in self._channels.values() if ch.channel_type == channel_type]

    def get_channels_by_priority(self) -> List[ChannelInfo]:
        """우선순위 순 채널 목록"""
        return sorted(self._channels.values(), key=lambda ch: ch.priority, reverse=True)

    def get_channels_by_language(self, language: str) -> List[ChannelInfo]:
        """v57.0.0: 언어별 채널 목록"""
        return [ch for ch in self._channels.values() if ch.target_language == language]

    def set_channel_language(self, channel_id: str, language: str) -> bool:
        """v57.0.0: 채널 언어 설정"""
        if language not in SUPPORTED_LANGUAGES:
            logger.warning(f"지원하지 않는 언어: {language}")
            return False
        return self.update_channel(channel_id, target_language=language)

    def get_channel_data_dir(self, channel_id: str) -> str:
        """채널별 데이터 폴더 경로"""
        return os.path.join(self.channels_dir, channel_id)

    def update_channel(self, channel_id: str, **kwargs) -> bool:
        """
        채널 정보 업데이트

        Args:
            channel_id: 채널 ID
            **kwargs: 업데이트할 필드들

        Returns:
            bool: 성공 여부
        """
        if channel_id not in self._channels:
            return False

        channel = self._channels[channel_id]

        for key, value in kwargs.items():
            if hasattr(channel, key):
                setattr(channel, key, value)

        channel.updated_at = datetime.now().isoformat()
        self._save_registry()

        return True

    def set_channel_active(self, channel_id: str, is_active: bool) -> bool:
        """채널 활성화/비활성화"""
        return self.update_channel(channel_id, is_active=is_active)

    def increment_video_count(self, channel_id: str) -> bool:
        """영상 수 증가"""
        if channel_id not in self._channels:
            return False

        self._channels[channel_id].total_videos += 1
        self._save_registry()
        return True

    def update_views(self, channel_id: str, views: int) -> bool:
        """조회수 업데이트"""
        return self.update_channel(channel_id, total_views=views)

    # ========== v60.1.0: 일일 생성 제한 API ==========

    def _reset_daily_if_needed(self, channel_id: str) -> None:
        """
        자정 넘으면 일일 카운트 리셋

        Args:
            channel_id: 채널 ID
        """
        if channel_id not in self._channels:
            return

        today = datetime.now().strftime("%Y-%m-%d")
        channel = self._channels[channel_id]

        if channel.last_reset_date != today:
            channel.today_video_count = 0
            channel.last_reset_date = today
            self._save_registry()
            logger.debug(f"일일 카운트 리셋: {channel_id} (날짜: {today})")

    def can_generate_today(self, channel_id: str) -> bool:
        """
        오늘 추가 영상 생성 가능 여부 (스레드 안전)

        Args:
            channel_id: 채널 ID

        Returns:
            True면 생성 가능, False면 한도 초과
        """
        if channel_id not in self._channels:
            # 미등록 채널은 제한 없음 (DEFAULT_CHANNELS 등)
            return True

        with self._file_lock:
            self._reset_daily_if_needed(channel_id)
            channel = self._channels[channel_id]
            return channel.today_video_count < channel.daily_video_limit

    def get_remaining_quota(self, channel_id: str) -> int:
        """
        오늘 남은 생성 가능 횟수 (스레드 안전)

        Args:
            channel_id: 채널 ID

        Returns:
            남은 생성 가능 횟수 (미등록 채널은 999 반환)
        """
        if channel_id not in self._channels:
            return 999

        with self._file_lock:
            self._reset_daily_if_needed(channel_id)
            channel = self._channels[channel_id]
            return max(0, channel.daily_video_limit - channel.today_video_count)

    def increment_daily_count(self, channel_id: str) -> bool:
        """
        일일 생성 카운트 +1 (생성 성공 시 호출, 스레드 안전)

        Args:
            channel_id: 채널 ID

        Returns:
            True면 성공, False면 실패
        """
        if channel_id not in self._channels:
            return False

        with self._file_lock:
            self._reset_daily_if_needed(channel_id)
            channel = self._channels[channel_id]
            channel.today_video_count += 1
            channel.total_videos += 1
            self._save_registry()
            logger.info(
                f"일일 생성 카운트: {channel_id} "
                f"({channel.today_video_count}/{channel.daily_video_limit})"
            )
            return True

    # ========== 통계 API ==========

    def get_stats(self) -> Dict[str, Any]:
        """전체 통계"""
        active = self.get_active_channels()
        return {
            "total_channels": len(self._channels),
            "active_channels": len(active),
            "max_channels": MAX_CHANNELS,
            "remaining_slots": MAX_CHANNELS - len(self._channels),
            "total_videos": sum(ch.total_videos for ch in self._channels.values()),
            "total_views": sum(ch.total_views for ch in self._channels.values()),
            "channels_by_type": self._count_by_type()
        }

    def _count_by_type(self) -> Dict[str, int]:
        """타입별 채널 수"""
        counts = {}
        for channel in self._channels.values():
            counts[channel.channel_type] = counts.get(channel.channel_type, 0) + 1
        return counts


# ========== 헬퍼 함수 ==========

_registry_instance: Optional[ChannelRegistry] = None

def get_channel_registry(data_dir: str = None) -> ChannelRegistry:
    """
    ChannelRegistry 싱글톤 가져오기

    Args:
        data_dir: 데이터 디렉토리 (최초 호출 시에만 적용)

    Returns:
        ChannelRegistry: 싱글톤 인스턴스
    """
    global _registry_instance

    if _registry_instance is None:
        _registry_instance = ChannelRegistry(data_dir)

    return _registry_instance
