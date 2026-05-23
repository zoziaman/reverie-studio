# src/utils/firebase_license.py
"""
================================================================================
Firebase 기반 온라인 라이센스 검증 시스템
================================================================================

이 모듈은 Firebase Firestore를 사용하여 라이센스를 실시간으로 검증합니다.

v37 업데이트:
- Cloud Functions API 통합 (패키지 소유권 검증)
- Firestore 규칙이 `allow read, write: if false`인 경우에도 작동
- 하드웨어 ID(HWID) 바인딩 지원

보안 특징:
- 서버 측 검증 (클라이언트 변조 불가)
- 하드웨어 ID 바인딩
- 실시간 라이센스 상태 확인
- 만료일/활성화 상태 체크
- 동시 접속 제한 (선택사항)

Firestore 구조:
/licenses/{license_key}
    - user_id: str (사용자 식별)
    - hardware_id: str (하드웨어 ID)
    - license_type: str (A/H/T/M)
    - expire_date: timestamp
    - is_active: bool
    - created_at: timestamp
    - last_verified: timestamp
    - memo: str (관리자 메모)
    - owned_packs: list (보유 패키지 ID 목록)
================================================================================
"""

import os
import sys
import hashlib
import uuid
import json
import logging
from datetime import datetime, timedelta
from typing import Tuple, Optional, Dict, Any, List

from utils.secret_redaction import redact_sensitive_text

logger = logging.getLogger(__name__)


def _redact_license_key_for_log(license_key: str | None) -> str:
    parts = str(license_key or "").split("-")
    if len(parts) >= 3:
        return "-".join([parts[0], *["****"] * (len(parts) - 2), parts[-1]])
    if len(license_key or "") <= 8:
        return "****"
    return f"{license_key[:4]}...{license_key[-4:]}"


# v62.22: license_cache.json 암호화
try:
    from utils.crypto_utils import (
        derive_fernet_key, encrypted_json_write, encrypted_json_read,
        FERNET_AVAILABLE
    )
    from utils.hardware_id import get_hardware_id as _get_hw_id_fb
    _FB_FERNET_KEY = derive_fernet_key(_get_hw_id_fb()) if FERNET_AVAILABLE else None
except ImportError:
    FERNET_AVAILABLE = False
    _FB_FERNET_KEY = None

# HTTP 요청용
try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    logger.warning("requests 패키지가 설치되지 않았습니다. pip install requests")

# Firebase Admin SDK
try:
    import firebase_admin
    from firebase_admin import credentials, firestore
    FIREBASE_AVAILABLE = True
except ImportError:
    FIREBASE_AVAILABLE = False
    print("⚠️ firebase-admin 패키지가 설치되지 않았습니다.")
    print("   설치: pip install firebase-admin")


# ============================================================
# v62.22: license_cache.json 암호화 헬퍼
# ============================================================

def _read_license_cache(path: str):
    """license_cache.json 읽기 (Fernet 암호화 지원 + 평문 자동 마이그레이션)"""
    if not os.path.exists(path):
        return None
    if FERNET_AVAILABLE and _FB_FERNET_KEY:
        try:
            return encrypted_json_read(path, _FB_FERNET_KEY)
        except Exception as e:
            logger.debug(f"[License] 암호화 캐시 읽기 실패: {e}")
            return None
    else:
        # Fernet 미사용: 평문 JSON
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError, OSError) as e:
            logger.debug(f"[License] 캐시 로드 실패: {e}")
            return None


def _write_license_cache(path: str, data):
    """license_cache.json 쓰기 (Fernet 암호화 + atomic write)"""
    dir_name = os.path.dirname(path) or "."
    os.makedirs(dir_name, exist_ok=True)
    if FERNET_AVAILABLE and _FB_FERNET_KEY:
        encrypted_json_write(path, data, _FB_FERNET_KEY)
    else:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


# ============================================================
# Cloud Functions API 클라이언트 (v37)
# ============================================================

class CloudFunctionsClient:
    """
    Firebase Cloud Functions API 클라이언트

    Firestore 규칙이 클라이언트 접근을 막은 경우에도
    Cloud Functions를 통해 패키지 소유권을 검증할 수 있음

    배포 정보:
    - 프로젝트 ID: reverie-license
    - 리전: us-central1
    """

    # Cloud Functions 설정
    PROJECT_ID = "reverie-license"
    REGION = "us-central1"

    # 엔드포인트 이름
    FUNC_CHECK_OWNERSHIP = "checkPackageOwnership"
    FUNC_GET_OWNED_PACKS = "getOwnedPacks"
    FUNC_GET_PACK_KEY = "getPackKey"  # v62.27: Phase B 팩 키 발급

    def __init__(self):
        self._available = REQUESTS_AVAILABLE
        self._base_url = f"https://{self.REGION}-{self.PROJECT_ID}.cloudfunctions.net"

    @property
    def is_available(self) -> bool:
        """Cloud Functions 사용 가능 여부"""
        return self._available

    def _get_machine_id(self) -> str:
        """현재 컴퓨터의 하드웨어 ID 생성"""
        try:
            # uuid.getnode()는 MAC 주소 기반 고유 ID 반환
            return str(uuid.getnode())
        except Exception:
            # 폴백: 플랫폼 정보 기반 해시
            import platform
            info = f"{platform.node()}|{platform.system()}|{platform.machine()}"
            return hashlib.md5(info.encode()).hexdigest()

    def check_package_ownership(self, license_key: str, pack_id: str) -> Tuple[bool, str]:
        """
        Cloud Functions를 통해 패키지 소유권 확인

        Args:
            license_key: 라이센스 키
            pack_id: 패키지 ID (예: "horror_pack")

        Returns:
            (bool, str): (소유 여부, 메시지)
        """
        if not self._available:
            return False, "HTTP 클라이언트를 사용할 수 없습니다. (requests 패키지 필요)"

        url = f"{self._base_url}/{self.FUNC_CHECK_OWNERSHIP}"
        machine_id = self._get_machine_id()

        # onRequest 형식: 직접 데이터 전송 (data 래핑 없음)
        payload = {
            "licenseKey": license_key.upper(),
            "packId": pack_id,
            "machineId": machine_id
        }

        headers = {
            "Content-Type": "application/json"
        }

        logger.debug(f"[CloudFunctions] 소유권 검증 요청: key=***{license_key[-4:] if license_key else '?'}, pack={pack_id}")

        import time as _time
        import random as _random

        max_retries = 2
        for attempt in range(max_retries):
            try:
                response = requests.post(url, json=payload, headers=headers, timeout=10)

                # 응답 디버깅
                logger.debug(f"[CloudFunctions] 응답 코드: {response.status_code}")
                logger.debug(f"[CloudFunctions] 응답 본문: {response.text[:500]}")

                if response.status_code != 200:
                    # 에러 응답도 JSON일 수 있음
                    try:
                        error_data = response.json()
                        error_msg = error_data.get("message", error_data.get("error", str(error_data)))
                        safe_error = redact_sensitive_text(error_msg)
                        logger.error(f"[CloudFunctions] 서버 에러: {safe_error}")
                        return False, safe_error
                    except (json.JSONDecodeError, ValueError) as e:
                        logger.debug(f"[CloudFunctions] 에러 응답 JSON 파싱 실패: {e}")
                    logger.error(f"[CloudFunctions] HTTP 오류: {response.status_code}")
                    return False, f"서버 통신 오류 (HTTP {response.status_code})"

                response_data = response.json()

                # onRequest 응답 형식: 직접 valid, message 반환
                is_valid = response_data.get("valid", False)
                message = response_data.get("message", "알 수 없는 응답")

                logger.info(f"[CloudFunctions] 검증 결과: valid={is_valid}, msg={message}")
                return is_valid, message

            except requests.exceptions.Timeout:
                if attempt < max_retries - 1:
                    delay = 2.0 * (attempt + 1) * (0.5 + _random.random())
                    logger.warning(f"[CloudFunctions] 시간 초과, {delay:.1f}초 후 재시도 ({attempt+1}/{max_retries})")
                    _time.sleep(delay)
                else:
                    logger.error("[CloudFunctions] 요청 시간 초과 (재시도 소진)")
                    return False, "서버 응답 시간 초과. 인터넷 연결을 확인해주세요."
            except requests.exceptions.ConnectionError:
                if attempt < max_retries - 1:
                    delay = 2.0 * (attempt + 1) * (0.5 + _random.random())
                    logger.warning(f"[CloudFunctions] 연결 실패, {delay:.1f}초 후 재시도 ({attempt+1}/{max_retries})")
                    _time.sleep(delay)
                else:
                    logger.error("[CloudFunctions] 연결 실패 (재시도 소진)")
                    return False, "서버에 연결할 수 없습니다. 인터넷 연결을 확인해주세요."
            except Exception as e:
                safe_error = redact_sensitive_text(e)
                logger.error(f"[CloudFunctions] 오류: {safe_error}")
                return False, f"서버 통신 오류: {safe_error}"

        return False, "서버 통신 실패 (재시도 소진)"

    def get_owned_packs(self, license_key: str) -> Tuple[bool, str, List[str]]:
        """
        Cloud Functions를 통해 보유 패키지 목록 조회

        Args:
            license_key: 라이센스 키

        Returns:
            (bool, str, list): (성공 여부, 메시지, 패키지 ID 목록)
        """
        if not self._available:
            return False, "HTTP 클라이언트를 사용할 수 없습니다.", []

        url = f"{self._base_url}/{self.FUNC_GET_OWNED_PACKS}"

        # onRequest 형식: 직접 데이터 전송
        payload = {
            "licenseKey": license_key.upper()
        }

        headers = {
            "Content-Type": "application/json"
        }

        logger.debug(f"[CloudFunctions] 패키지 목록 요청: key=***{license_key[-4:] if license_key else '?'}")

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=10)

            logger.debug(f"[CloudFunctions] 응답 코드: {response.status_code}")
            logger.debug(f"[CloudFunctions] 응답 본문: {response.text[:500]}")

            if response.status_code != 200:
                try:
                    error_data = response.json()
                    error_msg = error_data.get("message", error_data.get("error", str(error_data)))
                    return False, redact_sensitive_text(error_msg), []
                except (json.JSONDecodeError, ValueError) as e:
                    logger.debug(f"[CloudFunctions] 에러 응답 JSON 파싱 실패: {e}")
                return False, f"서버 통신 오류 (HTTP {response.status_code})", []

            response_data = response.json()

            # onRequest 응답 형식: packs 또는 ownedPacks 필드
            packs = response_data.get("packs") or response_data.get("ownedPacks", [])
            license_type = response_data.get("licenseType", "")

            # 전체 이용권(A)이면 특수 표시
            if license_type == "A":
                return True, "전체 이용권", ["*"]

            return True, "조회 성공", packs

        except Exception as e:
            safe_error = redact_sensitive_text(e)
            logger.error(f"[CloudFunctions] 패키지 목록 조회 오류: {safe_error}")
            return False, safe_error, []

    def get_pack_key(self, license_key: str, hwid: str, pack_id: str) -> Optional[str]:
        """
        v62.27: Cloud Functions를 통해 팩 복호화 키 조회.
        서버 /pack_keys/{pack_id} 컬렉션에서 팩 키를 발급받음.

        Args:
            license_key: 라이선스 키
            hwid: 하드웨어 ID
            pack_id: 팩 ID (예: "horror_v59")

        Returns:
            팩 키 문자열 또는 None (실패/미등록)
        """
        if not self._available:
            return None

        url = f"{self._base_url}/{self.FUNC_GET_PACK_KEY}"
        payload = {
            "licenseKey": license_key.upper(),
            "hwid": hwid,
            "packId": pack_id,
        }
        headers = {"Content-Type": "application/json"}

        try:
            import requests as _requests
            response = _requests.post(url, json=payload, headers=headers, timeout=10)
            if response.status_code != 200:
                logger.warning(f"[CloudFunctions] getPackKey HTTP {response.status_code}: {pack_id}")
                return None
            data = response.json()
            if "error" in data:
                logger.warning(f"[CloudFunctions] getPackKey 오류: {redact_sensitive_text(data['error'])}")
                return None
            pack_key = data.get("packKey")
            if pack_key:
                logger.info(f"[CloudFunctions] getPackKey 성공: {pack_id}")
            else:
                logger.debug(f"[CloudFunctions] getPackKey: packKey=null (레거시 모드)")
            return pack_key
        except Exception as e:
            logger.warning(f"[CloudFunctions] getPackKey 예외: {redact_sensitive_text(e)}")
            return None


# Cloud Functions 클라이언트 싱글톤
_cf_client: Optional[CloudFunctionsClient] = None

def get_cloud_functions_client() -> CloudFunctionsClient:
    """Cloud Functions 클라이언트 싱글톤"""
    global _cf_client
    if _cf_client is None:
        _cf_client = CloudFunctionsClient()
    return _cf_client


class FirebaseLicenseValidator:
    """
    Firebase 기반 온라인 라이센스 검증기

    사용법:
        validator = FirebaseLicenseValidator()
        valid, msg = validator.validate(license_key, hardware_id)
    """

    def __init__(self, credentials_path: str = None):
        """
        초기화

        Args:
            credentials_path: Firebase 서비스 계정 JSON 파일 경로
                             None이면 기본 경로 사용
        """
        self.db = None
        self.initialized = False

        if not FIREBASE_AVAILABLE:
            return

        # 인증 파일 경로 결정
        if credentials_path is None:
            # 기본 경로들 시도
            possible_paths = [
                os.path.join(os.path.dirname(__file__), "..", "..", "config", "firebase_credentials.json"),
                os.path.join(os.path.dirname(__file__), "..", "config", "firebase_credentials.json"),
                "config/firebase_credentials.json",
                "firebase_credentials.json",
            ]

            for path in possible_paths:
                abs_path = os.path.abspath(path)
                if os.path.exists(abs_path):
                    credentials_path = abs_path
                    break

        if credentials_path is None or not os.path.exists(credentials_path):
            print("⚠️ Firebase 인증 파일을 찾을 수 없습니다.")
            print("   config/firebase_credentials.json 파일이 필요합니다.")
            return

        try:
            # Firebase 앱 초기화 (이미 초기화되어 있으면 기존 앱 사용)
            if not firebase_admin._apps:
                cred = credentials.Certificate(credentials_path)
                firebase_admin.initialize_app(cred)

            self.db = firestore.client()
            self.initialized = True
            print("[OK] Firebase 연결 성공")

        except Exception as e:
            print(f"[ERROR] Firebase 초기화 실패: {e}")
            self.initialized = False

    def is_available(self) -> bool:
        """Firebase 사용 가능 여부"""
        return self.initialized and self.db is not None

    def validate(self, license_key: str, hardware_id: str) -> Tuple[bool, str, Optional[Dict]]:
        """
        라이센스 검증 (메인 메서드)

        Args:
            license_key: 라이센스 키
            hardware_id: 현재 PC의 하드웨어 ID

        Returns:
            (bool, str, dict): (유효 여부, 메시지, 라이센스 정보)
        """
        if not self.is_available():
            return False, "서버 연결 실패. 오프라인 모드로 전환합니다.", None

        try:
            # 라이센스 문서 조회
            license_ref = self.db.collection('licenses').document(license_key.upper())
            license_doc = license_ref.get()

            if not license_doc.exists:
                return False, "등록되지 않은 라이센스입니다.", None

            data = license_doc.to_dict()

            # 1. 활성화 상태 확인
            if not data.get('is_active', False):
                return False, "비활성화된 라이센스입니다. 관리자에게 문의하세요.", None

            # 2. 하드웨어 ID 확인
            registered_hw = data.get('hardware_id', '')
            if registered_hw and registered_hw != hardware_id:
                return False, f"이 라이센스는 다른 컴퓨터에 등록되어 있습니다.", None

            # 3. 만료일 확인
            expire_date = data.get('expire_date')
            if expire_date:
                # Firestore Timestamp를 datetime으로 변환
                if hasattr(expire_date, 'timestamp'):
                    expire_dt = datetime.fromtimestamp(expire_date.timestamp())
                else:
                    expire_dt = expire_date

                if datetime.now() > expire_dt:
                    return False, f"라이센스가 만료되었습니다. (만료일: {expire_dt.strftime('%Y-%m-%d')})", None

                days_left = (expire_dt - datetime.now()).days
            else:
                days_left = 9999  # 무제한
                expire_dt = None

            # 4. 검증 성공 - 마지막 검증 시간 업데이트
            license_ref.update({
                'last_verified': firestore.SERVER_TIMESTAMP,
                'hardware_id': hardware_id  # 하드웨어 ID 바인딩 (최초 등록 시)
            })

            # 라이센스 정보 반환
            license_info = {
                'license_key': license_key,
                'user_id': data.get('user_id', ''),
                'license_type': data.get('license_type', 'A'),
                'expire_date': expire_dt.strftime('%Y-%m-%d') if expire_dt else '무제한',
                'days_left': days_left,
                'is_active': True,
                'memo': data.get('memo', '')
            }

            return True, f"라이센스 유효 (남은 기간: {days_left}일)", license_info

        except Exception as e:
            return False, f"서버 검증 중 오류: {str(e)}", None

    def register_license(
        self,
        license_key: str,
        user_id: str,
        hardware_id: str,
        license_type: str = 'A',
        duration_days: int = 30,
        memo: str = "",
        owned_packs: List[str] = None
    ) -> Tuple[bool, str]:
        """
        라이센스 등록 (관리자용)

        Args:
            license_key: 라이센스 키
            user_id: 사용자 ID
            hardware_id: 하드웨어 ID
            license_type: 라이센스 타입 (A/H/T/M) - 하위호환용, 팩 기반으로 전환
            duration_days: 유효 기간 (일)
            memo: 관리자 메모
            owned_packs: 보유 패키지 목록 (새로운 팩 기반 시스템)

        Returns:
            (bool, str): (성공 여부, 메시지)
        """
        if not self.is_available():
            return False, "Firebase 연결 실패"

        try:
            expire_date = datetime.now() + timedelta(days=duration_days)

            # 기본 팩 설정 (owned_packs가 없으면 기본 3개 제공)
            if owned_packs is None:
                owned_packs = ['daily_life_toon_pack', 'mystery_toon_pack']

            license_data = {
                'user_id': user_id,
                'hardware_id': hardware_id,
                'license_type': license_type.upper(),  # 하위호환 유지
                'owned_packs': owned_packs,  # 새로운 팩 기반 시스템
                'expire_date': expire_date,
                'is_active': True,
                'created_at': firestore.SERVER_TIMESTAMP,
                'last_verified': None,
                'memo': memo
            }

            self.db.collection('licenses').document(license_key.upper()).set(license_data)

            return True, f"라이센스가 등록되었습니다. (만료일: {expire_date.strftime('%Y-%m-%d')}, 팩: {len(owned_packs)}개)"

        except Exception as e:
            return False, f"등록 실패: {str(e)}"

    def update_license(
        self,
        license_key: str,
        **kwargs
    ) -> Tuple[bool, str]:
        """
        라이센스 정보 수정 (관리자용)

        Args:
            license_key: 라이센스 키
            **kwargs: 수정할 필드들 (user_id, license_type, is_active, memo 등)

        Returns:
            (bool, str): (성공 여부, 메시지)
        """
        if not self.is_available():
            return False, "Firebase 연결 실패"

        try:
            license_ref = self.db.collection('licenses').document(license_key.upper())

            if not license_ref.get().exists:
                return False, "존재하지 않는 라이센스입니다."

            # 수정 가능한 필드만 필터링
            allowed_fields = ['user_id', 'license_type', 'is_active', 'memo', 'hardware_id', 'owned_packs']
            update_data = {k: v for k, v in kwargs.items() if k in allowed_fields}

            if 'owned_packs' in update_data:
                normalized_packs = []
                for pack_id in update_data.get('owned_packs') or []:
                    value = str(pack_id).strip()
                    if value and value not in normalized_packs:
                        normalized_packs.append(value)
                update_data['owned_packs'] = normalized_packs

            if update_data:
                update_data['updated_at'] = firestore.SERVER_TIMESTAMP
                license_ref.update(update_data)

            return True, "라이센스가 수정되었습니다."

        except Exception as e:
            return False, f"수정 실패: {str(e)}"

    def extend_license(self, license_key: str, additional_days: int) -> Tuple[bool, str]:
        """
        라이센스 연장 (관리자용)

        Args:
            license_key: 라이센스 키
            additional_days: 추가 일수

        Returns:
            (bool, str): (성공 여부, 메시지)
        """
        if not self.is_available():
            return False, "Firebase 연결 실패"

        try:
            license_ref = self.db.collection('licenses').document(license_key.upper())
            license_doc = license_ref.get()

            if not license_doc.exists:
                return False, "존재하지 않는 라이센스입니다."

            data = license_doc.to_dict()
            current_expire = data.get('expire_date')

            if current_expire:
                if hasattr(current_expire, 'timestamp'):
                    current_dt = datetime.fromtimestamp(current_expire.timestamp())
                else:
                    current_dt = current_expire

                # 이미 만료된 경우 오늘부터 계산
                if current_dt < datetime.now():
                    current_dt = datetime.now()
            else:
                current_dt = datetime.now()

            new_expire = current_dt + timedelta(days=additional_days)

            license_ref.update({
                'expire_date': new_expire,
                'updated_at': firestore.SERVER_TIMESTAMP
            })

            return True, f"라이센스가 연장되었습니다. (새 만료일: {new_expire.strftime('%Y-%m-%d')})"

        except Exception as e:
            return False, f"연장 실패: {str(e)}"

    def deactivate_license(self, license_key: str) -> Tuple[bool, str]:
        """라이센스 비활성화"""
        return self.update_license(license_key, is_active=False)

    def activate_license(self, license_key: str) -> Tuple[bool, str]:
        """라이센스 활성화"""
        return self.update_license(license_key, is_active=True)

    def get_license_info(self, license_key: str) -> Optional[Dict]:
        """라이센스 정보 조회"""
        if not self.is_available():
            return None

        try:
            license_doc = self.db.collection('licenses').document(license_key.upper()).get()

            if not license_doc.exists:
                return None

            data = license_doc.to_dict()

            # Timestamp 변환
            expire_date = data.get('expire_date')
            if expire_date and hasattr(expire_date, 'timestamp'):
                data['expire_date'] = datetime.fromtimestamp(expire_date.timestamp())

            created_at = data.get('created_at')
            if created_at and hasattr(created_at, 'timestamp'):
                data['created_at'] = datetime.fromtimestamp(created_at.timestamp())

            last_verified = data.get('last_verified')
            if last_verified and hasattr(last_verified, 'timestamp'):
                data['last_verified'] = datetime.fromtimestamp(last_verified.timestamp())

            return data

        except Exception as e:
            print(f"조회 실패: {e}")
            return None

    def get_all_licenses(self) -> list:
        """모든 라이센스 목록 조회 (관리자용)"""
        if not self.is_available():
            return []

        try:
            licenses = []
            docs = self.db.collection('licenses').stream()

            for doc in docs:
                data = doc.to_dict()
                data['license_key'] = doc.id

                # Timestamp 변환
                for field in ['expire_date', 'created_at', 'last_verified', 'updated_at']:
                    if field in data and data[field] and hasattr(data[field], 'timestamp'):
                        data[field] = datetime.fromtimestamp(data[field].timestamp())

                licenses.append(data)

            return licenses

        except Exception as e:
            print(f"목록 조회 실패: {e}")
            return []

    def delete_license(self, license_key: str) -> Tuple[bool, str]:
        """라이센스 삭제 (관리자용)"""
        if not self.is_available():
            return False, "Firebase 연결 실패"

        try:
            self.db.collection('licenses').document(license_key.upper()).delete()
            return True, "라이센스가 삭제되었습니다."
        except Exception as e:
            return False, f"삭제 실패: {str(e)}"

    # ============================================================
    # 패키지 소유권 확인 (v37)
    # ============================================================

    def check_package_ownership(self, license_key: str, pack_id: str) -> Tuple[bool, str]:
        """
        패키지 소유권 확인

        사용자의 라이센스 문서에서 owned_packs 배열을 확인하여
        해당 패키지를 보유했는지 검증

        Firestore 구조:
        /licenses/{license_key}
            - owned_packs: ["horror_pack", "senior_pack", ...]

        Args:
            license_key: 라이센스 키
            pack_id: 패키지 ID (예: "horror_pack")

        Returns:
            (bool, str): (소유 여부, 메시지)
        """
        if not self.is_available():
            return False, "서버 연결 실패"

        try:
            license_ref = self.db.collection('licenses').document(license_key.upper())
            license_doc = license_ref.get()

            if not license_doc.exists:
                return False, "등록되지 않은 라이센스입니다."

            data = license_doc.to_dict()

            # 라이센스 활성 상태 확인
            if not data.get('is_active', False):
                return False, "비활성화된 라이센스입니다."

            # owned_packs 배열 확인
            owned_packs = data.get('owned_packs', [])

            # 전체 이용권(A) 타입은 모든 패키지 접근 가능
            license_type = data.get('license_type', '')
            if license_type == 'A':
                return True, "전체 이용권 - 모든 패키지 사용 가능"

            # 패키지 소유 확인
            if pack_id in owned_packs:
                return True, f"패키지 '{pack_id}' 사용 가능"
            else:
                return False, f"구매하지 않은 패키지입니다.\n'{pack_id}' 패키지를 웹사이트에서 구매해주세요."

        except Exception as e:
            return False, f"소유권 확인 중 오류: {str(e)}"

    def get_owned_packs(self, license_key: str) -> list:
        """
        사용자가 보유한 패키지 목록 조회

        Args:
            license_key: 라이센스 키

        Returns:
            패키지 ID 목록
        """
        if not self.is_available():
            return []

        try:
            license_doc = self.db.collection('licenses').document(license_key.upper()).get()

            if not license_doc.exists:
                return []

            data = license_doc.to_dict()

            # 전체 이용권은 특수 처리
            if data.get('license_type') == 'A':
                return ['*']  # 모든 패키지

            return data.get('owned_packs', [])

        except Exception as e:
            print(f"패키지 목록 조회 실패: {e}")
            return []

    def add_pack_to_license(self, license_key: str, pack_id: str) -> Tuple[bool, str]:
        """
        라이센스에 패키지 추가 (관리자용)

        Args:
            license_key: 라이센스 키
            pack_id: 추가할 패키지 ID

        Returns:
            (bool, str): (성공 여부, 메시지)
        """
        if not self.is_available():
            return False, "Firebase 연결 실패"

        try:
            license_ref = self.db.collection('licenses').document(license_key.upper())
            license_doc = license_ref.get()

            if not license_doc.exists:
                return False, "존재하지 않는 라이센스입니다."

            # ArrayUnion으로 중복 없이 추가
            license_ref.update({
                'owned_packs': firestore.ArrayUnion([pack_id]),
                'updated_at': firestore.SERVER_TIMESTAMP
            })

            return True, f"패키지 '{pack_id}'가 추가되었습니다."

        except Exception as e:
            return False, f"패키지 추가 실패: {str(e)}"

    def remove_pack_from_license(self, license_key: str, pack_id: str) -> Tuple[bool, str]:
        """
        라이센스에서 패키지 제거 (관리자용)

        Args:
            license_key: 라이센스 키
            pack_id: 제거할 패키지 ID

        Returns:
            (bool, str): (성공 여부, 메시지)
        """
        if not self.is_available():
            return False, "Firebase 연결 실패"

        try:
            license_ref = self.db.collection('licenses').document(license_key.upper())

            # ArrayRemove로 제거
            license_ref.update({
                'owned_packs': firestore.ArrayRemove([pack_id]),
                'updated_at': firestore.SERVER_TIMESTAMP
            })

            return True, f"패키지 '{pack_id}'가 제거되었습니다."

        except Exception as e:
            return False, f"패키지 제거 실패: {str(e)}"

    # Alias 메서드 (GUI 호환성)
    def add_package_to_license(self, license_key: str, pack_id: str) -> Tuple[bool, str]:
        """add_pack_to_license의 alias"""
        return self.add_pack_to_license(license_key, pack_id)

    def remove_package_from_license(self, license_key: str, pack_id: str) -> Tuple[bool, str]:
        """remove_pack_from_license의 alias"""
        return self.remove_pack_from_license(license_key, pack_id)

    # ============================================================
    # 패키지 배포 관리 (v38)
    # ============================================================

    def get_package_distribution(self, pack_id: str) -> Dict:
        """
        특정 패키지의 배포 현황 조회

        Args:
            pack_id: 패키지 ID

        Returns:
            {
                'pack_id': str,
                'total_count': int,
                'active_count': int,
                'licenses': [{'license_key': str, 'user_id': str, 'is_active': bool, 'expire_date': datetime}, ...]
            }
        """
        if not self.is_available():
            return {'pack_id': pack_id, 'total_count': 0, 'active_count': 0, 'licenses': []}

        try:
            licenses = []
            active_count = 0

            # 모든 라이센스 조회 후 필터링
            docs = self.db.collection('licenses').stream()

            for doc in docs:
                data = doc.to_dict()
                owned_packs = data.get('owned_packs', [])

                # 이 패키지를 보유한 라이센스인지 확인
                if pack_id in owned_packs or data.get('license_type') == 'A':
                    license_info = {
                        'license_key': doc.id,
                        'user_id': data.get('user_id', ''),
                        'is_active': data.get('is_active', False),
                        'expire_date': data.get('expire_date'),
                        'memo': data.get('memo', '')
                    }

                    # Timestamp 변환
                    if license_info['expire_date'] and hasattr(license_info['expire_date'], 'timestamp'):
                        license_info['expire_date'] = datetime.fromtimestamp(license_info['expire_date'].timestamp())

                    licenses.append(license_info)

                    if data.get('is_active', False):
                        active_count += 1

            return {
                'pack_id': pack_id,
                'total_count': len(licenses),
                'active_count': active_count,
                'licenses': licenses
            }

        except Exception as e:
            print(f"배포 현황 조회 실패: {e}")
            return {'pack_id': pack_id, 'total_count': 0, 'active_count': 0, 'licenses': []}

    def get_all_package_stats(self) -> List[Dict]:
        """
        모든 패키지의 배포 통계 조회

        Returns:
            [{'pack_id': str, 'total_count': int, 'active_count': int}, ...]
        """
        if not self.is_available():
            return []

        try:
            # 패키지별 카운트
            pack_stats = {}

            docs = self.db.collection('licenses').stream()

            for doc in docs:
                data = doc.to_dict()
                is_active = data.get('is_active', False)
                owned_packs = data.get('owned_packs', [])

                for pack_id in owned_packs:
                    if pack_id not in pack_stats:
                        pack_stats[pack_id] = {'pack_id': pack_id, 'total_count': 0, 'active_count': 0}

                    pack_stats[pack_id]['total_count'] += 1
                    if is_active:
                        pack_stats[pack_id]['active_count'] += 1

            return list(pack_stats.values())

        except Exception as e:
            print(f"패키지 통계 조회 실패: {e}")
            return []

    def bulk_add_package(self, license_keys: List[str], pack_id: str) -> Tuple[int, int, List[str]]:
        """
        여러 라이센스에 패키지 일괄 추가

        Args:
            license_keys: 라이센스 키 목록
            pack_id: 추가할 패키지 ID

        Returns:
            (성공 수, 실패 수, 실패한 키 목록)
        """
        if not self.is_available():
            return 0, len(license_keys), license_keys

        success = 0
        failed = 0
        failed_keys = []

        for key in license_keys:
            ok, msg = self.add_pack_to_license(key, pack_id)
            if ok:
                success += 1
            else:
                failed += 1
                failed_keys.append(key)

        return success, failed, failed_keys

    def bulk_remove_package(self, license_keys: List[str], pack_id: str) -> Tuple[int, int, List[str]]:
        """
        여러 라이센스에서 패키지 일괄 제거

        Args:
            license_keys: 라이센스 키 목록
            pack_id: 제거할 패키지 ID

        Returns:
            (성공 수, 실패 수, 실패한 키 목록)
        """
        if not self.is_available():
            return 0, len(license_keys), license_keys

        success = 0
        failed = 0
        failed_keys = []

        for key in license_keys:
            ok, msg = self.remove_pack_from_license(key, pack_id)
            if ok:
                success += 1
            else:
                failed += 1
                failed_keys.append(key)

        return success, failed, failed_keys

    def get_registered_packages(self) -> List[str]:
        """
        시스템에 등록된 모든 패키지 ID 목록 조회
        (라이센스들의 owned_packs에서 수집)

        Returns:
            패키지 ID 목록
        """
        if not self.is_available():
            return []

        try:
            all_packs = set()

            docs = self.db.collection('licenses').stream()

            for doc in docs:
                data = doc.to_dict()
                owned_packs = data.get('owned_packs', [])
                all_packs.update(owned_packs)

            return sorted(list(all_packs))

        except Exception as e:
            print(f"패키지 목록 조회 실패: {e}")
            return []


# ============================================================
# 하이브리드 검증기 (온라인 + 오프라인 폴백)
# ============================================================

class HybridLicenseValidator:
    """
    온라인(Firebase) + 오프라인 하이브리드 라이센스 검증기

    동작 방식:
    1. Firebase 서버로 온라인 검증 시도
    2. 서버 연결 실패 시 오프라인 검증으로 폴백
    3. 온라인 검증 성공 시 로컬 캐시 업데이트
    """

    def __init__(self, data_dir: str = "data"):
        """
        초기화

        Args:
            data_dir: 로컬 데이터 저장 디렉토리
        """
        self.data_dir = data_dir

        # 온라인 검증기
        self.online_validator = FirebaseLicenseValidator()

        # 오프라인 검증기 (기존 모듈)
        try:
            from utils.license_validator import LicenseValidator
            self.offline_validator = LicenseValidator(data_dir=data_dir)
        except ImportError:
            self.offline_validator = None

        # 현재 하드웨어 ID
        try:
            from utils.hardware_id import get_hardware_id
            self.current_hw_id = get_hardware_id()
        except ImportError:
            import hashlib
            import platform
            self.current_hw_id = hashlib.md5(platform.node().encode()).hexdigest()[:16].upper()

    def validate(self) -> Tuple[bool, str, Optional[Dict]]:
        """
        라이센스 검증 (온라인 우선, 오프라인 폴백)

        Returns:
            (bool, str, dict): (유효 여부, 메시지, 라이센스 정보)
        """
        # 저장된 라이센스 키 불러오기
        license_key = self._load_saved_license_key()

        if not license_key:
            return False, "라이센스가 등록되지 않았습니다.", None

        # 1. 온라인 검증 시도
        if self.online_validator.is_available():
            valid, msg, info = self.online_validator.validate(license_key, self.current_hw_id)

            if valid:
                # 온라인 검증 성공 - 캐시 업데이트
                self._update_local_cache(license_key, info)
                return True, f"[온라인] {msg}", info
            else:
                # 온라인 검증 실패
                return False, f"[온라인] {msg}", None

        # 2. 온라인 실패 시 오프라인 폴백
        if self.offline_validator:
            valid, msg = self.offline_validator.validate()

            if valid:
                info = self.offline_validator.get_license_info()
                return True, f"[오프라인] {msg}", info
            else:
                return False, f"[오프라인] {msg}", None

        return False, "라이센스 검증에 실패했습니다.", None

    def set_license(self, license_key: str) -> Tuple[bool, str]:
        """
        라이센스 등록

        Args:
            license_key: 라이센스 키

        Returns:
            (bool, str): (성공 여부, 메시지)
        """
        license_key = license_key.strip().upper()

        # 온라인 검증
        if self.online_validator.is_available():
            valid, msg, info = self.online_validator.validate(license_key, self.current_hw_id)

            if valid:
                # 로컬에 키 저장
                self._save_license_key(license_key)
                self._update_local_cache(license_key, info)
                return True, f"라이센스가 등록되었습니다. {msg}"
            else:
                return False, msg

        # 오프라인 폴백
        if self.offline_validator:
            return self.offline_validator.set_license(license_key)

        return False, "라이센스 검증 서버에 연결할 수 없습니다."

    def get_license_info(self) -> Optional[Dict]:
        """라이센스 정보 반환"""
        license_key = self._load_saved_license_key()

        if not license_key:
            return None

        # 온라인 정보 조회
        if self.online_validator.is_available():
            info = self.online_validator.get_license_info(license_key)
            if info:
                info['license_key'] = license_key
                info['hardware_id'] = self.current_hw_id
                return info

        # 오프라인 폴백
        if self.offline_validator:
            return self.offline_validator.get_license_info()

        return None

    def _save_license_key(self, license_key: str):
        """라이센스 키 로컬 저장 (v62.22: Fernet 암호화)"""
        os.makedirs(self.data_dir, exist_ok=True)

        cache_path = os.path.join(self.data_dir, "license_cache.json")

        data = {
            'license_key': license_key,
            'hardware_id': self.current_hw_id,
            'saved_at': datetime.now().isoformat()
        }

        _write_license_cache(cache_path, data)

    def _load_saved_license_key(self) -> Optional[str]:
        """저장된 라이센스 키 불러오기 (v62.22: Fernet 암호화 + 평문 자동 마이그레이션)"""
        cache_path = os.path.join(self.data_dir, "license_cache.json")

        if os.path.exists(cache_path):
            data = _read_license_cache(cache_path)
            if data:
                return data.get('license_key')

        # 기존 license.dat 파일에서 불러오기 시도
        if self.offline_validator:
            return self.offline_validator._load_license()

        return None

    def _update_local_cache(self, license_key: str, info: Dict):
        """로컬 캐시 업데이트 (v62.22: Fernet 암호화)"""
        os.makedirs(self.data_dir, exist_ok=True)

        cache_path = os.path.join(self.data_dir, "license_cache.json")

        data = {
            'license_key': license_key,
            'hardware_id': self.current_hw_id,
            'license_type': info.get('license_type', 'A'),
            'expire_date': info.get('expire_date'),
            'days_left': info.get('days_left'),
            'user_id': info.get('user_id'),
            'last_online_verify': datetime.now().isoformat()
        }

        _write_license_cache(cache_path, data)

    # ============================================================
    # 패키지 소유권 확인 (v37 - Cloud Functions 우선)
    # ============================================================

    def check_package_ownership(self, pack_id: str) -> Tuple[bool, str]:
        """
        패키지 소유권 확인

        현재 로그인된 사용자가 해당 패키지를 보유했는지 확인
        시리얼 키 입력 없이 자동으로 검증

        검증 순서:
        1. Cloud Functions API (권장, Firestore 규칙 우회)
        2. Firebase Admin SDK (직접 접근, 규칙이 허용하는 경우)
        3. 오프라인 캐시 폴백

        Args:
            pack_id: 패키지 ID (예: "horror_pack")

        Returns:
            (bool, str): (소유 여부, 메시지)
        """
        license_key = self._load_saved_license_key()

        if not license_key:
            return False, "라이센스가 등록되지 않았습니다.\n먼저 구독을 등록해주세요."

        # 1. Cloud Functions API 우선 시도 (권장)
        cf_client = get_cloud_functions_client()
        if cf_client.is_available:
            try:
                valid, msg = cf_client.check_package_ownership(license_key, pack_id)

                # 성공 시 캐시 업데이트
                if valid:
                    self._update_ownership_cache(pack_id, True)

                return valid, msg
            except Exception as e:
                logger.warning(f"[HybridValidator] Cloud Functions 실패, 폴백 시도: {redact_sensitive_text(e)}")

        # 2. Firebase Admin SDK 직접 접근 (폴백)
        if self.online_validator.is_available():
            try:
                valid, msg = self.online_validator.check_package_ownership(license_key, pack_id)
                if valid:
                    self._update_ownership_cache(pack_id, True)
                return valid, msg
            except Exception as e:
                logger.warning(f"[HybridValidator] Firebase 직접 접근 실패: {redact_sensitive_text(e)}")

        # 3. 오프라인 폴백 - 로컬 캐시 확인
        return self._check_ownership_offline(pack_id)

    def _update_ownership_cache(self, pack_id: str, owned: bool):
        """패키지 소유권 캐시 업데이트 (v62.22: Fernet 암호화)"""
        try:
            cache_path = os.path.join(self.data_dir, "license_cache.json")

            data = _read_license_cache(cache_path) or {}

            # owned_packs 리스트 업데이트
            owned_packs = data.get('owned_packs', [])
            if owned and pack_id not in owned_packs:
                owned_packs.append(pack_id)
            elif not owned and pack_id in owned_packs:
                owned_packs.remove(pack_id)

            data['owned_packs'] = owned_packs
            data['ownership_cached_at'] = datetime.now().isoformat()

            _write_license_cache(cache_path, data)

        except Exception as e:
            logger.debug(f"[HybridValidator] 캐시 업데이트 실패: {e}")

    def _check_ownership_offline(self, pack_id: str) -> Tuple[bool, str]:
        """오프라인 패키지 소유권 확인 (캐시 기반, v62.22: Fernet 지원)"""
        cache_path = os.path.join(self.data_dir, "license_cache.json")

        if not os.path.exists(cache_path):
            return False, "오프라인 상태에서는 패키지 소유권을 확인할 수 없습니다."

        try:
            data = _read_license_cache(cache_path)

            if not data:
                return False, "캐시 파일을 읽을 수 없습니다."

            # 전체 이용권(A) 타입은 모든 패키지 접근 가능
            if data.get('license_type') == 'A':
                return True, "[오프라인] 전체 이용권 - 모든 패키지 사용 가능"

            # 캐시된 패키지 목록 확인
            owned_packs = data.get('owned_packs', [])
            if pack_id in owned_packs:
                return True, f"[오프라인] 패키지 '{pack_id}' 사용 가능"
            else:
                return False, f"[오프라인] 패키지 소유권을 확인할 수 없습니다.\n인터넷 연결 후 다시 시도해주세요."

        except Exception as e:
            return False, f"캐시 확인 실패: {e}"

    def get_owned_packs(self) -> list:
        """
        현재 사용자가 보유한 패키지 목록 조회

        검증 순서:
        1. Cloud Functions API (권장)
        2. Firebase Admin SDK (폴백)
        3. 오프라인 캐시

        Returns:
            패키지 ID 목록 (전체 이용권은 ['*'] 반환)
        """
        license_key = self._load_saved_license_key()

        if not license_key:
            return []

        # 1. Cloud Functions API 우선 시도
        cf_client = get_cloud_functions_client()
        if cf_client.is_available:
            try:
                success, msg, packs = cf_client.get_owned_packs(license_key)
                if success:
                    self._cache_owned_packs(packs)
                    return packs
            except Exception as e:
                logger.warning(f"[HybridValidator] Cloud Functions 패키지 목록 조회 실패: {redact_sensitive_text(e)}")

        # 2. Firebase Admin SDK 직접 접근 (폴백)
        if self.online_validator.is_available():
            try:
                packs = self.online_validator.get_owned_packs(license_key)
                self._cache_owned_packs(packs)
                return packs
            except Exception as e:
                logger.warning(f"[HybridValidator] Firebase 직접 조회 실패: {redact_sensitive_text(e)}")

        # 3. 오프라인 폴백
        return self._get_cached_packs()

    def _cache_owned_packs(self, packs: list):
        """패키지 목록 캐시 (v62.22: Fernet 암호화)"""
        cache_path = os.path.join(self.data_dir, "license_cache.json")

        try:
            data = _read_license_cache(cache_path) or {}

            data['owned_packs'] = packs
            data['packs_cached_at'] = datetime.now().isoformat()

            _write_license_cache(cache_path, data)

        except Exception as e:
            logger.warning(f"패키지 캐시 저장 실패: {e}")

    def _get_cached_packs(self) -> list:
        """캐시된 패키지 목록 조회 (v62.22: Fernet 지원)"""
        cache_path = os.path.join(self.data_dir, "license_cache.json")

        if os.path.exists(cache_path):
            data = _read_license_cache(cache_path)
            if data:
                return data.get('owned_packs', [])

        return []

    def get_pack_key(self, pack_id: str) -> Optional[str]:
        """
        v62.27: Phase B — 서버에서 팩 복호화 키 발급.

        흐름:
          1. 저장된 라이선스 키 로드
          2. Cloud Functions getPackKey API 호출
          3. 실패 또는 null 반환 시 None 반환 (Phase A 레거시 키 폴백은 pack_config에서 처리)

        Args:
            pack_id: 팩 ID (예: "horror_v59")

        Returns:
            팩 키 문자열 또는 None
        """
        license_key = self._load_saved_license_key()
        if not license_key:
            return None

        # HWID
        try:
            import uuid as _uuid
            hwid = str(_uuid.getnode())
        except Exception:
            hwid = ""

        cf_client = get_cloud_functions_client()
        if not cf_client.is_available:
            return None

        return cf_client.get_pack_key(license_key, hwid, pack_id)


# ============================================================
# 테스트
# ============================================================

if __name__ == "__main__":
    # 로깅 설정 (디버그 레벨)
    import logging
    logging.basicConfig(level=logging.DEBUG, format='%(levelname)s: %(message)s')

    print("=" * 60)
    print("Firebase 라이센스 시스템 테스트")
    print("=" * 60)

    # 1. Cloud Functions API 테스트 (v37)
    print("\n" + "=" * 60)
    print("[1] Cloud Functions API 테스트")
    print("=" * 60)

    cf_client = get_cloud_functions_client()

    if cf_client.is_available:
        print("✅ Cloud Functions 클라이언트 준비 완료")
        print(f"   프로젝트: {cf_client.PROJECT_ID}")
        print(f"   리전: {cf_client.REGION}")
        print(f"   하드웨어 ID: {cf_client._get_machine_id()}")
        print(f"   URL: {cf_client._base_url}")

        # 테스트 키로 소유권 확인 (Firestore에 등록된 키)
        test_key = "TEST-1234-5678-ABCD"
        test_pack = "daily_life_toon_pack"

        display_test_key = _redact_license_key_for_log(test_key)
        print(f"\n패키지 소유권 확인: key={display_test_key}, pack={test_pack}")
        valid, msg = cf_client.check_package_ownership(test_key, test_pack)
        print(f"  결과: {'✅ 승인' if valid else '❌ 거절'}")
        print(f"  메시지: {msg}")

        # 패키지 목록 조회
        print(f"\n패키지 목록 조회: key={display_test_key}")
        success, msg, packs = cf_client.get_owned_packs(test_key)
        print(f"  결과: {'✅ 성공' if success else '❌ 실패'}")
        print(f"  메시지: {msg}")
        print(f"  패키지: {packs}")
    else:
        print("❌ Cloud Functions 사용 불가 (requests 패키지 필요)")

    # 2. Firebase Admin SDK 테스트
    print("\n" + "=" * 60)
    print("[2] Firebase Admin SDK 테스트")
    print("=" * 60)

    validator = FirebaseLicenseValidator()

    if validator.is_available():
        print("✅ Firebase 연결 성공!")

        # 테스트 라이센스 등록
        test_key = "TEST-12345-ABCDE"
        test_hw = "ABCD1234EFGH5678"

        display_test_key = _redact_license_key_for_log(test_key)
        print(f"\n테스트 라이센스 등록: {display_test_key}")
        success, msg = validator.register_license(
            license_key=test_key,
            user_id="test_user",
            hardware_id=test_hw,
            license_type='A',
            duration_days=30,
            memo="테스트용"
        )
        print(f"  결과: {msg}")

        # 검증 테스트
        print(f"\n라이센스 검증: {display_test_key}")
        valid, msg, info = validator.validate(test_key, test_hw)
        print(f"  유효: {valid}")
        print(f"  메시지: {msg}")
        if info:
            print(f"  정보: {info}")

        # 잘못된 하드웨어 ID로 검증
        print(f"\n잘못된 하드웨어 ID로 검증:")
        valid, msg, info = validator.validate(test_key, "WRONG_HW_ID")
        print(f"  유효: {valid}")
        print(f"  메시지: {msg}")

    else:
        print("❌ Firebase Admin SDK 연결 실패")
        print("   config/firebase_credentials.json 파일을 확인하세요.")

    print("\n" + "=" * 60)
    print("테스트 완료")
    print("=" * 60)
