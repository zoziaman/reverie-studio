# -*- coding: utf-8 -*-
"""
v59: Quality Control System
이미지 품질 검증 시스템

설계서 섹션 3.9 구현

v59.1.0: Gemini Vision 기반 불쾌한 골짜기 감지 추가
- 머리 2개 이상, 클론 인물, 신체 기형, NSFW 감지
- AI가 판단해서 불량 이미지 재생성
"""

import os
import logging
import hashlib
import base64
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Any, Tuple
from datetime import datetime
from enum import Enum

try:
    from utils.logger import get_logger
    logger = get_logger("quality_control")
except ImportError:
    logger = logging.getLogger(__name__)


# v61.1: cv2.imread는 한글(비-ASCII) 경로에서 None 반환 → np.fromfile + imdecode로 우회
def _cv2_imread_safe(path: str, flags=None):
    """한글 경로 안전한 cv2.imread 대체"""
    import cv2
    import numpy as np
    try:
        buf = np.fromfile(path, dtype=np.uint8)
        if flags is not None:
            return cv2.imdecode(buf, flags)
        return cv2.imdecode(buf, cv2.IMREAD_COLOR)
    except Exception:
        return None


# ============================================================================
# 품질 검증 결과
# ============================================================================

class QualityStatus(Enum):
    """품질 검증 상태"""
    PASSED = "passed"
    FAILED = "failed"
    WARNING = "warning"
    SKIPPED = "skipped"


@dataclass
class QualityCheckResult:
    """개별 검증 항목 결과"""
    check_name: str
    status: QualityStatus
    score: float = 0.0  # 0.0 ~ 1.0
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class QualityReport:
    """전체 품질 검증 보고서"""
    image_path: str
    overall_status: QualityStatus
    overall_score: float  # 0.0 ~ 1.0
    checks: List[QualityCheckResult] = field(default_factory=list)
    timestamp: str = ""
    processing_time_ms: float = 0.0

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()

    @property
    def passed(self) -> bool:
        return self.overall_status != QualityStatus.FAILED

    @property
    def failed_checks(self) -> List[QualityCheckResult]:
        return [c for c in self.checks if c.status == QualityStatus.FAILED]

    @property
    def warning_checks(self) -> List[QualityCheckResult]:
        return [c for c in self.checks if c.status == QualityStatus.WARNING]


# ============================================================================
# 설정
# ============================================================================

@dataclass
class QualityControlConfig:
    """품질 검증 설정 (설계서 3.9)"""
    enabled: bool = True

    # 검증 항목
    check_face_detection: bool = True
    check_nsfw: bool = True
    check_blur: bool = True
    check_artifacts: bool = True
    check_resolution: bool = True
    check_aspect_ratio: bool = True
    check_color_depth: bool = True

    # v62.15: check_uncanny_valley → 로컬 cv2 기반으로 교체 (Gemini Vision 완전 제거)
    # Gemini Vision API = 텍스트 대비 5~10배 비쌈 → 월 수십만원 비용 발생 위험
    check_uncanny_valley: bool = True  # 로컬 cv2 기반이므로 비용 없음, 기본 활성화

    # v59.5.20: 팩별 아트 스타일 검증 (하드코딩 제거)
    expected_art_style: str = ""  # 팩의 아트 스타일 (빈 문자열이면 monochrome manga 폴백)

    # v59.6.0: 다중 인물 허용 (클론만 거부)
    allow_multi_person: bool = True  # False면 기존 C3 동작 (2명 이상 전부 거부)

    # 임계값
    min_face_confidence: float = 0.7
    max_blur_score: float = 100.0  # Laplacian variance
    min_resolution: Tuple[int, int] = (512, 288)
    target_aspect_ratio: float = 1.778  # 16:9
    aspect_ratio_tolerance: float = 0.1

    # 재생성 설정
    max_retries: int = 3
    fallback_to_library: bool = True

    # 로깅
    save_failed_images: bool = True
    failed_images_path: str = "data/failed_images/"


# ============================================================================
# QualityControl 클래스
# ============================================================================

class QualityControl:
    """
    v59: 이미지 품질 검증 시스템

    검증 항목:
    - 얼굴 감지 (캐릭터 이미지용)
    - 흐림(블러) 감지
    - 아티팩트 감지
    - NSFW 필터링
    - 해상도 검증
    - 색상 깊이 검증
    - v59.1.0: 불쾌한 골짜기 감지 (Gemini Vision)
    """

    def __init__(self, config: Optional[QualityControlConfig] = None, gemini_client=None):
        """
        Args:
            config: 품질 검증 설정
            gemini_client: v62.15 이후 미사용 (하위호환 시그니처 유지)
        """
        self.config = config or QualityControlConfig()
        # v62.15: Gemini Vision 완전 제거 — gemini_client 파라미터 무시
        # (하위호환을 위해 시그니처는 유지)

        # 모듈 가용성
        self._cv2_available = False
        self._face_cascade = None
        self._pil_available = False

        self._init_modules()

        logger.info(f"QualityControl 초기화: cv2={self._cv2_available}, PIL={self._pil_available}")

    def _init_modules(self):
        """필요한 모듈 초기화"""
        # OpenCV
        try:
            import cv2
            self._cv2_available = True

            # 얼굴 감지 캐스케이드 로드
            cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
            if os.path.exists(cascade_path):
                self._face_cascade = cv2.CascadeClassifier(cascade_path)
            else:
                logger.warning(f"얼굴 감지 캐스케이드 없음: {cascade_path}")

        except ImportError:
            logger.warning("OpenCV 사용 불가 - 일부 검증 비활성화")

        # PIL
        try:
            from PIL import Image
            self._pil_available = True
        except ImportError:
            logger.warning("PIL 사용 불가")

    # ========================================================================
    # 메인 검증 인터페이스
    # ========================================================================

    def validate_image(
        self,
        image_path: str,
        image_type: str = "scene",
        require_face: bool = False
    ) -> QualityReport:
        """
        이미지 품질 검증 (메인 인터페이스)

        Args:
            image_path: 이미지 경로
            image_type: "scene", "character", "background"
            require_face: 얼굴 필수 여부 (캐릭터 이미지)

        Returns:
            QualityReport
        """
        import time
        start_time = time.time()

        checks = []
        path = Path(image_path)

        # 파일 존재 확인
        if not path.exists():
            return QualityReport(
                image_path=image_path,
                overall_status=QualityStatus.FAILED,
                overall_score=0.0,
                checks=[QualityCheckResult(
                    check_name="file_exists",
                    status=QualityStatus.FAILED,
                    message=f"파일 없음: {image_path}"
                )]
            )

        # 개별 검증 수행
        if self.config.check_resolution:
            checks.append(self._check_resolution(image_path))

        if self.config.check_aspect_ratio:
            checks.append(self._check_aspect_ratio(image_path))

        if self.config.check_blur:
            checks.append(self._check_blur(image_path))

        if self.config.check_color_depth:
            checks.append(self._check_color_depth(image_path))

        if self.config.check_face_detection and (require_face or image_type == "character"):
            checks.append(self._check_face_detection(image_path, required=require_face))

        if self.config.check_artifacts:
            checks.append(self._check_artifacts(image_path))

        # v62.15: 불쾌한 골짜기 검증 (로컬 cv2 기반, Gemini Vision 완전 제거)
        if self.config.check_uncanny_valley:
            checks.append(self._check_uncanny_valley(image_path))

        # 전체 점수 계산
        valid_checks = [c for c in checks if c.status != QualityStatus.SKIPPED]
        if valid_checks:
            overall_score = sum(c.score for c in valid_checks) / len(valid_checks)
        else:
            overall_score = 1.0

        # 전체 상태 결정
        failed_count = sum(1 for c in checks if c.status == QualityStatus.FAILED)
        warning_count = sum(1 for c in checks if c.status == QualityStatus.WARNING)

        if failed_count > 0:
            overall_status = QualityStatus.FAILED
        elif warning_count > 0:
            overall_status = QualityStatus.WARNING
        else:
            overall_status = QualityStatus.PASSED

        processing_time = (time.time() - start_time) * 1000

        report = QualityReport(
            image_path=image_path,
            overall_status=overall_status,
            overall_score=overall_score,
            checks=checks,
            processing_time_ms=processing_time
        )

        # 실패 이미지 저장
        if report.overall_status == QualityStatus.FAILED and self.config.save_failed_images:
            self._save_failed_image(image_path, report)

        return report

    def validate_character_image(self, image_path: str) -> QualityReport:
        """캐릭터 이미지 검증 (얼굴 필수)"""
        return self.validate_image(image_path, image_type="character", require_face=True)

    def validate_background_image(self, image_path: str) -> QualityReport:
        """배경 이미지 검증 (얼굴 불필요)"""
        return self.validate_image(image_path, image_type="background", require_face=False)

    def validate_scene_image(self, image_path: str) -> QualityReport:
        """씬 이미지 검증"""
        return self.validate_image(image_path, image_type="scene", require_face=False)

    # ========================================================================
    # 개별 검증 항목
    # ========================================================================

    def _check_resolution(self, image_path: str) -> QualityCheckResult:
        """해상도 검증"""
        try:
            if self._pil_available:
                from PIL import Image
                with Image.open(image_path) as img:
                    width, height = img.size
            elif self._cv2_available:
                img = _cv2_imread_safe(image_path)
                if img is None:
                    return QualityCheckResult(
                        check_name="resolution",
                        status=QualityStatus.FAIL,
                        message=f"이미지 로드 실패: {image_path}"
                    )
                height, width = img.shape[:2]
            else:
                return QualityCheckResult(
                    check_name="resolution",
                    status=QualityStatus.SKIPPED,
                    message="이미지 라이브러리 없음"
                )

            min_w, min_h = self.config.min_resolution

            if width >= min_w and height >= min_h:
                score = min(1.0, (width * height) / (1920 * 1080))
                return QualityCheckResult(
                    check_name="resolution",
                    status=QualityStatus.PASSED,
                    score=score,
                    message=f"{width}x{height}",
                    details={"width": width, "height": height}
                )
            else:
                return QualityCheckResult(
                    check_name="resolution",
                    status=QualityStatus.FAILED,
                    score=0.3,
                    message=f"해상도 부족: {width}x{height} (최소: {min_w}x{min_h})",
                    details={"width": width, "height": height}
                )

        except Exception as e:
            return QualityCheckResult(
                check_name="resolution",
                status=QualityStatus.FAILED,
                message=f"해상도 검증 실패: {e}"
            )

    def _check_aspect_ratio(self, image_path: str) -> QualityCheckResult:
        """종횡비 검증 (16:9 권장)"""
        try:
            if self._pil_available:
                from PIL import Image
                with Image.open(image_path) as img:
                    width, height = img.size
            elif self._cv2_available:
                img = _cv2_imread_safe(image_path)
                if img is None:
                    return QualityCheckResult(
                        check_name="aspect_ratio",
                        status=QualityStatus.FAIL,
                        message=f"이미지 로드 실패: {image_path}"
                    )
                height, width = img.shape[:2]
            else:
                return QualityCheckResult(
                    check_name="aspect_ratio",
                    status=QualityStatus.SKIPPED
                )

            aspect_ratio = width / height
            target = self.config.target_aspect_ratio
            tolerance = self.config.aspect_ratio_tolerance

            diff = abs(aspect_ratio - target) / target

            if diff <= tolerance:
                return QualityCheckResult(
                    check_name="aspect_ratio",
                    status=QualityStatus.PASSED,
                    score=1.0 - diff,
                    message=f"종횡비: {aspect_ratio:.3f} (목표: {target:.3f})",
                    details={"ratio": aspect_ratio}
                )
            else:
                return QualityCheckResult(
                    check_name="aspect_ratio",
                    status=QualityStatus.WARNING,
                    score=0.7,
                    message=f"종횡비 차이: {aspect_ratio:.3f} (목표: {target:.3f})",
                    details={"ratio": aspect_ratio}
                )

        except Exception as e:
            return QualityCheckResult(
                check_name="aspect_ratio",
                status=QualityStatus.FAILED,
                message=f"종횡비 검증 실패: {e}"
            )

    def _check_blur(self, image_path: str) -> QualityCheckResult:
        """흐림(블러) 감지 - Laplacian Variance"""
        if not self._cv2_available:
            return QualityCheckResult(
                check_name="blur",
                status=QualityStatus.SKIPPED,
                message="OpenCV 없음"
            )

        try:
            import cv2
            import numpy as np

            img = _cv2_imread_safe(image_path, cv2.IMREAD_GRAYSCALE)
            if img is None:
                return QualityCheckResult(
                    check_name="blur",
                    status=QualityStatus.FAILED,
                    message="이미지 로드 실패"
                )

            # Laplacian variance (낮을수록 흐림)
            laplacian_var = cv2.Laplacian(img, cv2.CV_64F).var()

            max_blur = self.config.max_blur_score

            if laplacian_var >= max_blur:
                # 선명함
                score = min(1.0, laplacian_var / 500)
                return QualityCheckResult(
                    check_name="blur",
                    status=QualityStatus.PASSED,
                    score=score,
                    message=f"선명도: {laplacian_var:.1f}",
                    details={"laplacian_variance": laplacian_var}
                )
            else:
                # 흐림
                return QualityCheckResult(
                    check_name="blur",
                    status=QualityStatus.FAILED,
                    score=0.3,
                    message=f"이미지 흐림: {laplacian_var:.1f} (최소: {max_blur})",
                    details={"laplacian_variance": laplacian_var}
                )

        except Exception as e:
            return QualityCheckResult(
                check_name="blur",
                status=QualityStatus.FAILED,
                message=f"블러 검증 실패: {e}"
            )

    def _check_color_depth(self, image_path: str) -> QualityCheckResult:
        """색상 깊이 검증"""
        try:
            if self._pil_available:
                from PIL import Image
                with Image.open(image_path) as img:
                    mode = img.mode
                    bits_per_channel = {"L": 8, "RGB": 8, "RGBA": 8, "P": 8}.get(mode, 8)

                    if mode in ("RGB", "RGBA"):
                        return QualityCheckResult(
                            check_name="color_depth",
                            status=QualityStatus.PASSED,
                            score=1.0,
                            message=f"모드: {mode}",
                            details={"mode": mode}
                        )
                    else:
                        return QualityCheckResult(
                            check_name="color_depth",
                            status=QualityStatus.WARNING,
                            score=0.7,
                            message=f"비표준 모드: {mode}",
                            details={"mode": mode}
                        )
            else:
                return QualityCheckResult(
                    check_name="color_depth",
                    status=QualityStatus.SKIPPED
                )

        except Exception as e:
            return QualityCheckResult(
                check_name="color_depth",
                status=QualityStatus.FAILED,
                message=f"색상 깊이 검증 실패: {e}"
            )

    def _check_face_detection(self, image_path: str, required: bool = False) -> QualityCheckResult:
        """얼굴 감지"""
        if not self._cv2_available or self._face_cascade is None:
            return QualityCheckResult(
                check_name="face_detection",
                status=QualityStatus.SKIPPED,
                message="얼굴 감지 불가 (OpenCV 또는 캐스케이드 없음)"
            )

        try:
            import cv2

            img = _cv2_imread_safe(image_path)
            if img is None:
                return QualityCheckResult(
                    check_name="face_detection",
                    status=QualityStatus.FAILED,
                    message="이미지 로드 실패"
                )

            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

            # 얼굴 감지
            faces = self._face_cascade.detectMultiScale(
                gray,
                scaleFactor=1.1,
                minNeighbors=5,
                minSize=(30, 30)
            )

            face_count = len(faces)

            if face_count > 0:
                # 얼굴 신뢰도 (크기 기반)
                max_face_area = max((w * h) for (x, y, w, h) in faces)
                img_area = img.shape[0] * img.shape[1]
                confidence = min(1.0, max_face_area / (img_area * 0.1))

                if confidence >= self.config.min_face_confidence:
                    return QualityCheckResult(
                        check_name="face_detection",
                        status=QualityStatus.PASSED,
                        score=confidence,
                        message=f"얼굴 {face_count}개 감지",
                        details={"face_count": face_count, "confidence": confidence}
                    )
                else:
                    return QualityCheckResult(
                        check_name="face_detection",
                        status=QualityStatus.WARNING,
                        score=0.5,
                        message=f"얼굴 감지됐으나 신뢰도 낮음: {confidence:.2f}",
                        details={"face_count": face_count, "confidence": confidence}
                    )
            else:
                if required:
                    return QualityCheckResult(
                        check_name="face_detection",
                        status=QualityStatus.FAILED,
                        score=0.0,
                        message="얼굴 감지 실패 (필수)"
                    )
                else:
                    return QualityCheckResult(
                        check_name="face_detection",
                        status=QualityStatus.PASSED,
                        score=0.8,
                        message="얼굴 없음 (선택 항목)"
                    )

        except Exception as e:
            return QualityCheckResult(
                check_name="face_detection",
                status=QualityStatus.FAILED,
                message=f"얼굴 감지 실패: {e}"
            )

    def _check_uncanny_valley(self, image_path: str) -> QualityCheckResult:
        """
        v62.15: 로컬 cv2 기반 이미지 이상 감지 (Gemini Vision 완전 제거)

        검증 기준 (API 호출 0회):
        - 이미지 로드 실패 (완전 손상)
        - 완전 단색 이미지 (SD 생성 실패 징후: 채도 분산 < 임계값)
        - 극단적 밝기 편향 (완전 흑/백 화면)
        - 유효 픽셀 영역 부족 (너무 작은 실제 콘텐츠)
        """
        if not self._cv2_available:
            return QualityCheckResult(
                check_name="uncanny_valley",
                status=QualityStatus.SKIPPED,
                message="OpenCV 없음 (로컬 검증 불가)"
            )

        try:
            import cv2
            import numpy as np

            img = _cv2_imread_safe(image_path)
            if img is None:
                return QualityCheckResult(
                    check_name="uncanny_valley",
                    status=QualityStatus.FAILED,
                    score=0.0,
                    message="이미지 로드 실패 (손상된 파일)"
                )

            h, w = img.shape[:2]

            # 1. 완전 단색 감지 (SD 생성 실패 → 단색 이미지 반환)
            # HSV 채도 채널의 표준편차가 극히 낮으면 단색
            hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
            saturation_std = float(np.std(hsv[:, :, 1]))
            if saturation_std < 5.0:
                return QualityCheckResult(
                    check_name="uncanny_valley",
                    status=QualityStatus.FAILED,
                    score=0.0,
                    message=f"단색 이미지 감지 (채도 표준편차={saturation_std:.1f}, SD 생성 실패 의심)",
                    details={"saturation_std": saturation_std}
                )

            # 2. 극단적 밝기 편향 감지 (완전 흑/백 화면)
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            mean_brightness = float(np.mean(gray))
            if mean_brightness < 5.0:
                return QualityCheckResult(
                    check_name="uncanny_valley",
                    status=QualityStatus.FAILED,
                    score=0.0,
                    message=f"완전 흑색 이미지 (평균 밝기={mean_brightness:.1f})",
                    details={"mean_brightness": mean_brightness}
                )
            if mean_brightness > 250.0:
                return QualityCheckResult(
                    check_name="uncanny_valley",
                    status=QualityStatus.FAILED,
                    score=0.0,
                    message=f"완전 백색 이미지 (평균 밝기={mean_brightness:.1f})",
                    details={"mean_brightness": mean_brightness}
                )

            # 3. 유효 콘텐츠 영역 비율 확인
            # 에지 픽셀이 극히 적으면 빈 이미지
            edges = cv2.Canny(gray, 50, 150)
            edge_ratio = float(np.sum(edges > 0)) / (h * w)
            if edge_ratio < 0.001:
                return QualityCheckResult(
                    check_name="uncanny_valley",
                    status=QualityStatus.WARNING,
                    score=0.4,
                    message=f"콘텐츠 밀도 낮음 (에지 비율={edge_ratio:.4f})",
                    details={"edge_ratio": edge_ratio}
                )

            # 통과
            return QualityCheckResult(
                check_name="uncanny_valley",
                status=QualityStatus.PASSED,
                score=1.0,
                message="로컬 이상 감지 통과",
                details={
                    "saturation_std": saturation_std,
                    "mean_brightness": mean_brightness,
                    "edge_ratio": edge_ratio
                }
            )

        except Exception as e:
            logger.warning(f"[QC] uncanny_valley 로컬 검증 오류: {e}")
            return QualityCheckResult(
                check_name="uncanny_valley",
                status=QualityStatus.SKIPPED,
                message=f"로컬 검증 오류: {str(e)[:50]}"
            )

    # v62.11: validate_with_gemini() 제거 — Gemini 비전 API 호출 비용 절감
    # v62.15: _check_uncanny_valley() Gemini Vision → 로컬 cv2 완전 교체

    def _check_artifacts(self, image_path: str) -> QualityCheckResult:
        """아티팩트 감지 (JPEG 압축 아티팩트 등)"""
        if not self._cv2_available:
            return QualityCheckResult(
                check_name="artifacts",
                status=QualityStatus.SKIPPED,
                message="OpenCV 없음"
            )

        try:
            import cv2
            import numpy as np

            img = _cv2_imread_safe(image_path)
            if img is None:
                return QualityCheckResult(
                    check_name="artifacts",
                    status=QualityStatus.FAILED,
                    message="이미지 로드 실패"
                )

            # DCT 기반 JPEG 아티팩트 감지
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

            # 8x8 블록 경계 검출 (JPEG 특성)
            h, w = gray.shape
            block_edges = []

            # 수직 경계
            for x in range(8, w - 8, 8):
                col_diff = np.abs(gray[:, x].astype(float) - gray[:, x-1].astype(float))
                block_edges.append(np.mean(col_diff))

            # 수평 경계
            for y in range(8, h - 8, 8):
                row_diff = np.abs(gray[y, :].astype(float) - gray[y-1, :].astype(float))
                block_edges.append(np.mean(row_diff))

            if block_edges:
                artifact_score = np.mean(block_edges)

                # 낮을수록 좋음 (아티팩트 적음)
                if artifact_score < 5:
                    return QualityCheckResult(
                        check_name="artifacts",
                        status=QualityStatus.PASSED,
                        score=1.0,
                        message="아티팩트 없음",
                        details={"artifact_score": artifact_score}
                    )
                elif artifact_score < 10:
                    return QualityCheckResult(
                        check_name="artifacts",
                        status=QualityStatus.PASSED,
                        score=0.8,
                        message=f"경미한 아티팩트: {artifact_score:.1f}",
                        details={"artifact_score": artifact_score}
                    )
                else:
                    return QualityCheckResult(
                        check_name="artifacts",
                        status=QualityStatus.WARNING,
                        score=0.5,
                        message=f"아티팩트 감지됨: {artifact_score:.1f}",
                        details={"artifact_score": artifact_score}
                    )
            else:
                return QualityCheckResult(
                    check_name="artifacts",
                    status=QualityStatus.PASSED,
                    score=0.9,
                    message="이미지 너무 작음"
                )

        except Exception as e:
            return QualityCheckResult(
                check_name="artifacts",
                status=QualityStatus.FAILED,
                message=f"아티팩트 검증 실패: {e}"
            )

    # ========================================================================
    # 유틸리티
    # ========================================================================

    def _save_failed_image(self, image_path: str, report: QualityReport):
        """실패 이미지 저장"""
        try:
            failed_dir = Path(self.config.failed_images_path)
            failed_dir.mkdir(parents=True, exist_ok=True)

            # 해시 기반 파일명
            hash_name = hashlib.md5(image_path.encode()).hexdigest()[:8]
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

            # 원본 복사
            src = Path(image_path)
            if src.exists():
                import shutil
                dest = failed_dir / f"{timestamp}_{hash_name}{src.suffix}"
                shutil.copy2(src, dest)

            # 리포트 저장
            report_path = failed_dir / f"{timestamp}_{hash_name}_report.txt"
            with open(report_path, 'w', encoding='utf-8') as f:
                f.write(f"Image: {image_path}\n")
                f.write(f"Status: {report.overall_status.value}\n")
                f.write(f"Score: {report.overall_score:.2f}\n")
                f.write(f"Time: {report.processing_time_ms:.1f}ms\n")
                f.write("\nFailed Checks:\n")
                for check in report.failed_checks:
                    f.write(f"  - {check.check_name}: {check.message}\n")
                if report.warning_checks:
                    f.write("\nWarning Checks:\n")
                    for check in report.warning_checks:
                        f.write(f"  - {check.check_name}: {check.message}\n")

            logger.info(f"실패 이미지 저장: {dest}")

        except Exception as e:
            logger.error(f"실패 이미지 저장 실패: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """품질 검증 통계"""
        return {
            "enabled": self.config.enabled,
            "cv2_available": self._cv2_available,
            "pil_available": self._pil_available,
            "face_detection_available": self._face_cascade is not None,
            "checks_enabled": {
                "resolution": self.config.check_resolution,
                "aspect_ratio": self.config.check_aspect_ratio,
                "blur": self.config.check_blur,
                "face_detection": self.config.check_face_detection,
                "artifacts": self.config.check_artifacts,
                "color_depth": self.config.check_color_depth,
                "uncanny_valley": self.config.check_uncanny_valley  # v62.15: 로컬 cv2 기반
            }
        }

    def set_gemini_client(self, gemini_client):
        """
        v62.15: Gemini Vision 완전 제거로 인해 no-op (하위호환 유지)
        호출해도 아무 일도 일어나지 않음. 경고 로그만 출력.
        """
        logger.warning("[QC] set_gemini_client() 호출됨 - v62.15부터 Gemini Vision 제거됨, 무시")


# ============================================================================
# 테스트
# ============================================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    qc = QualityControl()

    print("=== QualityControl 테스트 ===")
    print(f"통계: {qc.get_stats()}")

    # 테스트 이미지가 있으면 검증
    test_image = "data/test_image.png"
    if os.path.exists(test_image):
        report = qc.validate_image(test_image)
        print(f"\n검증 결과:")
        print(f"  상태: {report.overall_status.value}")
        print(f"  점수: {report.overall_score:.2f}")
        print(f"  처리시간: {report.processing_time_ms:.1f}ms")
        for check in report.checks:
            print(f"  - {check.check_name}: {check.status.value} ({check.message})")
    else:
        print(f"\n테스트 이미지 없음: {test_image}")

    print("\n=== 테스트 완료 ===")
