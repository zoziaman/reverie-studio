# -*- coding: utf-8 -*-
"""
ReveriePack Pipeline Test Script
v57.7.6: 팩 로드 → 시나리오 생성 → 영상 생성 테스트
"""
import sys
import io
import os

# UTF-8 인코딩 설정
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
os.environ['PYTHONIOENCODING'] = 'utf-8'

# 경로 설정
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, 'src'))
sys.path.insert(0, os.path.join(BASE_DIR, 'lib'))

import json
from datetime import datetime


def test_pack_load():
    """팩 로드 테스트"""
    print("\n=== 1. Pack Load Test ===")
    from config.pack_config import ACTIVE_PACK, load_pack

    pack_path = os.path.join(BASE_DIR, 'data', 'exports', '소름돋는_실화_괴담.revpack')
    if not os.path.exists(pack_path):
        print(f"  [ERROR] Pack not found: {pack_path}")
        return False

    result = load_pack(pack_path)
    print(f"  Load result: {result}")
    print(f"  Pack name: {ACTIVE_PACK.pack_name}")
    print(f"  Genre: {ACTIVE_PACK.genre}")
    print(f"  Character config: {ACTIVE_PACK.character_config}")

    # audio_config 확인
    if hasattr(ACTIVE_PACK, 'assets'):
        assets = ACTIVE_PACK.assets
        print(f"  BGM channel: {getattr(assets, 'use_channel_bgm', 'N/A')}")
        print(f"  TTS channel: {getattr(assets, 'use_channel_tts', 'N/A')}")
        print(f"  SFX channel: {getattr(assets, 'use_channel_sfx', 'N/A')}")

    return result


def test_scenario_create():
    """시나리오 생성 테스트"""
    print("\n=== 2. Scenario Creation Test ===")
    from modules_pro.scenario_planner import ScenarioPlanner
    from config.pack_config import ACTIVE_PACK

    planner = ScenarioPlanner()

    topic = "폐교에서 들리는 발자국 소리"
    category = "horror"
    print(f"  Topic: {topic}")
    print(f"  Category: {category}")
    print("  Creating scenario... (1-2 min)")

    try:
        plan_data, _ = planner.create_plan(category=category, mode='', topic=topic)

        # v57.7.6: scenario_planner는 'script_list' 반환, 'scenes'가 아님
        if plan_data and 'script_list' in plan_data:
            script_list = plan_data['script_list']
            print(f"  [OK] Script created: {len(script_list)} turns")

            # 저장
            output_path = os.path.join(BASE_DIR, 'data', 'test_plan.json')
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(plan_data, f, ensure_ascii=False, indent=2)
            print(f"  Saved: {output_path}")

            # 첫 장면 확인
            if script_list:
                s = script_list[0]
                print(f"  First turn role: {s.get('role', '?')}")
                print(f"  First turn emotion: {s.get('emotion', '?')}")
                print(f"  First turn voice_type: {s.get('voice_type', '?')}")

            # 감정 분포 확인
            emotions = {}
            for turn in script_list:
                emo = turn.get('emotion', 'unknown')
                emotions[emo] = emotions.get(emo, 0) + 1
            print(f"  Emotion distribution: {emotions}")

            return plan_data
        else:
            print(f"  [FAIL] No script_list in plan")
            print(f"  Available keys: {list(plan_data.keys()) if plan_data else 'None'}")
            return None
    except Exception as e:
        print(f"  [ERROR] {e}")
        import traceback
        traceback.print_exc()
        return None


def test_media_generation(plan_data):
    """미디어 생성 테스트 (TTS + 이미지)"""
    print("\n=== 3. Media Generation Test ===")

    # v57.7.6: 'script_list'를 사용
    if not plan_data or 'script_list' not in plan_data:
        print("  [SKIP] No plan data")
        return False

    # 첫 3개 턴만 테스트
    test_scenes = plan_data['script_list'][:3]
    print(f"  Testing {len(test_scenes)} turns...")

    from modules_pro.media_factory import MediaFactory
    from config.pack_config import ACTIVE_PACK

    # MediaFactory 초기화
    factory = MediaFactory()

    # 테스트 출력 폴더
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = os.path.join(BASE_DIR, 'data', 'output', f'test_{timestamp}')
    os.makedirs(output_dir, exist_ok=True)
    print(f"  Output dir: {output_dir}")

    results = {
        'tts_success': 0,
        'tts_fail': 0,
        'image_success': 0,
        'image_fail': 0,
    }

    for i, scene in enumerate(test_scenes):
        print(f"\n  --- Scene {i+1} ---")
        print(f"    Role: {scene.get('role', '?')}")
        print(f"    Emotion: {scene.get('emotion', '?')}")
        print(f"    Voice: {scene.get('voice_type', '?')}")
        dialogue = scene.get('dialogue', '')[:50]
        print(f"    Dialogue: {dialogue}...")

        # TTS 테스트
        try:
            tts_path = os.path.join(output_dir, f'tts_{i+1}.wav')
            # TTS 생성 호출
            tts_result = factory.generate_tts(
                text=scene.get('dialogue', '테스트'),
                voice_type=scene.get('voice_type', 'narrator'),
                emotion=scene.get('emotion', 'calm'),
                output_path=tts_path
            )
            if tts_result and os.path.exists(tts_path):
                results['tts_success'] += 1
                print(f"    [TTS OK] {tts_path}")
            else:
                results['tts_fail'] += 1
                print(f"    [TTS FAIL]")
        except Exception as e:
            results['tts_fail'] += 1
            print(f"    [TTS ERROR] {e}")

        # 이미지 테스트
        try:
            image_path = os.path.join(output_dir, f'image_{i+1}.png')
            prompt = scene.get('image_prompt', 'abandoned school hallway')
            image_result = factory.generate_image(
                prompt=prompt,
                output_path=image_path
            )
            if image_result and os.path.exists(image_path):
                results['image_success'] += 1
                print(f"    [IMG OK] {image_path}")
            else:
                results['image_fail'] += 1
                print(f"    [IMG FAIL]")
        except Exception as e:
            results['image_fail'] += 1
            print(f"    [IMG ERROR] {e}")

    print(f"\n  === Results ===")
    print(f"  TTS: {results['tts_success']}/{len(test_scenes)} success")
    print(f"  Image: {results['image_success']}/{len(test_scenes)} success")

    return results


def main():
    print("=" * 50)
    print("ReveriePack Pipeline Test")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)

    # 1. 팩 로드
    pack_ok = test_pack_load()
    if not pack_ok:
        print("\n[ABORT] Pack load failed")
        return

    # 2. 시나리오 생성
    plan_data = test_scenario_create()
    if not plan_data:
        print("\n[ABORT] Scenario creation failed")
        return

    # 3. 미디어 생성 (선택적)
    print("\n=== Media Generation ===")
    print("Skipping media generation for quick test.")
    print("Run with --full flag for complete pipeline test.")

    print("\n" + "=" * 50)
    print("TEST COMPLETE")
    print("=" * 50)


if __name__ == '__main__':
    main()
