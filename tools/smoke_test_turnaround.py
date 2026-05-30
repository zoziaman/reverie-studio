"""v63: 턴어라운드 스모크 테스트 — 실제 SD 서버로 각도 생성 검증.

검증 항목:
1. front 생성 (OpenPose 미적용 = 베이스 파이프라인 회귀 확인)
2. left/right/back 생성 (OpenPose ControlNet 각도 스켈레톤 적용)
각 결과 이미지를 tools/_smoke_out/<angle>.png 로 저장 → 사람이 눈으로 비교.

사용: python tools/smoke_test_turnaround.py   (SD WebUI API가 127.0.0.1:7860에 떠 있어야 함)
"""
from __future__ import annotations

import base64
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from modules_pro.character_library_manager import CharacterLibraryManager  # noqa: E402

OUT = Path(__file__).resolve().parent / "_smoke_out"
OUT.mkdir(parents=True, exist_ok=True)

PROMPT = (
    "masterpiece, best quality, korean webtoon style, clean cel shading, "
    "a young woman, brown hair, casual clothes, simple plain background, full body"
)
NEG = "(worst quality:1.4), (low quality:1.4), blurry, text, watermark, multiple people, extra limbs"


def main():
    clm = CharacterLibraryManager.__new__(CharacterLibraryManager)
    clm.sd_api_url = os.environ.get("SD_URL", "http://127.0.0.1:7860")

    angles = ["front", "left", "right", "back"]
    results = {}
    for angle in angles:
        print(f"[smoke] generating angle={angle} ...", flush=True)
        result = clm._generate_sd_image(
            prompt=PROMPT,
            negative_prompt=NEG,
            seed=12345,             # 같은 시드로 각도만 바뀌는지 확인
            width=512,
            height=768,
            steps=20,
            cfg_scale=7.0,
            angle=angle,
        )
        if result and result.get("images"):
            img_b64 = result["images"][0]
            out_path = OUT / f"{angle}.png"
            with open(out_path, "wb") as f:
                f.write(base64.b64decode(img_b64.split(",", 1)[-1]))
            results[angle] = str(out_path)
            print(f"[smoke]   OK -> {out_path}", flush=True)
        else:
            results[angle] = None
            print(f"[smoke]   FAILED (no image) angle={angle}", flush=True)

    print("\n=== SMOKE RESULT ===")
    for angle, path in results.items():
        print(f"  {angle}: {'OK ' + path if path else 'FAILED'}")
    ok = sum(1 for v in results.values() if v)
    print(f"\n{ok}/{len(angles)} angles generated.")
    return 0 if ok == len(angles) else 1


if __name__ == "__main__":
    raise SystemExit(main())
