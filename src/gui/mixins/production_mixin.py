# src/gui/mixins/production_mixin.py
"""
v60.1.0: 영상 생산 Mixin — 큐 관리, 생산 워커, 미리보기, 품질 게이트

ReverieGUI에서 추출된 15개 메서드:
- _get_channel_mode_from_package: 채널/모드 추출
- _add_to_queue: 큐에 작업 추가
- _run_queue: 큐 실행
- _queue_worker: 큐 워커 (백그라운드)
- _activate_pack_for_job: 작업별 팩 활성화
- _auto_upload_video: 자동 업로드
- _start_production: 생산 시작
- _production_worker: 생산 워커 (백그라운드)
- _thumbnail_callback: 썸네일 콜백
- _preview_script: 대본 미리보기
- _show_preview_dialog: 미리보기 다이얼로그
- _start_production_with_plan: 플랜 기반 생산
- _stop_production: 생산 중단
- _on_autopilot_approve: 자율주행 승인
- _quality_gate: 품질 게이트

의존하는 self 변수:
- self.batch_queue, self.is_producing, self.channel_var, self.quantity_var
- self.topic_mode_var, self.manual_topic_entry, self.auto_upload_var
- self.prompt_mode_var, self.skip_thumbnail_popup_var, self.resume_from_checkpoint_var, self.upload_privacy_var
- self.start_button, self.stop_button, self.add_queue_button, self.preview_button
- self.status_label, self.progress_bar, self.progress_percent_label
"""
import json
import os
import shutil
import threading
import time
from datetime import datetime
from tkinter import messagebox

import customtkinter as ctk

from config.settings import config
from utils.logger import get_logger, get_user_friendly_error
from utils.shorts_manager import build_shorts_variant
from modules_pro.scenario_planner import ScenarioPlanner
from modules_pro.media_factory import MediaFactory
from gui.thumbnail_preview_dialog import ThumbnailPreviewDialog

logger = get_logger("production_mixin")


# v60.1.0: _sanitize_for_path를 pipeline_utils 정식 버전으로 통합
from pipeline.pipeline_utils import (
    get_ffmpeg_path,
    get_ffprobe_path,
    sanitize_for_path as _sanitize_for_path,
)


class ProductionMixin:
    """영상 생산 관련 메서드를 모은 Mixin 클래스"""

    def _safe_get_var(self, attr_name: str, default=None):
        var = getattr(self, attr_name, None)
        if var is None:
            return default

        getter = getattr(var, "get", None)
        if callable(getter):
            try:
                return getter()
            except Exception as e:
                logger.warning("[production] GUI 변수 조회 실패: %s", attr_name, exc_info=True)
                self._add_log(f"[WARN] 설정값 조회 실패({attr_name}) -> 기본값 사용: {e}")
                return default

        return var

    def _safe_get_entry_text(self, attr_name: str) -> str:
        entry = getattr(self, attr_name, None)
        if entry is None:
            return ""

        getter = getattr(entry, "get", None)
        if callable(getter):
            try:
                return (getter() or "").strip()
            except Exception as e:
                logger.warning("[production] GUI 텍스트 조회 실패: %s", attr_name, exc_info=True)
                self._add_log(f"[WARN] 텍스트 입력 조회 실패({attr_name}) -> 빈값 사용: {e}")
                return ""

        return ""

    def _safe_get_quantity(self, default: int = 1) -> int:
        raw_value = self._safe_get_var("quantity_var", default)
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            self._add_log(f"[WARN] 생산 수량 값이 비정상입니다 -> 기본값 {default} 사용")
            return default
        return max(1, value)

    def _run_production_preflight(self) -> None:
        """실생산 전에 고정형 런타임 의존성을 점검한다."""
        try:
            from utils.commercial_readiness import generate_commercial_readiness_report

            readiness = generate_commercial_readiness_report()
            self._add_log(
                f"[PREFLIGHT] 상용화 점검: {readiness.score}/100 "
                f"(실패 {readiness.fail_count}, 경고 {readiness.warn_count})"
            )
            if readiness.fail_count:
                failures = [check for check in readiness.checks if check.status == "fail"]
                preview = "; ".join(f"{check.id}: {check.detail}" for check in failures[:3])
                raise RuntimeError(f"상용화 프리플라이트 실패: {preview}")
        except RuntimeError:
            raise
        except Exception as exc:
            self._add_log(f"[PREFLIGHT][WARN] 상용화 점검을 건너뜀: {exc}")

        provider = (getattr(config, "STORY_LLM_PROVIDER", "") or "").strip().lower()
        if provider == "claude":
            provider = "claude_cli"

        if provider == "claude_cli":
            cli_path = (getattr(config, "CLAUDE_CLI_PATH", "claude") or "claude").strip()
            if not (shutil.which(cli_path) or os.path.exists(cli_path)):
                raise FileNotFoundError(f"Claude CLI 실행 파일을 찾을 수 없습니다: {cli_path}")

        ffmpeg_path = get_ffmpeg_path()
        ffprobe_path = get_ffprobe_path()
        for label, binary in (("FFmpeg", ffmpeg_path), ("ffprobe", ffprobe_path)):
            resolved = shutil.which(binary) if binary in {"ffmpeg", "ffprobe"} else binary
            if not resolved or not os.path.exists(resolved):
                raise FileNotFoundError(f"{label} 실행 파일을 찾을 수 없습니다: {binary}")

        remotion_root = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
            "remotion-poc",
        )
        if not os.path.exists(os.path.join(remotion_root, "package.json")):
            raise FileNotFoundError(f"Remotion 프로젝트가 없습니다: {remotion_root}")
        if not os.path.isdir(os.path.join(remotion_root, "node_modules")):
            raise RuntimeError(f"Remotion 의존성이 설치되지 않았습니다: {remotion_root}\\node_modules")
        if not (shutil.which("npx") or shutil.which("npx.cmd")):
            raise RuntimeError("Node.js/npx가 설치되지 않았습니다.")

        required_servers = ["SD WebUI"]
        tts_engine = (getattr(config, "TTS_ENGINE", "sovits") or "sovits").strip().lower()
        if tts_engine == "sovits" or bool(getattr(config, "TTS_HYBRID_ENABLED", False)):
            required_servers.append("GPT-SoVITS")

        from utils.server_manager import get_server_manager

        manager = get_server_manager()
        for server_name in required_servers:
            if manager.check_server(server_name):
                continue
            self._add_log(f"[PREFLIGHT] {server_name} 미가동 -> 자동 시작 시도")
            if not manager.start_server(server_name):
                status = manager.get_status(server_name)
                error_msg = status.get("error") or f"{server_name} 서버를 시작할 수 없습니다."
                raise RuntimeError(error_msg)
            if not manager.check_server(server_name):
                raise RuntimeError(f"{server_name} 서버가 시작 후에도 응답하지 않습니다.")

    def _resolve_pack_id_for_channel(self, channel: str, mode: str, pack_id: str = "") -> str:
        if pack_id:
            return pack_id
        if channel == "horror":
            return "horror"
        if channel == "senior" and mode:
            return f"senior_{mode}"
        return f"{channel}_{mode}" if mode else channel

    def _create_scenario_planner(self, prompt_mode: str):
        provider = (getattr(config, "STORY_LLM_PROVIDER", "") or "").strip().lower()
        if provider == "claude":
            provider = "claude_cli"

        if provider == "claude_cli":
            cli_path = getattr(config, "CLAUDE_CLI_PATH", "claude")
            if not (shutil.which(cli_path) or os.path.exists(cli_path)):
                raise FileNotFoundError(f"Claude CLI 실행 파일을 찾을 수 없습니다: {cli_path}")

        return ScenarioPlanner(prompt_mode=prompt_mode)

    def _get_channel_mode_from_package(self, channel_id: str) -> tuple:
        """
        v37: 패키지 정보에서 채널/모드 추출

        Args:
            channel_id: 선택된 채널 ID (패키지 ID)

        Returns:
            (channel, mode) 튜플
        """
        try:
            from utils.package_manager import get_package_manager
            pm = get_package_manager()
            package = pm.get_channel(channel_id)

            if package:
                channel_type = package.channel_type or channel_id
                package_id = getattr(package, "package_id", "") or ""

                # 구버전 channel json은 channel_type이 "senior"만 남아 있을 수 있다.
                # 이 경우 실제 pack_id 기준으로 모드를 복원한다.
                if channel_type in {"senior", "horror"} and package_id and "_" in package_id:
                    channel_type = package_id

                # VideoToon channel IDs are already concrete production modes.
                if channel_type in {"daily_life_toon", "mystery_toon"}:
                    return (channel_type, channel_type)
                elif channel_type == "horror":
                    return ("mystery_toon", "mystery_toon")
                elif channel_type in {"senior_touching", "senior_makjang", "senior"}:
                    return ("daily_life_toon", "daily_life_toon")
                elif "_" in channel_type:
                    # 일반적인 "channel_mode" 형식
                    parts = channel_type.split("_", 1)
                    return (parts[0], parts[1])
                else:
                    # 단일 값이면 channel = mode
                    return (channel_type, channel_type)
        except Exception as e:
            logger.warning(f"[main_window] 패키지에서 채널/모드 추출 실패: {e}")

        # 폴백: channel_id 자체 사용
        if "_" in channel_id:
            parts = channel_id.split("_", 1)
            return (parts[0], parts[1])
        return (channel_id, channel_id)

    def _build_thumbnail_callback(self, skip_thumbnail: bool = False):
        """현재 GUI 옵션 기준으로 썸네일 콜백을 구성한다."""
        if skip_thumbnail:
            self._add_log("[SKIP] 썸네일 팝업 건너뛰기 (자동 진행)")
            return None

        return lambda r, a, s, channel_type=None, main_title=None: self._thumbnail_callback(
            r, a, s, channel_type, main_title
        )

    def _produce_video_for_gui(self, factory, json_path: str, skip_thumbnail: bool = False, resume_from_checkpoint=None):
        """GUI 공통 옵션을 적용해 MediaFactory 실행을 위임한다."""
        if resume_from_checkpoint is None:
            resume_from_checkpoint = bool(self._safe_get_var("resume_from_checkpoint_var", False))

        thumb_callback = self._build_thumbnail_callback(skip_thumbnail)
        if resume_from_checkpoint:
            self._add_log("[RESUME] 체크포인트 재개 사용")

        return factory.produce_video_with_gui(
            json_path,
            thumbnail_callback=thumb_callback,
            progress_callback=self._update_progress,
            resume_from_checkpoint=resume_from_checkpoint,
            log_callback=self._add_log
        )

    # ============================================================
    # v58.3: 큐 기능
    # ============================================================
    def _add_to_queue(self):
        """현재 설정을 큐에 추가"""
        # 설정 가져오기
        channel_id = self._safe_get_var("channel_var", "")
        channel, mode = self._get_channel_mode_from_package(channel_id)

        quantity = self._safe_get_quantity()
        if quantity < 1:
            messagebox.showerror("오류", "수량은 1개 이상이어야 합니다.")
            return

        topic_mode = self._safe_get_var("topic_mode_var", "auto")
        manual_topic = self._safe_get_entry_text("manual_topic_entry")

        if topic_mode == "manual" and not manual_topic:
            messagebox.showerror("오류", "수동 주제를 입력해주세요.")
            return

        auto_upload = bool(self._safe_get_var("auto_upload_var", False))
        prompt_mode = self._safe_get_var("prompt_mode_var", "enhanced")
        skip_thumbnail = bool(self._safe_get_var("skip_thumbnail_popup_var", False))  # v58.3.2: 썸네일 건너뛰기 저장
        resume_from_checkpoint = bool(self._safe_get_var("resume_from_checkpoint_var", False))
        upload_privacy = self._safe_get_var("upload_privacy_var", "private")  # v58.3.2: 공개 설정 저장

        # 큐에 추가
        job_ids = self.batch_queue.add_batch(
            channel=channel,
            mode=mode,
            quantity=quantity,
            topic_mode=topic_mode,
            manual_topic=manual_topic,
            auto_upload=auto_upload,
            pack_id=channel_id,  # v58.3: pack_id 추가
            prompt_mode=prompt_mode,  # v58.3: prompt_mode 추가
            skip_thumbnail=skip_thumbnail,  # v58.3.2: 썸네일 건너뛰기 추가
            resume_from_checkpoint=resume_from_checkpoint,
            upload_privacy=upload_privacy  # v58.3.2: 공개 설정 추가
        )

        # 큐 요약 업데이트
        summary = self.batch_queue.get_queue_summary()

        self._add_log(f"[QUEUE] ➕ {quantity}개 작업 추가됨 (팩: {channel_id})")
        self._add_log(f"        대기 중: {summary['pending']}개")

        messagebox.showinfo(
            "큐 추가 완료",
            f"{quantity}개 작업이 큐에 추가되었습니다.\n\n"
            f"팩: {channel_id}\n"
            f"대기 중: {summary['pending']}개\n\n"
            f"📋 큐 버튼을 눌러 관리하거나\n"
            f"다른 팩을 선택해서 더 추가하세요."
        )

    def _run_queue(self):
        """큐에 있는 작업들 순차 실행"""
        if self.is_producing:
            messagebox.showwarning("경고", "이미 제작이 진행 중입니다.")
            return

        pending = self.batch_queue.get_pending_jobs()
        if not pending:
            messagebox.showinfo("알림", "실행할 작업이 없습니다.")
            return

        self.is_producing = True
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.add_queue_button.configure(state="disabled")

        # 로그 초기화
        self._clear_log()
        self._add_log(f"[QUEUE] 🚀 큐 실행 시작: {len(pending)}개 작업")

        # 백그라운드에서 큐 실행
        thread = threading.Thread(
            target=self._queue_worker,
            daemon=True
        )
        thread.start()

    def _load_reused_plan_for_job(self, job: dict):
        """Retry jobs can reuse an existing plan JSON instead of regenerating it."""
        reuse_json_path = job.get("json_path", "")
        if not reuse_json_path or not os.path.exists(reuse_json_path):
            return None, ""

        try:
            with open(reuse_json_path, "r", encoding="utf-8") as f:
                plan_data = json.load(f)
        except Exception as e:
            self._add_log(f"[WARN] 재사용 기획 JSON 로드 실패, 새로 생성합니다: {e}")
            logger.warning("[production] 재사용 기획 JSON 로드 실패: %s", reuse_json_path, exc_info=True)
            return None, ""

        if not isinstance(plan_data, dict):
            self._add_log("[WARN] 재사용 기획 JSON 형식 오류, 새로 생성합니다.")
            return None, ""

        self._add_log(f"[RESUME] 기존 기획 JSON 재사용: {reuse_json_path}")
        return plan_data, reuse_json_path

    def _ensure_plan_json(self, plan_data, json_path: str) -> tuple:
        """플래너 결과를 검증하고, 필요하면 JSON 파일을 디스크에 보정 저장한다."""
        if not isinstance(plan_data, dict):
            raise ValueError("기획안 데이터가 비정상입니다. dict 형식이어야 합니다.")

        project_name = (plan_data.get("project_name") or plan_data.get("title") or "").strip()
        if not project_name:
            raise ValueError("기획안에 project_name/title이 없어 저장 경로를 만들 수 없습니다.")
        plan_data.setdefault("project_name", project_name)

        if json_path and os.path.exists(json_path):
            return plan_data, json_path

        safe_project_name = _sanitize_for_path(project_name)
        fallback_json_path = os.path.join(config.DATA_DIR, "scripts", f"{safe_project_name}.json")
        os.makedirs(os.path.dirname(fallback_json_path), exist_ok=True)
        with open(fallback_json_path, "w", encoding="utf-8") as f:
            json.dump(plan_data, f, ensure_ascii=False, indent=2)
        self._add_log(f"[PLAN] 기획안 JSON 보정 저장: {fallback_json_path}")
        return plan_data, fallback_json_path

    def _find_manual_resume_candidate(self, channel: str, mode: str):
        """?? ??/??? ?? ?? ?? ??? ???."""
        candidate_json_paths = []
        resume_state = getattr(self, "_last_failed_plan_state", None)
        if isinstance(resume_state, dict):
            reuse_json_path = resume_state.get("json_path", "")
            if reuse_json_path:
                candidate_json_paths.append((reuse_json_path, {}))

        checkpoint_dir = os.path.join(config.DATA_DIR, "checkpoints")
        if os.path.isdir(checkpoint_dir):
            checkpoint_files = sorted(
                (os.path.join(checkpoint_dir, name) for name in os.listdir(checkpoint_dir) if name.endswith("_checkpoint.json")),
                key=lambda path: os.path.getmtime(path),
                reverse=True,
            )
            for checkpoint_path in checkpoint_files[:10]:
                try:
                    with open(checkpoint_path, "r", encoding="utf-8") as f:
                        checkpoint_data = json.load(f)
                except Exception:
                    continue
                reuse_json_path = (checkpoint_data.get("plan_json_path") or "").strip()
                if reuse_json_path and not any(existing == reuse_json_path for existing, _ in candidate_json_paths):
                    candidate_json_paths.append((reuse_json_path, checkpoint_data))

        for reuse_json_path, checkpoint_data in candidate_json_paths:
            if not reuse_json_path or not os.path.exists(reuse_json_path):
                continue
            try:
                with open(reuse_json_path, "r", encoding="utf-8") as f:
                    plan_data = json.load(f)
            except Exception:
                continue
            if not isinstance(plan_data, dict):
                continue
            plan_channel = (plan_data.get("category") or channel).strip()
            plan_mode = (plan_data.get("mode") or mode).strip()
            if plan_channel != channel or plan_mode != mode:
                continue
            return {
                "json_path": reuse_json_path,
                "plan_data": plan_data,
                "checkpoint_stage": checkpoint_data.get("stage", ""),
                "script_turns": int(checkpoint_data.get("script_turns", 0) or len(plan_data.get("script_list") or [])),
                "project_name": checkpoint_data.get("project_name") or plan_data.get("project_name") or "",
            }

        return None

    def _prompt_manual_resume_choice(self, channel: str, mode: str) -> None:
        """?? ?? ? ?? ??? ??? ???? ???? ???."""
        self._manual_resume_plan_choice = None
        if not bool(self._safe_get_var("resume_from_checkpoint_var", False)):
            return

        candidate = self._find_manual_resume_candidate(channel, mode)
        if not candidate:
            return

        stage_label_map = {
            "thumbnail": "대본 준비 완료 / TTS 전",
            "tts": "TTS 준비 완료 / 이미지 생성 전",
            "images": "이미지 생성 진행 중",
            "assembly": "조립 단계",
            "render": "최종 렌더 단계",
            "init": "초기 단계",
        }
        stage = candidate.get("checkpoint_stage") or "thumbnail"
        stage_label = stage_label_map.get(stage, stage)
        project_name = candidate.get("project_name") or "이름 없는 프로젝트"
        script_turns = candidate.get("script_turns") or 0
        json_path = candidate.get("json_path", "")

        message = (
            "완료되지 않은 작업을 찾았습니다.\n\n"
            f"프로젝트: {project_name}\n"
            f"단계: {stage_label}\n"
            f"대본 턴 수: {script_turns}\n"
            f"기획 JSON: {json_path}\n\n"
            "이 체크포인트와 기존 기획안을 이어서 진행할까요?\n"
            "아니오를 누르면 처음부터 새로 생성합니다."
        )
        accepted = messagebox.askyesno("체크포인트 재개", message)
        self._manual_resume_plan_choice = {
            "accepted": accepted,
            "channel": channel,
            "mode": mode,
            **candidate,
        }

    def _load_reused_plan_for_manual_resume(self, channel: str, mode: str):
        """?? ??? ???? ??? ?? JSON? ?????."""
        if not bool(self._safe_get_var("resume_from_checkpoint_var", False)):
            return None, ""

        choice = getattr(self, "_manual_resume_plan_choice", None)
        if not isinstance(choice, dict):
            return None, ""
        if choice.get("channel") != channel or choice.get("mode") != mode:
            return None, ""
        if not choice.get("accepted"):
            return None, ""

        reuse_json_path = choice.get("json_path", "")
        plan_data = choice.get("plan_data")
        if not reuse_json_path or not os.path.exists(reuse_json_path):
            return None, ""
        if not isinstance(plan_data, dict):
            return None, ""

        self._add_log(f"[RESUME] 기존 기획 JSON 재사용: {reuse_json_path}")
        return plan_data, reuse_json_path

    def _remember_failed_plan_state(self, channel: str, mode: str, json_path: str, plan_data: dict = None) -> None:
        if not json_path:
            return
        self._last_failed_plan_state = {
            "channel": channel,
            "mode": mode,
            "json_path": json_path,
            "project_name": (plan_data or {}).get("project_name", ""),
        }

    def _clear_failed_plan_state(self, json_path: str = "") -> None:
        current = getattr(self, "_last_failed_plan_state", None)
        if not isinstance(current, dict):
            return
        if json_path and current.get("json_path") and current.get("json_path") != json_path:
            return
        self._last_failed_plan_state = None

    def _resolve_queue_job_topic(self, planner, job: dict, channel: str, mode: str, reused_plan_data=None):
        """Resolve topic selection for queue and retry flows."""
        topic_mode = job.get("topic_mode", "auto")
        manual_topic = job.get("manual_topic", "")
        retry_topic = job.get("topic") or manual_topic

        if reused_plan_data is not None:
            retry_topic = retry_topic or reused_plan_data.get("topic") or reused_plan_data.get("title", "")
            topic_mode = "manual"
            manual_topic = retry_topic
        elif retry_topic:
            self._add_log(f"[RETRY] 이전 주제로 재시도: {retry_topic}")
            topic_mode = "manual"
            manual_topic = retry_topic

        if topic_mode == "auto":
            topic = planner.get_auto_topic(channel, mode)
            self._add_log(f"[AUTO] 자동 주제: {topic}")
        else:
            topic = manual_topic
            self._add_log(f"[MANUAL] 수동 주제: {topic}")

        return topic, topic_mode, manual_topic

    def _create_plan_for_channel(self, planner, channel: str, mode: str, topic: str):
        """Create a plan without queue-specific branching in the worker."""
        if channel == "horror":
            return planner.create_horror_plan(topic)
        return planner.create_senior_plan(topic, mode=mode)

    def _update_queue_job_plan_state(
        self,
        job_id: str,
        topic: str,
        topic_mode: str,
        manual_topic: str,
        json_path: str = "",
        plan_data: dict = None,
    ):
        """Persist queue metadata so failed jobs can retry deterministically."""
        updates = {
            "topic": topic,
            "manual_topic": topic or manual_topic,
            "topic_mode": "manual" if topic else topic_mode,
        }
        if json_path:
            updates["json_path"] = json_path
        if isinstance(plan_data, dict):
            updates["project_name"] = plan_data.get("project_name", "")
        self.batch_queue.update_job(job_id, **updates)

    def _get_queue_job_render_options(self, job: dict) -> tuple:
        """Resolve thumbnail and checkpoint options for a queue job."""
        skip_thumbnail = job.get("skip_thumbnail", False)
        default_resume = bool(self._safe_get_var("resume_from_checkpoint_var", False))
        resume_from_checkpoint = job.get("resume_from_checkpoint", default_resume)
        return skip_thumbnail, resume_from_checkpoint

    def _process_queue_job(self, job: dict):
        """Execute a single queued production job."""
        from modules_pro.media_factory import MediaFactory

        job_id = job["id"]
        channel = job["channel"]
        mode = job["mode"]
        prompt_mode = job.get("prompt_mode", "enhanced")
        pack_id = self._resolve_pack_id_for_channel(channel, mode, job.get("pack_id", ""))

        if not self._activate_pack_for_job(pack_id):
            self.batch_queue.fail_job(job_id, f"팩 로드 실패: {pack_id}")
            self._add_log(f"[FAIL] 작업 #{job_id} 실패 - 팩 로드 실패 ({pack_id})")
            return

        self._run_production_preflight()
        planner = self._create_scenario_planner(prompt_mode=prompt_mode)
        reused_plan_data, reuse_json_path = self._load_reused_plan_for_job(job)
        topic, topic_mode, manual_topic = self._resolve_queue_job_topic(
            planner,
            job,
            channel,
            mode,
            reused_plan_data=reused_plan_data,
        )

        self._update_progress("주제 생성 완료", 5)
        self._add_log("[PLAN] 기획안 작성 중...")
        self._update_queue_job_plan_state(job_id, topic, topic_mode, manual_topic)

        if reused_plan_data is not None and reuse_json_path:
            plan_data, json_path = reused_plan_data, reuse_json_path
        else:
            plan_data, json_path = self._create_plan_for_channel(planner, channel, mode, topic)
        plan_data, json_path = self._ensure_plan_json(plan_data, json_path)

        self._update_progress("기획안 작성 완료", 10)
        self._add_log(f"[OK] 기획안 저장: {json_path}")
        self._update_queue_job_plan_state(
            job_id,
            topic,
            topic_mode,
            manual_topic,
            json_path=json_path or "",
            plan_data=plan_data if isinstance(plan_data, dict) else None,
        )

        factory = MediaFactory(channel=channel)
        skip_thumbnail, resume_from_checkpoint = self._get_queue_job_render_options(job)
        video_path = self._produce_video_for_gui(
            factory,
            json_path,
            skip_thumbnail=skip_thumbnail,
            resume_from_checkpoint=resume_from_checkpoint
        )

        if not video_path:
            self.batch_queue.fail_job(job_id, "영상 생성 실패")
            self._add_log(f"[FAIL] 작업 #{job_id} 실패")
            return

        result = {"final_video": video_path}
        self.batch_queue.complete_job(job_id, result)
        self._add_log(f"[OK] 작업 #{job_id} 완료: {video_path}")

        if job.get("auto_upload"):
            self._auto_upload_video(result, plan_data, channel, job=job)

    def _queue_worker(self):
        """배치 작업 워커 스레드."""
        try:
            while self.is_producing:
                job = self.batch_queue.get_next_job()
                if not job:
                    self._add_log("[QUEUE] 모든 작업 완료!")
                    break

                job_id = job["id"]
                pack_id = self._resolve_pack_id_for_channel(
                    job["channel"], job["mode"], job.get("pack_id", "")
                )

                self._add_log(f"\n{'=' * 50}")
                self._add_log(f"[QUEUE] 작업 #{job_id} 시작")
                self._add_log(f"        팩: {pack_id}")
                self._add_log(f"{'=' * 50}\n")

                self.batch_queue.start_job(job_id)

                try:
                    self._process_queue_job(job)
                except Exception as e:
                    self.batch_queue.fail_job(job_id, str(e))
                    self._add_log(f"[ERROR] 작업 #{job_id} 오류: {e}")
                    logger.error(f"배치 작업 오류: {e}", exc_info=True)

            summary = self.batch_queue.get_queue_summary()
            self._add_log(
                f"\n[QUEUE] 요약 완료: {summary['completed']} | 실패: {summary['failed']} | 남음: {summary['pending']}"
            )

        except Exception as e:
            self._add_log(f"[ERROR] 큐 워커 오류: {e}")
            logger.error(f"큐 워커 오류: {e}", exc_info=True)
        finally:
            self.is_producing = False
            self.after(0, lambda: self.start_button.configure(state="normal"))
            self.after(0, lambda: self.stop_button.configure(state="disabled"))
            self.after(0, lambda: self.add_queue_button.configure(state="normal"))

    def _activate_pack_for_job(self, pack_id: str) -> bool:
        """
        v58.3.1: 큐 작업용 팩 활성화 (pack_id 직접 로드)

        pack_id 예시: daily_life_toon, mystery_toon
        """
        if not pack_id:
            self._add_log("[PACK] pack_id가 비어 있어 팩을 활성화할 수 없습니다.")
            return False

        try:
            from config.pack_config import load_pack_by_id, ACTIVE_PACK

            # v58.3.1: pack_id로 직접 팩 로드
            if load_pack_by_id(pack_id):
                self._add_log(f"[PACK] 팩 활성화: {ACTIVE_PACK.pack_name} ({pack_id})")
                return True

            self._add_log(f"[PACK] 팩 로드 실패 ({pack_id})")
            return False

        except Exception as e:
            logger.warning(f"팩 활성화 실패: {e}")
            self._add_log(f"[PACK] 팩 활성화 실패: {e}")
            return False

    def _auto_upload_video(self, result: dict, plan_data: dict, channel: str, job: dict = None):
        """
        v58.3: 큐 작업용 자동 업로드
        v58.3.2: job 파라미터 추가하여 저장된 upload_privacy 사용

        Args:
            result: 영상 제작 결과 {"final_video": path}
            plan_data: 기획안 데이터
            channel: 채널 타입
            job: 큐 작업 정보 (upload_privacy 포함)
        """
        video_path = result.get("final_video", "")
        if not video_path or not os.path.exists(video_path):
            self._add_log("[UPLOAD] 영상 파일 없음, 업로드 건너뜀")
            return

        mode = plan_data.get("mode", channel)

        self._add_log("\n[UPLOAD] 유튜브 업로드 준비 중...")

        # Quality Gate 실행
        ok, reason = self._quality_gate(video_path, plan_data)
        if not ok:
            self._add_log(f"[BLOCK] 업로드 차단: {reason}")
            return

        self._add_log(f"[OK] 업로드 준비: {reason}")

        try:
            from utils.youtube_uploader import YouTubeUploader

            # 채널 타입 결정
            channel_type = "senior" if channel == "senior" or mode in ["touching", "senior", "makjang"] else "horror"
            uploader = YouTubeUploader(channel_name=channel, channel_type=channel_type)

            # 썸네일 경로
            project_name = plan_data.get("project_name", "")
            safe_project_name = _sanitize_for_path(project_name)
            thumb_path = os.path.join(config.DATA_DIR, "thumbnails", f"{safe_project_name}_REAL.jpg")
            if not os.path.exists(thumb_path):
                thumb_path = os.path.join(config.DATA_DIR, "thumbnails", f"{safe_project_name}_ART.jpg")

            # 제목/설명/태그 생성
            video_title = uploader.generate_title(
                plan_data.get("thumbnail_title", ""),
                plan_data.get("title", "")
            )
            video_description = uploader.generate_description(
                plan_data.get("title", ""),
                plan_data.get("tags", []),
                channel_mode=mode
            )
            video_tags = plan_data.get("tags", [])
            if isinstance(video_tags, str):
                video_tags = [t.strip() for t in video_tags.split(",") if t.strip()]

            # 공개 설정 - v58.3.2: job에서 저장된 값 우선 사용
            if job and job.get("upload_privacy"):
                privacy_setting = job.get("upload_privacy")
            else:
                privacy_setting = self._safe_get_var("upload_privacy_var", "private")
            self._add_log(f"   공개 설정: {privacy_setting}")

            # 업로드
            upload_result = uploader.upload_video(
                video_path=video_path,
                title=video_title,
                description=video_description,
                tags=video_tags,
                privacy=privacy_setting,
                thumbnail_path=thumb_path if os.path.exists(thumb_path) else None,
                contains_synthetic_media=True,
                verified_true_story=bool(plan_data.get("verified_true_story", False)),
                channel_mode=mode,
            )

            if upload_result and upload_result.get('video_id'):
                self._add_log(f"[OK] 유튜브 업로드 완료: {upload_result['url']}")
                self._auto_upload_shorts_variant(
                    uploader=uploader,
                    video_path=video_path,
                    plan_data=plan_data,
                    privacy_setting=privacy_setting,
                )
            else:
                self._add_log("[ERROR] 유튜브 업로드 실패")

        except Exception as upload_err:
            user_msg = get_user_friendly_error(upload_err)
            self._add_log(f"[ERROR] 업로드 오류: {user_msg}")
            logger.error(f"업로드 오류: {upload_err}", exc_info=True)

    def _auto_upload_shorts_variant(self, uploader, video_path: str, plan_data: dict, privacy_setting: str):
        """Render and upload a shorts variant when the plan contains a usable shorts angle."""
        shorts_plan = plan_data.get("shorts_plan") or {}
        if not shorts_plan.get("enabled"):
            return
        if not shorts_plan.get("upload_with_main", True):
            return

        project_name = plan_data.get("project_name") or plan_data.get("title") or "shorts"
        shorts_dir = os.path.join(config.DATA_DIR, "shorts")

        try:
            self._add_log("[SHORTS] 세로 숏츠 버전 생성 중...")
            shorts_path = build_shorts_variant(
                video_path,
                output_dir=shorts_dir,
                project_name=project_name,
                duration_sec=shorts_plan.get("duration_sec", 35),
                start_sec=shorts_plan.get("start_sec", 0.0),
            )
            self._add_log(f"[SHORTS] 렌더 완료: {shorts_path}")
        except Exception as e:
            logger.warning("[SHORTS] 변환 실패: %s", e, exc_info=True)
            self._add_log(f"[SHORTS] 변환 실패: {get_user_friendly_error(e)}")
            return

        try:
            tags = shorts_plan.get("tags", [])
            if isinstance(tags, str):
                tags = [tag.strip() for tag in tags.split(",") if tag.strip()]

            upload_result = uploader.upload_video(
                video_path=shorts_path,
                title=shorts_plan.get("title") or f"{plan_data.get('title', '')} #Shorts",
                description=shorts_plan.get("description") or plan_data.get("description", ""),
                tags=tags,
                privacy=privacy_setting,
                thumbnail_path=None,
                contains_synthetic_media=True,
                verified_true_story=bool(plan_data.get("verified_true_story", False)),
                channel_mode=plan_data.get("mode", "") or "shorts",
            )
            if upload_result and upload_result.get("video_id"):
                self._add_log(f"[SHORTS] 업로드 완료: {upload_result['url']}")
            else:
                self._add_log("[SHORTS] 업로드 실패")
        except Exception as e:
            logger.warning("[SHORTS] 업로드 실패: %s", e, exc_info=True)
            self._add_log(f"[SHORTS] 업로드 실패: {get_user_friendly_error(e)}")

    def _start_production(self):
        """생산 시작"""
        if self.is_producing:
            messagebox.showwarning("경고", "이미 제작이 진행 중입니다.")
            return

        # 설정 가져오기 - v37: 패키지 기반 동적 채널/모드
        channel_id = self._safe_get_var("channel_var", "")

        # v60.1.0: 보유 패키지 없는 상태에서 생산 시도 차단
        if channel_id == "_no_owned" or not channel_id:
            messagebox.showerror("오류", "보유한 패키지가 없습니다.\n먼저 패키지를 구매/등록하세요.")
            return

        channel, mode = self._get_channel_mode_from_package(channel_id)
        self._prompt_manual_resume_choice(channel, mode)

        quantity = self._safe_get_quantity()
        if quantity < 1:
            messagebox.showerror("오류", "생산 수량은 1개 이상이어야 합니다.")
            return

        topic_mode = self._safe_get_var("topic_mode_var", "auto")
        manual_topic = self._safe_get_entry_text("manual_topic_entry")

        if topic_mode == "manual" and not manual_topic:
            messagebox.showerror("오류", "수동 주제를 입력해주세요.")
            return

        # UI 상태 변경
        self.is_producing = True
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")

        # v37: 프롬프트 모드 가져오기
        prompt_mode = self._safe_get_var("prompt_mode_var", "enhanced")

        # 로그 초기화
        self._clear_log()
        mode_label = "Enhanced" if prompt_mode == "enhanced" else "Classic"

        # v50: 테스트 모드 상태 동기화
        config.TEST_MODE = bool(self._safe_get_var("test_mode_var", False))
        test_mode_str = "[테스트]" if config.TEST_MODE else ""

        self._add_log(f"[START] 제작 시작: {channel} / {mode} / {quantity}개 (AI: {mode_label}) {test_mode_str}")

        if config.TEST_MODE:
            self._add_log(f"[TEST] 테스트 모드: {config.TEST_TURNS_PER_PART * 3}턴, {config.TEST_IMAGE_COUNT}장 이미지")

        vt_backend = self.settings_manager.get_videotoon_generation_backend()
        self.settings_manager.set_videotoon_local_enabled(True)
        config.VIDEOTOON_LOCAL_MODE_OVERRIDE = True
        config.MOTIONTOON_RENDER_MODE_OVERRIDE = "videotoon_layered"
        config.VIDEOTOON_IMAGE_BACKEND = vt_backend
        self._add_log(f"[VideoToon] 영상툰 전용 생산 모드: backend={vt_backend}")
        self._add_log("[VideoToon] 구 동적영상/모션툰 모드는 사용하지 않습니다. 배경+캐릭터 레이어 조립 기준으로 진행합니다.")

        # 백그라운드 스레드에서 실행
        thread = threading.Thread(
            target=self._production_worker,
            args=(channel, mode, quantity, topic_mode, manual_topic, prompt_mode, channel_id),
            daemon=True
        )
        thread.start()

    def _production_worker(self, channel: str, mode: str, quantity: int, topic_mode: str, manual_topic: str, prompt_mode: str = "enhanced", pack_id: str = ""):
        """생산 작업 스레드"""
        try:
            # v61: 팩 확실히 재활성화 (이전 세션 감정/프롬프트 잔존 방지)
            resolved_pack_id = self._resolve_pack_id_for_channel(channel, mode, pack_id)
            if not self._activate_pack_for_job(resolved_pack_id):
                self._add_log(f"[PACK] 필수 팩 로드 실패: {resolved_pack_id}")
                return

            # v63.1: 모션툰 비활성화 — 로그 제거

            self._run_production_preflight()
            # v37: 프롬프트 모드에 따라 ScenarioPlanner 초기화
            planner = self._create_scenario_planner(prompt_mode=prompt_mode)

            # v60.1.0: 일일 생성 한도 사전 체크 (quantity 조절)
            try:
                from utils.channel_registry import get_channel_registry
                registry = get_channel_registry()
                remaining = registry.get_remaining_quota(channel)
                if remaining < quantity:
                    if remaining <= 0:
                        self._add_log(f"[LIMIT] 일일 생성 한도 초과: {channel}. 내일 다시 시도하세요.")
                        return
                    self._add_log(
                        f"[LIMIT] 일일 한도로 {quantity}편 중 {remaining}편만 생성합니다."
                    )
                    quantity = remaining
            except ImportError:
                pass

            for i in range(quantity):
                if not self.is_producing:
                    self._add_log("[STOP] 사용자가 제작을 중단했습니다.")
                    break

                self._add_log(f"\n{'='*50}")
                self._add_log(f"[{i+1}/{quantity}] 영상 제작 시작")
                self._add_log(f"{'='*50}\n")

                reused_plan_data, reuse_json_path = self._load_reused_plan_for_manual_resume(channel, mode)
                if reused_plan_data is not None and reuse_json_path:
                    plan_data, json_path = self._ensure_plan_json(reused_plan_data, reuse_json_path)
                    topic = plan_data.get("topic") or plan_data.get("title", "")
                    self._add_log(f"[RESUME] 기존 대본 기획 재사용: {topic}")
                else:
                    # 1. Topic selection
                    if topic_mode == "auto":
                        topic = planner.get_auto_topic(channel, mode)
                        self._add_log(f"[AUTO] Topic: {topic}")
                    else:
                        topic = manual_topic
                        self._add_log(f"[MANUAL] Topic: {topic}")

                    self._update_progress("Topic ready", 5)

                    # 2. Plan creation
                    self._add_log("[PLAN] Building plan...")
                    if channel == "horror":
                        plan_data, json_path = planner.create_horror_plan(topic)
                    else:
                        plan_data, json_path = planner.create_senior_plan(topic, mode=mode)
                    plan_data, json_path = self._ensure_plan_json(plan_data, json_path)

                self._update_progress("Plan ready", 10)
                self._add_log(f"[OK] Plan saved: {json_path}")
                self._remember_failed_plan_state(channel, mode, json_path, plan_data)

                # 시나리오 요약 추출 (썸네일 조정용)
                scenario_summary = plan_data.get("title", topic)[:200]  # 제목 또는 주제

                # 3. 영상 제작 (썸네일 확인 포함)
                factory = MediaFactory(channel=channel)

                # v50: 썸네일 팝업 건너뛰기 옵션
                skip_thumbnail = bool(self._safe_get_var("skip_thumbnail_popup_var", False))
                video_path = self._produce_video_for_gui(
                    factory,
                    json_path,
                    skip_thumbnail=skip_thumbnail
                )

                if video_path:
                    self._add_log(f"[OK] 영상 제작 완료: {video_path}")
                    self._clear_failed_plan_state(json_path)

                    # 통계 기록 (성공)
                    project_name = plan_data.get("project_name", topic[:20])
                    self.production_stats.record_production(
                        channel=channel,
                        mode=mode,
                        success=True,
                        project_name=project_name
                    )

                    # 최근 프로젝트 목록 새로고침
                    self.after(0, self._load_recent_projects)

                    # Quality Gate & 업로드
                    if bool(self._safe_get_var("auto_upload_var", False)):
                        self._add_log("\n[UPLOAD] 유튜브 업로드 준비 중...")

                        # Quality Gate 실행
                        ok, reason = self._quality_gate(video_path, plan_data)
                        if not ok:
                            self._add_log(f"[BLOCK] 업로드 차단: {reason}")
                            self._add_log("   [TIP] 재생성하거나 설정을 조정해보세요.")
                        else:
                            self._add_log(f"[OK] 업로드 준비: {reason}")

                            # 업로드 실행
                            try:
                                from utils.youtube_uploader import YouTubeUploader

                                # v53: 채널 타입에 따라 올바른 토큰 사용
                                # v57.0.2: makjang 모드 추가 - mode가 "horror"면 horror 토큰, 그 외(touching/makjang)면 senior 토큰
                                channel_type = "senior" if mode in ["touching", "senior", "makjang"] else "horror"
                                uploader = YouTubeUploader(channel_name=channel, channel_type=channel_type)

                                # 썸네일 경로 (v57.7.6: 방어적 sanitize)
                                project_name = plan_data.get("project_name", "")
                                safe_project_name = _sanitize_for_path(project_name)
                                thumb_path = os.path.join(config.DATA_DIR, "thumbnails", f"{safe_project_name}_REAL.jpg")
                                if not os.path.exists(thumb_path):
                                    thumb_path = os.path.join(config.DATA_DIR, "thumbnails", f"{safe_project_name}_ART.jpg")

                                # 제목/설명/태그 생성
                                video_title = uploader.generate_title(
                                    plan_data.get("thumbnail_title", ""),
                                    plan_data.get("title", "")
                                )
                                video_description = uploader.generate_description(
                                    plan_data.get("title", ""),
                                    plan_data.get("tags", []),
                                    channel_mode=mode
                                )
                                video_tags = plan_data.get("tags", [])
                                if isinstance(video_tags, str):
                                    video_tags = [t.strip() for t in video_tags.split(",") if t.strip()]

                                # v53: 공개 설정 적용
                                privacy_setting = self._safe_get_var("upload_privacy_var", "private")
                                self._add_log(f"   공개 설정: {privacy_setting}")

                                # 업로드
                                result = uploader.upload_video(
                                    video_path=video_path,
                                    title=video_title,
                                    description=video_description,
                                    tags=video_tags,
                                    privacy=privacy_setting,
                                    thumbnail_path=thumb_path if os.path.exists(thumb_path) else None,
                                    contains_synthetic_media=True,
                                    verified_true_story=bool(plan_data.get("verified_true_story", False)),
                                    channel_mode=mode,
                                )

                                if result and result.get('video_id'):
                                    self._add_log(f"[OK] 유튜브 업로드 완료: {result['url']}")
                                else:
                                    self._add_log("[ERROR] 유튜브 업로드 실패")

                            except Exception as upload_err:
                                # 사용자 친화적 에러 메시지
                                user_msg = get_user_friendly_error(upload_err)
                                self._add_log(f"[ERROR] 업로드 오류: {user_msg}")
                                logger.error(f"업로드 오류: {upload_err}", exc_info=True)
                else:
                    self._add_log("[ERROR] 영상 제작 실패")

                    # 통계 기록 (실패)
                    self.production_stats.record_production(
                        channel=channel,
                        mode=mode,
                        success=False,
                        project_name=topic[:20]
                    )

                self._update_progress("완료", 100)

        except Exception as e:
            # 사용자 친화적 에러 메시지 표시
            user_msg = get_user_friendly_error(e)
            self._add_log(f"[ERROR] 오류 발생: {user_msg}")
            # 상세 에러는 파일 로그에만 기록
            logger.error(f"제작 오류: {e}", exc_info=True)

        finally:
            # UI 상태 복원 (메인 스레드에서 실행해야 함)
            self.is_producing = False
            self.after(0, lambda: self.start_button.configure(state="normal"))
            self.after(0, lambda: self.stop_button.configure(state="disabled"))
            self.after(0, lambda: self._update_progress("대기 중...", 0))
            self._add_log("\n[DONE] 제작 프로세스 종료됨")

    def _thumbnail_callback(self, real_path: str, art_path: str, scenario_summary: str = "시나리오 정보 없음",
                            channel_type: str = None, main_title: str = None) -> str:
        """썸네일 확인 콜백 (스레드 안전하게 메인 스레드에서 실행)"""
        import threading

        # 결과를 저장할 변수
        result = {"choice": None}
        event = threading.Event()

        def show_dialog():
            """메인 스레드에서 다이얼로그 표시"""
            try:
                # v50: 채널 타입과 메인 제목 전달 (클릭률 높은 프리셋 적용)
                dialog = ThumbnailPreviewDialog(
                    self, real_path, art_path, config.FONT_PATH, scenario_summary,
                    channel_type=channel_type, main_title=main_title
                )
                result["choice"] = dialog.get_choice()
            except Exception as e:
                logger.error(f"썸네일 다이얼로그 오류: {e}")
                result["choice"] = "cancel"
            finally:
                event.set()

        # 메인 스레드에서 다이얼로그 표시
        self.after(0, show_dialog)

        # 결과 대기
        event.wait()

        choice = result["choice"]

        if choice == "proceed":
            self._add_log("[OK] 썸네일 확정 - 본편 제작 진행")
        elif choice == "regenerate":
            self._add_log("[RETRY] 썸네일 재생성 요청")
        else:
            self._add_log("[CANCEL] 사용자가 제작을 취소")

        return choice

    def _preview_script(self):
        """v37: 대본 미리보기"""
        if self.is_producing:
            messagebox.showwarning("경고", "제작이 진행 중입니다.")
            return

        # 설정 가져오기 - v37: 패키지 기반 동적 채널/모드
        channel_id = self._safe_get_var("channel_var", "")
        channel, mode = self._get_channel_mode_from_package(channel_id)

        topic_mode = self._safe_get_var("topic_mode_var", "auto")
        manual_topic = self._safe_get_entry_text("manual_topic_entry")
        prompt_mode = self._safe_get_var("prompt_mode_var", "enhanced")

        if topic_mode == "manual" and not manual_topic:
            messagebox.showerror("오류", "수동 주제를 입력해주세요.")
            return

        # UI 상태 변경
        self.preview_button.configure(state="disabled", text="⏳ 대본 생성 중...")
        self._clear_log()
        self._add_log("📝 대본 미리보기 생성 시작...")
        self._add_log(f"   채널: {channel} / 모드: {mode}")
        self._add_log(f"   AI 프롬프트: {prompt_mode.upper()}")

        # 백그라운드에서 대본 생성
        def generate_task():
            try:
                channel_id = self._safe_get_var("channel_var", "")
                resolved_pack_id = self._resolve_pack_id_for_channel(
                    channel,
                    mode,
                    channel_id if channel_id and channel_id != "_no_owned" else "",
                )
                if not self._activate_pack_for_job(resolved_pack_id):
                    raise RuntimeError(f"팩 로드 실패: {resolved_pack_id}")

                planner = self._create_scenario_planner(prompt_mode=prompt_mode)

                # 주제 생성
                if topic_mode == "auto":
                    topic = planner.get_auto_topic(channel, mode)
                    self._add_log(f"[AUTO] 자동 주제: {topic}")
                else:
                    topic = manual_topic
                    self._add_log(f"[MANUAL] 수동 주제: {topic}")

                self._update_progress("대본 생성 중...", 30)

                # 기획안 생성
                if channel == "horror":
                    plan_data, json_path = planner.create_horror_plan(topic)
                else:
                    plan_data, json_path = planner.create_senior_plan(topic, mode=mode)
                plan_data, _ = self._ensure_plan_json(plan_data, json_path)

                # 프롬프트 모드 저장
                plan_data["prompt_mode"] = prompt_mode

                self._update_progress("대본 생성 완료", 100)
                self._add_log(f"[OK] 대본 생성 완료 ({len(plan_data.get('script_list', []))}턴)")

                # 미리보기 다이얼로그 표시 (메인 스레드에서)
                self.after(0, lambda: self._show_preview_dialog(plan_data, channel, mode))

            except Exception as e:
                self._add_log(f"[ERROR] 오류: {e}")
                logger.error(f"대본 미리보기 오류: {e}", exc_info=True)
            finally:
                self.after(0, lambda: self.preview_button.configure(
                    state="normal", text="👁️  대본 미리보기"
                ))

        thread = threading.Thread(target=generate_task, daemon=True)
        thread.start()

    def _show_preview_dialog(self, plan_data: dict, channel: str, mode: str):
        """미리보기 다이얼로그 표시"""
        from gui.script_preview_dialog import ScriptPreviewDialog

        def on_approve(approved_plan):
            """승인 시 영상 제작 진행"""
            self._add_log("\n[OK] 대본 승인됨 - 영상 제작 시작")
            self._start_production_with_plan(approved_plan, channel, mode)

        def on_regenerate():
            """재생성"""
            self._add_log("[RETRY] 대본 재생성 요청")
            self._preview_script()

        def on_cancel():
            """취소"""
            self._add_log("[CANCEL] 미리보기 취소됨")

        dialog = ScriptPreviewDialog(
            self,
            plan_data,
            on_approve=on_approve,
            on_regenerate=on_regenerate,
            on_cancel=on_cancel
        )

    def _start_production_with_plan(self, plan_data: dict, channel: str, mode: str):
        """승인된 기획안으로 영상 제작 시작"""
        if self.is_producing:
            return

        self.is_producing = True
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        approved_plan = dict(plan_data or {})

        def production_task():
            try:
                # v61: 팩 확실히 재활성화 (감정/프롬프트 잔존 방지)
                channel_id = self._safe_get_var("channel_var", "")
                resolved_pack_id = self._resolve_pack_id_for_channel(
                    channel,
                    mode,
                    channel_id if channel_id and channel_id != "_no_owned" else "",
                )
                if not self._activate_pack_for_job(resolved_pack_id):
                    raise RuntimeError(f"팩 로드 실패: {resolved_pack_id}")

                try:
                    from config.pack_config import get_motiontoon_support_info
                    requested_mode = self.settings_manager.get_motiontoon_render_mode()
                    motiontoon_support = get_motiontoon_support_info(requested_mode=requested_mode)
                    self._add_log(
                        f"[Motiontoon] requested={requested_mode} / pack={motiontoon_support['label']} / "
                        f"effective={motiontoon_support['effective_mode']}"
                    )
                except Exception:
                    pass

                self._run_production_preflight()
                import os
                import json

                # 기획안 저장/보정
                validated_plan, json_path = self._ensure_plan_json(approved_plan, "")
                project_name = validated_plan.get("project_name", f"{channel}_{mode}_{datetime.now().strftime('%Y%m%d_%H%M%S')}")

                self._add_log(f"[PLAN] 기획안 저장: {json_path}")

                # 시나리오 요약
                scenario_summary = validated_plan.get("title", validated_plan.get("topic", ""))[:200]

                # 영상 제작
                factory = MediaFactory(channel=channel)

                # v50: 썸네일 팝업 건너뛰기 옵션
                skip_thumbnail = bool(self._safe_get_var("skip_thumbnail_popup_var", False))
                video_path = self._produce_video_for_gui(
                    factory,
                    json_path,
                    skip_thumbnail=skip_thumbnail
                )

                if video_path:
                    self._add_log(f"[OK] 영상 제작 완료: {video_path}")

                    # 통계 기록
                    self.production_stats.record_production(
                        channel=channel,
                        mode=mode,
                        success=True,
                        project_name=project_name
                    )

                    self.after(0, self._load_recent_projects)

            except Exception as e:
                self._add_log(f"[ERROR] 제작 오류: {e}")
                logger.error(f"제작 오류: {e}", exc_info=True)
            finally:
                self.is_producing = False
                self.after(0, lambda: self.start_button.configure(state="normal"))
                self.after(0, lambda: self.stop_button.configure(state="disabled"))
                self._update_progress("대기 중...", 0)

        thread = threading.Thread(target=production_task, daemon=True)
        thread.start()

    def _stop_production(self):
        """생산 중단"""
        if messagebox.askyesno("확인", "정말 제작을 중단하시겠습니까?"):
            self.is_producing = False
            self._add_log("\n[STOP] 중단 요청됨... 현재 작업 완료 후 중단됩니다.")

    def _on_autopilot_approve(self, item):
        """v37: 자율주행 모드에서 주제 승인 시 콜백"""
        if self.is_producing:
            messagebox.showwarning("경고", "현재 제작이 진행 중입니다. 완료 후 다시 시도하세요.")
            return

        self._add_log(f"\n🤖 [자율주행] 승인된 주제: {item.topic[:40]}...")
        self._add_log(f"   채널: {item.channel} / 모드: {item.mode}")

        # 수동 주제로 설정하고 제작 시작
        self.channel_var.set(f"{item.channel}_{item.mode}" if item.mode != item.channel else item.channel)
        self.topic_mode_var.set("manual")
        self.manual_topic_entry.delete(0, "end")
        self.manual_topic_entry.insert(0, item.topic)

        # 제작 시작
        self._start_production()

    def _quality_gate(self, video_path: str, plan_data: dict) -> tuple:
        """
        업로드 전 품질 검증

        Returns:
            (bool, str): (통과여부, 메시지)
        """
        import subprocess

        MIN_MINUTES = 8
        MAX_MINUTES = 25
        MIN_SCRIPT_TURNS = 50

        # 1. 영상 파일 존재 확인
        if not video_path or not os.path.exists(video_path):
            return False, "영상 파일이 존재하지 않습니다."

        # 2. 영상 길이 체크
        try:
            # v60.1.0: config.FFMPEG_PATH에서 ffprobe 경로 유도 (시스템 PATH 4.3.2 방지)
            from pipeline.pipeline_utils import get_ffprobe_path
            ffprobe = get_ffprobe_path()
            cmd = [
                ffprobe, "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                video_path
            ]
            out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True).strip()
            dur = float(out)
            minutes = dur / 60.0

            if minutes < MIN_MINUTES:
                return False, f"영상 길이가 너무 짧음: {minutes:.1f}분 (< {MIN_MINUTES}분)"
            if minutes > MAX_MINUTES:
                return False, f"영상 길이가 너무 김: {minutes:.1f}분 (> {MAX_MINUTES}분)"
        except Exception:
            # ffprobe 없으면 스킵
            minutes = 0
            pass

        # 3. 대본 턴 수 체크
        script_list = plan_data.get("script_list", []) if isinstance(plan_data, dict) else []
        if isinstance(script_list, list) and len(script_list) < MIN_SCRIPT_TURNS:
            return False, f"대본 턴 수가 너무 적음: {len(script_list)} (최소 {MIN_SCRIPT_TURNS}턴)"

        # 4. 썸네일 존재 확인 (v57.7.6: 방어적 sanitize)
        project = plan_data.get("project_name", "")
        safe_project = _sanitize_for_path(project)
        thumb_real = os.path.join(config.DATA_DIR, "thumbnails", f"{safe_project}_REAL.jpg")
        thumb_art = os.path.join(config.DATA_DIR, "thumbnails", f"{safe_project}_ART.jpg")
        if not (os.path.exists(thumb_real) or os.path.exists(thumb_art)):
            return False, "썸네일 파일이 없습니다."

        # 5. 이미지 폴더 체크
        temp_images_dir = os.path.join(config.DATA_DIR, "temp_images", safe_project)
        if os.path.exists(temp_images_dir):
            image_files = [f for f in os.listdir(temp_images_dir) if f.endswith(('.png', '.jpg'))]
            if len(image_files) < 10:
                return False, f"이미지 생성 부족: {len(image_files)}장 (최소 10장)"

        # 6. 오디오 파일 체크
        temp_audio_dir = os.path.join(config.DATA_DIR, "temp_audio", safe_project)
        if os.path.exists(temp_audio_dir):
            full_audio = os.path.join(temp_audio_dir, "full.wav")
            if not os.path.exists(full_audio):
                return False, "통합 오디오 파일이 생성되지 않았습니다."

            audio_size = os.path.getsize(full_audio)
            if audio_size < 100000:
                return False, f"오디오 파일 크기 비정상: {audio_size} bytes"

        if minutes > 0:
            return True, f"통과 ({minutes:.1f}분, {len(script_list)}턴)"
        else:
            return True, f"통과 ({len(script_list)}턴)"
