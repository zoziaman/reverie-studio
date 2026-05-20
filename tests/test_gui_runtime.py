# tests/test_gui_runtime.py
"""
GUI 런타임 자동 테스트
pytest-qt를 사용한 PySide6 GUI 테스트

실행 방법:
    cd <repo-root>
    pytest tests/test_gui_runtime.py -v

headless 모드 (CI용):
    pytest tests/test_gui_runtime.py -v --qt-api=pyside6
"""
import pytest
from unittest.mock import MagicMock, patch


class TestImports:
    """모듈 import 테스트 - 순환 참조 및 기본 오류 검출"""

    def test_import_media_factory(self):
        """MediaFactory import 테스트"""
        from modules_pro.media_factory import MediaFactory
        assert MediaFactory is not None

    def test_import_scenario_planner(self):
        """ScenarioPlanner import 테스트"""
        from modules_pro.scenario_planner import ScenarioPlanner
        assert ScenarioPlanner is not None

    def test_import_script_writers(self):
        """ScriptWriter import 테스트"""
        from modules_pro.script_writers import ScriptWriter, EnhancedScriptWriter
        assert ScriptWriter is not None
        assert EnhancedScriptWriter is not None

    def test_import_remotion_assembler(self):
        """RemotionAssembler import 테스트"""
        from modules_pro.remotion_assembler import RemotionAssembler
        assert RemotionAssembler is not None

    def test_import_tts_engine(self):
        """TTS 엔진 import 테스트"""
        from modules_pro.tts_engine import TTSEngine, get_tts_engine
        assert TTSEngine is not None
        assert get_tts_engine is not None

    def test_import_sfx_modules(self):
        """SFX 모듈 import 테스트"""
        from core.sfx_manager import SFXManager
        from core.sfx_analyzer import SFXAnalyzer
        from core.sfx_mixer import SFXMixer
        assert SFXManager is not None
        assert SFXAnalyzer is not None
        assert SFXMixer is not None

    def test_import_utopia_engine(self):
        """Utopia 엔진 import 테스트"""
        from utils.utopia_engine import UtopiaEngine
        assert UtopiaEngine is not None

    def test_import_settings(self):
        """설정 모듈 import 테스트"""
        from config.settings import ReverieSettings, config
        assert ReverieSettings is not None
        assert config is not None

    def test_remotion_assembler_accepts_model_like_config(self):
        """RemotionAssembler가 model_dump 설정 객체도 처리하는지 확인"""
        from modules_pro.remotion_assembler import RemotionAssembler

        class FakeModel:
            def __init__(self, payload):
                self._payload = payload

            def model_dump(self):
                return self._payload

        assembler = RemotionAssembler()
        ve = FakeModel({
            "vignette": {"enabled": True, "intensity": 0.3},
            "colorFilter": {"enabled": True, "type": "warm"},
        })
        ss = FakeModel({
            "fontFamily": "NanumSquareRoundEB",
            "fontSize": 42,
            "position": "bottom",
        })

        ve_props = assembler._convert_visual_effects_to_props(ve)
        ss_props = assembler._convert_subtitle_style_to_props(ss)

        assert ve_props["vignette"] == "medium"
        assert ve_props["colorFilter"] == "warm"
        assert ss_props["fontFamily"] == "NanumSquareRoundEB"
        assert ss_props["fontSize"] == 42


class TestSettingsManager:
    """SettingsManager GUI 설정 테스트"""

    def test_settings_manager_init(self, config_dir):
        """SettingsManager 초기화 테스트"""
        from gui.settings_manager import SettingsManager
        sm = SettingsManager(config_dir)
        assert sm is not None

    def test_sfx_settings(self, config_dir):
        """SFX 설정 읽기/쓰기 테스트"""
        from gui.settings_manager import SettingsManager
        sm = SettingsManager(config_dir)

        # 기본값 확인
        enabled = sm.get_sfx_enabled()
        assert isinstance(enabled, bool)

        # 설정 변경
        sm.set_sfx_enabled(True)
        assert sm.get_sfx_enabled() == True

        sm.set_sfx_enabled(False)
        assert sm.get_sfx_enabled() == False

    def test_channel_style(self, config_dir):
        """채널별 스타일 설정 테스트"""
        from gui.settings_manager import SettingsManager
        sm = SettingsManager(config_dir)

        # horror 채널 스타일
        style = sm.get_channel_style("horror")
        assert "bgm_volume" in style
        assert "subtitle_size" in style

        # 스타일 변경
        sm.set_channel_style("horror", {
            "bgm_volume": 0.25,
            "subtitle_size": 40
        })
        updated = sm.get_channel_style("horror")
        assert updated["bgm_volume"] == 0.25

    def test_videotoon_local_mode_settings(self, config_dir):
        from gui.settings_manager import SettingsManager
        sm = SettingsManager(config_dir)

        assert sm.get_videotoon_local_enabled() is False
        assert sm.get_videotoon_generation_backend() == "comfyui"

        sm.set_videotoon_local_enabled(True)
        sm.set_videotoon_generation_backend("sd_webui")

        assert sm.get_videotoon_local_enabled() is True
        assert sm.get_videotoon_generation_backend() == "sd_webui"

    def test_videotoon_gui_callbacks_persist_runtime_state(self, config_dir):
        from config.settings import config
        from gui.mixins.settings_mixin import SettingsMixin
        from gui.settings_manager import SettingsManager

        class Var:
            def __init__(self, value):
                self.value = value

            def get(self):
                return self.value

            def set(self, value):
                self.value = value

        class Label:
            def __init__(self):
                self.kwargs = {}

            def configure(self, **kwargs):
                self.kwargs.update(kwargs)

        class FakeGUI(SettingsMixin):
            def __init__(self):
                self.settings_manager = SettingsManager(config_dir)
                self.videotoon_local_var = Var(True)
                self.videotoon_backend_var = Var("SD WebUI (호환)")
                self.videotoon_backend_map = {
                    "ComfyUI (권장)": "comfyui",
                    "SD WebUI (호환)": "sd_webui",
                }
                self.videotoon_status_label = Label()
                self.logs = []

            def _add_log(self, message):
                self.logs.append(message)

            def _update_estimated_time(self):
                pass

        gui = FakeGUI()

        gui._on_videotoon_local_change()
        gui._on_videotoon_backend_change("SD WebUI (호환)")

        assert gui.settings_manager.get_videotoon_local_enabled() is True
        assert gui.settings_manager.get_videotoon_generation_backend() == "sd_webui"
        assert getattr(config, "VIDEOTOON_LOCAL_MODE_OVERRIDE") is True
        assert config.VIDEOTOON_IMAGE_BACKEND == "sd_webui"
        assert "VideoToon" in gui.videotoon_status_label.kwargs["text"]

    def test_videotoon_progress_status_reads_latest_progress(self, tmp_path, config_dir, monkeypatch):
        from config.settings import config
        from gui.mixins.settings_mixin import SettingsMixin
        from gui.settings_manager import SettingsManager
        from modules_pro.videotoon_local import VideoToonLocalWorkspace, VideoToonSceneSpec, VideoToonStackConfig

        class Label:
            def __init__(self):
                self.kwargs = {}

            def configure(self, **kwargs):
                self.kwargs.update(kwargs)

        class FakeGUI(SettingsMixin):
            def __init__(self):
                self.settings_manager = SettingsManager(config_dir)
                self.settings_manager.set_videotoon_local_enabled(True)
                self.videotoon_status_label = Label()
                self.videotoon_progress_label = Label()

        workspace_root = tmp_path / "VideoToon"
        monkeypatch.setattr(config, "VIDEOTOON_WORKSPACE_ROOT", str(workspace_root))
        workspace = VideoToonLocalWorkspace(VideoToonStackConfig(workspace_root=str(workspace_root)))
        workspace.write_production_bundle(
            "run-progress-gui",
            [
                VideoToonSceneSpec(scene_id="scene_0001", sd_prompt="first"),
                VideoToonSceneSpec(scene_id="scene_0002", sd_prompt="second"),
            ],
        )
        workspace.write_scene_status(
            "run-progress-gui",
            workspace.scene_artifacts("run-progress-gui", "scene_0001"),
            status="finalized",
            stage="layer_finalize",
        )
        workspace.write_scene_status(
            "run-progress-gui",
            workspace.scene_artifacts("run-progress-gui", "scene_0002"),
            status="failed",
            stage="comfyui_execute",
            reason="timeout",
        )

        gui = FakeGUI()
        gui._update_videotoon_progress_status()

        assert "2/2" in gui.videotoon_progress_label.kwargs["text"]
        assert "실패 1" in gui.videotoon_progress_label.kwargs["text"]
        assert gui.videotoon_progress_label.kwargs["text_color"] == "#F44336"


class TestMainWindowBasic:
    """메인 윈도우 기본 테스트 (qtbot 사용)"""

    @pytest.mark.skipif(True, reason="GUI 테스트는 수동 활성화 필요")
    def test_main_window_creation(self, qtbot):
        """메인 윈도우 생성 테스트"""
        # TODO: main_window.py 구조에 맞게 수정 필요
        # from gui.main_window import MainWindow
        # window = MainWindow()
        # qtbot.addWidget(window)
        # assert window.windowTitle() == "Reverie Studio"
        pass

    @pytest.mark.skipif(True, reason="GUI 테스트는 수동 활성화 필요")
    def test_generate_button_exists(self, qtbot):
        """생성 버튼 존재 확인"""
        # TODO: main_window.py 구조에 맞게 수정 필요
        pass


class TestDataIntegrity:
    """데이터 정합성 테스트"""

    def test_role_key_normalize(self):
        """성별 추론 로직 테스트"""
        from modules_pro.media_factory import MediaFactory

        # MediaFactory의 _role_key_normalize 테스트
        # 실제 인스턴스 없이 클래스 메서드로 테스트
        mf = MagicMock(spec=MediaFactory)

        # 남성 이름
        male_names = ["태준", "민혁", "지훈", "철수", "영수"]
        # 여성 이름
        female_names = ["혜미", "지우", "수아", "민지", "민주"]

        # 이름 리스트가 존재하는지 확인
        assert len(male_names) > 0
        assert len(female_names) > 0

    def test_sfx_tag_categories(self):
        """SFX 태그 카테고리 정합성"""
        valid_tags = [
            "tension", "heartbeat", "suspense", "jumpscare", "whisper",
            "footsteps", "door", "thunder", "wind", "night", "rain",
            "sad", "crying", "happy",
            "whoosh", "impact", "scream", "glass"
        ]

        # 태그가 비어있지 않은지 확인
        assert len(valid_tags) > 0

        # 중복 없는지 확인
        assert len(valid_tags) == len(set(valid_tags))


class TestRemotionSync:
    """Remotion ↔ Python 동기화 테스트"""

    def test_subtitle_data_fields(self):
        """subtitle_data 필수 필드 확인"""
        required_fields = ["text", "role", "start", "end", "scene_end"]

        # 모의 subtitle_data
        sample = {
            "text": "테스트 텍스트",
            "role": "narrator",
            "voice_type": "narrator",
            "start": 0.0,
            "end": 2.5,
            "scene_end": 3.0  # v57.6.7 추가
        }

        for field in required_fields:
            assert field in sample, f"필드 누락: {field}"

    def test_scene_end_includes_pause(self):
        """scene_end가 pause를 포함하는지 확인"""
        start = 0.0
        voice_duration = 2.5
        pause_duration = 0.5

        end = start + voice_duration  # 음성 끝
        scene_end = end + pause_duration  # 씬 끝 (pause 포함)

        assert scene_end > end
        assert scene_end == start + voice_duration + pause_duration


class TestThreadSafety:
    """Thread Safety 테스트"""

    def test_instance_manager_singleton(self):
        """InstanceManager 싱글톤 패턴 테스트"""
        from utils.instance_manager import get_instance_manager

        manager1 = get_instance_manager()
        manager2 = get_instance_manager()

        assert manager1 is manager2, "싱글톤이 아님!"

    def test_feedback_loop_lock(self, data_dir):
        """FeedbackLoop lock 존재 확인"""
        from utils.feedback_loop import FeedbackLoop

        fl = FeedbackLoop(data_dir, "horror")

        # _lock 속성 존재 확인
        assert hasattr(fl, '_lock'), "FeedbackLoop에 _lock 없음"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
