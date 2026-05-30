"""v63: 캐릭터 턴어라운드용 OpenPose 스켈레톤 PNG 생성기.

front/left/right/back 4각도의 반신(half-body) OpenPose 스켈레톤을 그려
assets/actor_models/_openpose/<angle>.png 에 저장한다.
이 스켈레톤은 character_library_manager._append_openpose_angle_payload가
ControlNet(module=none, model=control_v11p_sd15_openpose)에 그대로 먹인다.

OpenPose(BODY_25 아님, COCO 18-keypoint) 색상/연결 규약을 따른다.
사용: python tools/make_openpose_skeletons.py
"""
from __future__ import annotations

import math
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError:
    raise SystemExit("Pillow 필요: pip install pillow")

# COCO 18 keypoint 인덱스
# 0 nose,1 neck,2 Rsho,3 Relb,4 Rwri,5 Lsho,6 Lelb,7 Lwri,
# 8 Rhip,9 Rkne,10 Rank,11 Lhip,12 Lkne,13 Lank,14 Reye,15 Leye,16 Rear,17 Lear
LIMB_SEQ = [
    (1, 2), (1, 5), (2, 3), (3, 4), (5, 6), (6, 7),
    (1, 8), (8, 9), (9, 10), (1, 11), (11, 12), (12, 13),
    (1, 0), (0, 14), (14, 16), (0, 15), (15, 17),
]
# OpenPose 표준 색상 (BGR가 아니라 RGB로)
COLORS = [
    (255, 0, 0), (255, 85, 0), (255, 170, 0), (255, 255, 0), (170, 255, 0),
    (85, 255, 0), (0, 255, 0), (0, 255, 85), (0, 255, 170), (0, 255, 255),
    (0, 170, 255), (0, 85, 255), (0, 0, 255), (85, 0, 255), (170, 0, 255),
    (255, 0, 255), (255, 0, 170), (255, 0, 85),
]

W, H = 1024, 1536


# 반신(half-body) 비율: 머리=상단, 골반이 캔버스 하단(~0.95)에 오도록 크게.
# 다리(무릎/발목)는 캔버스 밖으로 두어 half-body 크롭과 맞춘다.
def _front():
    """정면: 좌우 대칭, 양쪽 눈/귀 보임. 상반신 중심 반신 비율."""
    cx = 0.5
    return {
        0: (cx, 0.13), 1: (cx, 0.27),
        2: (cx - 0.16, 0.30), 3: (cx - 0.22, 0.52), 4: (cx - 0.24, 0.74),
        5: (cx + 0.16, 0.30), 6: (cx + 0.22, 0.52), 7: (cx + 0.24, 0.74),
        8: (cx - 0.11, 0.78), 9: (cx - 0.12, 1.05),
        11: (cx + 0.11, 0.78), 12: (cx + 0.12, 1.05),
        14: (cx - 0.045, 0.105), 15: (cx + 0.045, 0.105),
        16: (cx - 0.085, 0.12), 17: (cx + 0.085, 0.12),
    }


def _profile(face_dir: str):
    """측면(3/4): face_dir 'left' = 인물이 왼쪽을 봄(화면 기준).
    어깨 폭을 적당히 좁혀(0.10) 3/4 뷰를 주되, 목은 수직 유지(기형 방지).
    머리/코/눈만 바라보는 방향으로 틀고, 먼 쪽 눈 생략."""
    cx = 0.5
    s = -1 if face_dir == "left" else 1  # 바라보는 방향(왼쪽=-1)
    sw = 0.10  # 어깨 반폭(정면 0.16 → 측면감)
    hw = 0.075  # 골반 반폭
    pts = {
        0: (cx + s * 0.06, 0.125), 1: (cx, 0.27),
        2: (cx - sw, 0.31), 3: (cx - sw - 0.02, 0.53), 4: (cx - sw - 0.03, 0.75),
        5: (cx + sw, 0.31), 6: (cx + sw + 0.02, 0.53), 7: (cx + sw + 0.03, 0.75),
        8: (cx - hw, 0.78), 9: (cx - hw, 1.05),
        11: (cx + hw, 0.78), 12: (cx + hw, 1.05),
    }
    # 얼굴: 바라보는 쪽 눈/귀만 (코는 0이 이미 방향 틀어짐)
    if face_dir == "left":
        pts[15] = (cx + s * 0.04, 0.105)  # 앞쪽 눈
        pts[17] = (cx + 0.055, 0.12)      # 반대편 귀(뒤통수 쪽)
    else:
        pts[14] = (cx + s * 0.04, 0.105)
        pts[16] = (cx - 0.055, 0.12)
    return pts


def _back():
    """뒷모습: 코/눈 없음(머리 뒤), 귀만 살짝, 좌우 반전."""
    cx = 0.5
    return {
        1: (cx, 0.27),
        2: (cx + 0.16, 0.30), 3: (cx + 0.22, 0.52), 4: (cx + 0.24, 0.74),   # 뒤에서 보면 좌우 반대
        5: (cx - 0.16, 0.30), 6: (cx - 0.22, 0.52), 7: (cx - 0.24, 0.74),
        8: (cx + 0.11, 0.78), 9: (cx + 0.12, 1.05),
        11: (cx - 0.11, 0.78), 12: (cx - 0.12, 1.05),
        16: (cx + 0.07, 0.115), 17: (cx - 0.07, 0.115),  # 뒤통수 양 귀
    }


ANGLE_POSES = {
    "front": _front(),
    "left": _profile("left"),
    "right": _profile("right"),
    "back": _back(),
}


def draw_skeleton(points: dict) -> Image.Image:
    img = Image.new("RGB", (W, H), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    # 림(연결선) — 굵은 선
    for i, (a, b) in enumerate(LIMB_SEQ):
        if a in points and b in points:
            xa, ya = points[a][0] * W, points[a][1] * H
            xb, yb = points[b][0] * W, points[b][1] * H
            draw.line([(xa, ya), (xb, yb)], fill=COLORS[i % len(COLORS)], width=14)
    # 키포인트 — 원
    for idx, (px, py) in points.items():
        x, y = px * W, py * H
        r = 9
        draw.ellipse([x - r, y - r, x + r, y + r], fill=COLORS[idx % len(COLORS)])
    return img


def main():
    out_dir = Path(__file__).resolve().parent.parent / "assets" / "actor_models" / "_openpose"
    out_dir.mkdir(parents=True, exist_ok=True)
    for angle, pts in ANGLE_POSES.items():
        img = draw_skeleton(pts)
        path = out_dir / f"{angle}.png"
        img.save(path)
        print(f"saved: {path}")
    print(f"\nOpenPose 스켈레톤 4개 생성 완료 → {out_dir}")


if __name__ == "__main__":
    main()
