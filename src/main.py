# src/main.py (v31.2 FIXED - Enhanced Quality Gate)
# -*- coding: utf-8 -*-

# v58.2: 라이브러리 FutureWarning 숨기기
import os
os.environ["PYTHONWARNINGS"] = "ignore::FutureWarning"
import warnings
warnings.filterwarnings("ignore", category=FutureWarning)

import sys
import time
import gc
import re
import subprocess
from typing import Dict, Any, Tuple, Optional

from utils.console_utils import configure_utf8_stdio

# v60.1.0: _sanitize_for_path를 pipeline_utils 정식 버전으로 통합
from pipeline.pipeline_utils import sanitize_for_path as _sanitize_for_path

# Windows 콘솔 UTF-8 설정
configure_utf8_stdio()

from modules_pro.scenario_planner import ScenarioPlanner
from modules_pro.media_factory import MediaFactory
from utils.youtube_uploader import YouTubeUploader
from config.settings import config


def clean_factory():
    print("\n🧹 [공장 대청소] 가동 중...")
    targets = [
        os.path.join(config.DATA_DIR, "temp_audio"),
        os.path.join(config.DATA_DIR, "temp_images"),
        os.path.join(config.DATA_DIR, "scripts")
    ]
    import shutil
    for t in targets:
        if os.path.exists(t):
            shutil.rmtree(t)
            os.makedirs(t, exist_ok=True)
    print("✨ 깨끗해졌습니다!")


# =========================================================
# ✅ 업로드 전 Quality Gate (강화 버전)
# =========================================================
def _probe_duration_seconds(video_path: str) -> Optional[float]:
    """
    ffprobe로 영상 길이를 초 단위로 얻음.
    v60.1.0: config.FFMPEG_PATH에서 ffprobe 경로 유도 (시스템 PATH 4.3.2 방지)
    """
    try:
        from pipeline.pipeline_utils import get_ffprobe_path
        ffprobe = get_ffprobe_path()
        cmd = [
            ffprobe, "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            video_path
        ]
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True).strip()
        return float(out)
    except Exception:
        return None


def _quality_gate(video_path: str, plan_data: Dict[str, Any]) -> Tuple[bool, str]:
    """
    ✅ 수정 3: 검증 항목 추가
    - 영상 길이 (8~25분)
    - 대본 턴 수 (최소 50턴)
    - 썸네일 존재
    - 이미지 폴더 체크 (생성 실패 감지)
    - 오디오 파일 체크
    """
    MIN_MINUTES = 8
    MAX_MINUTES = 25
    MIN_SCRIPT_TURNS = 50

    # 1. 영상 파일 존재 확인
    if not video_path or not os.path.exists(video_path):
        return False, "영상 파일이 존재하지 않습니다."

    # 2. 영상 길이 체크
    dur = _probe_duration_seconds(video_path)
    if dur is None:
        return True, "ffprobe 미사용 환경(길이 체크 생략)"

    minutes = dur / 60.0
    if minutes < MIN_MINUTES:
        return False, f"영상 길이가 너무 짧음: {minutes:.1f}분 (< {MIN_MINUTES}분)"
    if minutes > MAX_MINUTES:
        return False, f"영상 길이가 너무 김: {minutes:.1f}분 (> {MAX_MINUTES}분)"

    # 3. 대본 턴 수 체크
    script_list = plan_data.get("script_list", []) if isinstance(plan_data, dict) else []
    if isinstance(script_list, list) and len(script_list) < MIN_SCRIPT_TURNS:
        return False, f"대본 턴 수가 너무 적음: {len(script_list)} (최소 {MIN_SCRIPT_TURNS}턴)"

    # 4. 썸네일 존재 확인 (v57.7.6: 방어적 sanitize)
    project = plan_data.get("project_name", "")
    safe_project = _sanitize_for_path(project)
    thumb_real = os.path.join(config.DATA_DIR, "thumbnails", f"{safe_project}_REAL.jpg")
    thumb_art = os.path.join(config.DATA_DIR, "thumbnails", f"{safe_project}_ART.jpg")
    if not (os.path.exists(thumb_real) or os.path.exists(thumb_art)):
        return False, "썸네일 파일이 없습니다."

    # ✅ 5. 이미지 폴더 체크 (생성 실패 감지)
    temp_images_dir = os.path.join(config.DATA_DIR, "temp_images", safe_project)
    if os.path.exists(temp_images_dir):
        image_files = [f for f in os.listdir(temp_images_dir) if f.endswith(('.png', '.jpg'))]
        if len(image_files) < 10:  # 최소 10장은 있어야 정상
            return False, f"이미지 생성 부족: {len(image_files)}장 (최소 10장)"
    
    # ✅ 6. 오디오 파일 체크
    temp_audio_dir = os.path.join(config.DATA_DIR, "temp_audio", safe_project)
    if os.path.exists(temp_audio_dir):
        full_audio = os.path.join(temp_audio_dir, "full.wav")
        if not os.path.exists(full_audio):
            return False, "통합 오디오 파일이 생성되지 않았습니다."
        
        # 오디오 파일 크기 체크 (너무 작으면 실패로 간주)
        audio_size = os.path.getsize(full_audio)
        if audio_size < 100000:  # 100KB 미만이면 비정상
            return False, f"오디오 파일 크기 비정상: {audio_size} bytes"

    return True, f"✅ 통과 ({minutes:.1f}분, {len(script_list)}턴)"


def process_one_topic(category: str, count: int, mode: str = ""):
    from config.pack_config import load_pack_by_id

    pack_id = f"{category}_{mode}" if mode else category
    if not load_pack_by_id(pack_id):
        print(f"🚨 팩 로드 실패: {pack_id}")
        return

    planner = ScenarioPlanner()

    for i in range(count):
        print(f"\n==========================================")
        print(f"🏭 [{category}:{mode}] {i+1}/{count} 번째 생산 시작")
        print(f"==========================================")

        factory = MediaFactory(channel=category)
        uploader = YouTubeUploader(channel_name=category)

        try:
            # 1) 기획
            topic = planner.get_auto_topic(category, mode)
            print(f"\n🚀 [작업 시작] 주제: '{topic}'")

            if category == "horror":
                plan_data, json_path = planner.create_horror_plan(topic)
            else:
                plan_data, json_path = planner.create_senior_plan(topic, mode=mode)

            # 2) 제작
            video_path = factory.produce_video(json_path)
            if not video_path:
                print("🚨 영상 제작 실패. 다음으로 넘어갑니다.")
                continue

            # 3) 업로드 전 Quality Gate (강화 버전)
            ok, reason = _quality_gate(video_path, plan_data)
            if not ok:
                print(f"⛔ [업로드 차단] {reason}")
                print("   💡 팁: 재생성하거나 설정을 조정해보세요.")
                continue
            else:
                print(f"✅ [업로드 준비] {reason}")

            # 4) 업로드 (v57.7.6: 방어적 sanitize)
            safe_project_name = _sanitize_for_path(plan_data['project_name'])
            thumb_path = os.path.join(config.DATA_DIR, "thumbnails", f"{safe_project_name}_REAL.jpg")
            if not os.path.exists(thumb_path):
                thumb_path = os.path.join(config.DATA_DIR, "thumbnails", f"{safe_project_name}_ART.jpg")

            video_title = uploader.generate_title(
                plan_data.get("thumbnail_title", ""),
                plan_data.get("title", topic),
            )
            video_description = uploader.generate_description(
                plan_data.get("title", topic),
                plan_data.get("tags", []),
                channel_mode=mode or category,
            )
            video_tags = plan_data.get("tags", [])
            if isinstance(video_tags, str):
                video_tags = [t.strip() for t in video_tags.split(",") if t.strip()]

            uploader.upload_video(
                video_path=video_path,
                title=video_title,
                description=video_description,
                tags=video_tags,
                privacy="private",
                thumbnail_path=thumb_path if os.path.exists(thumb_path) else None,
                contains_synthetic_media=True,
                verified_true_story=bool(plan_data.get("verified_true_story", False)),
                channel_mode=mode or category,
            )

        except Exception as e:
            print(f"🚨 공정 오류: {e}")
            import traceback
            traceback.print_exc()

        finally:
            print("\n🧊 [시스템] 정리 및 쿨링...")
            try:
                del factory
                del uploader
            except Exception:
                pass
            gc.collect()
            time.sleep(8)


def main():
    print("============================================")
    print("🏭 [Reverie Automation] 통합 무인 공장 v31.2")
    print(f"📍 저장소: {config.BASE_DIR}")
    print("============================================")

    while True:
        print("\n0. 🧹 청소 | 1. 👻 공포 | 2. 👵 감동 | 3. 🔥 막장 | 4. 🚀 멀티배치 | q. 종료")
        choice = input("👉 선택: ").strip()

        if choice == 'q':
            break

        if choice == '0':
            clean_factory()

        elif choice == '1':
            process_one_topic("horror", 1)

        elif choice == '2':
            process_one_topic("senior", 1, mode="touching")

        elif choice == '3':
            process_one_topic("senior", 1, mode="makjang")

        elif choice == '4':
            print("\n📊 [멀티 배치 설정] 생산 수량을 입력하세요.")
            try:
                h_cnt = int(input("👻 공포 채널 개수: "))
                s_t_cnt = int(input("👵 시니어 감동 개수: "))
                s_m_cnt = int(input("🔥 시니어 막장 개수: "))

                if h_cnt > 0:
                    process_one_topic("horror", h_cnt)
                if s_t_cnt > 0:
                    process_one_topic("senior", s_t_cnt, mode="touching")
                if s_m_cnt > 0:
                    process_one_topic("senior", s_m_cnt, mode="makjang")

                print("\n🎉 [멀티 배치] 모든 작업이 완료되었습니다!")
            except ValueError:
                print("⚠️ 숫자를 입력해주세요.")


if __name__ == "__main__":
    main()
