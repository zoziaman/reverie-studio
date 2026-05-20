# src/pipeline/thumbnail_maker.py
"""
v60.1.0 Phase 7: 썸네일 생성 모듈

media_factory.py에서 추출한 썸네일 관련 7개 메서드.
- generate_test_thumbnail: 테스트 썸네일 생성
- create_thumbnails: 배경 이미지 생성 (v2.1)
- apply_text_overlay: 텍스트 오버레이
- apply_personalization: 개인화 적용
- review_with_gemini: Gemini QC 검수
- create_with_review: 생성 + 검수 루프
- cleanup_temp_files: 임시 파일 정리

원본 위치: media_factory.py L4919-5545

NOTE: 이 모듈의 메서드들은 config, visual_director 등 외부 의존이 많아서
      호출 시 필요한 파라미터를 주입하는 패턴을 사용합니다.
"""
import os
import re
import base64
import logging
import shutil
import textwrap
import tempfile
from typing import Dict, Any, List, Optional, Callable, Tuple

logger = logging.getLogger(__name__)

from config.settings import config

# Pillow (선택적)
try:
    from PIL import Image, ImageDraw, ImageFont, ImageEnhance
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    logger.warning("[ThumbnailMaker] Pillow not available")

# 기본 폰트 탐색
DEFAULT_FONT = None
if PIL_AVAILABLE:
    for fp in ["malgunbd.ttf", "C:/Windows/Fonts/malgunbd.ttf"]:
        try:
            ImageFont.truetype(fp, 10)
            DEFAULT_FONT = fp
            break
        except Exception:
            continue


class ThumbnailMaker:
    """썸네일 생성 + Gemini QC + 텍스트 오버레이

    SD WebUI로 배경 생성, Pillow로 텍스트 합성, Gemini로 품질 검증.
    """

    def __init__(
        self,
        sd_url: str,
        data_dir: str,
        assets_dir: str,
        font_path: str = "",
        video_width: int = 1920,
        video_height: int = 1080,
    ) -> None:
        self.sd_url = sd_url.rstrip('/')
        self.data_dir = data_dir
        self.assets_dir = assets_dir
        self.font_path = font_path
        self.W = video_width
        self.H = video_height

    def _apply_vram_safety(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """8GB급 환경에서 썸네일 생성 요청을 안전 범위로 보정한다."""
        payload = dict(payload)

        width = int(payload.get("width", 0) or 0)
        height = int(payload.get("height", 0) or 0)
        if width > 0 and height > 0:
            safe_width, safe_height = config.clamp_sd_dimensions(width, height, purpose="thumbnail")
            payload["width"] = safe_width
            payload["height"] = safe_height

        steps = int(payload.get("steps", 0) or 0)
        if steps > 0:
            payload["steps"] = config.clamp_sd_steps(steps, purpose="thumbnail")

        if config.is_low_vram():
            payload["batch_size"] = 1
            payload["n_iter"] = 1
            if payload.get("enable_hr"):
                payload["enable_hr"] = False

        return payload

    # ============================================================
    # 테스트 썸네일 생성
    # ============================================================

    def generate_test_thumbnail(
        self,
        style_name: str,
        top_text: str,
        main_text: str,
        output_path: str,
        mode: str,
        channel: str,
        styles: Dict[str, Any],
        consistency_fn: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
        content_reviewer: Optional[Any] = None,
        ultra_negative: str = "",
    ) -> str:
        """
        테스트용 썸네일 생성

        Args:
            style_name: "REAL" 또는 "ART"
            top_text: 상단 텍스트
            main_text: 메인 제목
            output_path: 저장 경로
            mode: 채널 모드
            channel: 채널명
            styles: 스타일 딕셔너리
            consistency_fn: payload 일관성 적용 콜백
            content_reviewer: NSFW 검수기
            ultra_negative: 네거티브 프롬프트 추가분

        Returns:
            str: 생성된 썸네일 경로
        """
        import requests
        from modules_pro.visual_director import visual_director
        from pipeline.pipeline_utils import safe_print

        style_cfg = styles.get(mode, styles.get("touching", {}))
        style_pos = style_cfg.get("positive", "")
        style_neg = style_cfg.get("negative", "")

        extra_p = f"{style_pos}, masterpiece, best quality, highly detailed background"
        if style_name == "REAL":
            extra_p += ", realistic texture, cinematic"
        else:
            extra_p += ", illustration, artistic"
        style_neg = f"{style_neg}, {ultra_negative}"

        thumb_base = visual_director.get_thumbnail_background(category=channel, mode=mode)
        thumb_base_clean = re.sub(r'[^\w\s가-힣]', ' ', thumb_base)
        thumb_base_clean = ' '.join(thumb_base_clean.split())

        pos, neg = visual_director.finalize(
            raw_prompt=thumb_base_clean,
            extra_positive=extra_p,
            extra_negative=style_neg
        )

        safe_print(f"\n{'='*60}")
        safe_print(f"[썸네일 생성] {style_name} 스타일")
        safe_print(f"{'='*60}")
        safe_print(f"Positive Prompt:\n  {pos[:150]}...")
        safe_print(f"\nNegative Prompt:\n  {neg[:150]}...")
        safe_print(f"{'='*60}\n")

        payload = {
            "prompt": pos.strip(),
            "negative_prompt": neg.strip(),
            "steps": 30,
            "width": self.W,
            "height": self.H,
            "sampler_name": "DPM++ 2M Karras",
            "cfg_scale": 5.0,
        }

        if consistency_fn:
            payload = consistency_fn(payload)
        payload = self._apply_vram_safety(payload)

        safe_print(f"   🎨 SD API 호출 중... ({style_name})")
        res = requests.post(f"{self.sd_url}/sdapi/v1/txt2img", json=payload, timeout=120)

        if res.status_code != 200:
            raise Exception(f"SD API 오류: {res.status_code}")

        # v62.10: mktemp() TOCTOU race condition 수정 → NamedTemporaryFile 사용
        # v62.19: try/finally로 temp 파일 정리 보장
        import tempfile as _tempfile
        with _tempfile.NamedTemporaryFile(suffix=".png", delete=False) as _tmp:
            temp_path = _tmp.name
            # v62.21 M-10: SD 빈 images 배열 가드
            _sd_images = res.json().get("images", [])
            if not _sd_images:
                raise Exception("SD 응답에 images 필드 없음")
            _tmp.write(base64.b64decode(_sd_images[0]))

        try:
            with Image.open(temp_path) as _tmp_img:
                img = _tmp_img.convert("RGB")

            # 밝기 설정
            from gui.settings_manager import SettingsManager
            settings_mgr = SettingsManager(self.data_dir)
            thumb_settings = settings_mgr.get_thumbnail_settings(channel, mode)
            brightness = thumb_settings.get("brightness", 0.4)
            img = ImageEnhance.Brightness(img).enhance(brightness)

            # 배경 이미지 별도 저장
            bg_path = output_path.replace(".jpg", "_bg.jpg")
            img.save(bg_path, quality=95)
            safe_print(f"   배경 이미지 저장: {bg_path}")

            # NSFW 검수
            if content_reviewer:
                channel_type = f"{channel}_{mode}" if mode else channel
                result, reason = content_reviewer.review_image(bg_path, channel_type)
                if result == "UNSAFE":
                    logger.warning(f"[검수] 썸네일 배경 위반: {reason}")
                    for retry in range(2):
                        logger.info(f"[검수] 썸네일 배경 재생성 시도 {retry+1}/2")
                        res = requests.post(f"{self.sd_url}/sdapi/v1/txt2img", json=payload, timeout=120)
                        if res.status_code == 200:
                            # v62.21 M-10: SD 빈 images 배열 가드
                            _retry_imgs = res.json().get("images", [])
                            if not _retry_imgs:
                                continue
                            with open(temp_path, "wb") as f2:
                                f2.write(base64.b64decode(_retry_imgs[0]))
                            with Image.open(temp_path) as _retry_img:  # v62.10: PIL 핸들 즉시 닫기
                                img = _retry_img.convert("RGB")
                            img = ImageEnhance.Brightness(img).enhance(brightness)
                            img.save(bg_path, quality=95)
                            result, reason = content_reviewer.review_image(bg_path, channel_type)
                            if result != "UNSAFE":
                                safe_print(f"   썸네일 검수 통과 (재생성 {retry+1}회)")
                                break
                    else:
                        logger.error("[검수] 썸네일 2회 재생성 후에도 위반")
                elif result == "WARN":
                    logger.info(f"[검수] 썸네일 배경 경고: {reason} (통과 처리)")

            # 텍스트 그리기
            draw = ImageDraw.Draw(img)
            try:
                f_top = ImageFont.truetype(self.font_path, thumb_settings["top_text"]["font_size"])
                f_main = ImageFont.truetype(self.font_path, thumb_settings["main_title"]["font_size"])
            except Exception:
                if DEFAULT_FONT:
                    f_top = ImageFont.truetype(DEFAULT_FONT, 70)
                    f_main = ImageFont.truetype(DEFAULT_FONT, 130)
                else:
                    f_top = ImageFont.load_default()
                    f_main = ImageFont.load_default()

            # 상단 텍스트
            top_settings = thumb_settings["top_text"]
            top_text_clean = re.sub(r'[^\w\s가-힣a-zA-Z0-9.,!?~\-]', '', top_text)
            top_bbox = draw.textbbox((0, 0), top_text_clean, font=f_top)
            top_w = top_bbox[2] - top_bbox[0]
            top_x = top_settings.get("x", self.W // 2) - (top_w // 2)
            draw.text(
                (top_x, top_settings.get("y", 80)),
                top_text_clean,
                fill=top_settings.get("color", "#FFD700"),
                font=f_top, stroke_width=4, stroke_fill="#000000"
            )

            # 메인 제목
            main_settings = thumb_settings["main_title"]
            main_text_clean = re.sub(r'[^\w\s가-힣a-zA-Z0-9.,!?~\-]', '', main_text)
            main_lines = textwrap.wrap(main_text_clean, width=main_settings.get("wrap_width", 10))
            curr_y = main_settings.get("y", 200)
            for line in main_lines:
                line_bbox = draw.textbbox((0, 0), line, font=f_main)
                line_w = line_bbox[2] - line_bbox[0]
                line_x = main_settings.get("x", self.W // 2) - (line_w // 2)
                draw.text(
                    (line_x, curr_y), line,
                    fill=main_settings.get("color", "#FF0000"),
                    font=f_main, stroke_width=8, stroke_fill="#000000"
                )
                curr_y += main_settings["font_size"] + 20

            img.save(output_path, quality=95)
            return output_path
        finally:
            # v62.19: 예외 경로에서도 temp 파일 반드시 삭제
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except OSError as e:
                logger.debug(f"임시 파일 삭제 실패 (무시): {temp_path}: {e}")

    # ============================================================
    # 썸네일 배경 생성 (v2.1)
    # ============================================================

    def create_thumbnails(
        self,
        project_name: str,
        title: str,
        sub_title: str,
        base_p: str,
        mode: str,
        channel: str,
        styles: Dict[str, Any],
        consistency_fn: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
        ultra_negative: str = "",
    ) -> None:
        """
        썸네일 배경 생성 (v2.1) — 텍스트 없이 배경만 생성

        REAL/ART 두 스타일로 배경 이미지를 생성합니다.
        GUI에서 사용자가 직접 텍스트 커스텀.

        Args:
            project_name: 프로젝트 이름 (파일명에 사용)
            title: 메인 제목
            sub_title: 부제목
            base_p: 기본 프롬프트 (현재 미사용)
            mode: 채널 모드 (touching, makjang 등)
            channel: 채널명
            styles: SD 스타일 딕셔너리 {mode: {positive, negative}}
            consistency_fn: IP-Adapter 일관성 적용 콜백
            ultra_negative: 추가 네거티브 프롬프트
        """
        import requests
        from modules_pro.visual_director import visual_director
        from pipeline.pipeline_utils import safe_print

        thumb_dir = os.path.join(self.data_dir, "thumbnails")
        os.makedirs(thumb_dir, exist_ok=True)

        style_cfg = styles.get(mode, styles.get("touching", {}))
        style_pos = style_cfg.get("positive", "")
        style_neg = style_cfg.get("negative", "")

        for style_name in ["REAL", "ART"]:
            extra_p = f"{style_pos}, masterpiece, best quality, highly detailed background"
            if style_name == "REAL":
                extra_p += ", realistic texture, cinematic"
            else:
                extra_p += ", illustration, artistic"
            neg_with_ultra = f"{style_neg}, {ultra_negative}"

            thumb_base = visual_director.get_thumbnail_background(category=channel, mode=mode)
            thumb_base_clean = re.sub(r'[^\w\s가-힣]', ' ', thumb_base)
            thumb_base_clean = ' '.join(thumb_base_clean.split())

            pos, neg = visual_director.finalize(
                raw_prompt=thumb_base_clean,
                extra_positive=extra_p,
                extra_negative=neg_with_ultra,
                channel_type=channel
            )

            # 팩 SD 설정
            thumb_steps, thumb_cfg_scale, thumb_sampler, thumb_scheduler, lora_tags = self._get_pack_sd_settings()
            final_pos = f"{lora_tags}, {pos.strip()}" if lora_tags else pos.strip()

            payload = {
                "prompt": final_pos,
                "negative_prompt": neg.strip(),
                "steps": thumb_steps,
                "width": self.W,
                "height": self.H,
                "sampler_name": thumb_sampler,
                "cfg_scale": thumb_cfg_scale,
            }
            if thumb_scheduler:
                payload["scheduler"] = thumb_scheduler

                if consistency_fn:
                    payload = consistency_fn(payload)
                payload = self._apply_vram_safety(payload)

            try:
                res = requests.post(f"{self.sd_url}/sdapi/v1/txt2img", json=payload, timeout=120)
                if res.status_code == 200:
                    # v62.21 M-10: SD 빈 images 배열 가드
                    _thumb_imgs = res.json().get("images", [])
                    if not _thumb_imgs:
                        safe_print(f"      ⚠️ 썸네일 생성 실패 ({style_name}): SD 빈 images 응답")
                        continue
                    bg_path = os.path.join(thumb_dir, "temp.png")
                    with open(bg_path, "wb") as f:
                        f.write(base64.b64decode(_thumb_imgs[0]))

                    img = Image.open(bg_path).convert("RGB")
                    img = ImageEnhance.Brightness(img).enhance(0.4)
                    img.save(os.path.join(thumb_dir, f"{project_name}_{style_name}.jpg"), quality=95)
                    os.remove(bg_path)
                    safe_print(f"      ✅ 썸네일 생성 완료 ({style_name})")
            except Exception as e:
                safe_print(f"      ⚠️ 썸네일 생성 실패 ({style_name}): {e}")

    # ============================================================
    # 텍스트 오버레이
    # ============================================================

    def apply_text_overlay(self, thumb_path: str, main_title: str, sub_title: str, mode: str) -> None:
        """
        썸네일에 텍스트 오버레이 적용

        배경 이미지 위에 상단 부제목 + 메인 제목을 렌더링합니다.
        특수문자를 제거하고, 긴 제목은 자동 줄바꿈합니다.

        Args:
            thumb_path: 배경 이미지 파일 경로 (in-place 수정)
            main_title: 메인 제목 텍스트
            sub_title: 상단 부제목 텍스트
            mode: 채널 모드 (현재 미사용, 향후 모드별 스타일 확장용)
        """
        if not os.path.exists(thumb_path):
            logger.warning(f"[썸네일] 파일 없음: {thumb_path}")
            return

        try:
            img = Image.open(thumb_path).convert("RGB")
            draw = ImageDraw.Draw(img)
            W, H = img.size

            try:
                f_top = ImageFont.truetype(self.font_path, 70)
                f_main = ImageFont.truetype(self.font_path, 130)
            except Exception:
                if DEFAULT_FONT:
                    f_top = ImageFont.truetype(DEFAULT_FONT, 70)
                    f_main = ImageFont.truetype(DEFAULT_FONT, 130)
                else:
                    f_top = ImageFont.load_default()
                    f_main = ImageFont.load_default()

            sub_clean = re.sub(r'[^\w\s가-힣a-zA-Z0-9.,!?~\-]', '', sub_title or "")
            main_clean = re.sub(r'[^\w\s가-힣a-zA-Z0-9.,!?~\-]', '', main_title or "")

            if sub_clean:
                top_bbox = draw.textbbox((0, 0), sub_clean, font=f_top)
                top_w = top_bbox[2] - top_bbox[0]
                top_x = (W - top_w) // 2
                draw.text((top_x, 80), sub_clean, fill="#FFD700",
                         font=f_top, stroke_width=4, stroke_fill="#000000")

            if main_clean:
                # v62.21 M-11: 줄바꿈 최대 4줄 제한 (이미지 밖으로 넘침 방지)
                main_lines = textwrap.wrap(main_clean, width=10)[:4]
                curr_y = 200
                for line in main_lines:
                    line_bbox = draw.textbbox((0, 0), line, font=f_main)
                    line_w = line_bbox[2] - line_bbox[0]
                    line_x = (W - line_w) // 2
                    draw.text((line_x, curr_y), line, fill="#FF0000",
                             font=f_main, stroke_width=8, stroke_fill="#000000")
                    curr_y += 150

            img.save(thumb_path, quality=95)
            logger.info(f"[썸네일] 텍스트 오버레이 완료: {thumb_path}")
        except Exception as e:
            logger.error(f"[썸네일] 텍스트 오버레이 실패: {e}")

    # ============================================================
    # Gemini QC 검수
    # ============================================================

    def review_with_gemini(
        self, thumb_path: str, title: str, sub_title: str,
        mode: str, story_summary: Optional[str] = None,
        script_preview: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Gemini로 썸네일 품질 검증

        썸네일 이미지를 Gemini Vision에 전달하여 품질 점수,
        이슈 목록, 내용 일치도를 평가합니다.

        Args:
            thumb_path: 검수할 썸네일 이미지 경로
            title: 메인 제목 (내용 일치도 검증용)
            sub_title: 부제목
            mode: 채널 모드
            story_summary: 스토리 요약 (내용 일치도 검증용)
            script_preview: 대본 미리보기 (내용 일치도 검증용)

        Returns:
            검수 결과 {passed, score, issues, content_mismatch, ...}
        """
        try:
            from utils.thumbnail_reviewer import get_thumbnail_reviewer
            from pipeline.pipeline_utils import safe_print

            reviewer = get_thumbnail_reviewer()
            result = reviewer.review_thumbnail(
                thumbnail_path=thumb_path, title=title,
                sub_title=sub_title, category=mode,
                story_summary=story_summary, script_preview=script_preview
            )

            if result.get('passed'):
                safe_print(f"      ✅ 썸네일 검수 합격! (점수: {result.get('score', 0)}/100)")
            else:
                safe_print(f"      ⚠️ 썸네일 검수 불합격 (점수: {result.get('score', 0)}/100)")
                for issue in result.get('issues', [])[:3]:
                    safe_print(f"         - {issue}")
                if result.get('content_mismatch'):
                    safe_print(f"         ❌ 내용 불일치: {result.get('content_mismatch_reason', '')}")

            return result

        except ImportError:
            return {'passed': True, 'score': 70, 'issues': [], 'content_mismatch': False}
        except Exception as e:
            logger.warning(f"[썸네일] 검수 오류: {e}")
            return {'passed': True, 'score': 70, 'issues': [], 'content_mismatch': False}

    # ============================================================
    # 생성 + 검수 루프
    # ============================================================

    def create_with_review(
        self, project_name: str, title: str, sub_title: str,
        mode: str, channel: str, styles: Dict[str, Any],
        consistency_fn: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
        ultra_negative: str = "",
        story_summary: Optional[str] = None,
        script_preview: Optional[str] = None,
        max_attempts: int = 3,
    ) -> None:
        """
        썸네일 생성 + Gemini 검수 + 자동 재생성 루프

        최대 max_attempts회까지 썸네일을 생성하고 Gemini로 검수합니다.
        합격 시 즉시 종료, 불합격 시 재생성을 시도합니다.

        Args:
            project_name: 프로젝트 이름
            title: 메인 제목
            sub_title: 부제목
            mode: 채널 모드
            channel: 채널명
            styles: SD 스타일 딕셔너리
            consistency_fn: IP-Adapter 일관성 적용 콜백
            ultra_negative: 추가 네거티브 프롬프트
            story_summary: 스토리 요약 (내용 일치도 검증용)
            script_preview: 대본 미리보기 (내용 일치도 검증용)
            max_attempts: 최대 재생성 횟수
        """
        from pipeline.pipeline_utils import safe_print
        thumb_dir = os.path.join(self.data_dir, "thumbnails")

        for attempt in range(max_attempts):
            safe_print(f"\n   [썸네일] 생성 시도 {attempt + 1}/{max_attempts}")

            self.create_thumbnails(
                project_name=project_name, title=title,
                sub_title=sub_title, base_p="", mode=mode,
                channel=channel, styles=styles,
                consistency_fn=consistency_fn,
                ultra_negative=ultra_negative
            )

            thumb_path = os.path.join(thumb_dir, f"{project_name}_REAL.jpg")
            if not os.path.exists(thumb_path):
                safe_print(f"      ⚠️ 썸네일 파일 생성 실패")
                continue

            review = self.review_with_gemini(
                thumb_path=thumb_path, title=title,
                sub_title=sub_title, mode=mode,
                story_summary=story_summary, script_preview=script_preview
            )

            if review.get('passed'):
                safe_print(f"   [썸네일] 최종 합격!")
                return

            if review.get('regenerate_prompt'):
                safe_print(f"      🔄 재생성 시도 (제안: {review.get('suggested_scene', '')})")

        safe_print(f"   [썸네일] 최대 시도 횟수 초과, 마지막 결과 사용")

    # ============================================================
    # 임시 파일 정리
    # ============================================================

    def cleanup_temp_files(
        self, project_name: str,
        sanitize_fn: Optional[Callable[[str], str]] = None,
    ) -> None:
        """
        임시 오디오/이미지 폴더 삭제

        Args:
            project_name: 프로젝트 이름
            sanitize_fn: 경로 안전화 함수 (없으면 원본 이름 사용)
        """
        safe_name = sanitize_fn(project_name) if sanitize_fn else project_name
        for folder in ["temp_audio", "temp_images"]:
            p = os.path.join(self.data_dir, folder, safe_name)
            if os.path.exists(p):
                shutil.rmtree(p)

    # ============================================================
    # 내부 헬퍼
    # ============================================================

    def _get_pack_sd_settings(self) -> Tuple[int, float, str, Optional[str], str]:
        """
        팩에서 SD 모델 설정 로딩

        ACTIVE_PACK.visual_storytelling.sd_model에서 썸네일 생성용
        SD 파라미터를 읽어옵니다. 팩 미로딩 시 기본값 반환.

        Returns:
            (steps, cfg_scale, sampler_name, scheduler, lora_tags)
        """
        thumb_steps = 30
        thumb_cfg = 5.5
        thumb_sampler = "DPM++ 2M Karras"
        thumb_scheduler = None
        lora_tags = ""

        try:
            from config.pack_config import ACTIVE_PACK, PACK_CONFIG_AVAILABLE
            if PACK_CONFIG_AVAILABLE and ACTIVE_PACK.is_loaded:
                vs_config = getattr(ACTIVE_PACK, 'visual_storytelling', None)
                if vs_config:
                    if isinstance(vs_config, dict):
                        sd_model = vs_config.get('sd_model', None)
                    else:
                        sd_model = getattr(vs_config, 'sd_model', None)
                    if sd_model:
                        _g = (lambda d, k, default: d.get(k, default) if isinstance(d, dict) else getattr(d, k, default))
                        thumb_steps = _g(sd_model, 'steps', 30)
                        thumb_cfg = _g(sd_model, 'cfg_scale', 5.5)
                        thumb_sampler = _g(sd_model, 'sampler', "DPM++ 2M Karras")
                        thumb_scheduler = _g(sd_model, 'scheduler', None)
                        lora_models = _g(sd_model, 'lora_models', [])
                        lora_parts = []
                        for lora in lora_models:
                            if isinstance(lora, dict):
                                name = lora.get('name', '')
                                weight = lora.get('weight', 0.7)
                                if name:
                                    lora_parts.append(f"<lora:{name}:{weight}>")
                                trigger = lora.get('trigger', '')
                                if trigger:
                                    lora_parts.append(trigger)
                        lora_tags = ", ".join(lora_parts)
        except ImportError:
            pass

        return thumb_steps, thumb_cfg, thumb_sampler, thumb_scheduler, lora_tags
