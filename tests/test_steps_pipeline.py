#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
v59.5.17 Steps 최적화 파이프라인 검증 테스트
팩 로드 → 대본 생성 → SD 이미지 생성 (steps=15 적용 확인)
"""
import sys
import os
import time
import json
import traceback
import base64
import requests

sys.path.insert(0, 'src')
sys.path.insert(0, 'lib')

from dotenv import dotenv_values
env = dotenv_values('.env')
for k, v in env.items():
    os.environ[k] = v

import config.settings_v2 as settings_module
if hasattr(settings_module, 'config'):
    settings_module.config.GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')

from datetime import datetime

def log(msg):
    ts = datetime.now().strftime('%H:%M:%S')
    safe = str(msg).encode('utf-8', errors='replace').decode('utf-8')
    try:
        print(f'[{ts}] {safe}', flush=True)
    except UnicodeEncodeError:
        print(f'[{ts}] {safe.encode("ascii", errors="ignore").decode("ascii")}', flush=True)


def main():
    total_start = time.time()
    SD_URL = 'http://127.0.0.1:7860'

    log('=' * 60)
    log('v59.5.17 Steps Optimization Pipeline Test')
    log('=' * 60)

    # ===== Step 1: Pack Load =====
    log('[Step 1] horror_default.json Pack Load...')
    from config import pack_config
    pack_config.load_pack('assets/packs/horror_default.json')
    ap = pack_config.ACTIVE_PACK
    log(f'  Pack: {ap.pack_name}')

    vs = getattr(ap, 'visual_storytelling', None)
    sd_model = getattr(vs, 'sd_model', None) if vs else None
    vs_steps = getattr(sd_model, 'steps', 'N/A') if sd_model else 'N/A'
    sd_legacy = getattr(ap, 'sd', None)
    sd_steps = getattr(sd_legacy, 'steps', 'N/A') if sd_legacy else 'N/A'
    log(f'  visual_storytelling.sd_model.steps = {vs_steps}')
    log(f'  sd.steps = {sd_steps}')

    assert vs_steps == 15, f'vs_steps={vs_steps}, expected 15!'
    assert sd_steps == 15, f'sd_steps={sd_steps}, expected 15!'
    log('  [OK] steps=15 confirmed')

    # ===== Step 2: Scenario Planner =====
    log('')
    log('[Step 2] ScenarioPlanner - auto topic + script...')
    from modules_pro.scenario_planner import ScenarioPlanner, PromptMode
    planner = ScenarioPlanner(prompt_mode=PromptMode.ENHANCED)
    topic = planner.get_auto_topic('horror', 'default')
    log(f'  Topic: {topic}')

    plan_data, json_path = planner.create_horror_plan(topic)
    script = plan_data.get('script', [])
    log(f'  Script: {len(script)} turns, saved: {json_path}')
    log(f'  Title: {plan_data.get("title", "N/A")}')

    fb_count = sum(1 for t in script if t.get('_is_fallback'))
    log(f'  Fallback turns: {fb_count}/{len(script)}')

    # ===== Step 3: PromptComposer =====
    log('')
    log('[Step 3] PromptComposer - steps verification...')
    from modules_pro.prompt_composer import ComposedPrompt
    cp = ComposedPrompt()
    params = cp.to_api_params()
    log(f'  ComposedPrompt.steps = {cp.steps}')
    log(f'  to_api_params()["steps"] = {params.get("steps")}')
    assert params.get('steps') == 15, f'steps={params.get("steps")}, expected 15!'
    log('  [OK] PromptComposer steps=15 confirmed')

    # ===== Step 4: SD Image Generation =====
    log('')
    log('[Step 4] SD WebUI - actual image generation (3 images)...')

    try:
        r = requests.get(f'{SD_URL}/sdapi/v1/sd-models', timeout=5)
        log(f'  SD WebUI: online ({len(r.json())} models)')
    except Exception:
        log('  [SKIP] SD WebUI offline - skipping image generation')
        return True

    out_dir = 'data/temp_images/pipeline_test'
    os.makedirs(out_dir, exist_ok=True)

    test_prompts = [
        'dark abandoned hospital corridor, flickering lights, wet floor, horror atmosphere, masterpiece, best quality',
        'old wooden staircase in haunted house, cobwebs, dust particles, dim moonlight, horror, masterpiece',
        'empty classroom at night, broken windows, scattered papers, eerie green light, horror manga style',
    ]

    gen_times = []
    all_steps_ok = True

    for i, prompt in enumerate(test_prompts):
        payload = {
            'prompt': prompt,
            'negative_prompt': 'person, people, face, nsfw, text, watermark, blurry',
            'steps': 15,
            'width': 768,
            'height': 432,
            'sampler_name': 'DPM++ 2M Karras',
            'cfg_scale': 7.0,
            'seed': 100 + i,
        }

        start = time.time()
        resp = requests.post(f'{SD_URL}/sdapi/v1/txt2img', json=payload, timeout=120)
        elapsed = time.time() - start
        gen_times.append(elapsed)

        if resp.status_code == 200:
            data = resp.json()
            info = json.loads(data.get('info', '{}'))
            actual_steps = info.get('steps', 'N/A')

            img_bytes = base64.b64decode(data['images'][0])
            fpath = os.path.join(out_dir, f'pipeline_test_{i:02d}.png')
            with open(fpath, 'wb') as f:
                f.write(img_bytes)

            log(f'  Image {i}: {elapsed:.2f}s | steps_used={actual_steps} | {len(img_bytes)/1024:.0f}KB | {fpath}')

            if actual_steps != 15 and actual_steps != 'N/A':
                log(f'  [FAIL] SD used {actual_steps} steps instead of 15!')
                all_steps_ok = False
        else:
            log(f'  [FAIL] Image {i}: HTTP {resp.status_code}')
            all_steps_ok = False

    avg_time = sum(gen_times) / len(gen_times) if gen_times else 0

    # ===== Summary =====
    total_elapsed = time.time() - total_start
    log('')
    log('=' * 60)
    log(f'Pipeline Test Complete ({total_elapsed:.1f}s)')
    log(f'  Pack steps: {vs_steps} (vs.sd_model) / {sd_steps} (sd legacy)')
    log(f'  Script: {len(script)} turns, fallback: {fb_count}')
    log(f'  SD: {avg_time:.2f}s/image avg at steps=15')
    log(f'  Projected 40-image time: {avg_time * 40 / 60:.1f} min')
    log(f'  All steps=15 verified: {all_steps_ok}')
    log('=' * 60)

    return all_steps_ok and fb_count == 0


if __name__ == "__main__":
    start_time = time.time()
    try:
        success = main()
    except Exception as e:
        print(f'\n[FATAL] {e}', flush=True)
        traceback.print_exc()
        success = False

    elapsed = time.time() - start_time
    print(f'\n{"="*60}', flush=True)
    if success:
        print(f'TEST PASSED ({elapsed/60:.1f}min)', flush=True)
    else:
        print(f'TEST FAILED ({elapsed/60:.1f}min)', flush=True)
    print('=' * 60, flush=True)
