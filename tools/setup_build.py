# tools/setup_build.py
"""
Cython 빌드 설정 — .py → .pyd 컴파일

사용법:
    python tools/setup_build.py build_ext --inplace

빌드 결과:
    src/**/*.pyd (Windows)  또는  src/**/*.so (Linux)
"""
import os
import sys
from setuptools import setup, find_packages
from Cython.Build import cythonize
from Cython.Distutils import build_ext

# 프로젝트 루트
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")

# ============================================================
# Cython 컴파일 대상 (Tier 1 + Tier 2 = 핵심 비즈니스 로직)
# ============================================================

# Tier 1: CRITICAL — 파이프라인 핵심 + 라이센스 검증
TIER1_MODULES = [
    "pipeline/orchestrator.py",
    "pipeline/image_pipeline.py",
    "pipeline/tts_manager.py",
    "pipeline/video_renderer.py",
    "pipeline/thumbnail_maker.py",
    "pipeline/sfx_integrator.py",
    "pipeline/text_processor.py",
    "pipeline/consistency_manager.py",
    "pipeline/sd_client.py",
    "pipeline/vram_manager.py",
    "pipeline/pipeline_utils.py",
    "pipeline/context.py",
    "modules_pro/scenario_planner.py",
    "modules_pro/script_writers.py",
    "modules_pro/scene_analyzer.py",
    "modules_pro/visual_storytelling_director.py",
    "modules_pro/prompt_composer.py",
    "modules_pro/visual_director.py",
    "modules_pro/remotion_assembler.py",
    "config/pack_config.py",
    "utils/license_validator.py",
    "utils/firebase_license.py",
    "utils/crypto_utils.py",
]

# Tier 2: HIGH — 보조 모듈
TIER2_MODULES = [
    "modules_pro/quality_control.py",
    "modules_pro/sd_model_recommender.py",
    "modules_pro/background_library.py",
    "modules_pro/video_models.py",
    "config/settings_v2.py",
    "config/pack_validator.py",
    "utils/gemini_compat.py",
    "utils/hardware_id.py",
    "utils/batch_queue.py",
    "utils/production_stats.py",
    "core/sfx_analyzer.py",
    "core/sfx_manager.py",
    "core/auto_sfx.py",
    "facades/pipeline_facade.py",
    "facades/config_facade.py",
    "facades/infra_facade.py",
]

# GUI, insight, factory는 컴파일하지 않음 (사용자 커스터마이징 가능 영역)


def get_compile_targets(tier: str = "all"):
    """컴파일 대상 파일 목록 반환"""
    if tier == "1":
        modules = TIER1_MODULES
    elif tier == "2":
        modules = TIER2_MODULES
    elif tier == "all":
        modules = TIER1_MODULES + TIER2_MODULES
    else:
        modules = TIER1_MODULES + TIER2_MODULES

    targets = []
    for mod in modules:
        full_path = os.path.join(SRC_DIR, mod)
        if os.path.exists(full_path):
            targets.append(full_path)
        else:
            print(f"  [WARN] 파일 없음, 스킵: {mod}")

    return targets


def main():
    # --tier 옵션 파싱
    tier = "all"
    for arg in sys.argv:
        if arg.startswith("--tier="):
            tier = arg.split("=")[1]
            sys.argv.remove(arg)
            break

    targets = get_compile_targets(tier)
    print(f"\n=== Cython 빌드 ===")
    print(f"Tier: {tier}")
    print(f"대상 파일: {len(targets)}개")
    for t in targets:
        print(f"  - {os.path.relpath(t, PROJECT_ROOT)}")
    print()

    if not targets:
        print("[ERROR] 컴파일 대상이 없습니다.")
        sys.exit(1)

    setup(
        name="reverie-studio",
        ext_modules=cythonize(
            targets,
            compiler_directives={
                "language_level": "3",      # Python 3
                "boundscheck": False,       # 성능 최적화
                "wraparound": False,        # 성능 최적화
                "annotation_typing": True,  # 타입 힌트 활용
            },
            nthreads=os.cpu_count() or 4,   # 병렬 컴파일
        ),
        cmdclass={"build_ext": build_ext},
        packages=find_packages(where="src"),
        package_dir={"": "src"},
    )


if __name__ == "__main__":
    main()
