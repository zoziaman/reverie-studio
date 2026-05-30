"""v63: 캐릭터 '라이브러리' 턴어라운드 end-to-end 검증.

generate_character_library를 실제로 호출해 (표정×포즈)가 front/left/right/back
4각도로 라이브러리에 저장되는지 확인한다 (= 에셋화가 각도까지 자동 되는지).

사용: python tools/smoke_test_library_turnaround.py  (SD WebUI API 필요)
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from modules_pro.character_library_manager import CharacterLibraryManager  # noqa: E402


def main():
    tmp = Path(tempfile.mkdtemp(prefix="lib_turnaround_"))
    clm = CharacterLibraryManager(pack_id="smoke_test", library_base_path=str(tmp),
                                  sd_api_url="http://127.0.0.1:7860")

    # 최소 캐릭터 정의
    char = SimpleNamespace(
        id="test_woman",
        name="Test Woman",
        base_prompt=(
            "korean webtoon style, clean cel shading, a young woman, long brown hair, "
            "red hooded jacket, white t-shirt, blue jeans, white sneakers"
        ),
        negative_prompt="(worst quality:1.4), blurry, text, multiple people",
        expressions={},
        poses={},
    )

    print("[lib] generating neutral_standing in ALL angles (include_angles default) ...", flush=True)
    success, paths = clm.generate_character_library(
        character_def=char,
        variant_keys=["neutral_standing"],
        images_per_combo=1,
        # include_angles 미지정 → 기본 True (env REVERIE_TURNAROUND)
    )

    entry = clm.library.get("test_woman")
    keys = sorted(entry.images.keys()) if entry else []
    print(f"\n=== LIBRARY KEYS (생성된 변형) ===")
    for k in keys:
        n = len(entry.images.get(k, []))
        print(f"  {k}: {n} image(s)")
    print(f"\n생성 성공: {success}, 이미지 {len(paths)}장")
    print(f"라이브러리 경로: {tmp / 'test_woman'}")

    expected = {"neutral_standing", "neutral_standing_left", "neutral_standing_right", "neutral_standing_back"}
    got = set(keys)
    have_all = expected.issubset(got)
    print(f"\n4각도 전부 생성됨? {have_all}  (기대 {sorted(expected)})")
    return 0 if (success and have_all) else 1


if __name__ == "__main__":
    raise SystemExit(main())
