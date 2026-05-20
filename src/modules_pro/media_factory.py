# src/modules_pro/media_factory.py
# ============================================================
# v60.1.0 Phase 11: Import Shim
#
# 실제 구현은 pipeline/orchestrator.py로 이동됨.
# 이 파일은 기존 import 경로 호환성을 위한 shim입니다.
#
# 기존 import:
#   from modules_pro.media_factory import MediaFactory
#   from modules_pro.media_factory import QualityPreset
#
# 새 import:
#   from pipeline.orchestrator import MediaFactory
# ============================================================

from pipeline.orchestrator import MediaFactory  # noqa: F401

# QualityPreset은 video_models에서 직접 re-export
from modules_pro.video_models import QualityPreset  # noqa: F401

__all__ = ["MediaFactory", "QualityPreset"]
