"""v60.1.0: orchestrator.py unused import 정리"""
import sys, re
sys.stdout.reconfigure(encoding='utf-8')

path = 'src/pipeline/orchestrator.py'
with open(path, 'r', encoding='utf-8-sig') as f:
    content = f.read()

print(f'Before: {len(content.splitlines())} lines')

# 1. Remove unused stdlib imports
# base64, requests, subprocess, numpy, textwrap, threading, glob
for imp in ['import base64', 'import requests', 'import subprocess',
            'import numpy as np', 'import textwrap', 'import threading',
            'from glob import glob']:
    if imp in content:
        # Check if it's actually used after import line
        lines_after = content.split(imp, 1)[1]
        short_name = imp.split()[-1]  # base64, requests, etc
        if short_name == 'np':
            pattern = r'\bnp\.'
        elif short_name == 'glob':
            pattern = r'\bglob\('
        else:
            pattern = rf'\b{short_name}\.'

        if not re.search(pattern, lines_after):
            content = content.replace(imp + '\n', '')
            print(f'  Removed: {imp}')
        else:
            print(f'  KEPT: {imp} (still used)')

# 2. Remove unused PIL imports (keep Image, remove ImageDraw, ImageFont, ImageEnhance)
content = content.replace(
    'from PIL import Image, ImageDraw, ImageFont, ImageEnhance',
    'from PIL import Image'
)
print('  Cleaned: PIL imports (kept Image only)')

# 3. Remove unused dataclass/enum imports
content = content.replace(
    'from dataclasses import dataclass, field\nfrom enum import Enum\n',
    ''
)
print('  Removed: dataclass, field, Enum')

# 4. Remove unused moviepy imports (afx, vfx only)
# Keep moviepy.editor since _create_outro_clip was removed but ColorClip etc
# might still be used... let's check
if 'afx.' not in content.split('import moviepy.audio.fx.all as afx', 1)[-1]:
    content = content.replace('import moviepy.audio.fx.all as afx\n', '')
    print('  Removed: moviepy.audio.fx (afx)')
if 'vfx.' not in content.split('import moviepy.video.fx.all as vfx', 1)[-1]:
    content = content.replace('import moviepy.video.fx.all as vfx\n', '')
    print('  Removed: moviepy.video.fx (vfx)')

# 5. Check if moviepy.editor is still used
moviepy_symbols = ['VideoClip', 'VideoFileClip', 'ColorClip', 'TextClip',
                   'CompositeVideoClip', 'AudioFileClip', 'ImageClip',
                   'CompositeAudioClip', 'concatenate_videoclips']
moviepy_used = False
after_import = content.split('from moviepy.editor import *', 1)[-1]
for sym in moviepy_symbols:
    if sym in after_import:
        moviepy_used = True
        print(f'  moviepy.editor symbol used: {sym}')
        break
if not moviepy_used:
    content = content.replace('from moviepy.editor import *\n', '')
    print('  Removed: moviepy.editor (no symbols used)')

# 6. Remove entire video_assembler import block (all dead)
old_va_import = """from modules_pro.video_assembler import (
    cleanup_clips,
    estimate_silence_duration,
    create_ai_watermark_clip,
    create_media_clip,
    create_outro_clip,
    create_intro_clip,
    assemble_video,
    ffmpeg_concat_videos,  # v57.6: 초고속 최종 렌더링
    fix_remotion_timebase,  # v58.3.10: Remotion time_base 정규화
)"""
# Check each symbol
va_symbols_used = []
for sym in ['cleanup_clips', 'estimate_silence_duration', 'create_ai_watermark_clip',
            'create_media_clip', 'create_outro_clip', 'create_intro_clip',
            'assemble_video', 'ffmpeg_concat_videos', 'fix_remotion_timebase']:
    # Count occurrences AFTER the import block
    after = content.split(old_va_import, 1)[-1]
    if re.search(rf'\b{sym}\b', after):
        va_symbols_used.append(sym)

if not va_symbols_used:
    content = content.replace(old_va_import + '\n', '')
    print('  Removed: entire video_assembler import block (all dead)')
else:
    print(f'  KEPT video_assembler: {va_symbols_used}')

# 7. Remove AudioSynthesizer (dead)
if 'AudioSynthesizer(' not in content.split('from modules_pro.audio_synthesizer import AudioSynthesizer', 1)[-1]:
    content = content.replace('from modules_pro.audio_synthesizer import AudioSynthesizer\n', '')
    print('  Removed: AudioSynthesizer')

# 8. Remove RemotionAssembler block (now in video_renderer)
remotion_block = """# v57.4: Remotion 기반 렌더링 (선택적)
try:
    from modules_pro.remotion_assembler import RemotionAssembler
    REMOTION_AVAILABLE = True
except ImportError:
    RemotionAssembler = None
    REMOTION_AVAILABLE = False
    logger.info("[MediaFactory] Remotion 모듈 로드 실패 - MoviePy 전용 모드")"""
# Check if RemotionAssembler or REMOTION_AVAILABLE is used
after_block = content.split(remotion_block, 1)[-1] if remotion_block in content else content
if 'RemotionAssembler' not in after_block and 'REMOTION_AVAILABLE' not in after_block:
    content = content.replace(remotion_block + '\n', '')
    print('  Removed: RemotionAssembler/REMOTION_AVAILABLE block')
else:
    print('  KEPT: RemotionAssembler (still referenced)')

# 9. Remove dead TTS engine imports (TTSConfig, TTSEngineType, TTSEngineFactory, get_tts_engine)
# Keep TTSEngine if used
tts_block_old = """from modules_pro.tts_engine import (
    TTSEngine,
    TTSConfig,
    TTSEngineType,
    TTSEngineFactory,
    get_tts_engine,
)"""
after_tts = content.split(tts_block_old, 1)[-1] if tts_block_old in content else ''
tts_used = []
for sym in ['TTSEngine', 'TTSConfig', 'TTSEngineType', 'TTSEngineFactory', 'get_tts_engine']:
    if re.search(rf'\b{sym}\b', after_tts):
        tts_used.append(sym)

if tts_used:
    tts_block_new = f"from modules_pro.tts_engine import (\n    {', '.join(tts_used)},\n)"
    content = content.replace(tts_block_old, tts_block_new)
    print(f'  Cleaned TTS imports: kept {tts_used}')
else:
    content = content.replace(tts_block_old + '\n', '')
    print('  Removed: entire tts_engine import block')

# 10. Remove tts_server_manager imports (dead)
tsm_block = """from modules_pro.tts_server_manager import (
    TTSServerManager,
    call_tts_api,
    get_tts_server_manager,
)"""
after_tsm = content.split(tsm_block, 1)[-1] if tsm_block in content else ''
tsm_used = []
for sym in ['TTSServerManager', 'call_tts_api', 'get_tts_server_manager']:
    if re.search(rf'\b{sym}\b', after_tsm):
        tsm_used.append(sym)
if not tsm_used:
    content = content.replace(tsm_block + '\n', '')
    print('  Removed: entire tts_server_manager import block')
else:
    print(f'  KEPT tts_server_manager: {tsm_used}')

# 11. Remove auto_sfx imports (dead)
sfx_block = """try:
    from core.auto_sfx import AutoSFX
    from core.sfx_analyzer import ScriptSegment
    AUTO_SFX_AVAILABLE = True
except ImportError:
    AUTO_SFX_AVAILABLE = False
    logger.warning("[Auto-SFX] 모듈 로드 실패 - 효과음 자동 삽입 비활성화")"""
after_sfx = content.split(sfx_block, 1)[-1] if sfx_block in content else ''
sfx_used = any(re.search(rf'\b{sym}\b', after_sfx) for sym in ['AutoSFX', 'ScriptSegment', 'AUTO_SFX_AVAILABLE'])
if not sfx_used:
    content = content.replace(sfx_block + '\n', '')
    print('  Removed: AutoSFX/ScriptSegment/AUTO_SFX_AVAILABLE block')
else:
    print('  KEPT: AutoSFX block (still referenced)')

# 12. Remove unused aliases
for alias_line in [
    '_SDClientWrapper = SDClientWrapper\n',
    '_create_sd_client_wrapper = create_sd_client\n',
]:
    alias_name = alias_line.split('=')[0].strip()
    after_alias = content.split(alias_line, 1)[-1] if alias_line in content else ''
    if not re.search(rf'\b{alias_name}\b', after_alias):
        content = content.replace(alias_line, '')
        print(f'  Removed alias: {alias_name}')

# 13. Remove dead expression overlay vars
# expr_overlay_instance and EXPRESSION_OVERLAY_AVAILABLE
for var in ['expr_overlay_instance', 'EXPRESSION_OVERLAY_AVAILABLE']:
    # Count usage after definition
    all_occurrences = len(re.findall(rf'\b{var}\b', content))
    if all_occurrences <= 2:  # definition + comment only
        pass  # Keep for now, it's commented code

# 14. Clean up multiple blank lines and empty comment blocks
content = re.sub(r'\n{4,}', '\n\n\n', content)

lines = content.splitlines()
print(f'After: {len(lines)} lines')

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)

print('Written successfully')
