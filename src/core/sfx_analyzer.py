# src/core/sfx_analyzer.py
"""
v57.6.5: Auto-SFX 시스템 - 대본 분석기

작가가 지정한 sfx_tag를 우선 처리하고,
없는 세그먼트만 Gemini/키워드 분석으로 효과음 삽입 지점을 찾는다.

입력: 대본 텍스트 + 타이밍 정보 + sfx_tag (선택)
출력: SFXCue 리스트 (어디에 무슨 효과음을 넣을지)

"작가의 의도를 존중하고, AI가 빈 곳을 채운다"
"""
import json
import logging
import re
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, asdict
import threading

from core.sfx_manager import SFXCue, SFXTag
from utils.secret_redaction import redact_sensitive_text

logger = logging.getLogger(__name__)


@dataclass
class ScriptSegment:
    """대본 세그먼트 (타이밍 포함)"""
    index: int                      # 순서
    text: str                       # 대본 텍스트
    start_ms: int                   # 시작 시간 (밀리초)
    end_ms: int                     # 종료 시간 (밀리초)
    emotion: str = ""               # 감정 태그 (있으면)
    role: str = ""                  # v57.6.5: 역할 (narrator, man 등)
    sfx_tag: str = ""               # v57.6.5: 작가 지정 효과음 태그


class SFXAnalyzer:
    """
    대본 분석기 - Gemini를 사용하여 효과음 삽입 지점 분석

    분석 기준:
    1. 감정 변화 (긴장, 공포, 슬픔 등)
    2. 장면 전환
    3. 특정 키워드 (문이 열렸다, 비가 내렸다 등)
    4. 클라이막스/반전 순간
    """

    # 효과음 밀도 설정 (분당 최대 효과음 수)
    MAX_SFX_PER_MINUTE = 4

    def __init__(self, api_key: str = None):
        """
        Args:
            api_key: Gemini API 키 (없으면 config에서)
        """
        self.api_key = api_key
        self._lock = threading.Lock()
        self._init_gemini()

    def _init_gemini(self):
        """Gemini 초기화 (v59.3.4: gemini_compat 래퍼 사용)"""
        try:
            from utils.gemini_compat import get_gemini_model

            self.model = get_gemini_model(model_name="auto")
            if self.model:
                self.available = True
                logger.info(f"SFX Analyzer: Gemini 초기화 완료 ({getattr(self.model, 'model_name', 'unknown')})")
            else:
                self.available = False
                logger.warning("SFX Analyzer: Gemini 모델 없음, 키워드 폴백 사용")

        except Exception as e:
            logger.error(f"Gemini 초기화 실패: {redact_sensitive_text(e)}")
            self.model = None
            self.available = False

    def analyze_script(
        self,
        segments: List[ScriptSegment],
        category: str = "daily_life_toon",
        intensity: str = "medium"
    ) -> List[SFXCue]:
        """
        대본 분석하여 효과음 큐 생성

        v57.6.5: 작가 지정 sfx_tag 우선 처리
        1. sfx_tag가 있는 세그먼트 → 바로 SFXCue 생성
        2. sfx_tag가 없는 세그먼트 → AI/키워드 분석

        Args:
            segments: 대본 세그먼트 리스트 (타이밍 포함)
            category: 카테고리 (horror/emotional/comedy)
            intensity: 효과음 밀도 (low/medium/high)

        Returns:
            SFXCue 리스트
        """
        cues = []
        segments_for_analysis = []

        # v57.6.5: 작가 지정 sfx_tag 우선 처리
        for segment in segments:
            if segment.sfx_tag and segment.sfx_tag.strip():
                # 작가가 지정한 효과음 → 바로 큐 생성
                segment_duration = segment.end_ms - segment.start_ms
                # v57.6.6: 최소 500ms 보장 (0초 효과음 방지)
                auto_duration = max(500, min(round(segment_duration * 0.8), 5000))

                cue = SFXCue(
                    timestamp_ms=segment.start_ms,
                    tag=segment.sfx_tag.strip(),
                    intensity=0.7,
                    duration_ms=auto_duration,
                    fade_in_ms=200,
                    fade_out_ms=500,
                    reason=f"작가 지정: {segment.sfx_tag}"
                )
                cues.append(cue)
                logger.debug(f"작가 지정 SFX: {segment.index} → {segment.sfx_tag}")
            else:
                # sfx_tag 없음 → 분석 대상
                segments_for_analysis.append(segment)

        # 작가 지정 큐가 있으면 로그
        if cues:
            logger.info(f"작가 지정 효과음: {len(cues)}개")

        # 분석 대상이 없으면 작가 지정 큐만 반환
        if not segments_for_analysis:
            logger.info(f"모든 효과음이 작가 지정됨, AI 분석 스킵")
            return cues

        # AI 분석 또는 키워드 분석
        if not self.available or not self.model:
            logger.warning("Gemini 사용 불가, 키워드 기반 분석으로 대체")
            ai_cues = self._keyword_based_analysis(segments_for_analysis, category)
        else:
            ai_cues = self._ai_analyze_segments(segments_for_analysis, category, intensity)

        # 작가 지정 + AI 분석 결과 병합
        # VER-2: 작가 지정 개수는 병합 전에 기록
        author_cue_count = len(cues)
        cues.extend(ai_cues)

        # 타임스탬프 순 정렬
        cues.sort(key=lambda c: c.timestamp_ms)

        # v61.1 (#65): 분당 최대 SFX 수 제한 (MAX_SFX_PER_MINUTE 실제 적용)
        if len(cues) > self.MAX_SFX_PER_MINUTE:
            cues = self._limit_per_minute(cues)

        logger.info(f"최종 효과음 큐: {len(cues)}개 (작가 지정 {author_cue_count} + AI 분석 {len(ai_cues)}, 제한 후 {len(cues)})")
        return cues

    def _limit_per_minute(self, cues: List[SFXCue]) -> List[SFXCue]:
        """v61.1 (#65): 분당 MAX_SFX_PER_MINUTE 이하로 제한 (작가 지정 우선, 높은 intensity 우선)
        VER-1: 작가 지정 큐 우선 보존 (intensity 높은 것 우선 드랍)"""
        if not cues:
            return cues
        # 분별 그루핑
        from collections import defaultdict
        minute_groups: Dict[int, List[SFXCue]] = defaultdict(list)
        for cue in cues:
            minute = cue.timestamp_ms // 60000
            minute_groups[minute].append(cue)

        result = []
        for minute in sorted(minute_groups.keys()):
            group = minute_groups[minute]
            if len(group) <= self.MAX_SFX_PER_MINUTE:
                result.extend(group)
            else:
                # 작가 지정 큐 우선, 그 다음 높은 intensity 순
                def _priority(c: SFXCue):
                    is_author = 1 if c.reason.startswith("작가 지정") else 0
                    return (-is_author, -c.intensity)
                group.sort(key=_priority)
                kept = group[:self.MAX_SFX_PER_MINUTE]
                dropped = group[self.MAX_SFX_PER_MINUTE:]
                result.extend(kept)
                for d in dropped:
                    logger.debug(f"[SFX] 분당 제한 초과, 스킵: {d.tag} @{d.timestamp_ms}ms")

        # 타임스탬프 순 재정렬
        result.sort(key=lambda c: c.timestamp_ms)
        return result

    # v61.1 (#73): 배치 분석 크기
    GEMINI_BATCH_SIZE = 30

    def _ai_analyze_segments(
        self,
        segments: List[ScriptSegment],
        category: str,
        intensity: str
    ) -> List[SFXCue]:
        """
        v57.6.5: Gemini AI로 세그먼트 분석 (분리된 메서드)
        v61.1 (#73): 30턴씩 배치 분석 (105턴 한번에 보내면 토큰 한도 초과 위험)
        """
        # v61.1 (#73): 대규모 대본은 배치로 분할
        if len(segments) > self.GEMINI_BATCH_SIZE:
            import time as _time
            all_cues = []
            for _bi, batch_start in enumerate(range(0, len(segments), self.GEMINI_BATCH_SIZE)):
                # VER-10: 배치 간 rate limiting (첫 배치 제외)
                if _bi > 0:
                    _time.sleep(0.5)
                batch = segments[batch_start:batch_start + self.GEMINI_BATCH_SIZE]
                batch_cues = self._ai_analyze_batch(batch, category, intensity)
                all_cues.extend(batch_cues)
            _batch_count = (len(segments) + self.GEMINI_BATCH_SIZE - 1) // self.GEMINI_BATCH_SIZE
            logger.info(f"[SFX] 배치 분석 완료: {len(segments)}턴 → {len(all_cues)}개 큐 ({_batch_count}배치)")
            return all_cues

        return self._ai_analyze_batch(segments, category, intensity)

    def _ai_analyze_batch(
        self,
        segments: List[ScriptSegment],
        category: str,
        intensity: str
    ) -> List[SFXCue]:
        """v61.1 (#73): 단일 배치 Gemini 분석"""
        # 전체 대본 텍스트 구성
        script_with_timing = self._format_script_with_timing(segments)

        # 밀도 설정
        density_guide = {
            "low": "Minimal SFX only. Place 1-2 at the most critical moments",
            "medium": "Moderate SFX placement — effective but not excessive. 2-3 per minute",
            "high": "Maximize atmosphere with active SFX usage. 3-4 per minute"
        }

        # v60: 팩에서 SFX 카테고리 가이드 로딩 (하드코딩 제거)
        pack_category_guide = ""
        try:
            from config.pack_config import get_sfx_config, PACK_CONFIG_AVAILABLE
            if PACK_CONFIG_AVAILABLE:
                sfx_config = get_sfx_config()
                if sfx_config and sfx_config.category_guide:
                    pack_category_guide = sfx_config.category_guide
        except ImportError:
            pass

        if not pack_category_guide:
            # 팩 없을 때 기본 폴백
            pack_category_guide = """
This is a video. Use the following SFX tags as appropriate:
- tension: When tension builds (background drone sound)
- suspense: When something is about to happen
- dramatic: Dramatic/climactic moments (orchestral sting)
- sad: Sad moments (piano)
- happy: Joyful moments (notification chime)
- angry: Angry/confrontational moments (heavy impact)
- footsteps: Someone approaching
- door: Door opening/closing
- wind: Wind sounds
- rain: Rain sounds
- whoosh: Scene transitions
"""

        prompt = f"""You are a professional video sound effects (SFX) placement specialist.
Analyze the script below and identify the optimal positions for sound effects.

[Category & SFX Guide]
{pack_category_guide}

[Density Guide]
{density_guide.get(intensity, density_guide['medium'])}

[Script] (Each line: index | start_time_ms | end_time_ms | text)
{script_with_timing}

[Response Rules]
1. Sound effects are inserted at the START of a specific script segment
2. Do NOT use the same SFX tag consecutively
3. Place SFX only at the most dramatically effective moments
4. Jumpscare SFX: maximum 1-2 per entire video

[Response Format — Output ONLY this JSON]
```json
{{
    "cues": [
        {{
            "segment_index": 0,
            "tag": "tension",
            "intensity": 0.7,
            "fade_in_ms": 500,
            "fade_out_ms": 1000,
            "reason": "Tension buildup begins"
        }},
        ...
    ],
    "summary": "Overall SFX placement summary"
}}
```

Analyze the script and respond with ONLY the JSON format above.
"""

        try:
            with self._lock:
                response = self.model.generate_content(prompt)
                response_text = response.text

            cues = self._parse_analysis_response(response_text, segments)
            logger.info(f"AI 분석 완료: {len(cues)}개 효과음 큐 생성")
            return cues

        except Exception as e:
            logger.error(f"AI 분석 실패: {redact_sensitive_text(e)}")
            return self._keyword_based_analysis(segments, category)

    def _format_script_with_timing(self, segments: List[ScriptSegment]) -> str:
        """타이밍 포함 대본 포맷"""
        lines = []
        for seg in segments:
            lines.append(f"{seg.index} | {seg.start_ms} | {seg.end_ms} | {seg.text}")
        return "\n".join(lines)

    def _parse_analysis_response(
        self,
        response_text: str,
        segments: List[ScriptSegment]
    ) -> List[SFXCue]:
        """Gemini 응답 파싱"""
        try:
            # JSON 블록 추출
            json_match = re.search(r'```json\s*(.*?)\s*```', response_text, re.DOTALL)

            if json_match:
                json_str = json_match.group(1)
            else:
                json_str = response_text

            data = json.loads(json_str)
            cues = []

            # v61.1 (#63): segment_index → 실제 세그먼트 역매핑
            # Gemini에게 보낸 segments는 sfx_tag 없는 부분집합이므로
            # segment.index(원본 인덱스)와 리스트 위치가 다를 수 있음
            # Gemini 프롬프트에서 segment.index를 표시했으므로 응답도 원본 인덱스 기준
            idx_to_segment = {seg.index: seg for seg in segments}

            for cue_data in data.get('cues', []):
                seg_idx = cue_data.get('segment_index', 0)

                # v61.1 (#63): 원본 인덱스로 매핑 (리스트 위치가 아닌 segment.index)
                segment = idx_to_segment.get(seg_idx)
                if segment is None:
                    # 폴백: 리스트 위치로도 시도
                    if 0 <= seg_idx < len(segments):
                        segment = segments[seg_idx]
                    else:
                        logger.debug(f"[SFX] 유효하지 않은 segment_index: {seg_idx}")
                        continue

                # v61.1 (#67): 타입별 SFX 길이 — ambient는 턴 전체, point는 최대 5초
                segment_duration = segment.end_ms - segment.start_ms
                _tag = cue_data.get('tag', 'tension')
                _ambient_tags = {'rain', 'wind', 'night', 'thunder', 'breathing'}
                if _tag in _ambient_tags:
                    # ambient: 세그먼트 전체 길이 (최대 30초)
                    auto_duration = max(500, min(segment_duration, 30000))
                else:
                    # point: 최대 5초
                    auto_duration = max(500, min(round(segment_duration * 0.8), 5000))

                cue = SFXCue(
                    timestamp_ms=segment.start_ms,
                    tag=_tag,
                    intensity=cue_data.get('intensity', 0.7),
                    duration_ms=auto_duration,  # v53: 자동 계산된 길이
                    fade_in_ms=cue_data.get('fade_in_ms', 0),
                    fade_out_ms=cue_data.get('fade_out_ms', 500),
                    reason=cue_data.get('reason', '')
                )
                cues.append(cue)

            return cues

        except json.JSONDecodeError as e:
            logger.warning(f"JSON 파싱 실패: {e}")
            return []

    def _keyword_based_analysis(
        self,
        segments: List[ScriptSegment],
        category: str
    ) -> List[SFXCue]:
        """
        키워드 기반 분석 (Gemini 실패 시 폴백)

        특정 키워드가 포함된 세그먼트에 효과음 배치
        """
        cues = []

        # v60: 팩에서 키워드 → 태그 매핑 로딩 (하드코딩 제거)
        pack_keyword_map = {}
        try:
            from config.pack_config import get_sfx_config, PACK_CONFIG_AVAILABLE
            if PACK_CONFIG_AVAILABLE:
                sfx_config = get_sfx_config()
                if sfx_config and sfx_config.keyword_map:
                    pack_keyword_map = sfx_config.keyword_map
        except ImportError:
            pass

        if not pack_keyword_map:
            # 팩 없을 때 최소 폴백
            pack_keyword_map = {
                "긴장": SFXTag.TENSION.value,
                "두려": SFXTag.TENSION.value,
                "심장": SFXTag.HEARTBEAT.value,
                "갑자기": SFXTag.JUMPSCARE.value,
                "문이": SFXTag.DOOR.value,
                "발자국": SFXTag.FOOTSTEPS.value,
                "속삭": SFXTag.WHISPER.value,
                "비가": SFXTag.RAIN.value,
                "바람": SFXTag.WIND.value,
                "눈물": SFXTag.CRYING.value,
                "슬프": SFXTag.SAD.value,
                # v61.1 (VER-5): dramatic/angry 매핑
                "분노": SFXTag.ANGRY.value,
                "극적": SFXTag.DRAMATIC.value,
                "화가": SFXTag.ANGRY.value,
            }

        keywords = pack_keyword_map
        used_timestamps = set()

        for segment in segments:
            text_lower = segment.text.lower()

            for keyword, tag in keywords.items():
                # v61.1 (#66): 2글자 이하 키워드는 단어 경계 검사 (substring 오매칭 방지)
                if len(keyword) <= 2:
                    # v61.1 (#66): 키워드 전후에 조사/공백/구두점이 있어야 매칭
                    # VER-12: module-level re 사용 (루프 내 import 제거)
                    if not re.search(rf'(?:^|[\s,.!?]){re.escape(keyword)}(?:[\s,.!?가-힣]|$)', text_lower):
                        continue
                    matched = True
                else:
                    matched = keyword in text_lower
                if matched:
                    # 중복 방지 (같은 타임스탬프에 여러 효과음 X)
                    if segment.start_ms in used_timestamps:
                        continue

                    # v53: 세그먼트 길이 기반 효과음 길이 자동 계산
                    segment_duration = segment.end_ms - segment.start_ms
                    # v57.6.6: 최소 500ms 보장 (0초 효과음 방지)
                    auto_duration = max(500, min(round(segment_duration * 0.8), 5000))

                    cue = SFXCue(
                        timestamp_ms=segment.start_ms,
                        tag=tag,
                        intensity=0.7,
                        duration_ms=auto_duration,  # v53: 자동 계산된 길이
                        fade_in_ms=200,
                        fade_out_ms=500,
                        reason=f"키워드 감지: '{keyword}'"
                    )
                    cues.append(cue)
                    used_timestamps.add(segment.start_ms)
                    break  # 세그먼트당 하나만

        logger.info(f"키워드 분석 완료: {len(cues)}개 효과음 큐")
        return cues

    def analyze_from_scenario(
        self,
        scenario: Dict[str, Any],
    category: str = "daily_life_toon"
    ) -> List[SFXCue]:
        """
        시나리오 딕셔너리에서 직접 분석

        ⚠️ 레거시 경로: 현재 파이프라인(v57.6.5+)은 subtitle_data 기반
        convert_segments_v2()를 사용하여 실제 TTS 타이밍을 활용합니다.
        이 메서드는 subtitle_data 없이 시나리오만으로 분석할 때의 폴백입니다.

        Args:
            scenario: 시나리오 딕셔너리 (scenes 포함)
            category: 카테고리

        Returns:
            SFXCue 리스트
        """
        segments = []
        current_ms = 0

        # 씬에서 세그먼트 추출
        for idx, scene in enumerate(scenario.get('scenes', [])):
            narration = scene.get('narration', '')

            # v61.1 (#76): 글자당 100ms는 추정치 (실제 TTS 타이밍과 다를 수 있음)
            # 현재 파이프라인에서는 convert_segments_v2()로 실제 타이밍 사용
            duration_ms = len(narration) * 100
            if duration_ms < 2000:
                duration_ms = 2000

            segment = ScriptSegment(
                index=idx,
                text=narration,
                start_ms=current_ms,
                end_ms=current_ms + duration_ms,
                emotion=scene.get('emotion', '')
            )
            segments.append(segment)
            current_ms += duration_ms

        return self.analyze_script(segments, category)


# 싱글톤
_sfx_analyzer: Optional[SFXAnalyzer] = None
_sfx_analyzer_lock = threading.Lock()


def get_sfx_analyzer(api_key: str = None) -> SFXAnalyzer:
    """SFXAnalyzer 싱글톤 (Thread-safe)"""
    global _sfx_analyzer

    if _sfx_analyzer is None:
        with _sfx_analyzer_lock:
            if _sfx_analyzer is None:  # Double-check locking
                _sfx_analyzer = SFXAnalyzer(api_key)

    return _sfx_analyzer
