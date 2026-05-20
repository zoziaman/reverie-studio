# src/utils/package_security.py
"""
v37 - 패키지 보안 시스템

1. 패키지 암호화 (Fernet 대칭키 암호화)
2. 라이선스 키 생성/검증
3. 하드웨어 바인딩 (준비)

보안 정책:
- .revpack 파일 내부 JSON은 암호화된 바이너리로 저장
- 라이선스 키가 필요한 패키지는 Import 시 키 검증 필수
- 앱 고유 키로만 복호화 가능 (외부 도구로 열 수 없음)
"""

import os
import json
import hashlib
import hmac
import base64
import uuid
import platform
import logging
from pathlib import Path
from typing import Tuple, Optional, Dict, Any
from datetime import datetime
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)

# ==================== 앱 고유 키 (난독화) ====================
# 실제 배포 시에는 더 복잡한 난독화 필요
# 여기서는 기본적인 키 분리 방식 사용

def _get_app_secret() -> bytes:
    """
    앱 고유 암호화 키 생성 (난독화)

    키를 직접 노출하지 않고 여러 조각으로 분리해서 조합
    """
    # 키 조각들 (실제 배포 시 더 복잡하게)
    _p1 = b'R3v3r13_'
    _p2 = b'Stud10_'
    _p3 = b'S3cur3_'
    _p4 = b'P4ck4g3_'
    _p5 = b'K3y_2024'

    # 조합
    raw_key = _p1 + _p2 + _p3 + _p4 + _p5

    # SHA256으로 32바이트 키 생성 (Fernet 호환)
    return hashlib.sha256(raw_key).digest()


def _get_fernet_key() -> bytes:
    """Fernet 호환 키 생성 (base64 인코딩된 32바이트)"""
    secret = _get_app_secret()
    return base64.urlsafe_b64encode(secret)


# ==================== 패키지 암호화/복호화 ====================

class PackageEncryption:
    """
    패키지 암호화 관리자

    Fernet 대칭키 암호화 사용
    - 암호화: JSON → 암호화된 바이너리 → base64
    - 복호화: base64 → 암호화된 바이너리 → JSON
    """

    # 매직 헤더 (암호화된 파일 식별용)
    MAGIC_HEADER = b'REVPK01'  # Reverie Package v01

    def __init__(self):
        try:
            from cryptography.fernet import Fernet
            self._fernet = Fernet(_get_fernet_key())
            self._available = True
        except ImportError:
            logger.warning("[PackageEncryption] cryptography 라이브러리 없음, 암호화 비활성화")
            self._fernet = None
            self._available = False

    @property
    def is_available(self) -> bool:
        """암호화 사용 가능 여부"""
        return self._available

    def encrypt(self, data: dict) -> bytes:
        """
        딕셔너리를 암호화된 바이너리로 변환

        Args:
            data: 암호화할 딕셔너리

        Returns:
            암호화된 바이너리 (MAGIC_HEADER + 암호화된 데이터)
        """
        if not self._available:
            # 폴백: 그냥 JSON 반환
            return json.dumps(data, ensure_ascii=False).encode('utf-8')

        # JSON 직렬화
        json_bytes = json.dumps(data, ensure_ascii=False).encode('utf-8')

        # Fernet 암호화
        encrypted = self._fernet.encrypt(json_bytes)

        # 매직 헤더 추가
        return self.MAGIC_HEADER + encrypted

    def decrypt(self, data: bytes) -> dict:
        """
        암호화된 바이너리를 딕셔너리로 복호화

        Args:
            data: 암호화된 바이너리

        Returns:
            복호화된 딕셔너리

        Raises:
            ValueError: 잘못된 형식 또는 복호화 실패
        """
        if not self._available:
            # 폴백: JSON 파싱 시도
            return json.loads(data.decode('utf-8'))

        # 매직 헤더 확인
        if data.startswith(self.MAGIC_HEADER):
            # 암호화된 파일
            encrypted = data[len(self.MAGIC_HEADER):]
            try:
                decrypted = self._fernet.decrypt(encrypted)
                return json.loads(decrypted.decode('utf-8'))
            except Exception as e:
                raise ValueError(f"패키지 복호화 실패: {e}")
        else:
            # 암호화되지 않은 레거시 파일 (평문 JSON)
            try:
                return json.loads(data.decode('utf-8'))
            except json.JSONDecodeError:
                raise ValueError("잘못된 패키지 형식")

    def is_encrypted(self, data: bytes) -> bool:
        """데이터가 암호화되어 있는지 확인"""
        return data.startswith(self.MAGIC_HEADER)


# ==================== 라이선스 키 시스템 ====================

@dataclass
class LicenseKeyInfo:
    """라이선스 키 정보"""
    key: str                          # 라이선스 키
    package_id: str                   # 패키지 ID
    created_at: str                   # 생성일
    expires_at: Optional[str] = None  # 만료일
    max_activations: int = 1          # 최대 활성화 수
    hardware_id: Optional[str] = None # 바인딩된 하드웨어 ID

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> 'LicenseKeyInfo':
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class LicenseKeyManager:
    """
    라이선스 키 생성/검증 관리자

    키 형식: XXXX-XXXX-XXXX-XXXX (체크섬 포함)
    """

    # 키 생성용 시크릿 (난독화)
    _KEY_SALT = b'R3v3r13_L1c3ns3_S4lt_2024'

    def __init__(self):
        pass

    def generate_key(self, package_id: str, expires_at: Optional[str] = None) -> str:
        """
        라이선스 키 생성

        Args:
            package_id: 패키지 ID
            expires_at: 만료일 (ISO format, None=영구)

        Returns:
            라이선스 키 (XXXX-XXXX-XXXX-XXXX 형식)
        """
        # 기본 데이터 조합
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        raw_data = f"{package_id}:{timestamp}:{expires_at or 'PERM'}"

        # HMAC으로 고유 해시 생성
        signature = hmac.new(
            self._KEY_SALT,
            raw_data.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()[:28]  # 28자 (7*4)

        # 체크섬 생성 (마지막 4자)
        checksum = self._calculate_checksum(signature)

        # 키 형식화 (XXXX-XXXX-XXXX-XXXX)
        full_key = signature + checksum
        formatted = '-'.join([full_key[i:i+4].upper() for i in range(0, 32, 4)])

        return formatted

    def validate_key(self, key: str, package_id: str = None) -> Tuple[bool, str]:
        """
        라이선스 키 검증

        Args:
            key: 라이선스 키
            package_id: 패키지 ID (옵션, 추가 검증용)

        Returns:
            (유효여부, 메시지)
        """
        # 형식 정규화
        normalized = key.replace('-', '').replace(' ', '').upper()

        # 길이 검증
        if len(normalized) != 32:
            return False, "잘못된 키 형식입니다."

        # 체크섬 검증
        key_part = normalized[:28]
        checksum_part = normalized[28:]

        expected_checksum = self._calculate_checksum(key_part.lower())
        if checksum_part.lower() != expected_checksum:
            return False, "유효하지 않은 라이선스 키입니다."

        return True, "유효한 라이선스 키입니다."

    def _calculate_checksum(self, data: str) -> str:
        """체크섬 계산 (4자리 hex)"""
        hash_bytes = hashlib.md5(data.encode('utf-8')).digest()
        return hash_bytes[:2].hex()  # 4자리

    def generate_key_info(self, package_id: str,
                          expires_at: Optional[str] = None,
                          max_activations: int = 1) -> LicenseKeyInfo:
        """라이선스 키 정보 객체 생성"""
        key = self.generate_key(package_id, expires_at)

        return LicenseKeyInfo(
            key=key,
            package_id=package_id,
            created_at=datetime.now().isoformat(),
            expires_at=expires_at,
            max_activations=max_activations
        )


# ==================== 하드웨어 바인딩 ====================

class HardwareBinding:
    """
    하드웨어 바인딩 관리

    기기 고유 ID를 생성하여 패키지가 특정 컴퓨터에서만 작동하도록 함
    (현재는 스키마만 준비, 실제 검증은 나중에 활성화)
    """

    @staticmethod
    def get_hardware_id() -> str:
        """
        현재 기기의 고유 ID 생성

        여러 하드웨어 정보를 조합하여 고유한 ID 생성
        """
        components = []

        # 1. 플랫폼 정보
        components.append(platform.system())
        components.append(platform.machine())

        # 2. MAC 주소 (가용시)
        try:
            mac = uuid.getnode()
            components.append(str(mac))
        except Exception as e:
            logger.debug(f"MAC 주소 조회 실패: {e}")

        # 3. 컴퓨터 이름
        try:
            components.append(platform.node())
        except Exception as e:
            logger.debug(f"컴퓨터 이름 조회 실패: {e}")

        # 4. 사용자 이름
        try:
            import getpass
            components.append(getpass.getuser())
        except Exception as e:
            logger.debug(f"사용자 이름 조회 실패: {e}")

        # 조합하여 해시
        combined = '|'.join(components)
        hardware_hash = hashlib.sha256(combined.encode('utf-8')).hexdigest()[:16]

        return hardware_hash.upper()

    @staticmethod
    def verify_binding(stored_id: str, strict: bool = False) -> Tuple[bool, str]:
        """
        하드웨어 바인딩 검증

        Args:
            stored_id: 저장된 하드웨어 ID
            strict: 엄격 모드 (현재는 비활성화)

        Returns:
            (유효여부, 메시지)
        """
        if not stored_id:
            return True, "바인딩 없음"

        current_id = HardwareBinding.get_hardware_id()

        if current_id == stored_id:
            return True, "하드웨어 일치"

        if strict:
            return False, "이 패키지는 다른 컴퓨터에서 활성화되었습니다."

        # 비엄격 모드: 경고만
        logger.warning(f"[HardwareBinding] 하드웨어 ID 불일치: 저장={stored_id}, 현재={current_id}")
        return True, "하드웨어 변경 감지됨 (허용됨)"


# ==================== 통합 보안 매니저 ====================

class PackageSecurityManager:
    """
    패키지 보안 통합 관리자

    암호화, 라이선스, 하드웨어 바인딩을 통합 관리
    """

    def __init__(self):
        self.encryption = PackageEncryption()
        self.license_manager = LicenseKeyManager()
        self.hardware = HardwareBinding()

    def secure_package_data(self, data: dict,
                            require_license: bool = False,
                            bind_hardware: bool = False) -> bytes:
        """
        패키지 데이터 보안 처리 (Export용)

        Args:
            data: 패키지 데이터
            require_license: 라이선스 필요 여부
            bind_hardware: 하드웨어 바인딩 여부

        Returns:
            암호화된 바이너리
        """
        # 보안 메타데이터 추가
        secured_data = data.copy()
        secured_data['_security'] = {
            'encrypted': self.encryption.is_available,
            'license_required': require_license,
            'hardware_bound': bind_hardware,
            'created_at': datetime.now().isoformat(),
        }

        if bind_hardware:
            secured_data['_security']['hardware_id'] = self.hardware.get_hardware_id()

        # 암호화
        return self.encryption.encrypt(secured_data)

    def verify_and_decrypt(self, data: bytes,
                           license_key: Optional[str] = None) -> Tuple[bool, str, Optional[dict]]:
        """
        패키지 데이터 검증 및 복호화 (Import용)

        Args:
            data: 암호화된 바이너리
            license_key: 라이선스 키 (필요시)

        Returns:
            (성공여부, 메시지, 복호화된 데이터)
        """
        try:
            # 복호화
            decrypted = self.encryption.decrypt(data)

            # 보안 메타데이터 확인
            security = decrypted.get('_security', {})

            # 라이선스 검증
            if security.get('license_required', False):
                if not license_key:
                    return False, "이 패키지는 라이선스 키가 필요합니다.", None

                package_id = decrypted.get('package_id', '')
                valid, msg = self.license_manager.validate_key(license_key, package_id)
                if not valid:
                    return False, msg, None

            # 하드웨어 바인딩 검증 (현재는 비엄격 모드)
            if security.get('hardware_bound', False):
                stored_id = security.get('hardware_id', '')
                valid, msg = self.hardware.verify_binding(stored_id, strict=False)
                if not valid:
                    return False, msg, None

            # 보안 메타데이터 제거 후 반환
            if '_security' in decrypted:
                del decrypted['_security']

            return True, "검증 성공", decrypted

        except ValueError as e:
            return False, str(e), None
        except Exception as e:
            logger.error(f"[PackageSecurityManager] 검증 실패: {e}")
            return False, f"패키지 검증 오류: {e}", None

    def generate_license_for_package(self, package_id: str,
                                     expires_at: Optional[str] = None) -> str:
        """패키지용 라이선스 키 생성"""
        return self.license_manager.generate_key(package_id, expires_at)

    def check_license_required(self, data: bytes) -> bool:
        """패키지가 라이선스 필요한지 확인 (복호화 없이)"""
        try:
            # 헤더만 파싱 시도
            decrypted = self.encryption.decrypt(data)
            security = decrypted.get('_security', {})
            return security.get('license_required', False)
        except Exception:
            return False


# 싱글톤
_security_instance: Optional[PackageSecurityManager] = None

def get_security_manager() -> PackageSecurityManager:
    """보안 매니저 싱글톤"""
    global _security_instance
    if _security_instance is None:
        _security_instance = PackageSecurityManager()
    return _security_instance
