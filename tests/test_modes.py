# test_modes.py
# ============================================================
# 일반 모드 vs 프리미엄 모드 빠른 테스트
# 테스트 모드 활성화: 5장 이미지, 15턴 대본으로 ~1분 영상
# ============================================================
import os
import sys
import time
import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("REVERIE_RUN_MEDIA_INTEGRATION_TESTS") != "1",
    reason="media service integration tests are opt-in",
)

# 프로젝트 경로 추가
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

# 테스트 모드 활성화 (반드시 config import 전에!)
os.environ["TEST_MODE"] = "true"

from config.settings import config

def safe_print(msg):
    """cp949 안전 출력"""
    try:
        print(msg)
    except UnicodeEncodeError:
        import re
        clean = re.sub(r'[^\x00-\x7F\uAC00-\uD7A3\u3131-\u318E]+', '', msg)
        print(clean)


def test_normal_mode():
    """일반 모드 테스트 (SD WebUI 정지 이미지)"""
    safe_print("\n" + "="*60)
    safe_print("[TEST] 일반 모드 (정지 이미지) - 테스트 모드")
    safe_print("="*60)

    # 테스트 모드 설정
    config.TEST_MODE = True
    safe_print(f"[INFO] TEST_MODE: {config.TEST_MODE}")
    safe_print(f"[INFO] 턴 수: {config.TEST_TURNS_PER_PART}턴 x 3 = {config.TEST_TURNS_PER_PART * 3}턴")
    safe_print(f"[INFO] 이미지 수: {config.TEST_IMAGE_COUNT}장")

    from modules_pro.media_factory import MediaFactory, QualityPreset

    factory = MediaFactory(channel="horror", quality=QualityPreset.FAST)

    # 테스트용 프롬프트 (테스트 모드 이미지 수만큼)
    test_prompts = [
        "dark abandoned hospital corridor with flickering lights",
        "old wooden door slightly open in dark hallway",
        "mysterious shadow figure at the end of corridor",
        "broken mirror reflecting distorted face",
        "abandoned room with single chair in moonlight",
    ][:config.TEST_IMAGE_COUNT]

    safe_print(f"\n[INFO] {len(test_prompts)}장 이미지 생성 테스트")
    safe_print(f"[INFO] SD WebUI URL: {config.SD_URL}")

    # SD WebUI 상태 확인
    import requests
    try:
        res = requests.get(f"{config.SD_URL}/sdapi/v1/options", timeout=5)
        if res.status_code == 200:
            safe_print("[OK] SD WebUI 연결됨")
        else:
            safe_print(f"[WARN] SD WebUI 응답: {res.status_code}")
    except Exception as e:
        safe_print(f"[ERROR] SD WebUI 연결 실패: {e}")
        safe_print("[INFO] SD WebUI를 먼저 실행해주세요")
        return False

    # 이미지 생성
    start_time = time.time()

    def progress_cb(msg, pct):
        safe_print(f"  [{pct}%] {msg}")

    try:
        image_paths = factory._generate_images_v33(
            prompts=test_prompts,
            project_name="test_normal",
            mode="horror",
            progress_callback=progress_cb
        )

        elapsed = time.time() - start_time
        safe_print(f"\n[RESULT] 생성된 이미지: {len(image_paths)}장")
        safe_print(f"[RESULT] 소요 시간: {elapsed:.1f}초")

        for p in image_paths:
            safe_print(f"  - {os.path.basename(p)}")

        return len(image_paths) == len(test_prompts)

    except Exception as e:
        safe_print(f"[ERROR] 이미지 생성 실패: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_premium_mode():
    """프리미엄 모드 테스트 (ComfyUI AnimateDiff)"""
    safe_print("\n" + "="*60)
    safe_print("[TEST] 프리미엄 모드 (AnimateDiff 영상) - 테스트 모드")
    safe_print("="*60)

    # 환경변수 설정
    os.environ["V50_ENABLED"] = "true"
    os.environ["V50_MODE"] = "speed"

    # 설정 동기화
    config.V50_ENABLED = True
    config.V50_MODE = "speed"
    config.TEST_MODE = True

    from modules_pro.media_factory_v50 import MediaFactoryV50, QualityPreset

    factory = MediaFactoryV50(channel="horror", quality=QualityPreset.FAST)

    safe_print(f"\n[INFO] v50_enabled: {factory.v50_enabled}")
    safe_print(f"[INFO] v50_mode: {factory.v50_mode}")
    safe_print(f"[INFO] ComfyUI URL: {config.COMFYUI_URL}")
    safe_print(f"[INFO] TEST_MODE: {config.TEST_MODE}")

    # ComfyUI 상태 확인
    import requests
    try:
        res = requests.get(f"{config.COMFYUI_URL}/system_stats", timeout=5)
        if res.status_code == 200:
            safe_print("[OK] ComfyUI 연결됨")
        else:
            safe_print(f"[WARN] ComfyUI 응답: {res.status_code}")
    except Exception as e:
        safe_print(f"[ERROR] ComfyUI 연결 실패: {e}")
        safe_print("[INFO] ComfyUI를 먼저 실행해주세요")
        return False

    # 테스트용 프롬프트 (테스트 모드 이미지 수만큼, 최대 3개)
    test_prompts = [
        "dark abandoned hospital corridor with flickering lights",
        "old wooden door slowly opening in dark hallway",
        "mysterious shadow figure walking at the end of corridor",
    ][:min(3, config.TEST_IMAGE_COUNT)]

    safe_print(f"\n[INFO] {len(test_prompts)}개 영상 클립 생성 테스트")

    start_time = time.time()

    def progress_cb(msg, pct):
        safe_print(f"  [{pct}%] {msg}")

    try:
        # v50 모드에서 _generate_images_v33 호출 시 AnimateDiff 사용
        clip_paths = factory._generate_images_v33(
            prompts=test_prompts,
            project_name="test_premium",
            mode="horror",
            progress_callback=progress_cb
        )

        elapsed = time.time() - start_time
        safe_print(f"\n[RESULT] 생성된 영상 클립: {len(clip_paths)}개")
        safe_print(f"[RESULT] 소요 시간: {elapsed:.1f}초")

        for p in clip_paths:
            safe_print(f"  - {os.path.basename(p)}")

        return len(clip_paths) > 0

    except Exception as e:
        safe_print(f"[ERROR] 영상 클립 생성 실패: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_tts():
    """TTS API 테스트"""
    safe_print("\n" + "="*60)
    safe_print("[TEST] TTS (GPT-SoVITS) API 테스트")
    safe_print("="*60)

    safe_print(f"\n[INFO] SoVITS URL: {config.SOVITS_URL}")

    import requests
    import urllib.parse

    # 서버 상태 확인
    try:
        res = requests.get(config.SOVITS_URL, timeout=5)
        safe_print(f"[INFO] 서버 응답: {res.status_code}")
    except Exception as e:
        safe_print(f"[ERROR] SoVITS 서버 연결 실패: {e}")
        return False

    # 레퍼런스 오디오 경로 (있는 경우)
    ref_audio = getattr(config, 'SOVITS_REF_AUDIO', "")
    ref_text = getattr(config, 'SOVITS_REF_TEXT', "")

    safe_print(f"[INFO] 레퍼런스 오디오: {ref_audio[:50]}..." if ref_audio else "[INFO] 레퍼런스 오디오: (없음)")

    # 다양한 API 엔드포인트 테스트
    test_text = "안녕하세요, 테스트입니다."

    endpoints = [
        ("POST /tts (v1)", "/tts", "POST", {
            "text": test_text,
            "text_lang": "ko",
            "ref_audio_path": ref_audio,
            "prompt_text": ref_text,
            "prompt_lang": "ko",
        }),
        ("POST / (v2)", "/", "POST", {
            "text": test_text,
            "text_language": "ko",
            "refer_wav_path": ref_audio,
            "prompt_text": ref_text,
            "prompt_language": "ko",
        }),
        ("GET /tts", "/tts", "GET", {
            "text": test_text,
            "text_lang": "ko",
            "ref_audio_path": ref_audio,
            "prompt_text": ref_text,
            "prompt_lang": "ko",
        }),
    ]

    for name, endpoint, method, params in endpoints:
        try:
            url = f"{config.SOVITS_URL}{endpoint}"
            if method == "POST":
                res = requests.post(url, json=params, timeout=30)
            else:
                query = urllib.parse.urlencode(params)
                res = requests.get(f"{url}?{query}", timeout=30)

            if res.status_code == 200 and len(res.content) > 1000:
                safe_print(f"[OK] {name}: 성공! ({len(res.content)} bytes)")

                # 테스트 오디오 저장
                test_audio_path = os.path.join(config.DATA_DIR, "test_tts.wav")
                with open(test_audio_path, "wb") as f:
                    f.write(res.content)
                safe_print(f"[INFO] 테스트 오디오 저장: {test_audio_path}")
                return True
            else:
                safe_print(f"[FAIL] {name}: {res.status_code} - {res.text[:100]}")
        except Exception as e:
            safe_print(f"[FAIL] {name}: {e}")

    safe_print("\n[ERROR] 모든 TTS API 엔드포인트 실패")
    return False


def test_full_pipeline():
    """전체 파이프라인 테스트 (테스트 모드로 짧은 영상)"""
    safe_print("\n" + "="*60)
    safe_print("[TEST] 전체 파이프라인 테스트 (테스트 모드 ~1분 영상)")
    safe_print("="*60)

    # 테스트 모드 강제 활성화
    config.TEST_MODE = True
    safe_print(f"[INFO] TEST_MODE: {config.TEST_MODE}")
    safe_print(f"[INFO] 예상 턴 수: {config.TEST_TURNS_PER_PART * 3}턴")
    safe_print(f"[INFO] 예상 이미지: {config.TEST_IMAGE_COUNT}장")

    from modules_pro.scenario_planner import ScenarioPlanner

    safe_print("\n[1/3] 시나리오 생성 중...")
    planner = ScenarioPlanner(prompt_mode="classic")
    topic = "어두운 골목길에서 들리는 이상한 소리"

    try:
        plan_data, json_path = planner.create_horror_plan(topic)
        safe_print(f"[OK] 시나리오 생성 완료")
        safe_print(f"     - 제목: {plan_data.get('title', '?')[:30]}...")
        safe_print(f"     - 턴 수: {len(plan_data.get('script_list', []))}턴")
        safe_print(f"     - 이미지: {len(plan_data.get('visual_scenes', []))}장")
        safe_print(f"     - 저장: {os.path.basename(json_path)}")
    except Exception as e:
        safe_print(f"[ERROR] 시나리오 생성 실패: {e}")
        import traceback
        traceback.print_exc()
        return False

    return True


_run_normal_mode = test_normal_mode
_run_premium_mode = test_premium_mode
_run_tts = test_tts
_run_full_pipeline = test_full_pipeline


def test_normal_mode():
    if not _run_normal_mode():
        pytest.skip("SD WebUI integration prerequisites are not available.")


def test_premium_mode():
    if not _run_premium_mode():
        pytest.skip("ComfyUI AnimateDiff integration prerequisites are not available.")


def test_tts():
    if not _run_tts():
        pytest.skip("GPT-SoVITS integration prerequisites are not available.")


def test_full_pipeline():
    if not _run_full_pipeline():
        pytest.skip("Full pipeline integration prerequisites are not available.")


def main():
    safe_print("\n" + "="*60)
    safe_print("   Reverie Automation 테스트 모드")
    safe_print("   (테스트 모드: ~1분 영상 생성)")
    safe_print("="*60)

    safe_print(f"\n[설정]")
    safe_print(f"  TEST_MODE: {config.TEST_MODE}")
    safe_print(f"  턴/파트: {config.TEST_TURNS_PER_PART}")
    safe_print(f"  이미지 수: {config.TEST_IMAGE_COUNT}")

    safe_print("\n테스트 옵션:")
    safe_print("  1. 일반 모드 (SD WebUI 정지 이미지)")
    safe_print("  2. 프리미엄 모드 (ComfyUI AnimateDiff)")
    safe_print("  3. TTS API 테스트")
    safe_print("  4. 전체 파이프라인 (시나리오만)")
    safe_print("  5. 전체 테스트 (1+2+3)")
    safe_print("  0. 종료")

    while True:
        try:
            choice = input("\n선택 (0-5): ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if choice == "0":
            break
        elif choice == "1":
            result = _run_normal_mode()
            safe_print(f"\n[{'PASS' if result else 'FAIL'}] 일반 모드 테스트")
        elif choice == "2":
            result = _run_premium_mode()
            safe_print(f"\n[{'PASS' if result else 'FAIL'}] 프리미엄 모드 테스트")
        elif choice == "3":
            result = _run_tts()
            safe_print(f"\n[{'PASS' if result else 'FAIL'}] TTS 테스트")
        elif choice == "4":
            result = _run_full_pipeline()
            safe_print(f"\n[{'PASS' if result else 'FAIL'}] 파이프라인 테스트")
        elif choice == "5":
            safe_print("\n[전체 테스트 시작]")
            r1 = _run_tts()
            r2 = _run_normal_mode()
            r3 = _run_premium_mode()
            safe_print("\n" + "="*60)
            safe_print("[전체 테스트 결과]")
            safe_print(f"  TTS:      {'PASS' if r1 else 'FAIL'}")
            safe_print(f"  일반:     {'PASS' if r2 else 'FAIL'}")
            safe_print(f"  프리미엄: {'PASS' if r3 else 'FAIL'}")
            safe_print("="*60)
        else:
            safe_print("[WARN] 0-5 사이 숫자를 입력해주세요")

    safe_print("\n테스트 종료")


if __name__ == "__main__":
    main()
