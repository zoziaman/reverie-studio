# create_test_license.py
"""
Firebase Firestore에 테스트 라이선스 데이터 생성

실행: python create_test_license.py
"""

import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime, timedelta
import os
import sys

# 키 파일 경로
KEY_FILE_PATH = "config/firebase_credentials.json"
TEST_LICENSE_KEY = "TEST-1234-5678-ABCD"


def _redact_license_key(license_key: str) -> str:
    parts = str(license_key or "").split("-")
    if len(parts) >= 4:
        return "-".join([parts[0], *["****"] * (len(parts) - 2), parts[-1]])
    if len(license_key or "") <= 8:
        return "****"
    return f"{license_key[:4]}...{license_key[-4:]}"


def create_test_license():
    """테스트 라이선스 생성"""

    # 1. Firebase 초기화
    if not firebase_admin._apps:
        try:
            cred = credentials.Certificate(KEY_FILE_PATH)
            firebase_admin.initialize_app(cred)
            print("✅ Firebase Admin SDK 초기화 성공")
        except Exception as e:
            print(f"❌ 초기화 실패: {e}")
            return False

    db = firestore.client()

    # 2. 테스트 라이선스 데이터
    license_key = TEST_LICENSE_KEY
    display_license_key = _redact_license_key(license_key)

    doc_data = {
        "license_key": license_key,
        "user_id": "test_user",
        "hardware_id": "",                # 빈 값 (아직 바인딩 안됨)
        "license_type": "T",              # T = 개별팩 구매자
        "is_active": True,
        "created_at": firestore.SERVER_TIMESTAMP,
        "expire_date": datetime.now() + timedelta(days=365),  # 1년 뒤 만료
        "owned_packs": ["horror_pack", "romance_pack"],       # 보유 패키지
        "memo": "테스트용 라이선스"
    }

    # 3. Firestore에 저장
    print(f"\n💾 라이선스 생성 중...")
    print(f"   키: {display_license_key}")
    print(f"   타입: {doc_data['license_type']}")
    print(f"   보유 패키지: {doc_data['owned_packs']}")

    try:
        db.collection("licenses").document(license_key).set(doc_data)
        print("\n✅ 테스트 라이선스 생성 완료!")
        print(f"\n🔑 라이선스 키: {display_license_key}")
        print(f"📦 보유 패키지: horror_pack, romance_pack")
        print("\n실제 키는 Firestore 문서 ID에서 확인하세요.")
        return True

    except Exception as e:
        print(f"❌ 저장 실패: {e}")
        return False


def verify_license():
    """생성된 라이선스 확인"""

    if not firebase_admin._apps:
        cred = credentials.Certificate(KEY_FILE_PATH)
        firebase_admin.initialize_app(cred)

    db = firestore.client()

    license_key = TEST_LICENSE_KEY
    doc = db.collection("licenses").document(license_key).get()

    if doc.exists:
        data = doc.to_dict()
        print("\n📋 저장된 라이선스 정보:")
        print(f"   키: {_redact_license_key(data.get('license_key'))}")
        print(f"   타입: {data.get('license_type')}")
        print(f"   활성: {data.get('is_active')}")
        print(f"   보유 패키지: {data.get('owned_packs')}")
        print(f"   메모: {data.get('memo')}")
        return True
    else:
        print("❌ 라이선스를 찾을 수 없습니다.")
        return False


if __name__ == "__main__":
    print("=" * 50)
    print("Firebase 테스트 라이선스 생성기")
    print("=" * 50)

    # 키 파일 확인
    if not os.path.exists(KEY_FILE_PATH):
        print(f"❌ 키 파일 없음: {KEY_FILE_PATH}")
        sys.exit(1)

    # 라이선스 생성
    if create_test_license():
        print("\n" + "-" * 50)
        # 확인
        verify_license()

    print("\n" + "=" * 50)
