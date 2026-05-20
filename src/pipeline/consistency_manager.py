# src/pipeline/consistency_manager.py
"""
v60.1.0 Phase 4: 이미지 일관성 관리 모듈

media_factory.py에서 추출한 이미지 일관성(Consistency) 관련 코드.
- 4개 인스턴스 변수 캡슐화
- enable/disable/apply_to_payload 메서드
- consistency_enabled, fixed_seed 프로퍼티

원본 위치: media_factory.py L331-685
"""
import copy
import logging
import random
from typing import Dict, Optional, Any

logger = logging.getLogger(__name__)


class ConsistencyManager:
    """이미지 일관성 관리

    SD 이미지 생성 시 캐릭터/배경 일관성을 유지하기 위한 설정 관리.
    - Seed 고정: 동일 구도/스타일 유지
    - IP-Adapter: 캐릭터 참조 이미지 기반 일관성 (선택)
    """

    def __init__(self):
        self._consistency_enabled = False
        self._character_id: Optional[str] = None
        self._ip_adapter_config = None
        self._fixed_seed: Optional[int] = None

    # ============================================================
    # 활성화 / 비활성화
    # ============================================================

    def enable(
        self,
        character_id: str = None,
        data_dir: str = None,
        channel: str = None,
        fixed_seed: int = None,
        ip_weight: float = 0.7
    ) -> bool:
        """
        이미지 일관성 모드 활성화

        Args:
            character_id: 캐릭터 ID (CharacterManager 연동)
            data_dir: 데이터 디렉토리 (CharacterManager용)
            channel: 채널명 (CharacterManager 초기화용)
            fixed_seed: 고정 시드 (None이면 자동 생성)
            ip_weight: IP-Adapter 가중치 (0.0 ~ 1.0)

        Returns:
            bool: 활성화 성공 여부
        """
        try:
            # Seed 고정
            # v62.10: enable() 재호출 시 이미 설정된 seed를 재생성하지 않음
            # (세션 내 이미지 일관성 유지 — 재호출 시 seed가 바뀌면 캐릭터 외모가 달라짐)
            if fixed_seed is not None:
                self._fixed_seed = fixed_seed
            elif not self._fixed_seed:
                # 처음 활성화할 때만 seed 생성
                self._fixed_seed = random.randint(1, 2147483647)

            logger.info(f"[v55] 고정 시드 설정: {self._fixed_seed}")

            # 캐릭터 설정이 있으면 IP-Adapter 연동
            if character_id and data_dir:
                from core.character_manager import get_character_manager
                from core.ip_adapter_bridge import get_ip_adapter_bridge, IPAdapterConfig, IPAdapterMode

                # 캐릭터 매니저에서 설정 로드
                manager = get_character_manager(data_dir, channel)
                self._ip_adapter_config = manager.get_ip_adapter_config(character_id)

                if self._ip_adapter_config:
                    self._ip_adapter_config.weight = ip_weight
                    self._character_id = character_id

                    # IP-Adapter 사용 가능 여부 확인
                    bridge = get_ip_adapter_bridge()
                    available, msg = bridge.check_availability()

                    if available:
                        logger.info(f"[v55] IP-Adapter 연동 완료: {character_id} (weight={ip_weight})")
                    else:
                        logger.warning(f"[v55] IP-Adapter 사용 불가: {msg}")
                        self._ip_adapter_config = None
                else:
                    logger.warning(f"[v55] 캐릭터 '{character_id}'에 참조 이미지가 없습니다.")

            self._consistency_enabled = True
            logger.info(f"[v55] 이미지 일관성 모드 활성화")
            return True

        except ImportError as e:
            logger.warning(f"[v55] 일관성 모듈 로드 실패: {e}")
            # Seed 고정만이라도 활성화
            self._consistency_enabled = True
            return True
        except Exception as e:
            logger.error(f"[v55] 일관성 모드 활성화 실패: {e}")
            return False

    def disable(self):
        """이미지 일관성 모드 비활성화"""
        self._consistency_enabled = False
        self._character_id = None
        self._ip_adapter_config = None
        self._fixed_seed = None
        logger.info("[v55] 이미지 일관성 모드 비활성화")

    # ============================================================
    # Payload 적용
    # ============================================================

    def apply_to_payload(self, payload: Dict) -> Dict:
        """
        이미지 생성 payload에 일관성 설정 적용

        Args:
            payload: 기존 txt2img payload

        Returns:
            Dict: 일관성이 적용된 payload
        """
        if not self._consistency_enabled:
            return payload

        # v62.10: shallow copy → deep copy (override_settings 등 중첩 dict 공유 참조 방지)
        # v62.19: import copy를 모듈 레벨로 이동 (매 호출 오버헤드 제거)
        result = copy.deepcopy(payload)

        # Seed 고정 적용
        if self._fixed_seed is not None:
            result["seed"] = self._fixed_seed
            logger.debug(f"[v55] 고정 시드 적용: {self._fixed_seed}")

        # IP-Adapter 적용
        if self._ip_adapter_config:
            try:
                from core.ip_adapter_bridge import get_ip_adapter_bridge

                bridge = get_ip_adapter_bridge()
                result = bridge.enhance_payload(result, self._ip_adapter_config)

            except Exception as e:
                logger.warning(f"[v55] IP-Adapter 적용 실패: {e}")

        return result

    # ============================================================
    # 프로퍼티
    # ============================================================

    @property
    def enabled(self) -> bool:
        """일관성 모드 활성화 여부"""
        return self._consistency_enabled

    @property
    def fixed_seed(self) -> Optional[int]:
        """현재 고정 시드"""
        return self._fixed_seed

    @property
    def character_id(self) -> Optional[str]:
        """현재 캐릭터 ID"""
        return self._character_id
