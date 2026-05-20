# src/config/settings.py
# ============================================================
# v56.1: Pydantic BaseSettings로 전환
# 기존 Config 클래스 → ReverieSettings (Pydantic v2)
# 하위 호환성 100% 유지: from config.settings import config
# ============================================================

# v56.1: Pydantic 기반 설정으로 전환
# 기존 코드는 config/settings_legacy.py에 백업됨
from config.settings_v2 import config, settings, ReverieSettings

# 하위 호환성: Config 클래스명으로도 접근 가능
Config = ReverieSettings

__all__ = ['config', 'settings', 'Config', 'ReverieSettings']
