# tests/test_refactor_compat.py
"""
v60.1.0 리팩토링 호환성 테스트
- 기존 import 경로 동작 확인
- 새 import 경로 동작 확인 (Phase별 추가)
- 순환 의존성 자동 검출
- utils shim 동작 확인

Phase 0에서 생성, Phase별로 테스트 추가
"""
import sys
import os
import importlib
import pytest

# conftest.py에서 이미 src/ 경로 추가됨


# ============================================================
# 1. 기존 (레거시) import 경로 — 항상 동작해야 함
# ============================================================

class TestLegacyImportPaths:
    """기존 import 경로가 리팩토링 후에도 100% 동작하는지 검증"""

    def test_import_media_factory(self):
        """modules_pro.media_factory.MediaFactory import"""
        from modules_pro.media_factory import MediaFactory
        assert MediaFactory is not None

    def test_import_scenario_planner(self):
        """modules_pro.scenario_planner import"""
        from modules_pro.scenario_planner import ScenarioPlanner
        assert ScenarioPlanner is not None

    def test_import_script_writers(self):
        """modules_pro.script_writers import"""
        from modules_pro.script_writers import ScriptWriter
        assert ScriptWriter is not None

    def test_import_remotion_assembler(self):
        """modules_pro.remotion_assembler import"""
        from modules_pro.remotion_assembler import RemotionAssembler
        assert RemotionAssembler is not None

    def test_import_tts_engine(self):
        """modules_pro.tts_engine import"""
        from modules_pro.tts_engine import TTSEngine
        assert TTSEngine is not None

    def test_import_image_generator(self):
        """modules_pro.image_generator import"""
        from modules_pro.image_generator import ImageGenerator
        assert ImageGenerator is not None

    def test_import_visual_director(self):
        """modules_pro.visual_director import"""
        from modules_pro.visual_director import VisualDirector
        assert VisualDirector is not None

    def test_import_video_models(self):
        """modules_pro.video_models import"""
        from modules_pro.video_models import CancellationToken
        assert CancellationToken is not None

    def test_import_pack_config(self):
        """config.pack_config 전체 API"""
        from config.pack_config import (
            ACTIVE_PACK,
            get_prompt,
            get_scenario_pools,
            get_sfx_config,
            get_atmosphere_config,
            get_emergency_sequence,
            get_content_settings,
        )
        assert ACTIVE_PACK is not None
        # PACK_CONFIG_AVAILABLE은 소비자 모듈에서 try/except로 설정하는 패턴

    def test_import_settings(self):
        """config.settings_v2 import"""
        from config import settings_v2
        # settings_v2는 Pydantic BaseSettings — 클래스 정의 확인
        assert hasattr(settings_v2, 'ReverieSettings')

    def test_import_sfx_modules(self):
        """core.sfx_analyzer + sfx_manager import"""
        from core.sfx_analyzer import SFXAnalyzer
        from core.sfx_manager import SFXTag
        assert SFXAnalyzer is not None
        assert SFXTag is not None

    def test_import_utils_logger(self):
        """utils.logger import"""
        from utils.logger import get_logger
        assert get_logger is not None

    def test_import_utils_batch_queue(self):
        """utils.batch_queue import"""
        from utils.batch_queue import BatchQueue
        assert BatchQueue is not None

    def test_import_facades(self):
        """facades 모듈 import"""
        from facades.pipeline_facade import PipelineFacade
        from facades.config_facade import ConfigFacade
        from facades.infra_facade import InfraFacade
        assert PipelineFacade is not None
        assert ConfigFacade is not None
        assert InfraFacade is not None


# ============================================================
# 2. 새 import 경로 — Phase별로 활성화
# ============================================================

class TestNewImportPaths:
    """리팩토링으로 생성되는 새 모듈의 import 테스트
    Phase 미완료 시 skip됨 — 점진적으로 PASS 증가"""

    def test_import_pipeline_context(self):
        """Phase 1: pipeline.context import"""
        try:
            from pipeline.context import PipelineContext, PipelineStepResult
            assert PipelineContext is not None
            assert PipelineStepResult is not None
        except ImportError:
            pytest.skip("Phase 1 미완료: pipeline/context.py 없음")

    def test_import_pipeline_utils(self):
        """Phase 1: pipeline.pipeline_utils import"""
        try:
            from pipeline.pipeline_utils import safe_print
            assert safe_print is not None
        except ImportError:
            pytest.skip("Phase 1 미완료: pipeline/pipeline_utils.py 없음")

    def test_import_text_processor(self):
        """Phase 2: pipeline.text_processor import"""
        try:
            from pipeline.text_processor import TextProcessor
            assert TextProcessor is not None
        except ImportError:
            pytest.skip("Phase 2 미완료: pipeline/text_processor.py 없음")

    def test_import_sd_client(self):
        """Phase 3: pipeline.sd_client import"""
        try:
            from pipeline.sd_client import SDClientWrapper
            assert SDClientWrapper is not None
        except ImportError:
            pytest.skip("Phase 3 미완료: pipeline/sd_client.py 없음")

    def test_import_consistency_manager(self):
        """Phase 4: pipeline.consistency_manager import"""
        try:
            from pipeline.consistency_manager import ConsistencyManager
            assert ConsistencyManager is not None
        except ImportError:
            pytest.skip("Phase 4 미완료: pipeline/consistency_manager.py 없음")

    def test_import_vram_manager(self):
        """Phase 5: pipeline.vram_manager import"""
        try:
            from pipeline.vram_manager import VRAMManager
            assert VRAMManager is not None
        except ImportError:
            pytest.skip("Phase 5 미완료: pipeline/vram_manager.py 없음")

    def test_import_sfx_integrator(self):
        """Phase 6: pipeline.sfx_integrator import"""
        try:
            from pipeline.sfx_integrator import SFXIntegrator
            assert SFXIntegrator is not None
        except ImportError:
            pytest.skip("Phase 6 미완료: pipeline/sfx_integrator.py 없음")

    def test_import_thumbnail_maker(self):
        """Phase 7: pipeline.thumbnail_maker import"""
        try:
            from pipeline.thumbnail_maker import ThumbnailMaker
            assert ThumbnailMaker is not None
        except ImportError:
            pytest.skip("Phase 7 미완료: pipeline/thumbnail_maker.py 없음")

    def test_import_tts_manager(self):
        """Phase 8: pipeline.tts_manager import"""
        try:
            from pipeline.tts_manager import TTSManager
            assert TTSManager is not None
        except ImportError:
            pytest.skip("Phase 8 미완료: pipeline/tts_manager.py 없음")

    def test_import_image_pipeline(self):
        """Phase 9: pipeline.image_pipeline import"""
        try:
            from pipeline.image_pipeline import ImagePipeline
            assert ImagePipeline is not None
        except ImportError:
            pytest.skip("Phase 9 미완료: pipeline/image_pipeline.py 없음")

    def test_import_video_renderer(self):
        """Phase 10: pipeline.video_renderer import"""
        try:
            from pipeline.video_renderer import VideoRenderer
            assert VideoRenderer is not None
        except ImportError:
            pytest.skip("Phase 10 미완료: pipeline/video_renderer.py 없음")

    def test_import_orchestrator(self):
        """Phase 11: pipeline.orchestrator import"""
        try:
            from pipeline.orchestrator import MediaFactory
            assert MediaFactory is not None
        except ImportError:
            pytest.skip("Phase 11 미완료: pipeline/orchestrator.py 없음")


# ============================================================
# 3. 순환 의존성 자동 검출
# ============================================================

class TestNoCircularDeps:
    """순환 의존성이 없는지 검증"""

    def test_no_circular_pipeline_to_modules(self):
        """pipeline/ → modules_pro/ 단방향만 허용
        modules_pro/ → pipeline/ 역참조 금지"""
        import pathlib

        pipeline_dir = pathlib.Path(__file__).parent.parent / "src" / "pipeline"
        if not pipeline_dir.exists():
            pytest.skip("pipeline/ 폴더 미생성 (Phase 1 이전)")

        violations = []
        for py_file in pipeline_dir.rglob("*.py"):
            content = py_file.read_text(encoding="utf-8", errors="ignore")
            # pipeline 내부에서 modules_pro를 import하는 건 OK (정방향)
            # 여기서는 역방향 체크가 불가능하므로 skip
            pass

        # modules_pro → pipeline 역참조 검사
        # v60.1.0 Phase 11 완료: media_factory.py는 pipeline/orchestrator.py의 import shim
        # shim이므로 modules_pro → pipeline 역참조는 정당함 (영구 허용)
        ALLOWED_TRANSITIONAL = {"media_factory.py"}

        modules_dir = pathlib.Path(__file__).parent.parent / "src" / "modules_pro"
        for py_file in modules_dir.rglob("*.py"):
            if "_legacy" in str(py_file):
                continue
            if py_file.name in ALLOWED_TRANSITIONAL:
                continue  # Phase 11 이전 과도기적 위임 허용
            content = py_file.read_text(encoding="utf-8", errors="ignore")
            # from pipeline 또는 import pipeline 검출
            for i, line in enumerate(content.split("\n"), 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if "from pipeline" in stripped or "import pipeline" in stripped:
                    violations.append(f"{py_file.name}:{i}: {stripped}")

        assert violations == [], (
            f"modules_pro → pipeline 역참조 발견!\n"
            + "\n".join(violations)
        )

    def test_no_circular_config_to_pipeline(self):
        """config/ → pipeline/ 역참조 금지"""
        import pathlib

        pipeline_dir = pathlib.Path(__file__).parent.parent / "src" / "pipeline"
        if not pipeline_dir.exists():
            pytest.skip("pipeline/ 폴더 미생성")

        config_dir = pathlib.Path(__file__).parent.parent / "src" / "config"
        violations = []
        for py_file in config_dir.rglob("*.py"):
            content = py_file.read_text(encoding="utf-8", errors="ignore")
            for i, line in enumerate(content.split("\n"), 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if "from pipeline" in stripped or "import pipeline" in stripped:
                    violations.append(f"{py_file.name}:{i}: {stripped}")

        assert violations == [], (
            f"config → pipeline 역참조 발견!\n"
            + "\n".join(violations)
        )


# ============================================================
# 4. 데이터 모델 호환성
# ============================================================

class TestDataModelCompat:
    """리팩토링 전후 데이터 모델 호환성 검증"""

    def test_cancellation_token_interface(self):
        """CancellationToken API 보존"""
        from modules_pro.video_models import CancellationToken
        token = CancellationToken()
        assert hasattr(token, 'is_cancelled')
        assert hasattr(token, 'cancel')
        assert token.is_cancelled == False
        token.cancel()
        assert token.is_cancelled == True

    def test_pack_config_getter_api(self):
        """v60 팩 getter 함수 API 보존"""
        from config.pack_config import (
            get_prompt,
            get_scenario_pools,
            get_sfx_config,
            get_atmosphere_config,
            get_emergency_sequence,
            get_content_settings,
            PackSFX,
            PackAtmosphere,
            PackEmergency,
            PackScenario,
            PackContent,
        )
        # 반환 타입 확인 (빈 데이터라도 올바른 타입)
        sfx = get_sfx_config()
        assert isinstance(sfx, PackSFX)

        atmos = get_atmosphere_config()
        assert isinstance(atmos, PackAtmosphere)

        emergency = get_emergency_sequence()
        assert isinstance(emergency, list)

        content = get_content_settings()
        assert isinstance(content, PackContent)

        pools = get_scenario_pools()
        assert isinstance(pools, PackScenario)

    def test_active_pack_structure(self):
        """ACTIVE_PACK 구조 보존"""
        from config.pack_config import ACTIVE_PACK
        # v60 필수 속성
        assert hasattr(ACTIVE_PACK, 'pack_id')
        assert hasattr(ACTIVE_PACK, 'prompts')
        assert hasattr(ACTIVE_PACK, 'tts')
        assert hasattr(ACTIVE_PACK, 'visual')
        assert hasattr(ACTIVE_PACK, 'scenario')
        assert hasattr(ACTIVE_PACK, 'sfx')
        assert hasattr(ACTIVE_PACK, 'atmosphere')
        assert hasattr(ACTIVE_PACK, 'emergency')
        assert hasattr(ACTIVE_PACK, 'hook_style')
        assert hasattr(ACTIVE_PACK, 'is_loaded')
