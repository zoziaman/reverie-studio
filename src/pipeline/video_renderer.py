# src/pipeline/video_renderer.py
"""
v60.1.0 Phase 10: 영상 렌더링 모듈

media_factory.py에서 추출한 영상 조립/렌더링 관련 메서드.
2개 핵심 메서드:
  1. assemble_main: 렌더 엔진 라우터 (Remotion 전용)
  2. assemble_main_remotion: Remotion 기반 렌더링

원본 위치: media_factory.py L1822-2140
"""
import os
import random
import logging
import tempfile
from glob import glob
from typing import Dict, Any, List, Optional, Callable

logger = logging.getLogger(__name__)

try:
    import config
except ImportError:  # pragma: no cover
    config = None


class VideoRenderer:
    """Remotion 기반 영상 렌더링

    RemotionAssembler를 사용하여 이미지, 자막, 오디오, BGM, SFX, Hook을
    합성하여 최종 MP4를 생성합니다.

    외부 의존성은 생성자 파라미터 또는 콜백으로 주입받습니다.
    """

    # v62.10: 클래스 레벨 상수로 추출 (35턴 루프에서 매번 생성하던 것을 1회 정의로 변경)
    _ROLE_DISPLAY = {
        "grandma": "할머니", "grandpa": "할아버지",
        "man": "남자", "woman": "여자", "child": "손주",
        "narrator": "나레이션", "narration": "나레이션",
        "young_man": "청년", "young_woman": "청녀",
        "middle_man": "중년남", "middle_woman": "중년녀",
        "antagonist": "악역",
    }

    def __init__(
        self,
        channel: str,
        video_width: int = 1920,
        video_height: int = 1080,
        fps: int = 30,
        concurrency: int = 6,
    ) -> None:
        self.channel = channel
        self.video_width = video_width
        self.video_height = video_height
        self.fps = fps
        self.concurrency = concurrency

        # 외부 콜백 슬롯
        self._style_getter_fn: Optional[Callable[[str], Dict[str, Any]]] = None
        self._get_bgm_folder_fn: Optional[Callable[[str], str]] = None
        self._prepare_sfx_fn: Optional[Callable[..., None]] = None

    def set_callbacks(
        self,
        style_getter: Optional[Callable[[str], Dict[str, Any]]] = None,
        get_bgm_folder: Optional[Callable[[str], str]] = None,
        prepare_sfx_for_remotion: Optional[Callable[..., None]] = None,
    ) -> None:
        """
        외부 의존 콜백 주입

        VideoRenderer는 BGM, SFX, 스타일 정보를 외부에서 주입받습니다.
        orchestrator가 파이프라인 초기화 시 이 메서드로 콜백을 등록합니다.

        Args:
            style_getter: 채널별 시각 스타일 조회 콜백
            get_bgm_folder: 모드별 BGM 폴더 경로 반환 콜백
            prepare_sfx_for_remotion: SFX 데이터를 Remotion 어셈블러에 추가하는 콜백
        """
        if style_getter is not None:
            if not callable(style_getter):
                logger.warning(f"[VideoRenderer] style_getter is not callable: {type(style_getter)}")
            else:
                self._style_getter_fn = style_getter
        if get_bgm_folder is not None:
            if not callable(get_bgm_folder):
                logger.warning(f"[VideoRenderer] get_bgm_folder is not callable: {type(get_bgm_folder)}")
            else:
                self._get_bgm_folder_fn = get_bgm_folder
        if prepare_sfx_for_remotion is not None:
            if not callable(prepare_sfx_for_remotion):
                logger.warning(f"[VideoRenderer] prepare_sfx_for_remotion is not callable: {type(prepare_sfx_for_remotion)}")
            else:
                self._prepare_sfx_fn = prepare_sfx_for_remotion

    def assemble_main(
        self,
        audio_path: str,
        subtitle_data: List[Dict[str, Any]],
        image_paths: List[str],
        mode: str,
        topic: str = "",
    ) -> Optional[str]:
        """
        본편 영상 조립 (Remotion 전용)

        v58.3.3: Remotion 전용 (MoviePy 완전 제거)
        v58.4.0: Hook 통합 - 재조립 단계 완전 제거

        Args:
            audio_path: 전체 음성 파일 경로 (full.wav)
            subtitle_data: 자막 데이터 [{text, role, start, end}, ...]
            image_paths: 이미지 파일 경로 리스트
            mode: 채널 모드 (touching, makjang, horror)
            topic: 주제 텍스트 (Hook용)

        Returns:
            str: 렌더링된 MP4 파일 경로
        """
        try:
            from modules_pro.remotion_assembler import RemotionAssembler
            REMOTION_AVAILABLE = True
        except ImportError:
            REMOTION_AVAILABLE = False
            RemotionAssembler = None

        if REMOTION_AVAILABLE and RemotionAssembler is not None:
            return self._assemble_remotion(audio_path, subtitle_data, image_paths, mode, topic=topic)

        raise RuntimeError(
            "Remotion이 설치되지 않았습니다. "
            "remotion-poc/ 디렉토리가 존재하고 npm install이 완료되었는지 확인하세요."
        )

    def _assemble_remotion(
        self,
        audio_path: str,
        subtitle_data: List[Dict[str, Any]],
        image_paths: List[str],
        mode: str,
        topic: str = "",
    ) -> str:
        """
        v57.4: Remotion 기반 본편 영상 조립
        v58.4.0: Hook 통합 - 재조립 단계 완전 제거

        Returns:
            str: Remotion으로 렌더링된 최종 영상 경로
        """
        from modules_pro.remotion_assembler import RemotionAssembler

        try:
            from modules_pro.visual_director import visual_director  # v61.1: 싱글톤 인스턴스 import
        except ImportError:
            visual_director = None

        logger.info(f"[VideoRenderer] Remotion 렌더링 시작: {len(subtitle_data)}개 자막, {len(image_paths)}개 이미지")

        # Remotion 어셈블러 생성
        assembler = RemotionAssembler(
            fps=self.fps,
            width=self.video_width,
            height=self.video_height,
            concurrency=self.concurrency,
            channel=self.channel,
            style_getter=self._style_getter_fn,
            show_ai_disclosure=True,
            ai_disclosure_duration=3.0,
            # v61.1-fix: 1.0 하드코딩 제거 → RemotionAssembler 기본값 2.5 사용 (v58.3.7 볼륨 정책)
            # tts_volume=1.0,  # REMOVED: 기본값 2.5가 GPT-SoVITS -10 LUFS 보정
        )

        # 팩에서 Hook/Visual/Subtitle 설정 로드
        try:
            from config.pack_config import (
                ACTIVE_PACK,
                resolve_motiontoon_runtime_config,
            )
            if ACTIVE_PACK.is_loaded:
                if topic:
                    hook_style = ACTIVE_PACK.hook_style
                    hook_duration = getattr(hook_style, 'duration', 4.0) if hook_style else 4.0
                    assembler.set_hook(
                        topic=topic,
                        channel=self.channel,
                        mode=mode,
                        duration_sec=hook_duration,
                        hook_style=hook_style,
                    )
                    logger.info(f"[v59.1.6] Hook 설정 완료 (팩 기반): {topic[:30]}...")

                if visual_director:
                    ve_config = visual_director.get_visual_effects_config()
                    ss_config = visual_director.get_subtitle_style_config()

                    if ve_config:
                        assembler.set_visual_effects(config=ve_config)
                        logger.info("[v59.5.15b] visualEffects 설정 완료")
                    if ss_config:
                        assembler.set_subtitle_style(config=ss_config)
                        logger.info("[v59.5.15b] subtitleStyle 설정 완료")
                render_mode_override = getattr(config, "MOTIONTOON_RENDER_MODE_OVERRIDE", None) if config else None
                motiontoon_config, motiontoon_support = resolve_motiontoon_runtime_config(
                    render_mode_override=render_mode_override,
                )
                if motiontoon_support.get("reason") == "pack_basic_only":
                    logger.info("[Motiontoon] pack is basic-only; falling back to classic dynamic render")
                elif motiontoon_support.get("reason") == "pack_disabled":
                    logger.info("[Motiontoon] pack has motiontoon disabled; falling back to classic dynamic render")
                if motiontoon_config:
                    assembler.set_motiontoon_config(motiontoon_config)
            else:
                if topic:
                    assembler.set_hook(
                        topic=topic,
                        channel=self.channel,
                        mode=mode,
                        duration_sec=4.0,
                    )
        except ImportError:
            if topic:
                assembler.set_hook(
                    topic=topic,
                    channel=self.channel,
                    mode=mode,
                    duration_sec=4.0,
                )

        # 이미지 검증
        if len(image_paths) <= 0:
            raise RuntimeError("이미지가 없습니다. Remotion 렌더링 불가.")

        # v61.1 (#45): 이미지 시퀀스 준비 — 순차 반복 (셔플 제거)
        n_subs = len(subtitle_data)
        if len(image_paths) < n_subs:
            # 순차 반복: 0,1,2,...,N-1,0,1,2,...
            image_seq = [image_paths[i % len(image_paths)] for i in range(n_subs)]
        else:
            image_seq = image_paths[:n_subs]

        # 씬 추가
        for idx, sub in enumerate(subtitle_data):
            sub_start = float(sub.get("start", 0))
            sub_scene_end = float(sub.get("scene_end", sub.get("end", 0) + 0.5))
            dur_ms = round((sub_scene_end - sub_start) * 1000)
            start_ms = round(sub_start * 1000)

            if dur_ms <= 0:
                dur_ms = 1000

            # v62.19: 이미지 파일 존재 검증 — Remotion 렌더링 크래시 방지
            scene_img = image_seq[idx % len(image_seq)]
            if not os.path.exists(scene_img):
                logger.warning(f"[VideoRenderer] 이미지 파일 없음 (씬 {idx}): {scene_img}")
                # 긴급 검정 플레이스홀더 생성
                try:
                    from PIL import Image as _PIL_Image
                    _placeholder = _PIL_Image.new("RGB", (768, 432), (0, 0, 0))
                    _placeholder.save(scene_img)
                    logger.info(f"[VideoRenderer] 긴급 플레이스홀더 생성: {scene_img}")
                except Exception as _ph_e:
                    logger.error(f"[VideoRenderer] 플레이스홀더 생성 실패: {_ph_e}")

            # v61.1 (#44): audio_path=""는 의도적 (fullAudioPath 사용)
            # 개별 씬 오디오 대신 set_full_audio()로 전체 TTS를 한 번에 전달
            # v62.7: role → display_name 한국어 변환 (grandma→할머니 등)
            # v62.10: 클래스 레벨 _ROLE_DISPLAY 사용 (루프 내 재생성 불필요)
            role_raw = sub.get("role", "나레이션")
            # 팩 display_name 우선 → 기본 매핑 → role 그대로
            char_display = (
                sub.get("display_name")
                or self._ROLE_DISPLAY.get(role_raw.lower(), role_raw)
            )
            assembler.add_scene(
                image_path=scene_img,
                audio_path="",
                text=sub.get("text", ""),
                speaker=char_display,
                voice_type=sub.get("voice_type", "narrator"),
                duration_ms=dur_ms,
                start_ms=start_ms,
                background_path=str(sub.get("background_path", "") or ""),
                foreground_path=str(sub.get("foreground_path", "") or ""),
                head_path=str(sub.get("head_path", "") or ""),
                body_path=str(sub.get("body_path", "") or ""),
                left_arm_path=str(sub.get("left_arm_path", "") or ""),
                right_arm_path=str(sub.get("right_arm_path", "") or ""),
                eyes_open_path=str(sub.get("eyes_open_path", "") or ""),
                eyes_closed_path=str(sub.get("eyes_closed_path", "") or ""),
                mouth_closed_path=str(sub.get("mouth_closed_path", "") or ""),
                mouth_open_path=str(sub.get("mouth_open_path", "") or ""),
                motion_data=dict(sub.get("motion_data", {}) or {}) if isinstance(sub.get("motion_data"), dict) else None,
            )

        # BGM 설정
        bgm_path = None
        if self._get_bgm_folder_fn:
            bgm_dir = self._get_bgm_folder_fn(mode)
            # v62.10: bgm_dir="" 가드 — 빈 문자열이면 CWD glob 실행되어 무관한 mp3 로딩 위험
            if bgm_dir and os.path.isdir(bgm_dir):
                bgm_files = glob(os.path.join(bgm_dir, "*.mp3"))
            else:
                bgm_files = []
                if bgm_dir is not None and bgm_dir != "":
                    logger.warning(f"[VideoRenderer] BGM 폴더 없음: {bgm_dir!r}")
            if bgm_files:
                bgm_path = random.choice(bgm_files)
                # v61.1-fix: 0.12 하드코딩 제거 → 채널별 기본값 사용 (horror=0.35, senior=0.30)
                assembler.set_bgm(bgm_path)

        # 전체 TTS 오디오
        # v61.1 (#44): fullAudioPath 복사 실패 시 전체 무음 → 검증 추가
        if not audio_path or not os.path.exists(audio_path):
            logger.error(f"[VideoRenderer] TTS 오디오 파일 없음: {audio_path}")
            raise RuntimeError(f"TTS 오디오 파일이 존재하지 않습니다: {audio_path}")
        assembler.set_full_audio(audio_path)

        # SFX 통합
        if self._prepare_sfx_fn:
            self._prepare_sfx_fn(assembler, subtitle_data, mode)

        # 렌더링
        temp_dir = tempfile.mkdtemp(prefix="remotion_")
        temp_output = os.path.join(temp_dir, "main_clip.mp4")

        try:
            logger.info(f"[Remotion] 렌더링 중... (concurrency={self.concurrency})")
            result = assembler.render(
                output_path=temp_output,
                codec="h264",
                crf=18,
            )

            if not result.get("success"):
                raise RuntimeError("Remotion 렌더링 실패")

            logger.info(f"[Remotion] 렌더링 완료: {result['elapsed_seconds']:.1f}초, {result['file_size_mb']:.1f}MB")
            # v61.1 (#46): temp_dir은 호출자가 최종 파일 복사 후 삭제 필요
            logger.info(f"[Remotion] temp 디렉토리 (호출자가 삭제 필요): {temp_dir}")
            return temp_output

        except Exception as e:
            # v61.1 (#46): 렌더링 실패 시 temp 디렉토리 즉시 삭제
            import shutil
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
                logger.info(f"[Remotion] 실패 temp 삭제: {temp_dir}")
            except Exception:
                pass
            logger.error(f"[Remotion] 렌더링 실패: {e}")
            raise RuntimeError(f"Remotion 렌더링 실패: {e}")
