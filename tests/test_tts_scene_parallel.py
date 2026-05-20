#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
v59.8.1 TTS + SceneAnalyzer 병렬 실행 테스트
SD 생성 없이 TTS와 SceneAnalyzer가 동시에 돌아가는지 검증
"""
import sys
import os
import time

sys.path.insert(0, 'src')
sys.path.insert(0, 'lib')

from dotenv import dotenv_values
env = dotenv_values('.env')
for k, v in env.items():
    os.environ[k] = v

import config.settings_v2 as settings_module
if hasattr(settings_module, 'config'):
    settings_module.config.GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')

from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

def log(msg):
    timestamp = datetime.now().strftime("%H:%M:%S")
    safe_msg = str(msg).encode('utf-8', errors='replace').decode('utf-8')
    try:
        print(f"[{timestamp}] {safe_msg}", flush=True)
    except UnicodeEncodeError:
        ascii_msg = safe_msg.encode('ascii', errors='ignore').decode('ascii')
        print(f"[{timestamp}] {ascii_msg}", flush=True)

def main():
    total_start = time.time()
    log("=" * 60)
    log("v59.8.1 TTS + SceneAnalyzer 병렬 테스트")
    log("=" * 60)

    # 1. 팩 로드
    log("\n[Step 1] 팩 로드...")
    from config import pack_config
    pack_config.load_pack('assets/packs/senior_makjang.revpack')
    log(f"  팩: {pack_config.ACTIVE_PACK.pack_name}")

    # 2. 시나리오 생성
    log("\n[Step 2] 시나리오 생성...")
    from modules_pro.scenario_planner import ScenarioPlanner, PromptMode
    planner = ScenarioPlanner(prompt_mode=PromptMode.ENHANCED)
    topic = planner.get_auto_topic("senior", "makjang")
    log(f"  주제: {topic}")

    plan_data, json_path = planner.create_senior_plan(topic, mode="makjang")
    script_list = plan_data.get('script_list', plan_data.get('script', []))
    log(f"  대본: {len(script_list)}줄")
    if not script_list:
        # JSON 파일에서 직접 로드
        import json
        with open(json_path, 'r', encoding='utf-8') as f:
            raw = json.load(f)
        script_list = raw.get('script_list', raw.get('script', []))
        log(f"  JSON 재로드: {len(script_list)}줄")

    # 3. MediaFactory 초기화
    log("\n[Step 3] MediaFactory 초기화...")
    from modules_pro.media_factory import MediaFactory
    from modules_pro.video_models import QualityPreset
    factory = MediaFactory(channel="senior", quality=QualityPreset.STANDARD)
    log("  초기화 완료")

    # ============================================================
    # 핵심 테스트: TTS와 SceneAnalyzer 동시 실행
    # ============================================================
    log("\n" + "=" * 60)
    log("[핵심 테스트] TTS + SceneAnalyzer 병렬 실행")
    log("=" * 60)

    # Gemini 초기화
    from utils.gemini_compat import configure_gemini, get_gemini_model, GEMINI_AVAILABLE
    gemini_key = os.environ.get('GEMINI_API_KEY', '')
    configure_gemini(gemini_key)
    gemini_model = get_gemini_model("auto")
    log(f"  Gemini: {getattr(gemini_model, 'model_name', 'unknown')}")

    from modules_pro.scene_analyzer import SceneAnalyzer
    log(f"  SceneAnalyzer workers: {SceneAnalyzer.PARALLEL_MAX_WORKERS}")

    # --- A: SceneAnalyzer 비동기 시작 ---
    scene_start = time.time()
    log(f"\n[A] SceneAnalyzer 비동기 시작 ({len(script_list)}개 대사, workers={SceneAnalyzer.PARALLEL_MAX_WORKERS})")

    scene_executor = ThreadPoolExecutor(max_workers=1)
    scene_future = scene_executor.submit(
        factory._pre_analyze_scenes, script_list, gemini_model, None
    )

    # --- B: TTS 시작 (동시 진행) ---
    tts_start = time.time()
    log(f"[B] TTS 시작 ({len(script_list)}줄)")

    project_name = f"test_parallel_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    audio_path, subtitle_data = factory._generate_voice_and_subtitles_v33(
        script_list, project_name, lambda msg, pct: log(f"  [TTS] {msg}: {pct}%")
    )
    tts_elapsed = time.time() - tts_start
    tts_count = len(subtitle_data) if subtitle_data else 0
    log(f"[B] TTS 완료: {tts_count}개 ({tts_elapsed:.1f}초)")

    # --- C: SceneAnalyzer 결과 수거 ---
    log(f"\n[C] SceneAnalyzer 결과 수거...")
    scene_cache = scene_future.result(timeout=1800)
    scene_elapsed = time.time() - scene_start
    scene_count = len(scene_cache) if scene_cache else 0
    log(f"[C] SceneAnalyzer 완료: {scene_count}개 ({scene_elapsed:.1f}초)")
    scene_executor.shutdown(wait=False)

    # --- 결과 분석 ---
    total_elapsed = time.time() - total_start

    log("\n" + "=" * 60)
    log("결과 분석")
    log("=" * 60)
    log(f"  TTS: {tts_elapsed:.1f}초 ({tts_count}개)")
    log(f"  SceneAnalyzer: {scene_elapsed:.1f}초 ({scene_count}개, workers={SceneAnalyzer.PARALLEL_MAX_WORKERS})")

    # 병렬 효과 계산
    sequential_time = tts_elapsed + scene_elapsed
    parallel_time = max(tts_elapsed, scene_elapsed)
    saved = sequential_time - parallel_time

    log(f"")
    log(f"  직렬 시 예상: {sequential_time:.1f}초")
    log(f"  병렬 실제:    {parallel_time:.1f}초")
    log(f"  절감:         {saved:.1f}초 ({saved/sequential_time*100:.0f}%)")
    log(f"")
    log(f"  총 소요: {total_elapsed:.1f}초 ({total_elapsed/60:.1f}분)")

    if scene_cache and audio_path:
        log(f"\n[SUCCESS] 테스트 성공!")
        # 샘플 출력
        sample = scene_cache.get(0)
        if sample:
            log(f"  샘플 scene_0: action={getattr(sample, 'image_action', '?')}, "
                f"sd_prompt={getattr(sample, 'sd_prompt', '?')[:60]}...")
        return True
    else:
        log(f"\n[FAIL] 테스트 실패")
        return False

if __name__ == "__main__":
    success = main()
    print("\n" + "=" * 60, flush=True)
    print(f"{'성공' if success else '실패'}!", flush=True)
    print("=" * 60, flush=True)
