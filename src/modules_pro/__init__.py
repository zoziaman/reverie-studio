# src/modules_pro/__init__.py
"""
프로덕션 모듈 패키지

주요 모듈:
- media_factory: 영상 제작 공장
- scenario_planner: 시나리오 기획
- comfyui_client: ComfyUI 클라이언트
- visual_director: 비주얼 가드 + v59 파이프라인

v59 Visual Storytelling 모듈:
- sd_model_recommender: SD 모델 추천
- character_library_manager: 캐릭터 라이브러리 관리
- background_library: 배경 라이브러리 관리
- quality_control: 이미지 품질 검증
- scene_analyzer: 장면 분석 (Gemini)
- prompt_composer: SD 프롬프트 조합
"""

__all__ = [
    # 기존 모듈
    'media_factory',
    'scenario_planner',
    'comfyui_client',
    'visual_director',
    # v59 Visual Storytelling
    'sd_model_recommender',
    'character_library_manager',
    'background_library',
    'quality_control',
    'scene_analyzer',
    'prompt_composer',
    'videotoon_local',
    'tts_supertonic_adapter',
]
