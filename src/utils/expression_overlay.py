"""
표정 후처리 시스템 (Expression Overlay)
- SD가 생성한 캐릭터 형체 위에 간단한 표정 오버레이
- 미니멀/이모티콘 스타일 (Kurzgesagt/Headspace 느낌)
- 눈, 입, 눈물, 주름 등을 PIL로 그리기

사용:
    from utils.expression_overlay import apply_expression
    result_img = apply_expression(image_path, emotion="sad", channel_type="senior_touching")
"""

import os
import logging
from typing import Tuple, Optional, List
from PIL import Image, ImageDraw, ImageFilter
import math

logger = logging.getLogger(__name__)


class ExpressionOverlay:
    """
    캐릭터 형체에 표정 오버레이

    스타일:
    - 공포: 붉은 눈 점 (이미 프롬프트에 포함, 후처리 최소화)
    - 시니어: 간단한 이모티콘 표정 (점 눈 + 선 입 + 눈물/주름)
    """

    # 채널별 색상 팔레트
    CHANNEL_COLORS = {
        "daily_life_toon": {
            "eye": (55, 55, 60),
            "eye_glow": None,
            "mouth": (70, 65, 65),
            "tear": (100, 150, 200, 200),
            "wrinkle": (135, 115, 95),
        },
        "mystery_toon": {
            "eye": (35, 38, 45),
            "eye_glow": None,
            "mouth": (45, 45, 50),
            "tear": (80, 120, 180, 210),
            "wrinkle": (90, 80, 70),
        },
        "horror": {
            "eye": (255, 0, 0),       # 붉은 눈
            "eye_glow": (255, 50, 50, 150),
            "mouth": (50, 50, 50),
            "tear": None,             # 공포는 눈물 없음
            "wrinkle": (30, 30, 30),
        },
        "senior_touching": {
            "eye": (60, 60, 60),      # 부드러운 검정
            "eye_glow": None,
            "mouth": (80, 80, 80),
            "tear": (100, 150, 200, 200),  # 연한 파란 눈물
            "wrinkle": (150, 120, 100),    # 따뜻한 갈색 주름
        },
        "senior_makjang": {
            "eye": (40, 40, 40),      # 진한 검정
            "eye_glow": None,
            "mouth": (50, 50, 50),
            "tear": (80, 120, 180, 220),   # 진한 파란 눈물
            "wrinkle": (100, 80, 60),      # 어두운 갈색 주름
        },
    }

    # 감정별 표정 설정
    EMOTION_CONFIG = {
        # 긍정적 감정
        "happy": {
            "eye_shape": "dot",           # 점 눈
            "eye_curve": "up",            # 눈 살짝 위로 (웃는 눈)
            "mouth_shape": "smile",       # 웃는 입
            "tear": False,
            "wrinkle": False,
        },
        "joy": {
            "eye_shape": "arc_up",        # 초승달 눈 (웃음)
            "mouth_shape": "big_smile",
            "tear": False,
            "wrinkle": False,
        },
        "grateful": {
            "eye_shape": "dot",
            "eye_curve": "soft",
            "mouth_shape": "gentle_smile",
            "tear": False,
            "wrinkle": True,              # 감사 = 노인 주름
        },

        # 부정적 감정
        "sad": {
            "eye_shape": "dot",
            "eye_curve": "down",          # 처진 눈
            "mouth_shape": "frown",       # 입꼬리 내림
            "tear": False,
            "wrinkle": True,
        },
        "crying": {
            "eye_shape": "dot",
            "eye_curve": "down",
            "mouth_shape": "frown",
            "tear": True,                 # 눈물!
            "wrinkle": True,
        },
        "angry": {
            "eye_shape": "dot",
            "eye_curve": "angry",         # 찌푸린 눈
            "mouth_shape": "flat",        # 일자 입
            "tear": False,
            "wrinkle": True,
        },
        "frustrated": {
            "eye_shape": "dot",
            "eye_curve": "down",
            "mouth_shape": "wavy",        # 물결 입
            "tear": False,
            "wrinkle": True,
        },
        "scared": {
            "eye_shape": "big_dot",       # 큰 점 눈
            "mouth_shape": "open_small",  # 작게 벌린 입
            "tear": False,
            "wrinkle": False,
        },
        "shocked": {
            "eye_shape": "big_dot",
            "mouth_shape": "open_big",    # 크게 벌린 입
            "tear": False,
            "wrinkle": False,
        },
        "surprised": {
            "eye_shape": "big_dot",       # 큰 점 눈 (놀람)
            "mouth_shape": "open_small",  # 작게 벌린 입
            "tear": False,
            "wrinkle": False,
        },
        "worried": {
            "eye_shape": "dot",
            "eye_curve": "down",
            "mouth_shape": "wavy",        # 물결 입 (불안)
            "tear": False,
            "wrinkle": True,
        },

        # 중립
        "calm": {
            "eye_shape": "dot",
            "mouth_shape": "neutral",     # 일자 입
            "tear": False,
            "wrinkle": False,
        },
        "neutral": {
            "eye_shape": "dot",
            "mouth_shape": "neutral",
            "tear": False,
            "wrinkle": False,
        },
        "thinking": {
            "eye_shape": "dot",
            "eye_curve": "up",
            "mouth_shape": "side",        # 입 한쪽으로
            "tear": False,
            "wrinkle": True,
        },
    }

    def __init__(self):
        self.default_emotion = "neutral"

    def apply_expression(
        self,
        image: Image.Image,
        emotion: str = "neutral",
        channel_type: str = "daily_life_toon",
        face_region: Tuple[int, int, int, int] = None,  # (x, y, width, height)
        intensity: float = 1.0,  # 표정 강도 (0.5 = 연하게, 1.5 = 진하게)
    ) -> Image.Image:
        """
        이미지에 표정 오버레이 적용

        Args:
            image: PIL Image 객체
            emotion: 감정 (happy, sad, crying, angry, etc.)
            channel_type: 채널 타입 (horror, senior_touching, senior_makjang)
            face_region: 얼굴 영역 (없으면 자동 감지 시도)
            intensity: 표정 강도

        Returns:
            표정이 추가된 PIL Image
        """
        # 공포 채널은 후처리 최소화 (이미 붉은 눈이 프롬프트에 있음)
        if channel_type == "horror":
            logger.debug("[표정] 공포 채널 - 후처리 스킵")
            return image

        # 감정 설정 가져오기
        config = self.EMOTION_CONFIG.get(emotion, self.EMOTION_CONFIG["neutral"])
        colors = self.CHANNEL_COLORS.get(channel_type, self.CHANNEL_COLORS["daily_life_toon"])

        # 이미지 복사 (원본 보존)
        result = image.copy()

        # RGBA 모드로 변환 (투명도 지원)
        if result.mode != "RGBA":
            result = result.convert("RGBA")

        # 얼굴 영역 자동 감지 (간단한 방식: 이미지 중앙 상단)
        if not face_region:
            w, h = result.size
            # 기본: 이미지 중앙 상단 1/3 영역
            face_region = (
                int(w * 0.3),   # x
                int(h * 0.15),  # y
                int(w * 0.4),   # width
                int(h * 0.25),  # height
            )

        x, y, fw, fh = face_region

        # 표정 요소 크기 계산
        eye_size = int(fw * 0.08 * intensity)
        eye_spacing = int(fw * 0.25)
        mouth_width = int(fw * 0.2 * intensity)
        mouth_height = int(fh * 0.05 * intensity)

        # 표정 위치 계산
        center_x = x + fw // 2
        eye_y = y + int(fh * 0.35)
        mouth_y = y + int(fh * 0.6)

        # 오버레이 레이어 생성
        overlay = Image.new("RGBA", result.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        # 1. 눈 그리기
        self._draw_eyes(
            draw,
            center_x, eye_y, eye_spacing, eye_size,
            config.get("eye_shape", "dot"),
            config.get("eye_curve", "neutral"),
            colors["eye"],
            colors.get("eye_glow")
        )

        # 2. 입 그리기
        self._draw_mouth(
            draw,
            center_x, mouth_y, mouth_width, mouth_height,
            config.get("mouth_shape", "neutral"),
            colors["mouth"]
        )

        # 3. 눈물 그리기 (있으면)
        if config.get("tear") and colors.get("tear"):
            self._draw_tears(
                draw,
                center_x, eye_y, eye_spacing, eye_size,
                colors["tear"]
            )

        # 4. 주름 그리기 (있으면)
        if config.get("wrinkle") and colors.get("wrinkle"):
            self._draw_wrinkles(
                draw,
                center_x, y + int(fh * 0.15), fw,
                colors["wrinkle"]
            )

        # 오버레이 합성
        result = Image.alpha_composite(result, overlay)

        return result

    def _draw_eyes(
        self,
        draw: ImageDraw.Draw,
        center_x: int,
        y: int,
        spacing: int,
        size: int,
        shape: str,
        curve: str,
        color: Tuple,
        glow_color: Tuple = None
    ):
        """눈 그리기"""
        left_x = center_x - spacing
        right_x = center_x + spacing

        if shape == "dot":
            # 기본 점 눈
            offset_y = 0
            if curve == "up":
                offset_y = -size // 3
            elif curve == "down":
                offset_y = size // 3
            elif curve == "angry":
                # 찌푸린 눈 (왼쪽 위, 오른쪽 위)
                draw.ellipse([left_x - size, y - size // 2 - size, left_x + size, y + size // 2 - size], fill=color)
                draw.ellipse([right_x - size, y - size // 2 - size, right_x + size, y + size // 2 - size], fill=color)
                return

            draw.ellipse([left_x - size, y - size + offset_y, left_x + size, y + size + offset_y], fill=color)
            draw.ellipse([right_x - size, y - size + offset_y, right_x + size, y + size + offset_y], fill=color)

        elif shape == "big_dot":
            # 큰 점 눈 (놀람/공포)
            big_size = int(size * 1.5)
            draw.ellipse([left_x - big_size, y - big_size, left_x + big_size, y + big_size], fill=color)
            draw.ellipse([right_x - big_size, y - big_size, right_x + big_size, y + big_size], fill=color)

        elif shape == "arc_up":
            # 초승달 눈 (웃음)
            draw.arc([left_x - size * 2, y - size, left_x + size * 2, y + size * 2],
                     start=200, end=340, fill=color, width=max(2, size // 2))
            draw.arc([right_x - size * 2, y - size, right_x + size * 2, y + size * 2],
                     start=200, end=340, fill=color, width=max(2, size // 2))

        # 눈 글로우 효과 (공포 채널)
        if glow_color:
            glow_size = size * 2
            glow_layer = Image.new("RGBA", draw.im.size, (0, 0, 0, 0))
            glow_draw = ImageDraw.Draw(glow_layer)
            glow_draw.ellipse([left_x - glow_size, y - glow_size, left_x + glow_size, y + glow_size], fill=glow_color)
            glow_draw.ellipse([right_x - glow_size, y - glow_size, right_x + glow_size, y + glow_size], fill=glow_color)
            glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(radius=size))

    def _draw_mouth(
        self,
        draw: ImageDraw.Draw,
        center_x: int,
        y: int,
        width: int,
        height: int,
        shape: str,
        color: Tuple
    ):
        """입 그리기"""
        line_width = max(2, height // 2)

        if shape == "smile":
            # 웃는 입 (아래로 볼록한 곡선)
            draw.arc(
                [center_x - width, y - height, center_x + width, y + height * 2],
                start=0, end=180, fill=color, width=line_width
            )

        elif shape == "big_smile":
            # 큰 웃음
            draw.arc(
                [center_x - width * 1.3, y - height, center_x + width * 1.3, y + height * 3],
                start=0, end=180, fill=color, width=line_width + 1
            )

        elif shape == "gentle_smile":
            # 부드러운 미소
            draw.arc(
                [center_x - width * 0.8, y - height // 2, center_x + width * 0.8, y + height],
                start=10, end=170, fill=color, width=line_width
            )

        elif shape == "frown":
            # 슬픈 입 (위로 볼록한 곡선)
            draw.arc(
                [center_x - width, y - height * 2, center_x + width, y + height],
                start=180, end=360, fill=color, width=line_width
            )

        elif shape == "flat" or shape == "neutral":
            # 일자 입
            draw.line(
                [(center_x - width, y), (center_x + width, y)],
                fill=color, width=line_width
            )

        elif shape == "wavy":
            # 물결 입 (불만/혼란)
            points = []
            for i in range(5):
                px = center_x - width + (width * 2 * i // 4)
                py = y + (height if i % 2 == 0 else -height)
                points.append((px, py))
            draw.line(points, fill=color, width=line_width)

        elif shape == "open_small":
            # 작게 벌린 입 (O)
            draw.ellipse(
                [center_x - width // 2, y - height, center_x + width // 2, y + height],
                outline=color, width=line_width
            )

        elif shape == "open_big":
            # 크게 벌린 입
            draw.ellipse(
                [center_x - width, y - height * 2, center_x + width, y + height * 2],
                outline=color, width=line_width + 1
            )

        elif shape == "side":
            # 한쪽으로 치우친 입 (생각)
            draw.arc(
                [center_x, y - height, center_x + width * 2, y + height],
                start=150, end=210, fill=color, width=line_width
            )

    def _draw_tears(
        self,
        draw: ImageDraw.Draw,
        center_x: int,
        eye_y: int,
        eye_spacing: int,
        eye_size: int,
        color: Tuple
    ):
        """눈물 그리기"""
        tear_length = eye_size * 3
        tear_width = eye_size

        # 왼쪽 눈물
        left_x = center_x - eye_spacing
        self._draw_teardrop(draw, left_x, eye_y + eye_size, tear_width, tear_length, color)

        # 오른쪽 눈물
        right_x = center_x + eye_spacing
        self._draw_teardrop(draw, right_x, eye_y + eye_size, tear_width, tear_length, color)

    def _draw_teardrop(
        self,
        draw: ImageDraw.Draw,
        x: int,
        y: int,
        width: int,
        length: int,
        color: Tuple
    ):
        """눈물방울 하나 그리기"""
        # 타원 + 삼각형으로 눈물 모양
        draw.ellipse(
            [x - width, y + length - width * 2, x + width, y + length],
            fill=color
        )
        draw.polygon(
            [(x, y), (x - width, y + length - width), (x + width, y + length - width)],
            fill=color
        )

    def _draw_wrinkles(
        self,
        draw: ImageDraw.Draw,
        center_x: int,
        y: int,
        face_width: int,
        color: Tuple
    ):
        """이마 주름 그리기"""
        wrinkle_width = int(face_width * 0.3)
        line_spacing = 4
        line_width = 1

        # 2-3개의 짧은 가로선
        for i in range(3):
            line_y = y + i * line_spacing
            # 약간의 곡선 느낌
            draw.arc(
                [center_x - wrinkle_width, line_y - 2, center_x + wrinkle_width, line_y + 2],
                start=10, end=170, fill=color, width=line_width
            )


# 싱글톤 인스턴스
expression_overlay = ExpressionOverlay()


def apply_expression(
    image_path: str,
    emotion: str = "neutral",
    channel_type: str = "daily_life_toon",
    output_path: str = None,
    face_region: Tuple[int, int, int, int] = None,
) -> str:
    """
    이미지 파일에 표정 오버레이 적용 (편의 함수)

    Args:
        image_path: 입력 이미지 경로
        emotion: 감정
        channel_type: 채널 타입
        output_path: 출력 경로 (없으면 원본 덮어쓰기)
        face_region: 얼굴 영역

    Returns:
        저장된 이미지 경로
    """
    if not os.path.exists(image_path):
        logger.error(f"[표정] 이미지 없음: {image_path}")
        return image_path

    try:
        img = Image.open(image_path)
        result = expression_overlay.apply_expression(
            image=img,
            emotion=emotion,
            channel_type=channel_type,
            face_region=face_region
        )

        # 저장
        save_path = output_path or image_path

        # RGBA → RGB 변환 (JPEG 저장용)
        if save_path.lower().endswith(('.jpg', '.jpeg')):
            if result.mode == "RGBA":
                # 흰색 배경에 합성
                background = Image.new("RGB", result.size, (255, 255, 255))
                background.paste(result, mask=result.split()[3])
                result = background

        result.save(save_path, quality=95)
        logger.info(f"[표정] 적용 완료: {emotion} → {save_path}")
        return save_path

    except Exception as e:
        logger.error(f"[표정] 오류: {e}")
        return image_path


def detect_face_region(image: Image.Image) -> Optional[Tuple[int, int, int, int]]:
    """
    이미지에서 캐릭터 형체의 '얼굴' 영역 감지
    (간단한 방식: 밝기/색상 기반)

    TODO: 더 정교한 감지 필요 시 확장
    """
    # 현재는 기본값 사용 (이미지 중앙 상단)
    w, h = image.size
    return (
        int(w * 0.3),
        int(h * 0.15),
        int(w * 0.4),
        int(h * 0.25),
    )
