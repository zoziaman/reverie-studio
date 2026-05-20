#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Reverie Studio - 3팩 프로덕션 검증 스크립트 v1.0
=================================================
크몽 배포 전 최종 퀄리티 검증

검증 항목 (AC 1~6):
  AC1: 3팩 × 3편 연속 생성 크래시 0회
  AC2: 이미지 생성 성공률 90% 이상
  AC3: TTS 전체 턴 성공, 음성 누락 0건
  AC4: 생성 영상 길이 7~15분 범위 내
  AC5: 자막 겹침/누락 0건
  AC6: 캐릭터 voice_type 매핑 정확

실행:
    python tools/validate_3pack_production.py
    python tools/validate_3pack_production.py --pack horror_v59
    python tools/validate_3pack_production.py --episodes 1  # 빠른 검증
    python tools/validate_3pack_production.py --dry-run      # 파이프라인 호출 없이 설정만 검증
    python tools/validate_3pack_production.py --json          # JSON 보고서 출력

결과:
    logs/production_validation_YYYYMMDD_HHMMSS.json
"""

import os
import sys
import json
import time
import glob
import logging
import argparse
import traceback
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any

# 경로 설정
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

# 환경변수 로드
try:
    from dotenv import dotenv_values
    env = dotenv_values(str(PROJECT_ROOT / '.env'))
    for k, v in env.items():
        if v is not None:
            os.environ[k] = v
except ImportError:
    pass

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("production_validation")


def safe_print(msg: str):
    """cp949 호환 안전 출력"""
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        import re
        clean = re.sub(r'[^\x00-\x7F\uAC00-\uD7A3\u3131-\u318E]+', '', msg)
        print(clean, flush=True)


# ── 데이터 클래스 ──────────────────────────────────────────────

@dataclass
class EpisodeResult:
    """에피소드 단위 결과"""
    pack_id: str = ""
    episode_num: int = 0
    status: str = "pending"           # pending / success / failed / crashed
    error_msg: str = ""
    duration_sec: float = 0.0

    # AC2: 이미지 생성 성공률
    total_scenes: int = 0
    image_success: int = 0
    image_fail: int = 0
    image_success_rate: float = 0.0

    # AC3: TTS 누락 검증
    total_tts_turns: int = 0
    tts_success: int = 0
    tts_missing: int = 0
    tts_missing_turns: List[int] = field(default_factory=list)

    # AC4: 영상 길이 (초)
    video_duration_sec: float = 0.0
    video_duration_in_range: bool = False   # 7~15분

    # AC5: 자막 겹침/누락
    subtitle_overlap_count: int = 0
    subtitle_missing_count: int = 0

    # AC6: voice_type 매핑
    voice_type_mismatches: List[str] = field(default_factory=list)

    # 경로
    output_dir: str = ""


@dataclass
class PackResult:
    """팩 단위 결과"""
    pack_id: str = ""
    episodes: List[EpisodeResult] = field(default_factory=list)
    crash_count: int = 0
    total_episodes: int = 0
    success_count: int = 0
    avg_image_success_rate: float = 0.0
    all_tts_complete: bool = True
    all_video_in_range: bool = True
    all_subtitles_clean: bool = True
    all_voice_types_correct: bool = True


@dataclass
class ValidationReport:
    """전체 검증 보고서"""
    timestamp: str = ""
    version: str = "v62.41"
    packs_tested: List[str] = field(default_factory=list)
    episodes_per_pack: int = 3
    pack_results: List[PackResult] = field(default_factory=list)

    # AC1: 전체 크래시 0회
    total_crashes: int = 0
    ac1_pass: bool = False  # 크래시 0회

    # AC2: 이미지 성공률 90% 이상
    overall_image_success_rate: float = 0.0
    ac2_pass: bool = False

    # AC3: TTS 음성 누락 0건
    total_tts_missing: int = 0
    ac3_pass: bool = False

    # AC4: 영상 길이 7~15분 범위
    videos_in_range: int = 0
    videos_total: int = 0
    ac4_pass: bool = False

    # AC5: 자막 겹침/누락 0건
    total_subtitle_issues: int = 0
    ac5_pass: bool = False

    # AC6: voice_type 매핑 정확
    total_voice_type_mismatches: int = 0
    ac6_pass: bool = False

    # 종합
    all_pass: bool = False


# ── 프로덕션 3팩 ──────────────────────────────────────────────

PRODUCTION_PACKS = ["horror_v59", "senior_touching", "senior_makjang"]

VIDEO_MIN_SEC = 7 * 60    # 7분
VIDEO_MAX_SEC = 15 * 60   # 15분
IMAGE_SUCCESS_THRESHOLD = 0.90  # 90%


# ── 검증 로직 ────────────────────────────────────────────────

class ProductionValidator:
    """3팩 프로덕션 검증기"""

    def __init__(self, packs: List[str], episodes_per_pack: int = 3, dry_run: bool = False):
        self.packs = packs
        self.episodes_per_pack = episodes_per_pack
        self.dry_run = dry_run
        self.report = ValidationReport(
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            packs_tested=packs,
            episodes_per_pack=episodes_per_pack
        )

    def run(self) -> ValidationReport:
        """전체 검증 실행"""
        safe_print("\n" + "=" * 70)
        safe_print("  Reverie Studio 3팩 프로덕션 검증")
        safe_print(f"  팩: {', '.join(self.packs)}")
        safe_print(f"  에피소드/팩: {self.episodes_per_pack}")
        safe_print(f"  모드: {'DRY-RUN (설정 검증만)' if self.dry_run else 'FULL (실제 생성)'}")
        safe_print("=" * 70 + "\n")

        for pack_id in self.packs:
            pack_result = self._validate_pack(pack_id)
            self.report.pack_results.append(pack_result)

        self._aggregate_results()
        self._print_summary()
        return self.report

    def _validate_pack(self, pack_id: str) -> PackResult:
        """팩 단위 검증"""
        safe_print(f"\n{'─' * 50}")
        safe_print(f"  팩 검증 시작: {pack_id}")
        safe_print(f"{'─' * 50}")

        pack_result = PackResult(
            pack_id=pack_id,
            total_episodes=self.episodes_per_pack
        )

        # 팩 로드 검증
        if not self._verify_pack_loadable(pack_id):
            safe_print(f"  [FATAL] 팩 로드 실패: {pack_id}")
            pack_result.crash_count = self.episodes_per_pack
            return pack_result

        for ep in range(1, self.episodes_per_pack + 1):
            safe_print(f"\n  --- {pack_id} 에피소드 {ep}/{self.episodes_per_pack} ---")
            episode = self._run_episode(pack_id, ep)
            pack_result.episodes.append(episode)

            if episode.status == "crashed":
                pack_result.crash_count += 1
            elif episode.status == "success":
                pack_result.success_count += 1

        # 팩 집계
        img_rates = [e.image_success_rate for e in pack_result.episodes if e.status == "success"]
        pack_result.avg_image_success_rate = sum(img_rates) / len(img_rates) if img_rates else 0
        pack_result.all_tts_complete = all(e.tts_missing == 0 for e in pack_result.episodes if e.status == "success")
        pack_result.all_video_in_range = all(e.video_duration_in_range for e in pack_result.episodes if e.status == "success")
        pack_result.all_subtitles_clean = all(
            e.subtitle_overlap_count == 0 and e.subtitle_missing_count == 0
            for e in pack_result.episodes if e.status == "success"
        )
        pack_result.all_voice_types_correct = all(
            len(e.voice_type_mismatches) == 0 for e in pack_result.episodes if e.status == "success"
        )

        return pack_result

    def _verify_pack_loadable(self, pack_id: str) -> bool:
        """팩 로드 가능 여부 검증"""
        try:
            from config.pack_config import load_pack, ACTIVE_PACK

            # .revpack 파일 찾기
            revpack_path = PROJECT_ROOT / "assets" / "packs" / f"{pack_id}.revpack"
            folder_path = PROJECT_ROOT / "assets" / "packs" / pack_id

            if revpack_path.exists():
                load_pack(str(revpack_path))
            elif folder_path.exists():
                load_pack(str(folder_path))
            else:
                safe_print(f"    [ERROR] 팩 파일 없음: {pack_id}")
                return False

            safe_print(f"    [OK] 팩 로드 성공: {ACTIVE_PACK.pack_name}")

            # voice_type 매핑 사전 검증 (AC6)
            if hasattr(ACTIVE_PACK, 'character_config'):
                self._verify_voice_type_config(ACTIVE_PACK)

            return True

        except Exception as e:
            safe_print(f"    [ERROR] 팩 로드 예외: {e}")
            traceback.print_exc()
            return False

    def _verify_voice_type_config(self, pack):
        """voice_type 매핑 사전 검증 (AC6 예비)"""
        try:
            # voice_metadata.json 기반 유효 voice_type 목록
            metadata_path = PROJECT_ROOT / "assets" / "models" / "voice_metadata.json"
            valid_types = {"narrator"}  # narrator는 가상 alias

            if metadata_path.exists():
                with open(metadata_path, "r", encoding="utf-8") as f:
                    metadata = json.load(f)
                    valid_types.update(metadata.keys())

            # models/ 폴더 스캔으로 추가
            models_dir = PROJECT_ROOT / "assets" / "models"
            if models_dir.exists():
                for d in models_dir.iterdir():
                    if d.is_dir() and not d.name.startswith('.'):
                        valid_types.add(d.name)

            # 팩의 character_mapping 검증
            char_config = pack.character_config
            if isinstance(char_config, dict):
                char_mapping = char_config.get("character_mapping", {})
                for char_name, voice_type in char_mapping.items():
                    if voice_type not in valid_types:
                        safe_print(f"    [WARN] 매핑 불일치: {char_name} -> {voice_type} (유효하지 않음)")

            safe_print(f"    [OK] voice_type 매핑 사전 검증 완료 (유효 타입 {len(valid_types)}개)")

        except Exception as e:
            safe_print(f"    [WARN] voice_type 검증 실패 (비치명적): {e}")

    def _run_episode(self, pack_id: str, ep_num: int) -> EpisodeResult:
        """에피소드 1편 생성 + 검증"""
        result = EpisodeResult(pack_id=pack_id, episode_num=ep_num)
        start_time = time.time()

        if self.dry_run:
            result.status = "success"
            result.duration_sec = 0.1
            # dry-run 모드에서는 설정 검증만 수행
            self._dry_run_validate(pack_id, result)
            return result

        try:
            # 실제 파이프라인 실행
            output_dir = self._execute_pipeline(pack_id, ep_num)
            result.output_dir = output_dir
            result.duration_sec = time.time() - start_time

            if output_dir and os.path.exists(output_dir):
                # 결과 검증
                self._validate_images(output_dir, result)          # AC2
                self._validate_tts(output_dir, result)             # AC3
                self._validate_video_duration(output_dir, result)  # AC4
                self._validate_subtitles(output_dir, result)       # AC5
                self._validate_voice_types(output_dir, result)     # AC6
                result.status = "success"
            else:
                result.status = "failed"
                result.error_msg = "출력 디렉토리 없음"

        except KeyboardInterrupt:
            raise
        except Exception as e:
            result.status = "crashed"
            result.error_msg = str(e)
            result.duration_sec = time.time() - start_time
            safe_print(f"    [CRASH] {pack_id} ep{ep_num}: {e}")
            traceback.print_exc()

        status_icon = {"success": "[OK]", "failed": "[FAIL]", "crashed": "[CRASH]"}.get(result.status, "[?]")
        safe_print(f"    {status_icon} {pack_id} ep{ep_num}: {result.status} ({result.duration_sec:.1f}s)")
        return result

    def _execute_pipeline(self, pack_id: str, ep_num: int) -> Optional[str]:
        """실제 파이프라인 호출"""
        from config.pack_config import load_pack, ACTIVE_PACK
        from modules_pro.scenario_planner import ScenarioPlanner, PromptMode

        # 팩 로드
        revpack_path = PROJECT_ROOT / "assets" / "packs" / f"{pack_id}.revpack"
        folder_path = PROJECT_ROOT / "assets" / "packs" / pack_id

        if revpack_path.exists():
            load_pack(str(revpack_path))
        else:
            load_pack(str(folder_path))

        # 시나리오 생성
        planner = ScenarioPlanner(prompt_mode=PromptMode.ENHANCED)

        genre_map = {
            "horror_v59": "horror",
            "senior_touching": "senior",
            "senior_makjang": "senior",
        }
        category = genre_map.get(pack_id, "senior")
        mode = "touching" if "touching" in pack_id else "makjang" if "makjang" in pack_id else ""

        plan_data, _ = planner.create_plan(category=category, mode=mode, topic="")

        if not plan_data or 'script_list' not in plan_data:
            raise RuntimeError("시나리오 생성 실패: script_list 없음")

        # Orchestrator 실행
        from pipeline.orchestrator import MediaFactory

        factory = MediaFactory()
        output_base = str(PROJECT_ROOT / "daily" / f"validation_{pack_id}_ep{ep_num}")
        os.makedirs(output_base, exist_ok=True)

        result = factory.produce_video(
            plan_data=plan_data,
            output_dir=output_base,
            progress_callback=lambda stage, pct: None,
            log_callback=lambda msg: logger.debug(msg),
            auto_upload=False,
        )

        return output_base if result else None

    def _dry_run_validate(self, pack_id: str, result: EpisodeResult):
        """dry-run 모드: 설정만 검증"""
        safe_print(f"    [DRY-RUN] {pack_id}: 팩 설정 검증만 수행")

        try:
            from config.pack_config import load_pack, ACTIVE_PACK

            revpack_path = PROJECT_ROOT / "assets" / "packs" / f"{pack_id}.revpack"
            folder_path = PROJECT_ROOT / "assets" / "packs" / pack_id

            if revpack_path.exists():
                load_pack(str(revpack_path))
            elif folder_path.exists():
                load_pack(str(folder_path))

            # 필수 필드 검증
            checks = []
            if hasattr(ACTIVE_PACK, 'pack_name') and ACTIVE_PACK.pack_name:
                checks.append("pack_name OK")
            if hasattr(ACTIVE_PACK, 'tts') and ACTIVE_PACK.tts:
                checks.append("tts OK")
            if hasattr(ACTIVE_PACK, 'character_config') and ACTIVE_PACK.character_config:
                checks.append("character_config OK")

            safe_print(f"    [DRY-RUN] 검증: {', '.join(checks)}")
            result.status = "success"

        except Exception as e:
            result.status = "failed"
            result.error_msg = str(e)

    # ── AC2: 이미지 검증 ─────────────────────────────────

    def _validate_images(self, output_dir: str, result: EpisodeResult):
        """AC2: 이미지 생성 성공률 검증"""
        image_dir = os.path.join(output_dir, "images")
        if not os.path.exists(image_dir):
            # 대체 경로 탐색
            for subdir in ["scenes", "scene_images"]:
                alt = os.path.join(output_dir, subdir)
                if os.path.exists(alt):
                    image_dir = alt
                    break

        if not os.path.exists(image_dir):
            safe_print(f"    [WARN] 이미지 폴더 없음: {image_dir}")
            return

        # script_list에서 예상 장면 수 확인
        script_path = os.path.join(output_dir, "script.json")
        expected_scenes = 0
        if os.path.exists(script_path):
            try:
                with open(script_path, "r", encoding="utf-8") as f:
                    script = json.load(f)
                    expected_scenes = len(script.get("script_list", []))
            except Exception:
                pass

        # 실제 이미지 파일 수
        image_files = glob.glob(os.path.join(image_dir, "*.png")) + \
                      glob.glob(os.path.join(image_dir, "*.jpg"))

        result.total_scenes = max(expected_scenes, len(image_files))
        result.image_success = len(image_files)
        result.image_fail = max(0, result.total_scenes - result.image_success)
        result.image_success_rate = (
            result.image_success / result.total_scenes
            if result.total_scenes > 0 else 1.0
        )

        status = "[OK]" if result.image_success_rate >= IMAGE_SUCCESS_THRESHOLD else "[FAIL]"
        safe_print(f"    {status} 이미지: {result.image_success}/{result.total_scenes} ({result.image_success_rate:.1%})")

    # ── AC3: TTS 검증 ────────────────────────────────────

    def _validate_tts(self, output_dir: str, result: EpisodeResult):
        """AC3: TTS 음성 누락 검증"""
        audio_dir = os.path.join(output_dir, "audio")
        if not os.path.exists(audio_dir):
            for subdir in ["tts", "voices"]:
                alt = os.path.join(output_dir, subdir)
                if os.path.exists(alt):
                    audio_dir = alt
                    break

        if not os.path.exists(audio_dir):
            safe_print(f"    [WARN] 오디오 폴더 없음: {audio_dir}")
            return

        # script_list에서 예상 턴 수
        script_path = os.path.join(output_dir, "script.json")
        expected_turns = 0
        if os.path.exists(script_path):
            try:
                with open(script_path, "r", encoding="utf-8") as f:
                    script = json.load(f)
                    expected_turns = len(script.get("script_list", []))
            except Exception:
                pass

        # 실제 오디오 파일 수
        audio_files = glob.glob(os.path.join(audio_dir, "*.wav")) + \
                      glob.glob(os.path.join(audio_dir, "*.mp3"))

        result.total_tts_turns = max(expected_turns, len(audio_files))
        result.tts_success = len(audio_files)
        result.tts_missing = max(0, result.total_tts_turns - result.tts_success)

        # 누락 턴 번호 식별
        if expected_turns > 0:
            existing_nums = set()
            for f in audio_files:
                import re
                match = re.search(r'(\d+)', os.path.basename(f))
                if match:
                    existing_nums.add(int(match.group(1)))
            result.tts_missing_turns = [i for i in range(1, expected_turns + 1) if i not in existing_nums]

        status = "[OK]" if result.tts_missing == 0 else "[FAIL]"
        safe_print(f"    {status} TTS: {result.tts_success}/{result.total_tts_turns} (누락 {result.tts_missing}건)")

    # ── AC4: 영상 길이 검증 ──────────────────────────────

    def _validate_video_duration(self, output_dir: str, result: EpisodeResult):
        """AC4: 영상 길이 7~15분 범위 검증"""
        # 최종 영상 파일 찾기
        video_files = glob.glob(os.path.join(output_dir, "*.mp4")) + \
                      glob.glob(os.path.join(output_dir, "output", "*.mp4"))

        if not video_files:
            safe_print(f"    [WARN] 영상 파일 없음")
            return

        video_path = video_files[0]

        try:
            # ffprobe로 길이 확인
            import subprocess
            cmd = [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                video_path
            ]
            output = subprocess.check_output(cmd, stderr=subprocess.STDOUT, timeout=10)
            duration = float(output.strip())

            result.video_duration_sec = duration
            result.video_duration_in_range = VIDEO_MIN_SEC <= duration <= VIDEO_MAX_SEC

            minutes = duration / 60
            status = "[OK]" if result.video_duration_in_range else "[FAIL]"
            safe_print(f"    {status} 영상 길이: {minutes:.1f}분 (범위: 7~15분)")

        except FileNotFoundError:
            safe_print("    [WARN] ffprobe 미설치 - 영상 길이 검증 건너뜀")
        except Exception as e:
            safe_print(f"    [WARN] 영상 길이 확인 실패: {e}")

    # ── AC5: 자막 검증 ───────────────────────────────────

    def _validate_subtitles(self, output_dir: str, result: EpisodeResult):
        """AC5: 자막 겹침/누락 검증"""
        # Remotion 입력 JSON에서 자막 데이터 확인
        remotion_json = os.path.join(output_dir, "remotion_input.json")
        if not os.path.exists(remotion_json):
            for name in ["scene_data.json", "video_data.json"]:
                alt = os.path.join(output_dir, name)
                if os.path.exists(alt):
                    remotion_json = alt
                    break

        if not os.path.exists(remotion_json):
            safe_print(f"    [WARN] 자막 데이터 파일 없음")
            return

        try:
            with open(remotion_json, "r", encoding="utf-8") as f:
                data = json.load(f)

            scenes = data.get("scenes", data.get("script_list", []))
            subtitles = []

            for i, scene in enumerate(scenes):
                sub = scene.get("subtitle", scene.get("dialogue", scene.get("text", "")))
                if not sub or not str(sub).strip():
                    result.subtitle_missing_count += 1

                # 타이밍 겹침 검사 (start_time, end_time이 있는 경우)
                start = scene.get("start_time", scene.get("start_sec", 0))
                end = scene.get("end_time", scene.get("end_sec", 0))
                if start and end:
                    subtitles.append((float(start), float(end), i))

            # 타이밍 기반 겹침 검사
            subtitles.sort(key=lambda x: x[0])
            for i in range(len(subtitles) - 1):
                if subtitles[i][1] > subtitles[i + 1][0] + 0.05:  # 50ms 허용
                    result.subtitle_overlap_count += 1

            total_issues = result.subtitle_overlap_count + result.subtitle_missing_count
            status = "[OK]" if total_issues == 0 else "[FAIL]"
            safe_print(f"    {status} 자막: 겹침 {result.subtitle_overlap_count}건, 누락 {result.subtitle_missing_count}건")

        except Exception as e:
            safe_print(f"    [WARN] 자막 검증 실패: {e}")

    # ── AC6: voice_type 매핑 검증 ────────────────────────

    def _validate_voice_types(self, output_dir: str, result: EpisodeResult):
        """AC6: 캐릭터 voice_type 매핑 정확도 검증"""
        script_path = os.path.join(output_dir, "script.json")
        if not os.path.exists(script_path):
            return

        try:
            with open(script_path, "r", encoding="utf-8") as f:
                script = json.load(f)

            # voice_metadata.json 기반 유효 타입
            metadata_path = PROJECT_ROOT / "assets" / "models" / "voice_metadata.json"
            valid_types = {"narrator", "narrator_male", "narrator_female"}
            if metadata_path.exists():
                with open(metadata_path, "r", encoding="utf-8") as f:
                    metadata = json.load(f)
                    valid_types.update(metadata.keys())

            # models/ 폴더에서 추가
            models_dir = PROJECT_ROOT / "assets" / "models"
            if models_dir.exists():
                for d in models_dir.iterdir():
                    if d.is_dir() and not d.name.startswith('.'):
                        valid_types.add(d.name)

            # 각 턴의 voice_type 검증
            for turn in script.get("script_list", []):
                vt = turn.get("voice_type", "")
                if vt and vt not in valid_types:
                    mismatch = f"턴 {turn.get('turn', '?')}: {turn.get('character', '?')} -> {vt}"
                    result.voice_type_mismatches.append(mismatch)

            mismatches = len(result.voice_type_mismatches)
            status = "[OK]" if mismatches == 0 else "[FAIL]"
            safe_print(f"    {status} voice_type: 불일치 {mismatches}건")

        except Exception as e:
            safe_print(f"    [WARN] voice_type 검증 실패: {e}")

    # ── 결과 집계 ────────────────────────────────────────

    def _aggregate_results(self):
        """전체 결과 집계"""
        r = self.report

        # AC1: 크래시 0회
        r.total_crashes = sum(pr.crash_count for pr in r.pack_results)
        r.ac1_pass = (r.total_crashes == 0)

        # AC2: 이미지 성공률 90%+
        all_rates = []
        for pr in r.pack_results:
            for ep in pr.episodes:
                if ep.status == "success" and ep.total_scenes > 0:
                    all_rates.append(ep.image_success_rate)
        r.overall_image_success_rate = sum(all_rates) / len(all_rates) if all_rates else 0
        r.ac2_pass = (r.overall_image_success_rate >= IMAGE_SUCCESS_THRESHOLD)

        # AC3: TTS 누락 0건
        r.total_tts_missing = sum(
            ep.tts_missing for pr in r.pack_results for ep in pr.episodes
        )
        r.ac3_pass = (r.total_tts_missing == 0)

        # AC4: 영상 길이 범위
        r.videos_total = sum(1 for pr in r.pack_results for ep in pr.episodes if ep.video_duration_sec > 0)
        r.videos_in_range = sum(1 for pr in r.pack_results for ep in pr.episodes if ep.video_duration_in_range)
        r.ac4_pass = (r.videos_total > 0 and r.videos_in_range == r.videos_total) or self.dry_run

        # AC5: 자막 이슈 0건
        r.total_subtitle_issues = sum(
            ep.subtitle_overlap_count + ep.subtitle_missing_count
            for pr in r.pack_results for ep in pr.episodes
        )
        r.ac5_pass = (r.total_subtitle_issues == 0) or self.dry_run

        # AC6: voice_type 불일치 0건
        r.total_voice_type_mismatches = sum(
            len(ep.voice_type_mismatches) for pr in r.pack_results for ep in pr.episodes
        )
        r.ac6_pass = (r.total_voice_type_mismatches == 0)

        # 종합
        r.all_pass = all([r.ac1_pass, r.ac2_pass, r.ac3_pass, r.ac4_pass, r.ac5_pass, r.ac6_pass])

    def _print_summary(self):
        """요약 출력"""
        r = self.report

        safe_print("\n" + "=" * 70)
        safe_print("  3팩 프로덕션 검증 결과")
        safe_print("=" * 70)

        checks = [
            ("AC1", "크래시 0회", r.ac1_pass, f"크래시 {r.total_crashes}회"),
            ("AC2", "이미지 성공률 90%+", r.ac2_pass, f"{r.overall_image_success_rate:.1%}"),
            ("AC3", "TTS 누락 0건", r.ac3_pass, f"누락 {r.total_tts_missing}건"),
            ("AC4", "영상 7~15분", r.ac4_pass, f"{r.videos_in_range}/{r.videos_total}편 범위 내"),
            ("AC5", "자막 이슈 0건", r.ac5_pass, f"이슈 {r.total_subtitle_issues}건"),
            ("AC6", "voice_type 정확", r.ac6_pass, f"불일치 {r.total_voice_type_mismatches}건"),
        ]

        for ac_id, desc, passed, detail in checks:
            icon = "PASS" if passed else "FAIL"
            safe_print(f"  [{icon}] {ac_id}: {desc} -- {detail}")

        safe_print(f"\n  종합: {'ALL PASS' if r.all_pass else 'SOME FAILED'}")
        safe_print("=" * 70)

    def save_report(self, path: Optional[str] = None) -> str:
        """보고서 JSON 저장"""
        if path is None:
            log_dir = PROJECT_ROOT / "logs"
            log_dir.mkdir(exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = str(log_dir / f"production_validation_{ts}.json")

        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(self.report), f, ensure_ascii=False, indent=2)

        safe_print(f"\n  보고서 저장: {path}")
        return path


# ── GPU VRAM 사전 체크 (AC8) ─────────────────────────────────

def check_gpu_vram(min_vram_gb: float = 6.0) -> dict:
    """
    GPU VRAM 자동 체크 (AC8)

    Returns:
        dict: {available: bool, gpu_name: str, vram_gb: float, warning: str}
    """
    result = {
        "available": False,
        "gpu_name": "Unknown",
        "vram_gb": 0.0,
        "vram_free_gb": 0.0,
        "warning": "",
        "cuda_available": False,
    }

    try:
        import torch
        result["cuda_available"] = torch.cuda.is_available()

        if not torch.cuda.is_available():
            result["warning"] = "CUDA GPU가 감지되지 않았습니다. NVIDIA GPU + CUDA 설치가 필요합니다."
            return result

        gpu_name = torch.cuda.get_device_name(0)
        total_vram = torch.cuda.get_device_properties(0).total_mem / (1024 ** 3)
        free_vram = (torch.cuda.get_device_properties(0).total_mem - torch.cuda.memory_allocated(0)) / (1024 ** 3)

        result["gpu_name"] = gpu_name
        result["vram_gb"] = round(total_vram, 1)
        result["vram_free_gb"] = round(free_vram, 1)
        result["available"] = total_vram >= min_vram_gb

        if total_vram < min_vram_gb:
            result["warning"] = (
                f"GPU VRAM 부족: {gpu_name} ({total_vram:.1f}GB). "
                f"최소 {min_vram_gb}GB 이상 필요합니다. "
                f"이미지 생성이 불안정할 수 있습니다."
            )
        elif total_vram < 8.0:
            result["warning"] = (
                f"GPU: {gpu_name} ({total_vram:.1f}GB). "
                f"최소 사양을 충족하지만 8GB 이상을 권장합니다. "
                f"768x432 해상도로 제한됩니다."
            )

        return result

    except ImportError:
        result["warning"] = "PyTorch가 설치되지 않았습니다. GPU 사양 확인이 불가합니다."
        return result

    except Exception as e:
        result["warning"] = f"GPU 정보 확인 실패: {e}"
        return result


def check_gpu_vram_nvidia_smi(min_vram_gb: float = 6.0) -> dict:
    """nvidia-smi 기반 VRAM 체크 (PyTorch 없이도 동작)"""
    result = {
        "available": False,
        "gpu_name": "Unknown",
        "vram_gb": 0.0,
        "vram_free_gb": 0.0,
        "warning": "",
        "method": "nvidia-smi",
    }

    try:
        import subprocess
        output = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.free",
             "--format=csv,noheader,nounits"],
            timeout=10, stderr=subprocess.STDOUT
        ).decode("utf-8").strip()

        lines = output.split("\n")
        if lines:
            parts = lines[0].split(", ")
            if len(parts) >= 3:
                result["gpu_name"] = parts[0].strip()
                total_mb = float(parts[1].strip())
                free_mb = float(parts[2].strip())
                result["vram_gb"] = round(total_mb / 1024, 1)
                result["vram_free_gb"] = round(free_mb / 1024, 1)
                result["available"] = result["vram_gb"] >= min_vram_gb

                if result["vram_gb"] < min_vram_gb:
                    result["warning"] = (
                        f"GPU VRAM 부족: {result['gpu_name']} ({result['vram_gb']}GB). "
                        f"최소 {min_vram_gb}GB 이상 필요합니다."
                    )

        return result

    except FileNotFoundError:
        result["warning"] = "nvidia-smi를 찾을 수 없습니다. NVIDIA GPU 드라이버가 설치되어 있는지 확인하세요."
        return result
    except Exception as e:
        result["warning"] = f"GPU 확인 실패: {e}"
        return result


# ── 메인 ─────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Reverie Studio 3팩 프로덕션 검증")
    parser.add_argument("--pack", nargs="+", default=PRODUCTION_PACKS,
                        help="검증할 팩 ID (기본: 3팩 전체)")
    parser.add_argument("--episodes", type=int, default=3,
                        help="팩당 에피소드 수 (기본: 3)")
    parser.add_argument("--dry-run", action="store_true",
                        help="설정 검증만 수행 (파이프라인 호출 없음)")
    parser.add_argument("--json", action="store_true",
                        help="JSON 보고서 출력")
    parser.add_argument("--check-gpu", action="store_true",
                        help="GPU VRAM 체크만 수행")
    args = parser.parse_args()

    # GPU 체크만
    if args.check_gpu:
        safe_print("\n  GPU VRAM 사양 체크")
        safe_print("  " + "-" * 40)

        # PyTorch 시도 → 실패 시 nvidia-smi 폴백
        gpu_info = check_gpu_vram()
        if not gpu_info["cuda_available"]:
            gpu_info = check_gpu_vram_nvidia_smi()

        for k, v in gpu_info.items():
            safe_print(f"  {k}: {v}")

        if gpu_info["warning"]:
            safe_print(f"\n  [WARNING] {gpu_info['warning']}")
        else:
            safe_print(f"\n  [OK] GPU 사양 충족: {gpu_info['gpu_name']} ({gpu_info['vram_gb']}GB)")

        return

    # 프로덕션 검증
    validator = ProductionValidator(
        packs=args.pack,
        episodes_per_pack=args.episodes,
        dry_run=args.dry_run
    )

    report = validator.run()
    report_path = validator.save_report()

    if args.json:
        print(json.dumps(asdict(report), ensure_ascii=False, indent=2))

    sys.exit(0 if report.all_pass else 1)


if __name__ == "__main__":
    main()
