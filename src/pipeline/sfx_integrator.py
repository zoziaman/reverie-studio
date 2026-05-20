# src/pipeline/sfx_integrator.py
"""
v60.1.0 Phase 6: SFX 통합 모듈

media_factory.py에서 추출한 SFX → Remotion 통합 + 레거시 FFmpeg SFX 로직.
- _prepare_sfx_for_remotion → prepare_for_remotion()
- _apply_auto_sfx → apply_auto_sfx()
- _convert_to_script_segments_v2 → convert_segments_v2()
- _convert_to_script_segments → convert_segments()

원본 위치: media_factory.py L1772-2088
"""
import os
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


class SFXIntegrator:
    """SFX 효과음 분석 + Remotion 통합

    Auto-SFX 시스템(Gemini/키워드 분석)의 결과를
    RemotionAssembler에 전달하거나 FFmpeg으로 믹싱.
    """

    def __init__(self, assets_dir: str, gemini_api_key: str = ""):
        self.assets_dir = assets_dir
        self.gemini_api_key = gemini_api_key
        self._auto_sfx_available = False
        self._AutoSFX = None
        self._ScriptSegment = None

        # Auto-SFX 모듈 가용성 체크
        try:
            from core.auto_sfx import AutoSFX
            from core.sfx_analyzer import ScriptSegment
            self._auto_sfx_available = True
            self._AutoSFX = AutoSFX
            self._ScriptSegment = ScriptSegment
        except ImportError:
            logger.warning("[SFXIntegrator] Auto-SFX 모듈 없음")

    @property
    def available(self) -> bool:
        """Auto-SFX 사용 가능 여부"""
        return self._auto_sfx_available

    # ============================================================
    # SFX → Remotion 통합 (v59.3.5, ACTIVE)
    # ============================================================

    def prepare_for_remotion(
        self,
        assembler,
        subtitle_data: List[Dict[str, Any]],
        script_list: List[Dict[str, Any]],
        channel: str,
        data_dir: str,
        mode: str = ""
    ):
        """
        v59.3.5: SFX 분석 + 매칭 결과를 RemotionAssembler에 전달

        기존: Remotion 렌더링 후 FFmpeg로 SFX 믹싱 (재인코딩, 5분 추가)
        변경: Remotion 렌더링 시 <Audio> 컴포넌트로 SFX 직접 포함 (0초 추가)
        """
        if not self._auto_sfx_available:
            return

        # GUI 설정에서 Auto-SFX 활성화 여부 확인
        if not self._check_sfx_enabled(data_dir):
            logger.info("[v59.3.5] SFX 비활성화 (GUI 설정)")
            return

        try:
            from pipeline.pipeline_utils import safe_print

            safe_print("   🔊 [v59.3.5] SFX 분석 → Remotion 통합...")

            # 대본 세그먼트 변환
            segments = self.convert_segments_v2(script_list, subtitle_data)
            if not segments:
                logger.warning("[v59.3.5] SFX 세그먼트 변환 실패")
                return

            # SFX 분석 (Gemini/키워드)
            sfx_dir = os.path.join(self.assets_dir, "sfx")
            auto_sfx = self._AutoSFX(sfx_dir=sfx_dir, api_key=self.gemini_api_key)

            # v60: 팩에서 SFX 카테고리/밀도 로딩
            sfx_category, sfx_intensity = self._get_sfx_pack_config(channel)

            # daily 영상툰은 common/emotional/ambient 효과음을 함께 쓰므로 카테고리 필터를 걸지 않는다.
            analysis_category = (sfx_category or channel or "horror").strip()
            unfiltered_categories = {"daily", "daily_life_toon", "videotoon", "all", "*"}
            category_filter = None if analysis_category in unfiltered_categories else analysis_category

            # 분석만 수행 (믹싱 X)
            cues = auto_sfx.analyzer.analyze_script(
                segments,
                category=analysis_category,
                intensity=sfx_intensity
            )

            if not cues:
                safe_print("   ⚠️ [SFX] 분석 결과 0개")
                return

            # 큐 → SFX 파일 매칭
            sfx_cue_data = []
            for cue in cues:
                # v61.1 (#68): category_filter가 빈 문자열이면 None으로 (필터 비활성화)
                _cat_filter = category_filter
                sfx_info = auto_sfx.manager.find_by_tag(
                    cue.tag, category_filter=_cat_filter
                )
                if not sfx_info:
                    continue

                sfx_path = auto_sfx.manager.get_sfx_path(sfx_info)
                if not os.path.exists(sfx_path):
                    continue

                # 볼륨 계산 (0.0~1.0 스케일)
                base_volume = 0.3
                volume = base_volume * cue.intensity

                # VER-9: duration_ms를 실제 파일 길이로 cap (침묵/반복 방지)
                cue_duration = cue.duration_ms or 0
                sfx_actual_duration = getattr(sfx_info, 'duration_ms', 0) or 0
                if sfx_actual_duration > 0 and cue_duration > sfx_actual_duration:
                    cue_duration = sfx_actual_duration
                    logger.debug(f"[SFX] duration cap: {cue.tag} {cue.duration_ms}ms → {sfx_actual_duration}ms (실제 파일 길이)")

                sfx_cue_data.append({
                    'sfx_path': sfx_path,
                    'timestamp_ms': cue.timestamp_ms,
                    'volume': min(volume, 0.7),
                    'duration_ms': cue_duration,
                    'fade_in_ms': cue.fade_in_ms,
                    'fade_out_ms': cue.fade_out_ms,
                })

            if sfx_cue_data:
                assembler.set_sfx_cues(sfx_cue_data)
                tagged_count = sum(1 for s in segments if getattr(s, 'sfx_tag', ''))
                safe_print(f"   ✅ [SFX] {len(sfx_cue_data)}개 효과음 → Remotion 통합 (작가 지정: {tagged_count}개)")
            else:
                safe_print("   ⚠️ [SFX] 매칭된 효과음 0개")

        except Exception as e:
            logger.warning(f"[v59.3.5] SFX Remotion 통합 실패 (무시): {e}")
            try:
                from pipeline.pipeline_utils import safe_print
                safe_print(f"   ⚠️ [SFX] 통합 실패, 효과음 없이 진행: {e}")
            except ImportError:
                pass

    # ============================================================
    # Auto-SFX 레거시 (v57.6.5, FFmpeg 기반 — v59.3.5에서 대체됨)
    # ============================================================

    def apply_auto_sfx(
        self,
        video_path: str,
        script_list: List[Dict[str, Any]],
        subtitle_data: List[Dict[str, Any]],
        channel: str,
        data_dir: str,
        category: str = "",
        mode: str = ""
    ) -> str:
        """
        Auto-SFX로 효과음 자동 삽입 (레거시 FFmpeg 방식)

        v57.6.5: sfx_tag 우선 처리 + subtitle_data 실제 타이밍 활용
        v59.3.5에서 Remotion 통합으로 대체되어 현재 미사용

        Returns:
            str: 효과음이 적용된 비디오 경로 (실패 시 원본 경로)
        """
        if not self._auto_sfx_available:
            logger.warning("[Auto-SFX] 모듈 없음 - 효과음 삽입 생략")
            return video_path

        if not self._check_sfx_enabled(data_dir):
            logger.info("[Auto-SFX] GUI에서 비활성화됨 - 효과음 삽입 생략")
            return video_path

        try:
            from pipeline.pipeline_utils import safe_print
            safe_print("\n🔊 [Auto-SFX] 효과음 자동 삽입 중...")

            segments = self.convert_segments_v2(script_list, subtitle_data)
            if not segments:
                logger.warning("[Auto-SFX] 세그먼트 변환 실패")
                return video_path

            tagged_count = sum(1 for s in segments if getattr(s, 'sfx_tag', ''))
            logger.info(f"[Auto-SFX] 작가 지정 sfx_tag: {tagged_count}개")

            sfx_dir = os.path.join(self.assets_dir, "sfx")
            auto_sfx = self._AutoSFX(sfx_dir=sfx_dir, api_key=self.gemini_api_key)

            # v60: 팩에서 SFX 설정
            sfx_category, intensity = self._get_sfx_pack_config(category or channel)

            base, ext = os.path.splitext(video_path)
            output_path = f"{base}_sfx{ext}"

            result = auto_sfx.process_video(
                video_path=video_path,
                script_segments=segments,
                category=sfx_category,
                intensity=intensity,
                master_volume=0.7,
                output_path=output_path
            )

            if result.success and result.cues_applied > 0:
                safe_print(f"   ✅ [Auto-SFX] 완료: {result.cues_applied}개 효과음 적용 (작가 지정: {tagged_count}개)")
                logger.info(f"[Auto-SFX] 성공: {result.cues_generated}개 분석, {result.cues_applied}개 적용 ({result.analysis_method})")

                try:
                    os.remove(video_path)
                    os.rename(output_path, video_path)
                    logger.info(f"[Auto-SFX] 원본 교체 완료: {video_path}")
                except Exception as e:
                    logger.warning(f"[Auto-SFX] 파일 교체 실패: {e}")
                    return output_path

                return video_path
            else:
                safe_print(f"   ⚠️ [Auto-SFX] 효과음 0개 적용 (분석: {result.cues_generated}개)")
                if result.errors:
                    for err in result.errors:
                        logger.warning(f"[Auto-SFX] 오류: {err}")
                return video_path

        except Exception as e:
            logger.error(f"[Auto-SFX] 예외 발생: {e}")
            return video_path

    # ============================================================
    # 세그먼트 변환
    # ============================================================

    def convert_segments_v2(
        self,
        script_list: List[Dict[str, Any]],
        subtitle_data: List[Dict[str, Any]]
    ) -> List:
        """
        v57.6.5: script_list + subtitle_data → ScriptSegment 리스트

        subtitle_data의 실제 TTS 타이밍을 사용하고,
        script_list의 sfx_tag를 포함시킴
        """
        if not self._auto_sfx_available:
            return []

        ScriptSegment = self._ScriptSegment
        segments = []

        for i, sub in enumerate(subtitle_data):
            role = sub.get("role", "narrator")
            # v62.10: subtitle_data에 직접 sfx_tag/emotion 포함됨 (_split_subtitle_entry가 dict 복사로 전파)
            # 이전 방식(script_list[i])은 split 후 길이 불일치로 sfx_tag 누락 위험
            sfx_tag = sub.get("sfx_tag", "")
            emotion = sub.get("emotion", "calm")
            # v62.19: 폴백 가드 강화 — subtitle 분할 후 인덱스 불일치 방지
            # script_list 폴백은 분할 전 원본 인덱스와 매칭될 때만 안전
            # 분할된 subtitle은 sub.get()에 이미 sfx_tag/emotion이 전파되므로 폴백 불필요
            # 그래도 구버전 호환을 위해 script_list 길이 === subtitle_data 길이일 때만 폴백
            if not sfx_tag and len(script_list) == len(subtitle_data) and i < len(script_list):
                sfx_tag = script_list[i].get("sfx_tag", "")
            if emotion == "calm" and len(script_list) == len(subtitle_data) and i < len(script_list):
                emotion = script_list[i].get("emotion", "calm")

            start_ms = round(sub.get("start", 0) * 1000)
            end_ms = round(sub.get("end", 0) * 1000)

            segment = ScriptSegment(
                index=i,
                text=sub.get("text", ""),
                role=role,
                emotion=emotion,
                start_ms=start_ms,
                end_ms=end_ms
            )
            segment.sfx_tag = sfx_tag
            segments.append(segment)

        logger.debug(f"[Auto-SFX] {len(segments)}개 세그먼트 변환 완료 (실제 TTS 타이밍 사용)")
        return segments

    def convert_segments(
        self,
        script_list: List[Dict[str, Any]],
        channel: str = ""
    ) -> List:
        """
        script_list → ScriptSegment 리스트 (예상 타이밍)

        레거시: subtitle_data 없이 글자수 기반 타이밍 추정
        """
        if not self._auto_sfx_available:
            return []

        ScriptSegment = self._ScriptSegment
        segments = []
        current_time_ms = 0

        for i, item in enumerate(script_list):
            text = item.get("text", "")
            role = item.get("role", "narrator")
            emotion = item.get("emotion", "calm")

            char_count = len(text)
            duration_ms = max(1000, char_count * 100)

            segment = ScriptSegment(
                index=i,
                text=text,
                role=role,
                emotion=emotion,
                start_ms=current_time_ms,
                end_ms=current_time_ms + duration_ms
            )
            segments.append(segment)

            pause_ms = 400 if channel == "horror" else 500
            current_time_ms += duration_ms + pause_ms

        logger.debug(f"[Auto-SFX] {len(segments)}개 세그먼트 변환 완료")
        return segments

    # ============================================================
    # 내부 헬퍼
    # ============================================================

    def _check_sfx_enabled(self, data_dir: str) -> bool:
        """GUI 설정에서 SFX 활성화 여부 확인"""
        try:
            from gui.settings_manager import SettingsManager
            sm = SettingsManager(data_dir)
            return sm.get_sfx_enabled()
        except Exception:
            return True  # 기본값: 활성화

    def _get_sfx_pack_config(self, fallback_category: str) -> tuple:
        """팩에서 SFX 카테고리/밀도 로딩

        Returns:
            (sfx_category, sfx_intensity) tuple
        """
        try:
            from config.pack_config import ACTIVE_PACK, PACK_CONFIG_AVAILABLE
            if PACK_CONFIG_AVAILABLE and ACTIVE_PACK.is_loaded:
                sfx_category = getattr(ACTIVE_PACK.assets, 'sfx_category', fallback_category) if hasattr(ACTIVE_PACK, 'assets') else fallback_category
                sfx_intensity = getattr(ACTIVE_PACK.assets, 'sfx_intensity', 'medium') if hasattr(ACTIVE_PACK, 'assets') else 'medium'
                return sfx_category, sfx_intensity
        except ImportError:
            pass
        return fallback_category, "medium"
