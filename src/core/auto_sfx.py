# src/core/auto_sfx.py
"""
v53: Auto-SFX 통합 엔진

모든 SFX 기능을 하나로 통합한 간편 API

사용법:
    from core.auto_sfx import AutoSFX

    sfx = AutoSFX()

    # 대본에서 효과음 자동 추가
    output_video = sfx.process_video(
        video_path="output/video.mp4",
        script_segments=segments,
        category="horror"
    )

"한 줄로 효과음 자동 추가"
"""
import os
import logging
import threading
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, asdict

from core.sfx_manager import SFXManager, SFXCue, SFXInfo, SFXTag, get_sfx_manager
from core.sfx_analyzer import SFXAnalyzer, ScriptSegment, get_sfx_analyzer
from core.sfx_mixer import SFXMixer, MixedSFX, get_sfx_mixer

logger = logging.getLogger(__name__)


@dataclass
class AutoSFXResult:
    """Auto-SFX 처리 결과"""
    success: bool
    output_path: str
    cues_generated: int             # 생성된 큐 수
    cues_applied: int               # 적용된 큐 수
    mixed_sfx: List[MixedSFX]       # 믹싱된 효과음 정보
    analysis_method: str            # 분석 방법 (gemini/keyword)
    errors: List[str]               # 오류 목록

    def to_dict(self) -> Dict:
        return {
            'success': self.success,
            'output_path': self.output_path,
            'cues_generated': self.cues_generated,
            'cues_applied': self.cues_applied,
            'analysis_method': self.analysis_method,
            'errors': self.errors,
            'sfx_details': [
                {
                    'tag': m.cue.tag,
                    'timestamp_ms': m.cue.timestamp_ms,
                    'filename': m.sfx_info.filename if m.sfx_info else None,
                    'success': m.success
                }
                for m in self.mixed_sfx
            ]
        }


class AutoSFX:
    """
    Auto-SFX 통합 엔진

    대본 → 분석 → 효과음 매칭 → 믹싱을 한 번에 처리
    """

    def __init__(
        self,
        sfx_dir: str = None,
        api_key: str = None
    ):
        """
        Args:
            sfx_dir: 효과음 폴더 경로 (기본: assets/sfx)
            api_key: Gemini API 키 (대본 분석용)
        """
        self.sfx_dir = sfx_dir or "assets/sfx"

        # 컴포넌트 초기화
        self.manager = get_sfx_manager(self.sfx_dir)
        self.analyzer = get_sfx_analyzer(api_key)
        self.mixer = get_sfx_mixer(self.manager)

        # 초기 스캔
        self._scan_sfx_library()

    def _scan_sfx_library(self):
        """효과음 라이브러리 스캔"""
        new_count = self.manager.scan_directory()
        if new_count > 0:
            logger.info(f"새 효과음 {new_count}개 등록됨")

    def process_video(
        self,
        video_path: str,
        script_segments: List[ScriptSegment] = None,
        scenario: Dict[str, Any] = None,
        category: str = "daily_life_toon",
        intensity: str = "medium",
        master_volume: float = 1.0,
        output_path: str = None
    ) -> AutoSFXResult:
        """
        비디오에 효과음 자동 추가

        Args:
            video_path: 원본 비디오 경로
            script_segments: 대본 세그먼트 (직접 제공)
            scenario: 시나리오 딕셔너리 (scenes 포함)
            category: 카테고리 (horror/emotional/comedy)
            intensity: 효과음 밀도 (low/medium/high)
            master_volume: 전체 볼륨 (0.0 ~ 2.0)
            output_path: 출력 경로 (없으면 자동 생성)

        Returns:
            AutoSFXResult
        """
        errors = []

        # 입력 검증
        if not os.path.exists(video_path):
            return AutoSFXResult(
                success=False,
                output_path="",
                cues_generated=0,
                cues_applied=0,
                mixed_sfx=[],
                analysis_method="none",
                errors=[f"비디오 파일 없음: {video_path}"]
            )

        # 출력 경로 생성
        if not output_path:
            base, ext = os.path.splitext(video_path)
            output_path = f"{base}_sfx{ext}"

        # 1. 대본 분석
        analysis_method = "none"

        if script_segments:
            # 직접 제공된 세그먼트 사용
            cues = self.analyzer.analyze_script(
                script_segments,
                category=category,
                intensity=intensity
            )
            analysis_method = "gemini" if self.analyzer.available else "keyword"

        elif scenario:
            # 시나리오에서 추출
            cues = self.analyzer.analyze_from_scenario(scenario, category)
            analysis_method = "gemini" if self.analyzer.available else "keyword"

        else:
            # 대본 없음 - 효과음 추가 불가
            logger.warning("대본 정보 없음, 효과음 추가 생략")
            import shutil
            shutil.copy(video_path, output_path)
            return AutoSFXResult(
                success=True,
                output_path=output_path,
                cues_generated=0,
                cues_applied=0,
                mixed_sfx=[],
                analysis_method="none",
                errors=["대본 정보 없음"]
            )

        logger.info(f"분석 완료: {len(cues)}개 효과음 큐 ({analysis_method})")

        # 2. 효과음 믹싱
        success, final_path, mixed_sfx = self.mixer.mix_sfx_to_video(
            video_path=video_path,
            cues=cues,
            output_path=output_path,
            category=category,
            master_volume=master_volume
        )

        if not success:
            errors.append("효과음 믹싱 실패")

        # 적용된 효과음 수 계산
        applied_count = sum(1 for m in mixed_sfx if m.success)

        return AutoSFXResult(
            success=success,
            output_path=final_path,
            cues_generated=len(cues),
            cues_applied=applied_count,
            mixed_sfx=mixed_sfx,
            analysis_method=analysis_method,
            errors=errors
        )

    def process_audio(
        self,
        audio_path: str,
        script_segments: List[ScriptSegment],
        category: str = "daily_life_toon",
        intensity: str = "medium",
        master_volume: float = 1.0,
        output_path: str = None
    ) -> AutoSFXResult:
        """
        오디오에 효과음 자동 추가

        Args:
            audio_path: 원본 오디오 경로
            script_segments: 대본 세그먼트
            category: 카테고리
            intensity: 밀도
            master_volume: 볼륨
            output_path: 출력 경로

        Returns:
            AutoSFXResult
        """
        errors = []

        if not os.path.exists(audio_path):
            return AutoSFXResult(
                success=False,
                output_path="",
                cues_generated=0,
                cues_applied=0,
                mixed_sfx=[],
                analysis_method="none",
                errors=[f"오디오 파일 없음: {audio_path}"]
            )

        if not output_path:
            base, ext = os.path.splitext(audio_path)
            output_path = f"{base}_sfx{ext}"

        # 분석
        cues = self.analyzer.analyze_script(
            script_segments,
            category=category,
            intensity=intensity
        )
        analysis_method = "gemini" if self.analyzer.available else "keyword"

        # 믹싱
        success, final_path, mixed_sfx = self.mixer.mix_sfx_to_audio(
            audio_path=audio_path,
            cues=cues,
            output_path=output_path,
            category=category,
            master_volume=master_volume
        )

        if not success:
            errors.append("효과음 믹싱 실패")

        applied_count = sum(1 for m in mixed_sfx if m.success)

        return AutoSFXResult(
            success=success,
            output_path=final_path,
            cues_generated=len(cues),
            cues_applied=applied_count,
            mixed_sfx=mixed_sfx,
            analysis_method=analysis_method,
            errors=errors
        )

    def add_sfx_manually(
        self,
        video_path: str,
        cues: List[Dict[str, Any]],
        category: str = "daily_life_toon",
        output_path: str = None
    ) -> AutoSFXResult:
        """
        수동으로 효과음 큐 지정하여 추가

        Args:
            video_path: 비디오 경로
            cues: 효과음 큐 딕셔너리 리스트
                  [{'timestamp_ms': 5000, 'tag': 'tension'}, ...]
            category: 카테고리
            output_path: 출력 경로

        Returns:
            AutoSFXResult
        """
        # 딕셔너리를 SFXCue로 변환
        sfx_cues = []
        for cue_dict in cues:
            sfx_cue = SFXCue(
                timestamp_ms=cue_dict.get('timestamp_ms', 0),
                tag=cue_dict.get('tag', 'tension'),
                intensity=cue_dict.get('intensity', 0.7),
                fade_in_ms=cue_dict.get('fade_in_ms', 200),
                fade_out_ms=cue_dict.get('fade_out_ms', 500),
                reason=cue_dict.get('reason', '수동 추가')
            )
            sfx_cues.append(sfx_cue)

        if not output_path:
            base, ext = os.path.splitext(video_path)
            output_path = f"{base}_sfx{ext}"

        # 믹싱
        success, final_path, mixed_sfx = self.mixer.mix_sfx_to_video(
            video_path=video_path,
            cues=sfx_cues,
            output_path=output_path,
            category=category
        )

        applied_count = sum(1 for m in mixed_sfx if m.success)

        return AutoSFXResult(
            success=success,
            output_path=final_path,
            cues_generated=len(sfx_cues),
            cues_applied=applied_count,
            mixed_sfx=mixed_sfx,
            analysis_method="manual",
            errors=[] if success else ["믹싱 실패"]
        )

    def get_available_tags(self) -> List[str]:
        """사용 가능한 효과음 태그 목록"""
        return [tag.value for tag in SFXTag]

    def get_sfx_stats(self) -> Dict[str, Any]:
        """효과음 라이브러리 통계"""
        return self.manager.get_stats()

    def preview_analysis(
        self,
        script_segments: List[ScriptSegment],
        category: str = "daily_life_toon"
    ) -> List[Dict[str, Any]]:
        """
        대본 분석 미리보기 (실제 믹싱 없이)

        Returns:
            효과음 큐 리스트 (딕셔너리)
        """
        cues = self.analyzer.analyze_script(script_segments, category)
        return [cue.to_dict() for cue in cues]


# 싱글톤
_auto_sfx: Optional[AutoSFX] = None
_auto_sfx_lock = threading.Lock()


def get_auto_sfx(sfx_dir: str = None, api_key: str = None) -> AutoSFX:
    """AutoSFX 싱글톤 (Thread-safe)"""
    global _auto_sfx

    if _auto_sfx is None:
        with _auto_sfx_lock:
            if _auto_sfx is None:  # Double-check locking
                _auto_sfx = AutoSFX(sfx_dir, api_key)

    return _auto_sfx


# 편의 함수
def add_sfx_to_video(
    video_path: str,
    scenario: Dict[str, Any] = None,
    category: str = "daily_life_toon",
    intensity: str = "medium"
) -> str:
    """
    비디오에 효과음 추가 (간편 API)

    Args:
        video_path: 비디오 경로
        scenario: 시나리오 딕셔너리
        category: 카테고리
        intensity: 밀도

    Returns:
        출력 비디오 경로 (실패시 원본 경로)
    """
    sfx = get_auto_sfx()
    result = sfx.process_video(
        video_path=video_path,
        scenario=scenario,
        category=category,
        intensity=intensity
    )

    if result.success:
        logger.info(f"효과음 추가 완료: {result.cues_applied}개")
        return result.output_path
    else:
        logger.warning(f"효과음 추가 실패: {result.errors}")
        return video_path
