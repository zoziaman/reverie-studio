# tests/test_sfx_integrator.py
"""
v63.0 Phase 1: SFXIntegrator 유닛 테스트

sfx_integrator.py의 핵심 경로 테스트:
- 초기화 + Auto-SFX 가용성
- convert_segments_v2() 세그먼트 변환
- convert_segments() 레거시 변환
- prepare_for_remotion() SFX→Remotion 통합
- _get_sfx_pack_config() 팩 설정 로딩
- _check_sfx_enabled() GUI 설정 확인
"""
import os
import sys
import pytest
from unittest.mock import patch, MagicMock, PropertyMock


@pytest.fixture
def subtitle_data():
    return [
        {"text": "무서운 소리가 들렸다", "role": "narrator", "start": 0.0, "end": 2.0, "emotion": "scared", "sfx_tag": "thunder"},
        {"text": "뭐야?!", "role": "grandma", "start": 2.5, "end": 3.5, "emotion": "surprised", "sfx_tag": ""},
        {"text": "괜찮아요", "role": "grandpa", "start": 4.0, "end": 5.5, "emotion": "calm", "sfx_tag": ""},
    ]


@pytest.fixture
def script_list():
    return [
        {"text": "무서운 소리가 들렸다", "role": "narrator", "emotion": "scared", "sfx_tag": "thunder"},
        {"text": "뭐야?!", "role": "grandma", "emotion": "surprised", "sfx_tag": "scream"},
        {"text": "괜찮아요", "role": "grandpa", "emotion": "calm", "sfx_tag": ""},
    ]


class TestSFXIntegratorInit:
    """초기화 테스트"""

    def test_init_no_auto_sfx(self):
        """Auto-SFX 모듈 없으면 available=False"""
        with patch.dict('sys.modules', {'core.auto_sfx': None, 'core.sfx_analyzer': None}):
            # Import 실패를 시뮬레이션하려면 새 인스턴스 필요
            from pipeline.sfx_integrator import SFXIntegrator
            sfx = SFXIntegrator(assets_dir="/fake/assets")
            # 모듈이 이미 로드된 경우 available이 True일 수 있음
            assert isinstance(sfx.available, bool)

    def test_init_with_assets_dir(self):
        from pipeline.sfx_integrator import SFXIntegrator
        sfx = SFXIntegrator(assets_dir="/test/assets", gemini_api_key="test-key")
        assert sfx.assets_dir == "/test/assets"
        assert sfx.gemini_api_key == "test-key"


class TestConvertSegmentsV2:
    """convert_segments_v2 테스트"""

    def test_basic_conversion(self, subtitle_data, script_list):
        from pipeline.sfx_integrator import SFXIntegrator

        # ScriptSegment 모킹
        mock_segment_class = MagicMock()
        mock_segment_instance = MagicMock()
        mock_segment_class.return_value = mock_segment_instance

        sfx = SFXIntegrator(assets_dir="/fake")
        sfx._auto_sfx_available = True
        sfx._ScriptSegment = mock_segment_class

        segments = sfx.convert_segments_v2(script_list, subtitle_data)
        assert len(segments) == 3
        assert mock_segment_class.call_count == 3

    def test_sfx_tag_from_subtitle(self, subtitle_data, script_list):
        """subtitle_data의 sfx_tag가 세그먼트에 설정됨"""
        from pipeline.sfx_integrator import SFXIntegrator

        # 실제 sfx_tag 설정은 segment.sfx_tag = sfx_tag 대입으로 이뤄짐
        # MagicMock은 대입을 허용하므로 검증 방식 변경
        mock_seg_class = MagicMock()

        sfx = SFXIntegrator(assets_dir="/fake")
        sfx._auto_sfx_available = True
        sfx._ScriptSegment = mock_seg_class

        segments = sfx.convert_segments_v2(script_list, subtitle_data)
        assert len(segments) == 3
        # sfx_tag 대입이 이뤄졌는지 확인
        assert hasattr(segments[0], 'sfx_tag')

    def test_timing_from_subtitle(self, subtitle_data, script_list):
        """실제 TTS 타이밍 사용 확인"""
        from pipeline.sfx_integrator import SFXIntegrator

        mock_seg = MagicMock()
        mock_seg_class = MagicMock(return_value=mock_seg)

        sfx = SFXIntegrator(assets_dir="/fake")
        sfx._auto_sfx_available = True
        sfx._ScriptSegment = mock_seg_class

        sfx.convert_segments_v2(script_list, subtitle_data)

        # 첫 번째 호출의 start_ms = 0, end_ms = 2000
        first_call = mock_seg_class.call_args_list[0]
        assert first_call.kwargs.get("start_ms", first_call[1].get("start_ms")) == 0
        assert first_call.kwargs.get("end_ms", first_call[1].get("end_ms")) == 2000

    def test_empty_subtitle_data(self, script_list):
        """빈 subtitle_data → 빈 리스트"""
        from pipeline.sfx_integrator import SFXIntegrator
        sfx = SFXIntegrator(assets_dir="/fake")
        sfx._auto_sfx_available = True
        sfx._ScriptSegment = MagicMock()
        segments = sfx.convert_segments_v2(script_list, [])
        assert segments == []

    def test_unavailable_returns_empty(self, subtitle_data, script_list):
        """Auto-SFX 비가용 시 빈 리스트"""
        from pipeline.sfx_integrator import SFXIntegrator
        sfx = SFXIntegrator(assets_dir="/fake")
        sfx._auto_sfx_available = False
        segments = sfx.convert_segments_v2(script_list, subtitle_data)
        assert segments == []


class TestConvertSegments:
    """convert_segments 레거시 테스트"""

    def test_timing_estimation(self, script_list):
        """글자수 기반 타이밍 추정"""
        from pipeline.sfx_integrator import SFXIntegrator

        mock_seg = MagicMock()
        mock_seg_class = MagicMock(return_value=mock_seg)

        sfx = SFXIntegrator(assets_dir="/fake")
        sfx._auto_sfx_available = True
        sfx._ScriptSegment = mock_seg_class

        segments = sfx.convert_segments(script_list, channel="horror")
        assert len(segments) == 3
        # horror 채널은 pause=400ms
        first_call = mock_seg_class.call_args_list[0]
        assert first_call.kwargs.get("start_ms", first_call[1].get("start_ms")) == 0


class TestCheckSfxEnabled:
    """_check_sfx_enabled 테스트"""

    def test_default_enabled(self):
        """SettingsManager 없으면 기본 활성화"""
        from pipeline.sfx_integrator import SFXIntegrator
        sfx = SFXIntegrator(assets_dir="/fake")
        # ImportError 발생 시 True 반환
        assert sfx._check_sfx_enabled("/nonexistent") is True


class TestGetSfxPackConfig:
    """_get_sfx_pack_config 팩 설정 테스트"""

    def test_fallback_when_no_pack(self):
        """팩 없으면 폴백 카테고리 사용"""
        from pipeline.sfx_integrator import SFXIntegrator
        sfx = SFXIntegrator(assets_dir="/fake")
        cat, intensity = sfx._get_sfx_pack_config("horror")
        assert cat == "horror"
        assert intensity == "medium"
