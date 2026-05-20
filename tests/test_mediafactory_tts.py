"""MediaFactory TTS 엔진 확인 테스트"""
import sys
sys.path.insert(0, 'src')
sys.path.insert(0, 'lib')

import json
from config.settings import config

# 1. GUI처럼 설정 로드 및 config 업데이트
gui_path = "C:/ReverieStudio/data/gui_settings.json"
with open(gui_path, 'r', encoding='utf-8') as f:
    gui_settings = json.load(f)

gui_engine = gui_settings.get('tts', {}).get('engine', 'sovits')
config.TTS_ENGINE = gui_engine

print(f"config.TTS_ENGINE = {config.TTS_ENGINE}")
print(f"config.QWEN3_MODEL = {config.QWEN3_MODEL}")

# 2. MediaFactory 생성
print("\nMediaFactory 생성 중...")
from modules_pro.media_factory import MediaFactory

factory = MediaFactory(channel="senior")

print(f"\nfactory._using_sovits = {factory._using_sovits}")
print(f"factory._tts_engine = {factory._tts_engine}")
print(f"factory._tts_engine.engine_name = {factory._tts_engine.engine_name}")
print(f"factory._tts_engine.is_available = {factory._tts_engine.is_available}")
