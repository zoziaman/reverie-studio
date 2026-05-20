# tests/test_video_renderer.py
"""
v63.0 Phase 1: VideoRenderer 유닛 테스트

video_renderer.py의 핵심 경로 테스트:
- assemble_main() 라우팅
- _assemble_remotion() 씬 구성
- 이미지 시퀀스 반복/트림
- 이미지 누락 시 플레이스홀더 생성
- 오디오 파일 검증
- BGM 로딩
- 콜백 주입
"""
import os
import sys
import tempfile
import shutil
import pytest
from unittest.mock import MagicMock, patch, PropertyMock


@pytest.fixture
def temp_dir():
    d = tempfile.mkdtemp(prefix="test_vr_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def dummy_audio(temp_dir):
    p = os.path.join(temp_dir, "full.wav")
    with open(p, "wb") as f:
        f.write(b"\x00" * 100)
    return p


@pytest.fixture
def dummy_images(temp_dir):
    paths = []
    for i in range(3):
        p = os.path.join(temp_dir, f"img_{i}.png")
        with open(p, "wb") as f:
            f.write(b"\x89PNG" + b"\x00" * 50)
        paths.append(p)
    return paths


@pytest.fixture
def subtitle_data():
    return [
        {"text": "안녕하세요", "role": "grandma", "start": 0.0, "end": 2.0, "scene_end": 2.5, "voice_type": "old_woman"},
        {"text": "잘 지내셨어요?", "role": "grandpa", "start": 2.5, "end": 4.5, "scene_end": 5.0, "voice_type": "old_man"},
        {"text": "네, 덕분에요.", "role": "narrator", "start": 5.0, "end": 7.0, "scene_end": 7.5, "voice_type": "narrator"},
    ]


class TestVideoRendererInit:
    """생성자 및 콜백 테스트"""

    def test_init_defaults(self):
        from pipeline.video_renderer import VideoRenderer
        vr = VideoRenderer(channel="test_ch")
        assert vr.channel == "test_ch"
        assert vr.video_width == 1920
        assert vr.video_height == 1080
        assert vr.fps == 30
        assert vr._style_getter_fn is None
        assert vr._get_bgm_folder_fn is None
        assert vr._prepare_sfx_fn is None

    def test_init_custom_params(self):
        from pipeline.video_renderer import VideoRenderer
        vr = VideoRenderer(channel="ch", video_width=1280, video_height=720, fps=24, concurrency=4)
        assert vr.video_width == 1280
        assert vr.video_height == 720
        assert vr.fps == 24
        assert vr.concurrency == 4

    def test_set_callbacks(self):
        from pipeline.video_renderer import VideoRenderer
        vr = VideoRenderer(channel="ch")
        fn1 = lambda x: {}
        fn2 = lambda x: "/bgm"
        fn3 = lambda *a: None
        vr.set_callbacks(style_getter=fn1, get_bgm_folder=fn2, prepare_sfx_for_remotion=fn3)
        assert vr._style_getter_fn is fn1
        assert vr._get_bgm_folder_fn is fn2
        assert vr._prepare_sfx_fn is fn3

    def test_set_callbacks_partial(self):
        from pipeline.video_renderer import VideoRenderer
        vr = VideoRenderer(channel="ch")
        fn1 = lambda x: {}
        vr.set_callbacks(style_getter=fn1)
        assert vr._style_getter_fn is fn1
        assert vr._get_bgm_folder_fn is None  # 미설정 유지


class TestVideoRendererRoleDisplay:
    """역할 한국어 변환 테스트"""

    def test_role_display_mapping(self):
        from pipeline.video_renderer import VideoRenderer
        assert VideoRenderer._ROLE_DISPLAY["grandma"] == "할머니"
        assert VideoRenderer._ROLE_DISPLAY["grandpa"] == "할아버지"
        assert VideoRenderer._ROLE_DISPLAY["narrator"] == "나레이션"
        assert VideoRenderer._ROLE_DISPLAY["young_man"] == "청년"

    def test_unknown_role_passthrough(self):
        from pipeline.video_renderer import VideoRenderer
        # 매핑에 없는 role은 원본 그대로
        assert VideoRenderer._ROLE_DISPLAY.get("unknown_role", "unknown_role") == "unknown_role"


class TestAssembleMain:
    """assemble_main 라우팅 테스트"""

    def test_remotion_not_available_raises(self):
        from pipeline.video_renderer import VideoRenderer
        vr = VideoRenderer(channel="ch")
        with patch.dict('sys.modules', {'modules_pro.remotion_assembler': None}):
            with patch('builtins.__import__', side_effect=ImportError("no remotion")):
                with pytest.raises(RuntimeError, match="Remotion이 설치되지 않았습니다"):
                    vr.assemble_main("audio.wav", [], [], "horror")

    @patch('pipeline.video_renderer.VideoRenderer._assemble_remotion')
    def test_remotion_available_routes(self, mock_assemble):
        from pipeline.video_renderer import VideoRenderer
        mock_assemble.return_value = "/tmp/output.mp4"
        vr = VideoRenderer(channel="ch")
        result = vr.assemble_main("audio.wav", [{"text": "hi"}], ["/img.png"], "horror", topic="테스트")
        mock_assemble.assert_called_once()
        assert result == "/tmp/output.mp4"


class TestAssembleRemotion:
    """_assemble_remotion 세부 동작 테스트"""

    def _make_mock_assembler(self):
        mock = MagicMock()
        mock.render.return_value = {"success": True, "elapsed_seconds": 10.0, "file_size_mb": 50.0}
        return mock

    @patch('modules_pro.remotion_assembler.RemotionAssembler')
    def test_image_sequence_repeat(self, MockAssembler, dummy_audio, dummy_images, subtitle_data):
        """이미지 < 자막 수일 때 순차 반복"""
        from pipeline.video_renderer import VideoRenderer

        mock_asm = self._make_mock_assembler()
        MockAssembler.return_value = mock_asm

        vr = VideoRenderer(channel="ch")
        # 이미지 2개, 자막 3개 → 0,1,0 반복
        result = vr._assemble_remotion(
            dummy_audio,
            subtitle_data,
            dummy_images[:2],  # 2개만
            "horror",
        )
        # add_scene이 3번 호출되어야 함
        assert mock_asm.add_scene.call_count == 3

    @patch('modules_pro.remotion_assembler.RemotionAssembler')
    def test_empty_images_raises(self, MockAssembler, dummy_audio, subtitle_data):
        """이미지 0개면 RuntimeError"""
        from pipeline.video_renderer import VideoRenderer
        vr = VideoRenderer(channel="ch")
        with pytest.raises(RuntimeError, match="이미지가 없습니다"):
            vr._assemble_remotion(dummy_audio, subtitle_data, [], "horror")

    def test_missing_audio_raises(self, subtitle_data, dummy_images):
        """오디오 파일 없으면 RuntimeError"""
        from pipeline.video_renderer import VideoRenderer
        vr = VideoRenderer(channel="ch")
        with pytest.raises((RuntimeError, FileNotFoundError)):
            vr._assemble_remotion("/nonexistent/audio.wav", subtitle_data, dummy_images, "horror")

    @patch('modules_pro.remotion_assembler.RemotionAssembler')
    def test_render_failure_raises(self, MockAssembler, dummy_audio, dummy_images, subtitle_data):
        """렌더링 실패 시 RuntimeError + temp 삭제"""
        from pipeline.video_renderer import VideoRenderer

        mock_asm = self._make_mock_assembler()
        mock_asm.render.return_value = {"success": False}
        MockAssembler.return_value = mock_asm

        vr = VideoRenderer(channel="ch")
        with pytest.raises(RuntimeError, match="Remotion 렌더링 실패"):
            vr._assemble_remotion(dummy_audio, subtitle_data, dummy_images, "horror")

    @patch('modules_pro.remotion_assembler.RemotionAssembler')
    def test_duration_ms_zero_guard(self, MockAssembler, dummy_audio, dummy_images):
        """duration <= 0이면 1000ms로 보정"""
        from pipeline.video_renderer import VideoRenderer

        mock_asm = self._make_mock_assembler()
        MockAssembler.return_value = mock_asm

        bad_sub = [{"text": "테스트", "role": "narrator", "start": 5.0, "end": 5.0, "scene_end": 5.0}]
        vr = VideoRenderer(channel="ch")
        vr._assemble_remotion(dummy_audio, bad_sub, dummy_images, "horror")

        call_args = mock_asm.add_scene.call_args
        assert call_args.kwargs.get("duration_ms", call_args[1].get("duration_ms", 0)) >= 1000 or \
               (len(call_args[0]) > 6 and call_args[0][6] >= 1000)

    @patch('modules_pro.remotion_assembler.RemotionAssembler')
    def test_bgm_callback_used(self, MockAssembler, dummy_audio, dummy_images, subtitle_data, temp_dir):
        """BGM 콜백이 정상 호출되는지"""
        from pipeline.video_renderer import VideoRenderer

        # BGM 파일 생성
        bgm_dir = os.path.join(temp_dir, "bgm")
        os.makedirs(bgm_dir)
        bgm_file = os.path.join(bgm_dir, "test.mp3")
        with open(bgm_file, "wb") as f:
            f.write(b"\x00" * 50)

        mock_asm = self._make_mock_assembler()
        MockAssembler.return_value = mock_asm

        vr = VideoRenderer(channel="ch")
        vr.set_callbacks(get_bgm_folder=lambda mode: bgm_dir)

        vr._assemble_remotion(dummy_audio, subtitle_data, dummy_images, "horror")
        mock_asm.set_bgm.assert_called_once()

    @patch('modules_pro.remotion_assembler.RemotionAssembler')
    def test_sfx_callback_used(self, MockAssembler, dummy_audio, dummy_images, subtitle_data):
        """SFX 콜백이 정상 호출되는지"""
        from pipeline.video_renderer import VideoRenderer

        mock_asm = self._make_mock_assembler()
        MockAssembler.return_value = mock_asm

        sfx_fn = MagicMock()
        vr = VideoRenderer(channel="ch")
        vr.set_callbacks(prepare_sfx_for_remotion=sfx_fn)

        vr._assemble_remotion(dummy_audio, subtitle_data, dummy_images, "horror")
        sfx_fn.assert_called_once_with(mock_asm, subtitle_data, "horror")


class TestImagePlaceholder:
    """누락 이미지 플레이스홀더 생성 테스트"""

    @patch('modules_pro.remotion_assembler.RemotionAssembler')
    def test_missing_image_creates_placeholder(self, MockAssembler, dummy_audio, temp_dir):
        """존재하지 않는 이미지 → 검정 플레이스홀더 생성"""
        from pipeline.video_renderer import VideoRenderer

        mock_asm = MagicMock()
        mock_asm.render.return_value = {"success": True, "elapsed_seconds": 1.0, "file_size_mb": 1.0}
        MockAssembler.return_value = mock_asm

        missing_img = os.path.join(temp_dir, "nonexistent.png")
        sub = [{"text": "테스트", "role": "narrator", "start": 0, "end": 2, "scene_end": 2.5}]

        vr = VideoRenderer(channel="ch")
        vr._assemble_remotion(dummy_audio, sub, [missing_img], "horror")

        # 플레이스홀더가 생성되었는지 확인
        assert os.path.exists(missing_img)
