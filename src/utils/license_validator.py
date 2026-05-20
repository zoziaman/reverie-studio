# src/utils/license_validator.py
"""
라이센스 검증 모듈 (프로그램 내장)

이 파일은 프로그램에 포함되어 배포됩니다.
"""
import os
import hashlib
import datetime
import logging
from typing import Tuple, Optional

logger = logging.getLogger(__name__)

# v62.22: Fernet 암호화 (XOR 대체)
try:
    from utils.crypto_utils import (
        derive_fernet_key, fernet_encrypt, fernet_decrypt,
        FERNET_AVAILABLE
    )
except ImportError:
    FERNET_AVAILABLE = False
    derive_fernet_key = None


def _get_secret_key() -> str:
    """
    SECRET_KEY를 안전하게 가져옴

    우선순위:
    1. 환경변수 REVERIE_SECRET_KEY
    2. 난독화된 기본값 (배포용)
    """
    # 1. 환경변수에서 가져오기 (개발/관리자용)
    env_key = os.environ.get("REVERIE_SECRET_KEY", "")
    if env_key:
        return env_key

    # 2. 난독화된 기본값 (배포용)
    # 실제 배포 시 이 값을 고유한 값으로 변경하세요
    _k = [82, 69, 86, 69, 82, 73, 69, 95, 80, 82, 79, 68, 95, 50, 48, 50, 53, 95,
          83, 69, 67, 85, 82, 69, 95, 75, 69, 89, 95, 70, 73, 78, 65, 76]
    return bytes(_k).decode('utf-8')


class LicenseValidator:
    """
    라이센스 검증기

    기능:
    - 라이센스 키 검증
    - 하드웨어 바인딩 확인
    - 만료일 확인
    - 라이센스 저장/불러오기
    """

    # SECRET_KEY는 함수로 가져옴 (난독화)
    SECRET_KEY = _get_secret_key()
    
    def __init__(self, data_dir: str = "data"):
        """
        초기화
        
        Args:
            data_dir: 데이터 저장 디렉토리
        """
        self.data_dir = data_dir
        self.license_file = os.path.join(data_dir, "license.dat")
        
        # 현재 PC의 하드웨어 ID
        from utils.hardware_id import get_hardware_id
        self.current_hw_id = get_hardware_id()
    
    # ==============================================
    # 공통 인터페이스 (나중에 온라인 전환 시에도 동일)
    # ==============================================
    
    def validate(self) -> Tuple[bool, str]:
        """
        저장된 라이센스 검증

        Returns:
            (bool, str): (유효 여부, 메시지)
        """
        # 개발자 모드 바이패스: .dev 파일 + REVERIE_DEV_MODE 환경변수 둘 다 필요
        # v62.23: 배포 빌드에서는 이 블록 자체가 제거됨
        dev_marker = os.path.join(self.data_dir, ".dev")
        if os.path.exists(dev_marker) and os.environ.get("REVERIE_DEV_MODE") == "1":
            return True, "개발자 모드 (라이센스 검증 건너뜀)"

        # 저장된 라이센스 불러오기
        license_key = self._load_license()

        if not license_key:
            return False, "라이센스가 등록되지 않았습니다."

        # 오프라인 검증
        return self._validate_offline(license_key)
    
    def set_license(self, license_key: str) -> Tuple[bool, str]:
        """
        라이센스 등록
        
        Args:
            license_key: 라이센스 키
        
        Returns:
            (bool, str): (성공 여부, 메시지)
        """
        # 형식 확인
        license_key = license_key.strip().upper()
        
        # 검증
        valid, msg = self._validate_offline(license_key)
        
        if not valid:
            return False, f"라이센스 검증 실패: {msg}"
        
        # 저장
        try:
            self._save_license(license_key)
            return True, "라이센스가 성공적으로 등록되었습니다."
        except Exception as e:
            return False, f"라이센스 저장 실패: {e}"
    
    def get_license_info(self) -> Optional[dict]:
        """
        라이센스 정보 조회
        
        Returns:
            dict or None: 라이센스 정보
        """
        license_key = self._load_license()
        
        if not license_key:
            return None
        
        valid, msg = self._validate_offline(license_key)
        
        if not valid:
            return None
        
        # 만료일 및 타입 파싱
        parts = license_key.split('-')
        if len(parts) >= 5:
            expire_encoded = parts[1]
            license_type = parts[3]
        else:
            # Fallback for old/invalid (should be caught by validate)
            return None
        
        try:
            expire_int = int(expire_encoded, 36)
            expire_str = str(expire_int).zfill(8)  # YYYYMMDD (8자리)
            expire_date = datetime.datetime.strptime(expire_str, "%Y%m%d")
            days_left = (expire_date - datetime.datetime.now()).days
        except Exception:
            expire_date = None
            days_left = 0
        
        # 타입 코드 매핑
        type_map = {
            'A': 'all',
            'H': 'horror',
            'T': 'touching',
            'M': 'makjang'
        }
        type_str = type_map.get(license_type, 'unknown')
        
        return {
            "license_key": license_key,
            "hardware_id": self.current_hw_id,
            "expire_date": expire_date.strftime("%Y-%m-%d") if expire_date else "Unknown",
            "days_left": max(0, days_left),
            "status": "유효" if valid else "무효",
            "type": type_str,
            "type_code": license_type
        }
    
    def delete_license(self):
        """
        저장된 라이센스 삭제
        """
        if os.path.exists(self.license_file):
            os.remove(self.license_file)
    
    # ==============================================
    # 내부 메서드 (검증 로직)
    # ==============================================
    
    def _validate_offline(self, license_key: str) -> Tuple[bool, str]:
        """
        오프라인 라이센스 검증
        
        Args:
            license_key: 라이센스 키
        
        Returns:
            (bool, str): (유효 여부, 메시지)
        """
        # 1. 형식 확인 (5부분으로 변경: User-Expire-HW-Type-Verif)
        if not license_key or len(license_key) < 20:
            return False, "잘못된 라이센스 형식입니다."
        
        parts = license_key.split('-')
        if len(parts) != 5:
            # 구버전 호환성 체크 (4부분이면 무효 처리)
            if len(parts) == 4:
                return False, "이전 버전의 라이센스입니다. 새로운 라이센스가 필요합니다."
            return False, "잘못된 라이센스 형식입니다."
        
        user_hash, expire_encoded, hw_hash, license_type, verification = parts
        
        # 2. 검증 해시 확인 (변조 방지)
        # Type 포함하여 해시 생성
        verification_string = f"{user_hash}{expire_encoded}{hw_hash}{license_type}{self.SECRET_KEY}"
        expected_verification = hashlib.sha256(
            verification_string.encode()
        ).hexdigest()[:5].upper()
        
        if verification != expected_verification:
            return False, "라이센스가 변조되었습니다."
        
        # 3. 하드웨어 ID 확인 (다른 PC 방지)
        current_hw_hash = hashlib.sha256(
            self.current_hw_id.encode()
        ).hexdigest()[:5].upper()
        
        if hw_hash != current_hw_hash:
            return False, f"이 라이센스는 다른 컴퓨터용입니다.\n현재 PC: {self.current_hw_id}"
            
        # 4. 라이센스 타입 확인 (Part 4) - 'A', 'H', 'T', 'M' 등이 올 수 있음
        if license_type not in ['A', 'H', 'T', 'M']:
             return False, "알 수 없는 라이센스 등급입니다."
        
        # 5. 만료일 확인
        try:
            # Base36 디코딩
            expire_int = int(expire_encoded, 36)
            expire_str = str(expire_int).zfill(8)  # YYYYMMDD (8자리)
            
            # 날짜 파싱
            expire_date = datetime.datetime.strptime(expire_str, "%Y%m%d")
            now = datetime.datetime.now()
            
            if now > expire_date:
                return False, f"라이센스가 만료되었습니다. (만료일: {expire_date.strftime('%Y-%m-%d')})"
            
            days_left = (expire_date - now).days
            
            return True, f"유효 (남은 기간: {days_left}일)"
        
        except Exception as e:
            return False, f"만료일 확인 실패: {e}"
    
    def _save_license(self, license_key: str):
        """
        라이센스를 암호화하여 저장

        v62.22: XOR → Fernet 전환 (PBKDF2 키 파생, 하드웨어 ID 기반)

        Args:
            license_key: 라이센스 키
        """
        # 디렉토리 생성
        os.makedirs(self.data_dir, exist_ok=True)

        # v62.22: Fernet 암호화 우선 (XOR 폴백)
        if FERNET_AVAILABLE and derive_fernet_key:
            key = derive_fernet_key(self.current_hw_id)
            encrypted = fernet_encrypt(license_key, key)
        else:
            # Fernet 미사용 환경 폴백 (레거시 XOR)
            encrypted = self._simple_encrypt(license_key, self.current_hw_id)

        # 저장
        with open(self.license_file, 'w', encoding='utf-8') as f:
            f.write(encrypted)
    
    def _load_license(self) -> Optional[str]:
        """
        저장된 라이센스 불러오기

        v62.22: Fernet 우선 시도 → 실패 시 XOR 폴백 → 성공 시 Fernet으로 자동 마이그레이션

        Returns:
            str or None: 라이센스 키
        """
        if not os.path.exists(self.license_file):
            return None

        try:
            with open(self.license_file, 'r', encoding='utf-8') as f:
                encrypted = f.read().strip()
        except Exception:
            return None

        if not encrypted:
            return None

        # v62.22: Fernet 복호화 우선 시도
        if FERNET_AVAILABLE and derive_fernet_key:
            key = derive_fernet_key(self.current_hw_id)

            # Case 1: Fernet 토큰 (gAAAAA...)
            if encrypted.startswith('gAAAAA'):
                try:
                    return fernet_decrypt(encrypted, key)
                except Exception as e:
                    logger.debug(f"[License] Fernet 복호화 실패: {e}")
                    return None

            # Case 2: 레거시 XOR+Base64 → Fernet 자동 마이그레이션
            try:
                license_key = self._simple_decrypt(encrypted, self.current_hw_id)
                # 유효성 간이 확인 (5-part dash-separated)
                if license_key and '-' in license_key and len(license_key) >= 20:
                    logger.info("[License] XOR → Fernet 자동 마이그레이션 수행")
                    try:
                        new_encrypted = fernet_encrypt(license_key, key)
                        with open(self.license_file, 'w', encoding='utf-8') as f:
                            f.write(new_encrypted)
                    except Exception as e:
                        logger.warning(f"[License] 마이그레이션 저장 실패: {e}")
                    return license_key
            except Exception:
                pass

            return None

        # Fernet 미사용 환경: 레거시 XOR만
        try:
            return self._simple_decrypt(encrypted, self.current_hw_id)
        except Exception:
            return None
    
    def _simple_encrypt(self, text: str, key: str) -> str:
        """
        간단 암호화 (XOR + Base64)
        
        Args:
            text: 평문
            key: 암호화 키
        
        Returns:
            str: 암호화된 문자열
        """
        import base64
        
        # XOR 암호화
        key_bytes = key.encode()
        text_bytes = text.encode()
        
        encrypted_bytes = bytearray()
        for i, byte in enumerate(text_bytes):
            encrypted_bytes.append(byte ^ key_bytes[i % len(key_bytes)])
        
        # Base64 인코딩
        return base64.b64encode(encrypted_bytes).decode()
    
    def _simple_decrypt(self, encrypted: str, key: str) -> str:
        """
        간단 복호화
        
        Args:
            encrypted: 암호화된 문자열
            key: 복호화 키
        
        Returns:
            str: 평문
        """
        import base64
        
        # Base64 디코딩
        encrypted_bytes = base64.b64decode(encrypted.encode())
        
        # XOR 복호화
        key_bytes = key.encode()
        
        decrypted_bytes = bytearray()
        for i, byte in enumerate(encrypted_bytes):
            decrypted_bytes.append(byte ^ key_bytes[i % len(key_bytes)])
        
        return decrypted_bytes.decode()


# ==============================================
# 테스트 코드
# ==============================================

if __name__ == "__main__":
    print("=" * 60)
    print("라이센스 검증 테스트")
    print("=" * 60)
    
    # 테스트용 validator
    validator = LicenseValidator(data_dir="test_data")
    
    print(f"\n현재 하드웨어 ID: {validator.current_hw_id}")
    
    # 라이센스 입력 테스트
    print("\n테스트용 라이센스 키를 입력하세요:")
    test_key = input("라이센스 키: ").strip().upper()
    
    if test_key:
        # 검증
        valid, msg = validator._validate_offline(test_key)
        
        print(f"\n검증 결과: {'✅ 유효' if valid else '❌ 무효'}")
        print(f"메시지: {msg}")
        
        if valid:
            # 저장 테스트
            success, save_msg = validator.set_license(test_key)
            print(f"\n저장: {'✅ 성공' if success else '❌ 실패'}")
            print(f"메시지: {save_msg}")
            
            # 불러오기 테스트
            loaded = validator._load_license()
            print(f"\n불러오기: {loaded}")
            
            # 정보 조회
            info = validator.get_license_info()
            if info:
                print("\n라이센스 정보:")
                for key, value in info.items():
                    print(f"  {key}: {value}")
    
    print("\n" + "=" * 60)
