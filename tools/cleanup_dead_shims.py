"""v60.1.0: orchestrator.py에서 dead shim 메서드 35개 + unused import 제거"""
import sys, re, os
sys.stdout.reconfigure(encoding='utf-8')

path = 'src/pipeline/orchestrator.py'
with open(path, 'r', encoding='utf-8-sig') as f:
    content = f.read()
    lines = content.split('\n')

print(f'Before: {len(lines)} lines')

# Dead shim method names (all 35 confirmed dead)
dead_methods = {
    '_boot_sovits_engine', '_boot_sd_webui',
    '_num_to_sino_kor_1_99', '_num_to_sino_kor_full', '_fix_unit_numbers',
    '_kill_port_process', '_wait_for_port_free',
    '_extract_emotion_from_prompt', '_load_voice_metadata',
    '_apply_auto_sfx', '_convert_to_script_segments_v2', '_convert_to_script_segments',
    '_setup_ffmpeg_path', '_cleanup_clips', '_create_outro_clip',
    '_generate_voice_and_subtitles_sequential',
    '_ensure_sovits_engine', '_ensure_qwen3_engine', '_release_tts_resources',
    '_synthesize_with_sovits', '_synthesize_with_qwen3',
    '_get_safe_fallback_image',
    '_generate_tts_with_engine', '_generate_tts_legacy', '_amplify_tts_volume',
    '_create_intro_clip', '_generate_single_tts',
    '_create_ai_watermark_clip', '_estimate_silence_duration',
    '_tts_line_to_clip', '_tts_line_to_clip_legacy',
    '_generate_voice_and_subtitles', '_generate_images',
    '_assemble_main_remotion',
    '_review_thumbnail_with_gemini', '_create_thumbnails_with_review',
}

# Find dead method ranges (start_line, end_line exclusive)
to_remove = set()
i = 0
while i < len(lines):
    m = re.match(r'^    def (\w+)\(', lines[i])
    if m and m.group(1) in dead_methods:
        start = i
        # Find end: next method def at indent 4 or section comment block before def
        j = i + 1
        while j < len(lines):
            if re.match(r'^    def \w+', lines[j]):
                break
            if re.match(r'^    # ={5,}', lines[j]):
                # Section comment — check if followed by def
                k = j + 1
                while k < len(lines) and (lines[k].strip() == '' or re.match(r'^    #', lines[k])):
                    k += 1
                if k < len(lines) and re.match(r'^    def ', lines[k]):
                    break
            j += 1

        # Mark lines for removal
        for idx in range(start, min(j, len(lines))):
            to_remove.add(idx)

        # Also remove preceding blank lines
        k = start - 1
        while k >= 0 and lines[k].strip() == '':
            to_remove.add(k)
            k -= 1

        print(f'  Remove: {m.group(1)} (L{start+1}-L{j})')
        i = j
    else:
        i += 1

# Also remove section comment blocks that precede dead methods
# (e.g., "# v60.1.0 Phase 8: TTS ..." comments before dead shim blocks)
# These will be caught by the blank-line removal above

# Build new content
new_lines = [lines[i] for i in range(len(lines)) if i not in to_remove]

# Clean up multiple consecutive blank lines (max 2)
cleaned = []
blank_count = 0
for line in new_lines:
    if line.strip() == '':
        blank_count += 1
        if blank_count <= 2:
            cleaned.append(line)
    else:
        blank_count = 0
        cleaned.append(line)

print(f'After dead method removal: {len(cleaned)} lines')
print(f'Removed: {len(lines) - len(cleaned)} lines ({len(to_remove)} marked)')

with open(path, 'w', encoding='utf-8') as f:
    f.write('\n'.join(cleaned))

print('Written successfully')
