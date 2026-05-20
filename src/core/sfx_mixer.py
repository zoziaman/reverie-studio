# src/core/sfx_mixer.py
"""
v53: Auto-SFX 시스템 - 오디오 믹서

FFmpeg를 사용하여 효과음을 오디오/비디오에 합성

입력: 원본 오디오 + SFXCue 리스트
출력: 효과음이 믹싱된 오디오

"효과음을 적절한 타이밍에 적절한 볼륨으로 믹싱"
"""
import os
import subprocess
import sys
# v62.17: Windows 콘솔 창 깜빡임 방지
_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
def _hidden_startupinfo():
    if sys.platform == 'win32':
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = subprocess.SW_HIDE
        return si
    return None
import logging
import tempfile
import json
import threading
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass

from core.sfx_manager import SFXManager, SFXCue, SFXInfo, get_sfx_manager
from config.settings_v2 import config  # v61.1: 인스턴스 import (FFMPEG_PATH 접근 필요)

logger = logging.getLogger(__name__)


@dataclass
class MixedSFX:
    """믹싱된 효과음 정보"""
    cue: SFXCue                     # 원본 큐
    sfx_info: SFXInfo               # 효과음 정보
    actual_volume: float            # 실제 적용 볼륨 (dB)
    success: bool                   # 믹싱 성공 여부


class SFXMixer:
    """
    효과음 믹서 - FFmpeg 기반

    기능:
    1. 효과음 볼륨 조절 (배경음악/나레이션과 균형)
    2. 페이드 인/아웃
    3. 다중 효과음 동시 믹싱
    4. 원본 오디오와 합성
    """

    # 기본 볼륨 설정 (dB)
    DEFAULT_SFX_VOLUME = -10        # 효과음 기본 볼륨
    NARRATION_DUCK_DB = -6          # 나레이션 있을 때 효과음 덕킹

    # v53: 배경음 덕킹 설정 (효과음 나올 때 배경음 줄이기)
    DUCKING_ENABLED = True          # 덕킹 활성화
    DUCKING_RATIO = 0.5             # 효과음 나올 때 배경음 볼륨 비율 (0.5 = 50%)

    def __init__(self, sfx_manager: SFXManager = None):
        """
        Args:
            sfx_manager: 효과음 관리자 (없으면 자동 생성)
        """
        self.sfx_manager = sfx_manager or get_sfx_manager()
        self._check_ffmpeg()

    def _check_ffmpeg(self):
        """FFmpeg 설치 확인 (v58.3.9: config.FFMPEG_PATH 사용)"""
        # v58.3.9: 시스템 PATH의 ffmpeg(4.3.2) 대신 config.FFMPEG_PATH(8.0.1) 사용
        self.ffmpeg_path = getattr(config, 'FFMPEG_PATH', None)
        if not self.ffmpeg_path or not os.path.exists(self.ffmpeg_path):
            self.ffmpeg_path = 'ffmpeg'  # 폴백

        try:
            result = subprocess.run(
                [self.ffmpeg_path, '-version'],
                capture_output=True,
                text=True,
                creationflags=_NO_WINDOW,
                startupinfo=_hidden_startupinfo(),
            )
            self.ffmpeg_available = result.returncode == 0
            if self.ffmpeg_available:
                logger.info(f"FFmpeg 확인 완료: {self.ffmpeg_path}")
        except FileNotFoundError:
            self.ffmpeg_available = False
            logger.warning(f"FFmpeg를 찾을 수 없습니다: {self.ffmpeg_path}")

    def mix_sfx_to_audio(
        self,
        audio_path: str,
        cues: List[SFXCue],
        output_path: str,
        category: str = "daily_life_toon",
        master_volume: float = 1.0
    ) -> Tuple[bool, str, List[MixedSFX]]:
        """
        오디오 파일에 효과음 믹싱

        Args:
            audio_path: 원본 오디오 경로
            cues: 효과음 큐 리스트
            output_path: 출력 경로
            category: 카테고리 (효과음 검색용)
            master_volume: 전체 효과음 볼륨 배율 (0.0 ~ 2.0)

        Returns:
            (성공여부, 출력경로, 믹싱된 효과음 정보)
        """
        if not self.ffmpeg_available:
            logger.error("FFmpeg 사용 불가")
            return False, "", []

        if not os.path.exists(audio_path):
            logger.error(f"원본 오디오 없음: {audio_path}")
            return False, "", []

        if not cues:
            logger.info("효과음 큐 없음, 원본 복사")
            # 원본 그대로 복사
            import shutil
            shutil.copy(audio_path, output_path)
            return True, output_path, []

        # 효과음 매칭 및 준비
        mixed_sfx_list = []
        temp_files = []

        try:
            # 원본 오디오 길이 측정
            audio_duration_ms = self._get_audio_duration(audio_path)

            # 각 큐에 대해 효과음 준비
            sfx_inputs = []  # (sfx_path, start_ms, volume_db, fade_in, fade_out)

            for cue in cues:
                # 효과음 찾기
                sfx_info = self.sfx_manager.find_by_tag(
                    cue.tag,
                    category_filter=category
                )

                if not sfx_info:
                    logger.warning(f"효과음 없음: {cue.tag}")
                    mixed_sfx_list.append(MixedSFX(
                        cue=cue,
                        sfx_info=None,
                        actual_volume=0,
                        success=False
                    ))
                    continue

                sfx_path = self.sfx_manager.get_sfx_path(sfx_info)

                if not os.path.exists(sfx_path):
                    logger.warning(f"효과음 파일 없음: {sfx_path}")
                    continue

                # 볼륨 계산
                volume_db = self.DEFAULT_SFX_VOLUME + sfx_info.volume_adjust
                volume_db *= master_volume
                # 강도에 따른 볼륨 조절
                volume_db += (cue.intensity - 0.5) * 6  # 0.5 기준 ±3dB

                # v53: 효과음 길이 결정
                # cue.duration_ms가 지정되어 있으면 그 길이로 자름
                # 효과음 파일이 더 짧으면 파일 길이 사용
                sfx_file_duration = sfx_info.duration_ms or 5000  # 기본 5초
                requested_duration = cue.duration_ms

                # 실제 사용할 길이 계산
                if requested_duration and requested_duration > 0:
                    # 요청된 길이와 파일 길이 중 짧은 것 사용
                    actual_duration = min(requested_duration, sfx_file_duration)
                    # 파일보다 짧으면 trim 필요
                    trim_duration = actual_duration if actual_duration < sfx_file_duration else None
                else:
                    actual_duration = sfx_file_duration
                    trim_duration = None

                sfx_inputs.append({
                    'path': sfx_path,
                    'start_ms': cue.timestamp_ms,
                    'volume_db': volume_db,
                    'fade_in_ms': cue.fade_in_ms,
                    'fade_out_ms': cue.fade_out_ms,
                    'duration_ms': actual_duration,
                    'trim_duration_ms': trim_duration  # v53: 자르기용
                })

                mixed_sfx_list.append(MixedSFX(
                    cue=cue,
                    sfx_info=sfx_info,
                    actual_volume=volume_db,
                    success=True
                ))

            if not sfx_inputs:
                logger.warning("유효한 효과음 없음")
                import shutil
                shutil.copy(audio_path, output_path)
                return True, output_path, mixed_sfx_list

            # FFmpeg 복합 필터 생성
            success = self._mix_with_ffmpeg(
                audio_path,
                sfx_inputs,
                output_path,
                audio_duration_ms
            )

            return success, output_path if success else "", mixed_sfx_list

        except Exception as e:
            logger.error(f"믹싱 실패: {e}")
            return False, "", mixed_sfx_list

        finally:
            # 임시 파일 정리
            for temp_file in temp_files:
                try:
                    os.remove(temp_file)
                except OSError:
                    pass

    def _mix_with_ffmpeg(
        self,
        audio_path: str,
        sfx_inputs: List[Dict],
        output_path: str,
        total_duration_ms: int
    ) -> bool:
        """FFmpeg로 믹싱 수행"""

        # 입력 파일 수집
        input_args = ['-i', audio_path]
        for i, sfx in enumerate(sfx_inputs):
            input_args.extend(['-i', sfx['path']])

        # 복합 필터 생성
        filter_parts = []
        mix_inputs = ['[0:a]']  # 원본 오디오

        for i, sfx in enumerate(sfx_inputs):
            input_idx = i + 1
            output_label = f'sfx{i}'

            # 효과음 처리 필터
            filters = []

            # v53: 필요한 길이만큼 자르기 (trim)
            # 예: 20초 효과음인데 3초만 필요하면 3초로 자름
            if sfx.get('trim_duration_ms'):
                trim_sec = sfx['trim_duration_ms'] / 1000
                filters.append(f"atrim=0:{trim_sec}")

            # 볼륨 조절
            volume_ratio = 10 ** (sfx['volume_db'] / 20)
            filters.append(f"volume={volume_ratio:.3f}")

            # 페이드 인
            if sfx['fade_in_ms'] > 0:
                fade_in_sec = sfx['fade_in_ms'] / 1000
                filters.append(f"afade=t=in:st=0:d={fade_in_sec}")

            # 페이드 아웃
            if sfx['fade_out_ms'] > 0:
                duration_sec = sfx['duration_ms'] / 1000
                fade_out_start = max(0, duration_sec - sfx['fade_out_ms'] / 1000)
                fade_out_dur = sfx['fade_out_ms'] / 1000
                filters.append(f"afade=t=out:st={fade_out_start}:d={fade_out_dur}")

            filter_chain = ','.join(filters) if filters else 'anull'

            # 딜레이 적용 (시작 시점)
            delay_ms = sfx['start_ms']

            # 효과음 필터: 볼륨/페이드 → 딜레이 → 패딩
            filter_parts.append(
                f"[{input_idx}:a]{filter_chain},adelay={delay_ms}|{delay_ms},"
                f"apad=whole_dur={total_duration_ms / 1000}[{output_label}]"
            )
            mix_inputs.append(f'[{output_label}]')

        # v53: 배경음 덕킹 (효과음 나올 때 배경음 줄이기)
        # 사이드체인 컴프레서로 효과음 신호에 맞춰 배경음 볼륨 자동 조절
        if self.DUCKING_ENABLED and len(sfx_inputs) > 0:
            # 1. 모든 효과음을 하나로 믹스 (덕킹 사이드체인용)
            if len(mix_inputs) > 2:  # 원본 + 효과음 2개 이상
                sfx_labels = [m for m in mix_inputs if m != '[0:a]']
                sfx_mix_part = ''.join(sfx_labels) + f"amix=inputs={len(sfx_labels)}:normalize=0[sfx_all]"
                filter_parts.append(sfx_mix_part)
            else:
                # 효과음 1개면 그대로 사용
                sfx_labels = [m for m in mix_inputs if m != '[0:a]']
                if sfx_labels:
                    filter_parts.append(f"{sfx_labels[0]}acopy[sfx_all]")

            # 2. 사이드체인 컴프레서로 덕킹 적용
            # 효과음이 나올 때 배경음(나레이션) 볼륨을 줄임
            ducking_filter = (
                f"[0:a][sfx_all]sidechaincompress="
                f"threshold=0.01:ratio=4:attack=50:release=300:"
                f"level_in=1:level_sc=1:mix={1 - self.DUCKING_RATIO}[ducked]"
            )
            filter_parts.append(ducking_filter)

            # 3. 덕킹된 배경음 + 효과음 믹스
            # v58.3.9: FFmpeg 8.0.1 사용 → normalize=0 지원
            # weights: 메인=1.5 (볼륨 증폭), SFX=0.6
            final_mix = "[ducked][sfx_all]amix=inputs=2:duration=first:normalize=0:weights=1.5 0.6[out]"
            filter_parts.append(final_mix)
            filter_complex = ';'.join(filter_parts)
        else:
            # 덕킹 없이 단순 믹스
            filter_complex = ';'.join(filter_parts)
            # v58.3.9: FFmpeg 8.0.1 사용 → normalize=0 지원
            mix_part = ''.join(mix_inputs) + f"amix=inputs={len(mix_inputs)}:duration=first:normalize=0[out]"

            if filter_parts:
                filter_complex += ';' + mix_part
            else:
                filter_complex = mix_part

        # FFmpeg 명령 실행 (v58.3.9: self.ffmpeg_path 사용)
        cmd = [
            self.ffmpeg_path, '-y',
            *input_args,
            '-filter_complex', filter_complex,
            '-map', '[out]',
            '-c:a', 'aac', '-b:a', '192k',
            output_path
        ]

        logger.debug(f"FFmpeg 명령: {' '.join(cmd)}")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
                creationflags=_NO_WINDOW,
                startupinfo=_hidden_startupinfo(),
            )

            if result.returncode != 0:
                logger.error(f"FFmpeg 오류: {result.stderr}")
                return False

            logger.info(f"믹싱 완료: {output_path}")
            return True

        except subprocess.TimeoutExpired:
            logger.error("FFmpeg 타임아웃")
            return False
        except Exception as e:
            logger.error(f"FFmpeg 실행 실패: {e}")
            return False

    def mix_sfx_to_video(
        self,
        video_path: str,
        cues: List[SFXCue],
        output_path: str,
    category: str = "daily_life_toon",
        master_volume: float = 1.0
    ) -> Tuple[bool, str, List[MixedSFX]]:
        """
        비디오 파일에 효과음 믹싱

        비디오의 오디오 트랙에 효과음을 합성

        Args:
            video_path: 원본 비디오 경로
            cues: 효과음 큐 리스트
            output_path: 출력 경로
            category: 카테고리
            master_volume: 전체 효과음 볼륨

        Returns:
            (성공여부, 출력경로, 믹싱된 효과음 정보)
        """
        if not self.ffmpeg_available:
            return False, "", []

        if not os.path.exists(video_path):
            logger.error(f"비디오 없음: {video_path}")
            return False, "", []

        if not cues:
            logger.info("효과음 큐 없음")
            import shutil
            shutil.copy(video_path, output_path)
            return True, output_path, []

        # 효과음 매칭
        mixed_sfx_list = []
        sfx_inputs = []

        video_duration_ms = self._get_video_duration(video_path)

        for cue in cues:
            sfx_info = self.sfx_manager.find_by_tag(cue.tag, category_filter=category)

            if not sfx_info:
                mixed_sfx_list.append(MixedSFX(cue=cue, sfx_info=None, actual_volume=0, success=False))
                continue

            sfx_path = self.sfx_manager.get_sfx_path(sfx_info)
            if not os.path.exists(sfx_path):
                continue

            volume_db = self.DEFAULT_SFX_VOLUME + sfx_info.volume_adjust
            volume_db *= master_volume
            volume_db += (cue.intensity - 0.5) * 6

            sfx_inputs.append({
                'path': sfx_path,
                'start_ms': cue.timestamp_ms,
                'volume_db': volume_db,
                'fade_in_ms': cue.fade_in_ms,
                'fade_out_ms': cue.fade_out_ms,
                'duration_ms': cue.duration_ms or sfx_info.duration_ms
            })

            mixed_sfx_list.append(MixedSFX(
                cue=cue,
                sfx_info=sfx_info,
                actual_volume=volume_db,
                success=True
            ))

        if not sfx_inputs:
            import shutil
            shutil.copy(video_path, output_path)
            return True, output_path, mixed_sfx_list

        # 비디오용 FFmpeg 믹싱
        success = self._mix_video_with_ffmpeg(
            video_path,
            sfx_inputs,
            output_path,
            video_duration_ms
        )

        return success, output_path if success else "", mixed_sfx_list

    def _mix_video_with_ffmpeg(
        self,
        video_path: str,
        sfx_inputs: List[Dict],
        output_path: str,
        total_duration_ms: int
    ) -> bool:
        """비디오에 효과음 믹싱"""

        input_args = ['-i', video_path]
        for sfx in sfx_inputs:
            input_args.extend(['-i', sfx['path']])

        # v58.3.9: 필터 생성 (볼륨 증폭, FFmpeg 4.x 호환)
        filter_parts = []
        sfx_labels = []  # SFX 라벨만 저장 ([0:a] 제외)

        for i, sfx in enumerate(sfx_inputs):
            input_idx = i + 1
            output_label = f'sfx{i}'

            filters = []
            volume_ratio = 10 ** (sfx['volume_db'] / 20)
            filters.append(f"volume={volume_ratio:.3f}")

            if sfx['fade_in_ms'] > 0:
                filters.append(f"afade=t=in:st=0:d={sfx['fade_in_ms']/1000}")

            if sfx['fade_out_ms'] > 0:
                duration_sec = sfx['duration_ms'] / 1000
                fade_start = max(0, duration_sec - sfx['fade_out_ms'] / 1000)
                filters.append(f"afade=t=out:st={fade_start}:d={sfx['fade_out_ms']/1000}")

            filter_chain = ','.join(filters) if filters else 'anull'

            filter_parts.append(
                f"[{input_idx}:a]{filter_chain},adelay={sfx['start_ms']}|{sfx['start_ms']},"
                f"apad=whole_dur={total_duration_ms/1000}[{output_label}]"
            )
            sfx_labels.append(f'[{output_label}]')

        # v58.3.9: 메인 오디오 볼륨 증폭 후 SFX와 믹싱
        # duration=first: 원본 비디오 길이 유지 (핵심!)
        # volume=3.0: amix 볼륨 희석 보상 (FFmpeg 4.x는 normalize 미지원)
        # v58.3.9: FFmpeg 8.0.1 사용 → normalize=0 지원
        if sfx_labels:
            # 메인 오디오 볼륨 2배 증폭 (normalize=0이면 희석 없음)
            main_amp_filter = '[0:a]volume=2.0[main_amp]'
            # SFX 필터들
            sfx_filters = ';'.join(filter_parts)
            # 믹싱: [main_amp] + [sfx0] + [sfx1] + ... (총 1 + len(sfx_labels)개)
            all_inputs = '[main_amp]' + ''.join(sfx_labels)
            # duration=first: 원본 비디오 길이 유지, normalize=0: 볼륨 희석 방지
            mix_filter = f"{all_inputs}amix=inputs={len(sfx_labels) + 1}:duration=first:normalize=0[aout]"
            filter_complex = f"{main_amp_filter};{sfx_filters};{mix_filter}"
        else:
            # SFX 없으면 볼륨 증폭만
            filter_complex = '[0:a]volume=2.0[aout]'

        # v58.3.9: self.ffmpeg_path 사용 (8.0.1 버전)
        cmd = [
            self.ffmpeg_path, '-y',
            *input_args,
            '-filter_complex', filter_complex,
            '-map', '0:v',
            '-map', '[aout]',
            '-c:v', 'copy',
            '-c:a', 'aac', '-b:a', '192k',
            output_path
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300, creationflags=_NO_WINDOW, startupinfo=_hidden_startupinfo())

            if result.returncode != 0:
                logger.error(f"FFmpeg 오류: {result.stderr}")
                return False

            logger.info(f"비디오 믹싱 완료: {output_path}")
            return True

        except Exception as e:
            logger.error(f"비디오 믹싱 실패: {e}")
            return False

    def _get_audio_duration(self, audio_path: str) -> int:
        """오디오 길이 (밀리초)"""
        try:
            # v60.1.0: config 기반 ffprobe 경로 사용 (시스템 PATH 4.3.2 방지)
            try:
                from pipeline.pipeline_utils import get_ffprobe_path
                ffprobe_cmd = get_ffprobe_path()
            except ImportError:
                ffprobe_cmd = 'ffprobe'
            cmd = [
                ffprobe_cmd, '-v', 'quiet',
                '-show_entries', 'format=duration',
                '-of', 'json',
                audio_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, creationflags=_NO_WINDOW, startupinfo=_hidden_startupinfo())
            data = json.loads(result.stdout)
            duration_sec = float(data['format']['duration'])
            # v58.3.14: int() → round()로 정밀도 향상
            return round(duration_sec * 1000)
        except Exception:
            return 60000  # 기본 1분

    def _get_video_duration(self, video_path: str) -> int:
        """비디오 길이 (밀리초)"""
        return self._get_audio_duration(video_path)


# 싱글톤
_sfx_mixer: Optional[SFXMixer] = None
_sfx_mixer_lock = threading.Lock()


def get_sfx_mixer(sfx_manager: SFXManager = None) -> SFXMixer:
    """SFXMixer 싱글톤 (Thread-safe)"""
    global _sfx_mixer

    if _sfx_mixer is None:
        with _sfx_mixer_lock:
            if _sfx_mixer is None:  # Double-check locking
                _sfx_mixer = SFXMixer(sfx_manager)

    return _sfx_mixer
