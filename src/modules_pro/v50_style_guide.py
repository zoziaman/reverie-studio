# src/modules_pro/v50_style_guide.py
# ============================================================
# v60.1.0 Phase 12: Import Shim
# 실제 구현은 modules_pro/_legacy/v50_style_guide.py로 이동됨.
# ============================================================

from modules_pro._legacy.v50_style_guide import (  # noqa: F401
    ChannelStyle,
    V50StyleConfig,
    HORROR_STYLE,
    SENIOR_TOUCHING_STYLE,
    SENIOR_MAKJANG_STYLE,
    DARK_CHANNELS,
    WARM_CHANNELS,
    DRAMATIC_CHANNELS,
    get_channel_category,
    get_style_for_channel,
    transform_prompt_for_v50,
    analyze_scene_for_humans,
    get_scene_type,
    transform_scene_prompts,
)

__all__ = [
    "ChannelStyle",
    "V50StyleConfig",
    "HORROR_STYLE",
    "SENIOR_TOUCHING_STYLE",
    "SENIOR_MAKJANG_STYLE",
    "DARK_CHANNELS",
    "WARM_CHANNELS",
    "DRAMATIC_CHANNELS",
    "get_channel_category",
    "get_style_for_channel",
    "transform_prompt_for_v50",
    "analyze_scene_for_humans",
    "get_scene_type",
    "transform_scene_prompts",
]
