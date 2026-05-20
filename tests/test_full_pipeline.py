#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
v58 전체 파이프라인 테스트 스크립트
시니어 막장 팩 + 자동 주제 생성 + 전체 영상 제작
"""
import sys
import os

# 경로 설정
sys.path.insert(0, 'src')
sys.path.insert(0, 'lib')

# 환경변수 로드
from dotenv import dotenv_values
env = dotenv_values('.env')
for k, v in env.items():
    os.environ[k] = v

# config에도 직접 설정
import config.settings_v2 as settings_module
if hasattr(settings_module, 'config'):
    settings_module.config.GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')

import time
import traceback
from datetime import datetime

def log(msg):
    """타임스탬프 로깅 (이모지 안전)"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    # Windows cp949 인코딩 에러 방지
    safe_msg = str(msg).encode('utf-8', errors='replace').decode('utf-8')
    try:
        print(f"[{timestamp}] {safe_msg}", flush=True)
    except UnicodeEncodeError:
        # 이모지 등 특수문자 제거
        ascii_msg = safe_msg.encode('ascii', errors='ignore').decode('ascii')
        print(f"[{timestamp}] {ascii_msg}", flush=True)

def progress_callback(stage, percent):
    """진행률 콜백"""
    log(f"  [PROGRESS] {stage}: {percent}%")

def log_callback(msg):
    """로그 콜백"""
    log(f"  [LOG] {msg}")

def main():
    log("=" * 60)
    log("v58 전체 파이프라인 테스트 시작")
    log("팩: senior_touching.revpack")
    log("=" * 60)

    # 1. 팩 로드
    log("\n[Step 1] 팩 로드...")
    try:
        from config import pack_config
        pack_config.load_pack('assets/packs/senior_touching.revpack')
        log(f"  팩 로드 완료: {pack_config.ACTIVE_PACK.pack_name}")
        log(f"  narrator: {pack_config.ACTIVE_PACK.tts.narrator}")
        log(f"  bgm_folder: {pack_config.ACTIVE_PACK.assets.bgm_folder}")
    except Exception as e:
        log(f"  [ERROR] 팩 로드 실패: {e}")
        traceback.print_exc()
        return False

    # 2. ScenarioPlanner 초기화
    log("\n[Step 2] ScenarioPlanner 초기화...")
    try:
        from modules_pro.scenario_planner import ScenarioPlanner, PromptMode

        planner = ScenarioPlanner(prompt_mode=PromptMode.ENHANCED)
        log("  ScenarioPlanner 초기화 완료")
    except Exception as e:
        log(f"  [ERROR] ScenarioPlanner 초기화 실패: {e}")
        traceback.print_exc()
        return False

    # 3. 자동 주제 생성
    log("\n[Step 3] 자동 주제 생성...")
    try:
        topic = planner.get_auto_topic("senior", "makjang")
        log(f"  생성된 주제: {topic}")
    except Exception as e:
        log(f"  [ERROR] 주제 생성 실패: {e}")
        traceback.print_exc()
        return False

    # 4. 기획안 생성
    log("\n[Step 4] 기획안(대본) 생성...")
    try:
        plan_data, json_path = planner.create_senior_plan(topic, mode="makjang")
        log(f"  기획안 저장: {json_path}")
        log(f"  장면 수: {len(plan_data.get('script', []))}개")
        log(f"  제목: {plan_data.get('title', 'N/A')}")
    except Exception as e:
        log(f"  [ERROR] 기획안 생성 실패: {e}")
        traceback.print_exc()
        return False

    # 5. MediaFactory로 영상 제작
    log("\n[Step 5] MediaFactory 초기화...")
    try:
        from modules_pro.media_factory import MediaFactory
        from modules_pro.video_models import QualityPreset

        factory = MediaFactory(channel="senior", quality=QualityPreset.STANDARD)
        log("  MediaFactory 초기화 완료")
    except Exception as e:
        log(f"  [ERROR] MediaFactory 초기화 실패: {e}")
        traceback.print_exc()
        return False

    # 6. 영상 제작
    log("\n[Step 6] 영상 제작 시작...")
    log("  (TTS → 이미지 → 렌더링 순서로 진행)")
    try:
        video_path = factory.produce_video_with_gui(
            json_path,
            thumbnail_callback=None,
            progress_callback=progress_callback,
            log_callback=log_callback
        )

        if video_path and os.path.exists(video_path):
            file_size = os.path.getsize(video_path) / (1024 * 1024)  # MB
            log(f"\n[SUCCESS] 영상 제작 완료!")
            log(f"  출력 파일: {video_path}")
            log(f"  파일 크기: {file_size:.1f} MB")
            return True
        else:
            log(f"\n[FAIL] 영상 제작 실패 - 파일 없음")
            return False

    except Exception as e:
        log(f"  [ERROR] 영상 제작 중 오류: {e}")
        traceback.print_exc()
        return False

if __name__ == "__main__":
    start_time = time.time()
    success = main()
    elapsed = time.time() - start_time

    print("\n" + "=" * 60, flush=True)
    if success:
        print(f"테스트 성공! (소요 시간: {elapsed/60:.1f}분)", flush=True)
    else:
        print(f"테스트 실패 - 로그를 확인하세요 (소요 시간: {elapsed/60:.1f}분)", flush=True)
    print("=" * 60, flush=True)
