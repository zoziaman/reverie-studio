# test_expression_overlay.py
# 표정 오버레이 시스템 테스트
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from PIL import Image, ImageDraw
from utils.expression_overlay import ExpressionOverlay, expression_overlay

def create_test_silhouette(width=720, height=1280, channel_type="horror"):
    """테스트용 실루엣 이미지 생성"""
    img = Image.new("RGB", (width, height), (30, 30, 40))
    draw = ImageDraw.Draw(img)

    # 배경 그라데이션 효과
    for y in range(height):
        factor = y / height
        r = int(30 + factor * 20)
        g = int(30 + factor * 15)
        b = int(40 + factor * 30)
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    # 실루엣 형태 (타원형 몸체 + 머리)
    cx, cy = width // 2, height // 3

    if "horror" in channel_type:
        # 검은 실루엣
        color = (10, 10, 15)
    elif "touching" in channel_type:
        # 따뜻한 코랄 색상
        color = (200, 150, 130)
    else:
        # 막장 - 짙은 색상
        color = (80, 60, 70)

    # 머리 (원형)
    head_radius = 80
    draw.ellipse(
        (cx - head_radius, cy - head_radius, cx + head_radius, cy + head_radius),
        fill=color
    )

    # 몸체 (타원)
    body_top = cy + head_radius - 20
    body_bottom = cy + head_radius + 250
    body_width = 120
    draw.ellipse(
        (cx - body_width, body_top, cx + body_width, body_bottom),
        fill=color
    )

    return img

def run_tests():
    """다양한 채널/감정 조합 테스트"""
    output_dir = os.path.join(os.path.dirname(__file__), "test_output_expressions")
    os.makedirs(output_dir, exist_ok=True)

    test_cases = [
        # (채널 타입, 감정, 설명)
        ("horror", "scared", "공포 - 무서운 표정"),
        ("horror", "angry", "공포 - 화난 표정"),
        ("senior_touching", "happy", "시니어 감동 - 행복한 표정"),
        ("senior_touching", "crying", "시니어 감동 - 우는 표정"),
        ("senior_touching", "sad", "시니어 감동 - 슬픈 표정"),
        ("senior_makjang", "angry", "시니어 막장 - 화난 표정"),
        ("senior_makjang", "surprised", "시니어 막장 - 놀란 표정"),
    ]

    print("=" * 60)
    print("표정 오버레이 시스템 테스트")
    print("=" * 60)

    for channel_type, emotion, desc in test_cases:
        print(f"\n[테스트] {desc}")

        # 테스트 이미지 생성
        img = create_test_silhouette(720, 1280, channel_type)

        # 얼굴 영역 설정 (머리 부분) - (x, y, width, height) 형식
        cx, cy = 720 // 2, 1280 // 3
        head_radius = 80
        face_region = (
            cx - head_radius,      # x
            cy - head_radius,      # y
            head_radius * 2,       # width
            head_radius * 2        # height
        )

        # 표정 적용
        result = expression_overlay.apply_expression(
            image=img,
            emotion=emotion,
            channel_type=channel_type,
            face_region=face_region,
            intensity=1.0
        )

        if result:
            # 저장
            filename = f"{channel_type}_{emotion}.png"
            filepath = os.path.join(output_dir, filename)
            result.save(filepath, quality=95)
            print(f"  -> 저장: {filepath}")
        else:
            print(f"  -> 실패!")

    print("\n" + "=" * 60)
    print(f"테스트 완료! 결과 폴더: {output_dir}")
    print("=" * 60)

if __name__ == "__main__":
    run_tests()
