# src/facades/__init__.py
"""
v57.6.8: Facade 패턴 - 레이어 간 통합 진입점

각 레이어의 복잡한 모듈들을 단일 인터페이스로 제공
- PipelineFacade: 영상 생성 파이프라인 (modules_pro)
- InfraFacade: 인프라/유틸리티 (utils, core)
- ConfigFacade: 설정 (config)

사용법:
    from facades import get_pipeline, get_infra, get_config

    pipeline = get_pipeline()
    result = pipeline.generate_video(topic, channel)
"""

from facades.pipeline_facade import PipelineFacade, get_pipeline_facade
from facades.infra_facade import InfraFacade, get_infra_facade
from facades.config_facade import ConfigFacade, get_config_facade

# 편의 alias
get_pipeline = get_pipeline_facade
get_infra = get_infra_facade
get_config = get_config_facade

__all__ = [
    'PipelineFacade', 'get_pipeline_facade', 'get_pipeline',
    'InfraFacade', 'get_infra_facade', 'get_infra',
    'ConfigFacade', 'get_config_facade', 'get_config',
]
