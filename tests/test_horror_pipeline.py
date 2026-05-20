#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""horror_v59 팩 전체 파이프라인 테스트"""
import sys, os
sys.path.insert(0, 'src')
sys.path.insert(0, 'lib')

from dotenv import dotenv_values
env = dotenv_values('.env')
for k, v in env.items():
    os.environ[k] = v

import config.settings_v2 as settings_module
if hasattr(settings_module, 'config'):
    settings_module.config.GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')

import time, traceback
from datetime import datetime

def log(msg):
    timestamp = datetime.now().strftime("%H:%M:%S")
    safe_msg = str(msg).encode('utf-8', errors='replace').decode('utf-8')
    try:
        print(f"[{timestamp}] {safe_msg}", flush=True)
    except UnicodeEncodeError:
        print(f"[{timestamp}] {msg.encode('ascii', errors='ignore').decode('ascii')}", flush=True)

def progress_callback(stage, percent): log(f"  [PROGRESS] {stage}: {percent}%")
def log_callback(msg): log(f"  [LOG] {msg}")

def main():
    log("=" * 60)
    log("horror_v59 전체 파이프라인 테스트")
    log("=" * 60)

    # 1. 팩 로드
    log("\n[Step 1] horror_v59 팩 로드...")
    try:
        from config import pack_config
        pack_config.load_pack('assets/packs/horror_v59.revpack')
        log(f"  팩 로드 완료: {pack_config.ACTIVE_PACK.pack_name}")
    except Exception as e:
        log(f"  [ERROR] 팩 로드 실패: {e}")
        traceback.print_exc()
        return False

    # 2. ScenarioPlanner
    log("\n[Step 2] ScenarioPlanner 초기화...")
    try:
        from modules_pro.scenario_planner import ScenarioPlanner, PromptMode
        planner = ScenarioPlanner(prompt_mode=PromptMode.ENHANCED)
        log("  완료")
    except Exception as e:
        log(f"  [ERROR] {e}")
        traceback.print_exc()
        return False

    # 3. 주제 생성
    log("\n[Step 3] 주제 생성...")
    try:
        topic = planner.get_auto_topic("horror", "horror")
        log(f"  주제: {topic}")
    except Exception as e:
        log(f"  [ERROR] {e}")
        traceback.print_exc()
        return False

    # 4. 기획안 생성
    log("\n[Step 4] 기획안 생성...")
    try:
        plan_data, json_path = planner.create_plan("horror", "horror", topic)
        log(f"  저장: {json_path}")
        log(f"  장면 수: {len(plan_data.get('script', []))}개")
    except Exception as e:
        log(f"  [ERROR] {e}")
        traceback.print_exc()
        return False

    # 5. MediaFactory
    log("\n[Step 5] MediaFactory 초기화...")
    try:
        from modules_pro.media_factory import MediaFactory
        from modules_pro.video_models import QualityPreset
        factory = MediaFactory(channel="horror", quality=QualityPreset.STANDARD)
        log("  완료")
    except Exception as e:
        log(f"  [ERROR] {e}")
        traceback.print_exc()
        return False

    # 6. 영상 제작
    log("\n[Step 6] 영상 제작 시작...")
    try:
        video_path = factory.produce_video_with_gui(
            json_path,
            thumbnail_callback=None,
            progress_callback=progress_callback,
            log_callback=log_callback
        )
        if video_path and os.path.exists(video_path):
            size_mb = os.path.getsize(video_path) / (1024*1024)
            log(f"\n[SUCCESS] 완료! {video_path} ({size_mb:.1f}MB)")
            return True
        else:
            log(f"\n[FAIL] 파일 없음")
            return False
    except Exception as e:
        log(f"  [ERROR] {e}")
        traceback.print_exc()
        return False

if __name__ == "__main__":
    start = time.time()
    success = main()
    elapsed = time.time() - start
    print(f"\n{'성공' if success else '실패'} (소요: {elapsed/60:.1f}분)", flush=True)
