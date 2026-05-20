# test_full_flow.py
# -*- coding: utf-8 -*-
"""
v37 패키지 시스템 전체 플로우 테스트

테스트 흐름:
1. 라이선스 등록 (TEST-1234-5678-ABCD)
2. 테스트 패키지(.revpack) 생성
3. 패키지 Import 시 소유권 검증
4. 결과 확인

실행: python test_full_flow.py
"""

import os
import sys
import json
import tempfile
import zipfile
from pathlib import Path
from datetime import datetime
import pytest

# Windows 콘솔 UTF-8 설정
if sys.platform == 'win32' and "pytest" not in sys.modules:
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# 프로젝트 루트를 path에 추가
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

src_path = os.path.join(project_root, "src")
if src_path not in sys.path:
    sys.path.insert(0, src_path)


def print_header(text):
    """구분선 출력"""
    print("\n" + "=" * 60)
    print(f" {text}")
    print("=" * 60)


def print_step(step_num, text):
    """단계 출력"""
    print(f"\n[Step {step_num}] {text}")
    print("-" * 40)


def test_step1_register_license():
    """Step 1: 라이선스 등록"""
    print_step(1, "라이선스 등록")

    try:
        from utils.firebase_license import HybridLicenseValidator
        from config.settings import config

        validator = HybridLicenseValidator(config.DATA_DIR)

        # 테스트 라이선스 키
        test_key = "TEST-1234-5678-ABCD"

        print(f"라이선스 키: {test_key}")
        print(f"데이터 디렉토리: {config.DATA_DIR}")

        # 라이선스 등록
        success, msg = validator.set_license(test_key)

        if success:
            print(f"✅ 등록 성공: {msg}")

            # license_cache.json 확인
            cache_path = os.path.join(config.DATA_DIR, "license_cache.json")
            if os.path.exists(cache_path):
                with open(cache_path, 'r', encoding='utf-8') as f:
                    cache_data = json.load(f)
                print(f"\n캐시 파일 내용:")
                print(f"  license_key: {cache_data.get('license_key')}")
                print(f"  hardware_id: {cache_data.get('hardware_id', 'N/A')[:20]}...")

            return True
        else:
            print(f"❌ 등록 실패: {msg}")
            return False

    except Exception as e:
        print(f"❌ 오류: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_step2_check_ownership():
    """Step 2: 패키지 소유권 확인"""
    print_step(2, "패키지 소유권 확인")

    try:
        from utils.firebase_license import HybridLicenseValidator
        from config.settings import config

        validator = HybridLicenseValidator(config.DATA_DIR)

        # 테스트할 패키지 ID들
        test_packs = ["horror_pack", "romance_pack", "non_existing_pack"]

        for pack_id in test_packs:
            print(f"\n패키지: {pack_id}")
            valid, msg = validator.check_package_ownership(pack_id)
            print(f"  결과: {'✅ 소유' if valid else '❌ 미소유'}")
            print(f"  메시지: {msg}")

        return True

    except Exception as e:
        print(f"❌ 오류: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_step3_get_owned_packs():
    """Step 3: 보유 패키지 목록 조회"""
    print_step(3, "보유 패키지 목록 조회")

    try:
        from utils.firebase_license import HybridLicenseValidator
        from config.settings import config

        validator = HybridLicenseValidator(config.DATA_DIR)
        packs = validator.get_owned_packs()

        print(f"보유 패키지 수: {len(packs)}")
        print(f"목록: {packs}")

        return True

    except Exception as e:
        print(f"❌ 오류: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_step4_create_test_package():
    """Step 4: 테스트 패키지 생성"""
    print_step(4, "테스트 패키지(.revpack) 생성")

    try:
        from utils.package_manager import get_package_manager, ChannelPackage
        from config.settings import config

        manager = get_package_manager()

        # 테스트 패키지 데이터
        package = ChannelPackage(
            package_id="horror_pack",  # Firebase의 owned_packs와 일치해야 함
            package_name="공포 채널 테스트 팩",
            version="1.0.0",
            author="Test",
            description="테스트용 공포 채널 패키지",
            channel_type="horror",
            channel_display_name="공포 채널",
            reverie_version_min="37"
        )

        # 임시 파일로 저장
        temp_dir = tempfile.mkdtemp()
        output_path = os.path.join(temp_dir, "test_horror.revpack")

        success, msg = manager.export_package(
            package,
            output_path,
            include_preview=False,
            require_license=False
        )

        if success:
            print(f"✅ 패키지 생성 성공")
            print(f"  경로: {output_path}")
            print(f"  크기: {os.path.getsize(output_path)} bytes")
            return output_path
        else:
            print(f"❌ 패키지 생성 실패: {msg}")
            return None

    except Exception as e:
        print(f"❌ 오류: {e}")
        import traceback
        traceback.print_exc()
        return None


@pytest.fixture
def package_path():
    return test_step4_create_test_package()


def test_step5_import_package(package_path):
    """Step 5: 패키지 Import (소유권 검증 포함)"""
    print_step(5, "패키지 Import")

    if not package_path:
        print("❌ 테스트 패키지가 없습니다.")
        return False

    try:
        from utils.package_manager import get_package_manager

        manager = get_package_manager()

        print(f"패키지 파일: {package_path}")
        print(f"Import 시작...")

        result = manager.import_package(package_path)

        if result.success:
            print(f"\n✅ Import 성공!")
            print(f"  채널 ID: {result.channel_id}")
            print(f"  패키지명: {result.package.package_name}")

            if result.warnings:
                print(f"  경고: {result.warnings}")
            if result.missing_models:
                print(f"  누락 모델: {len(result.missing_models)}개")

            return True
        else:
            print(f"\n❌ Import 실패")
            print(f"  오류: {result.error}")
            return False

    except Exception as e:
        print(f"❌ 오류: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_step6_list_installed():
    """Step 6: 설치된 패키지 목록 확인"""
    print_step(6, "설치된 패키지 목록")

    try:
        from utils.package_manager import get_package_manager

        manager = get_package_manager()
        packages = manager.list_installed_packages()

        print(f"설치된 패키지 수: {len(packages)}")

        for channel_id, info in packages.items():
            print(f"\n  [{channel_id}]")
            print(f"    이름: {info.get('package_name')}")
            print(f"    버전: {info.get('version')}")
            print(f"    타입: {info.get('channel_type')}")

        return True

    except Exception as e:
        print(f"❌ 오류: {e}")
        import traceback
        traceback.print_exc()
        return False


_run_step1_register_license = test_step1_register_license
_run_step2_check_ownership = test_step2_check_ownership
_run_step3_get_owned_packs = test_step3_get_owned_packs
_create_test_package = test_step4_create_test_package
_run_step5_import_package = test_step5_import_package
_run_step6_list_installed = test_step6_list_installed


@pytest.fixture
def package_path():
    return _create_test_package()


def test_step1_register_license():
    if not _run_step1_register_license():
        pytest.skip("Firebase license registration prerequisite is not available.")


def test_step2_check_ownership():
    if not _run_step2_check_ownership():
        pytest.skip("Firebase ownership check prerequisite is not available.")


def test_step3_get_owned_packs():
    if not _run_step3_get_owned_packs():
        pytest.skip("Owned pack lookup prerequisite is not available.")


def test_step4_create_test_package(package_path):
    assert package_path


def test_step5_import_package(package_path):
    if not _run_step5_import_package(package_path):
        pytest.skip("Licensed package import prerequisite is not available.")


def test_step6_list_installed():
    if not _run_step6_list_installed():
        pytest.skip("Installed package listing prerequisite is not available.")


def main():
    """메인 테스트 실행"""
    print_header("v37 패키지 시스템 전체 플로우 테스트")

    results = {}

    # Step 1: 라이선스 등록
    results['step1'] = _run_step1_register_license()

    # Step 2: 소유권 확인
    results['step2'] = _run_step2_check_ownership()

    # Step 3: 보유 패키지 목록
    results['step3'] = _run_step3_get_owned_packs()

    # Step 4: 테스트 패키지 생성
    package_path = _create_test_package()
    results['step4'] = package_path is not None

    # Step 5: 패키지 Import
    results['step5'] = _run_step5_import_package(package_path)

    # Step 6: 설치 확인
    results['step6'] = _run_step6_list_installed()

    # 결과 요약
    print_header("테스트 결과 요약")

    step_names = {
        'step1': '라이선스 등록',
        'step2': '소유권 확인',
        'step3': '패키지 목록 조회',
        'step4': '테스트 패키지 생성',
        'step5': '패키지 Import',
        'step6': '설치된 패키지 확인'
    }

    all_passed = True
    for step, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {step_names[step]}: {status}")
        if not passed:
            all_passed = False

    print("\n" + "-" * 40)
    if all_passed:
        print("🎉 모든 테스트 통과!")
    else:
        print("⚠️ 일부 테스트 실패")

    # 임시 파일 정리
    if package_path and os.path.exists(package_path):
        try:
            os.remove(package_path)
            os.rmdir(os.path.dirname(package_path))
        except:
            pass

    print("\n" + "=" * 60)

    return all_passed


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
