"""v63: 턴어라운드 + 정체성(옷/얼굴) 일관성 결합 스모크 테스트.

흐름 (사장님이 보는 채널의 실제 방식):
1. front를 golden-cast 레퍼런스로 1장 생성 (구체적 의상 프롬프트로 고정)
2. 그 front 이미지를 IP-Adapter 레퍼런스로 삼아 left/right/back 생성
   → 각도(OpenPose ControlNet) + 정체성(IP-Adapter, 옷/얼굴) 동시 적용
결과: tools/_smoke_out2/<angle>.png — 4각도가 같은 옷/얼굴을 유지하는지 확인.

사용: python tools/smoke_test_turnaround_consistent.py  (SD WebUI API 필요)
"""
from __future__ import annotations

import base64
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from modules_pro.character_library_manager import CharacterLibraryManager  # noqa: E402

OUT = Path(__file__).resolve().parent / "_smoke_out2"
OUT.mkdir(parents=True, exist_ok=True)

# 의상을 '구체적으로' 박아 정체성 기준을 만든다 (막연한 'casual clothes' 금지)
PROMPT = (
    "masterpiece, best quality, korean webtoon style, clean cel shading, "
    "a young woman, long brown hair, "
    "wearing a red hooded jacket over a white t-shirt, blue jeans, white sneakers, "
    "simple plain background, full body"
)
NEG = "(worst quality:1.4), (low quality:1.4), blurry, text, watermark, multiple people, extra limbs, different outfit"
SEED = 12345


def _save(result, path):
    if result and result.get("images"):
        with open(path, "wb") as f:
            f.write(base64.b64decode(result["images"][0].split(",", 1)[-1]))
        return True
    return False


def main():
    clm = CharacterLibraryManager.__new__(CharacterLibraryManager)
    clm.sd_api_url = os.environ.get("SD_URL", "http://127.0.0.1:7860")

    # 1) front 레퍼런스 생성
    print("[smoke2] generating FRONT reference ...", flush=True)
    front = clm._generate_sd_image(
        prompt=PROMPT, negative_prompt=NEG, seed=SEED,
        width=512, height=768, steps=22, cfg_scale=7.0, angle="front",
    )
    front_path = OUT / "front.png"
    if not _save(front, front_path):
        print("[smoke2] FRONT 생성 실패 — 중단")
        return 1
    print(f"[smoke2]   front ref -> {front_path}", flush=True)

    # 2) front를 IP-Adapter 레퍼런스로 left/right/back 생성 (각도 + 정체성 동시)
    results = {"front": str(front_path)}
    for angle in ["left", "right", "back"]:
        print(f"[smoke2] generating angle={angle} with identity ref ...", flush=True)
        r = clm._generate_sd_image(
            prompt=PROMPT, negative_prompt=NEG, seed=SEED,
            width=512, height=768, steps=22, cfg_scale=7.0,
            angle=angle,
            consistency_image_path=str(front_path),  # golden-cast 레퍼런스
            consistency_mode="full",                  # 얼굴+옷+스타일
            consistency_weight=0.75,
        )
        p = OUT / f"{angle}.png"
        results[angle] = str(p) if _save(r, p) else None
        print(f"[smoke2]   {angle}: {'OK' if results[angle] else 'FAILED'}", flush=True)

    print("\n=== SMOKE2 RESULT (turnaround + identity) ===")
    for a, p in results.items():
        print(f"  {a}: {'OK ' + p if p else 'FAILED'}")
    ok = sum(1 for v in results.values() if v)
    print(f"\n{ok}/4 generated. 레퍼런스={front_path}")
    return 0 if ok == 4 else 1


if __name__ == "__main__":
    raise SystemExit(main())
