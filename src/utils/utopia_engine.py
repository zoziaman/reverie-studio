# src/utils/utopia_engine.py
"""
v57.0.0: 유토피아 엔진 (UtopiaEngine)

완전 자동 YouTube 운영 시스템

모든 유토피아 시스템 통합:
1. 콘텐츠 자동 생성 (MediaFactory)
2. 개인화 최적화 (PromptOptimizer)
3. 다국어 번역 (ContentTranslator) - v57.0.0
4. 자동 업로드 (UploadScheduler)
5. 성과 추적 (FeedbackLoop)
6. 자동 개선 (AutoOptimizer)

v54.8.0 변경사항:
- channel_id 파라미터 추가 (멀티채널 지원)
- ChannelRegistry 연동
- 채널별 독립 데이터 폴더 지원

v57.0.0 변경사항:
- TRANSLATING 상태 추가
- ContentTranslator 연동
- 채널별 target_language 지원

"하나의 버튼으로 YouTube 채널 완전 자동화"
"""
import os
import json
import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Callable
from enum import Enum

from utils.secret_redaction import redact_sensitive_text

logger = logging.getLogger(__name__)


class UtopiaMode(Enum):
    """유토피아 모드"""
    MANUAL = "manual"           # 수동 - 각 단계 직접 실행
    SEMI_AUTO = "semi_auto"     # 반자동 - 생성 후 확인 대기
    FULL_AUTO = "full_auto"     # 완전 자동 - 모든 것 자동


class UtopiaState(Enum):
    """유토피아 상태"""
    IDLE = "idle"               # 대기 중
    GENERATING = "generating"   # 콘텐츠 생성 중
    TRANSLATING = "translating" # 번역 중 (v57.0.0)
    REVIEWING = "reviewing"     # 검토 대기 중
    UPLOADING = "uploading"     # 업로드 중
    MONITORING = "monitoring"   # 모니터링 중
    OPTIMIZING = "optimizing"   # 최적화 중
    ERROR = "error"             # 오류


class UtopiaEngine:
    """
    유토피아 엔진 - 완전 자동 YouTube 운영

    하나의 엔진으로 모든 유토피아 시스템 통합 관리
    """

    def __init__(
        self,
        data_dir: str,
        channel_type: str = "daily_life_toon",
        channel_id: str = None,
        media_factory_getter: Callable[[], Any] = None,  # v57.6.8: 의존성 주입
    ):
        """
        유토피아 엔진 초기화

        Args:
            data_dir: 기본 데이터 디렉토리
            channel_type: 채널 타입 (horror, emotional, romance 등)
            channel_id: 채널 고유 ID (멀티채널 지원, v54.8.0)
                        None이면 레거시 모드 (단일 채널)
            media_factory_getter: MediaFactory 인스턴스 반환 콜백 (v57.6.8)
                                  () -> MediaFactory 인스턴스
        """
        # v57.6.8: 의존성 주입 (레이어 분리)
        self._media_factory_getter = media_factory_getter

        # v54.8.0: 채널 ID가 있으면 채널별 데이터 폴더 사용
        self.channel_id = channel_id
        if channel_id:
            # 멀티채널 모드: data/channels/{channel_id}/
            self.data_dir = os.path.join(data_dir, "channels", channel_id)
            os.makedirs(self.data_dir, exist_ok=True)
        else:
            # 레거시 모드: data/ (기존 호환성)
            self.data_dir = data_dir

        self.channel_type = channel_type

        # 설정 파일
        self.config_path = os.path.join(self.data_dir, "utopia_config.json")
        self.state_path = os.path.join(self.data_dir, "utopia_state.json")
        self.log_path = os.path.join(self.data_dir, "utopia_log.json")

        # 설정 로드
        self.config = self._load_config()
        self.state = self._load_state()
        self.log = self._load_log()

        # 서브시스템 (지연 로드)
        self._media_factory = None
        self._prompt_optimizer = None
        self._upload_scheduler = None
        self._feedback_loop = None
        self._auto_optimizer = None
        self._translator = None  # v57.0.0: 다국어 번역기

        # v57.0.0: 채널 언어 설정 로드
        self._target_language = self._get_channel_language()

        # v54.7.3: Thread Safety를 위한 lock
        self._lock = threading.Lock()

        # 엔진 상태
        self._running = False
        self._engine_thread = None
        self._current_state = UtopiaState.IDLE

        # 콜백
        self.on_state_change: Optional[Callable[[UtopiaState, str], None]] = None
        self.on_mode_change: Optional[Callable[[UtopiaMode], None]] = None  # v54.7.1: UI 동기화용
        self.on_video_complete: Optional[Callable[[Dict], None]] = None
        self.on_error: Optional[Callable[[str], None]] = None
        self.on_log: Optional[Callable[[str], None]] = None

    # =========================================================
    # v57.0.0: 다국어 관련 메서드
    # =========================================================

    def _get_channel_language(self) -> str:
        """v57.0.0: 채널의 타겟 언어 조회"""
        if not self.channel_id:
            return "ko"  # 레거시 모드는 한국어 기본

        try:
            from utils.channel_registry import get_channel_registry
            registry = get_channel_registry()
            channel = registry.get_channel(self.channel_id)
            if channel:
                return getattr(channel, 'target_language', 'ko')
        except Exception as e:
            logger.warning(f"채널 언어 조회 실패: {e}")

        return "ko"

    def get_translator(self):
        """v57.0.0: ContentTranslator 인스턴스 반환"""
        if self._translator is None:
            try:
                from core.translator import get_translator
                self._translator = get_translator()
            except Exception as e:
                logger.warning(f"Translator 로드 실패: {e}")
        return self._translator

    def translate_content(self, content: Dict[str, Any]) -> Dict[str, Any]:
        """
        v57.0.0: 콘텐츠 번역

        채널의 target_language가 'ko'가 아니면 자동 번역

        Args:
            content: 번역할 콘텐츠 (시나리오, 메타데이터 등)

        Returns:
            번역된 콘텐츠 (실패 시 원본 반환)
        """
        if self._target_language == "ko":
            return content  # 한국어면 번역 불필요

        translator = self.get_translator()
        if not translator or not translator.is_available():
            logger.warning("Translator 사용 불가, 원본 반환")
            return content

        self._set_state(UtopiaState.TRANSLATING)
        self._add_log(f"콘텐츠 번역 중: ko → {self._target_language}")

        try:
            result = translator.translate_scenario(
                scenario=content,
                target_language=self._target_language,
                source_language="ko"
            )

            if result.success:
                self._add_log(f"번역 완료: {self._target_language}")
                return result.translated
            else:
                self._add_log(f"번역 실패: {result.error_message}")
                return content

        except Exception as e:
            logger.error(f"번역 중 오류: {e}")
            self._add_log(f"번역 오류: {e}")
            return content

    @property
    def target_language(self) -> str:
        """v57.0.0: 현재 채널의 타겟 언어"""
        return self._target_language

    # =========================================================
    # 설정 로드/저장
    # =========================================================

    def _load_config(self) -> Dict[str, Any]:
        """설정 로드"""
        default_config = {
            "mode": UtopiaMode.SEMI_AUTO.value,
            "enabled": False,
            # 생성 설정
            "generation": {
                "videos_per_day": 1,             # 일일 생성 목표
                "auto_generate_time": 10,        # 자동 생성 시간 (시)
                "use_personalization": True,     # 개인화 사용
                "quality_threshold": 70,         # 최소 품질 점수
            },
            # 업로드 설정
            "upload": {
                "auto_upload": True,             # 자동 업로드
                "require_review": True,          # 검토 필요
                "optimal_time_only": True,       # 최적 시간에만 업로드
            },
            # 모니터링 설정
            "monitoring": {
                "check_interval_hours": 6,       # 성과 체크 간격
                "auto_optimize": True,           # 자동 최적화
                "ctr_threshold": 2.0,            # CTR 기준 (미만이면 최적화)
            },
            # 안전 설정
            "safety": {
                "max_uploads_per_day": 3,        # 일일 최대 업로드
                "pause_on_error": True,          # 오류 시 일시정지
                "require_confirmation": False,   # 확인 필요 (full_auto에서도)
            },
        }

        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                    # 딥 머지
                    self._deep_merge(default_config, loaded)
            except Exception as e:
                logger.warning(f"설정 로드 실패: {e}")

        return default_config

    def _deep_merge(self, base: dict, update: dict):
        """딕셔너리 딥 머지"""
        for key, value in update.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._deep_merge(base[key], value)
            else:
                base[key] = value

    def _save_config(self):
        """설정 저장 (v54.7.3: Thread Safe)"""
        with self._lock:
            try:
                with open(self.config_path, 'w', encoding='utf-8') as f:
                    json.dump(self.config, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.error(f"설정 저장 실패: {e}")

    def _load_state(self) -> Dict[str, Any]:
        """상태 로드"""
        default_state = {
            "current_state": UtopiaState.IDLE.value,
            "last_generation": None,
            "last_upload": None,
            "last_check": None,
            "today_generated": 0,
            "today_uploaded": 0,
            "pending_review": [],
            "errors": [],
        }

        if os.path.exists(self.state_path):
            try:
                with open(self.state_path, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                    default_state.update(loaded)
            except Exception as e:
                logger.warning(f"상태 로드 실패: {e}")

        # 날짜가 바뀌면 카운터 초기화
        if default_state.get("last_generation"):
            try:
                last_date = datetime.fromisoformat(default_state["last_generation"]).date()
                if last_date < datetime.now().date():
                    default_state["today_generated"] = 0
                    default_state["today_uploaded"] = 0
            except (ValueError, TypeError) as e:
                logger.debug(f"날짜 비교 실패: {e}")

        return default_state

    def _save_state(self):
        """상태 저장 (v54.7.3: Thread Safe)"""
        with self._lock:
            try:
                self.state["current_state"] = self._current_state.value
                with open(self.state_path, 'w', encoding='utf-8') as f:
                    json.dump(self.state, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.error(f"상태 저장 실패: {e}")

    def _load_log(self) -> List[Dict[str, Any]]:
        """로그 로드"""
        if os.path.exists(self.log_path):
            try:
                with open(self.log_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"로그 로드 실패: {e}")
        return []

    def _save_log(self):
        """로그 저장 (최근 500개) (v54.7.3: Thread Safe)"""
        with self._lock:
            try:
                with open(self.log_path, 'w', encoding='utf-8') as f:
                    json.dump(self.log[-500:], f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.error(f"로그 저장 실패: {e}")

    def _add_log(self, message: str, level: str = "info", details: Dict = None):
        """로그 추가 (v54.7.3: Thread Safe)"""
        message = redact_sensitive_text(message)
        entry = {
            "timestamp": datetime.now().isoformat(),
            "level": level,
            "message": message,
            "details": details or {},
        }

        # v54.7.3: lock으로 log 리스트 보호
        with self._lock:
            self.log.append(entry)

        # _save_log는 내부에서 lock 사용하므로 별도 호출
        self._save_log()

        # 로그 출력 (I/O는 lock 밖에서 수행)
        if level == "error":
            logger.error(message)
        elif level == "warning":
            logger.warning(message)
        else:
            logger.info(message)

        # 콜백
        if self.on_log:
            self.on_log(f"[{entry['timestamp'][:19]}] {message}")

    # =========================================================
    # 서브시스템 접근
    # =========================================================

    @property
    def media_factory(self):
        """MediaFactory 지연 로드 (v57.6.8: 의존성 주입 우선)"""
        if self._media_factory is None:
            # v57.6.8: 콜백 우선 (레이어 분리)
            if self._media_factory_getter:
                try:
                    self._media_factory = self._media_factory_getter()
                except Exception as e:
                    logger.error(f"MediaFactory getter 실패: {e}")

            # 하위호환: 직접 import (deprecated)
            if self._media_factory is None:
                try:
                    from modules_pro.media_factory import MediaFactory
                    self._media_factory = MediaFactory(channel=self.channel_type)
                except Exception as e:
                    logger.error(f"MediaFactory 로드 실패: {e}")
        return self._media_factory

    @property
    def prompt_optimizer(self):
        """PromptOptimizer 지연 로드"""
        if self._prompt_optimizer is None:
            try:
                from utils.prompt_optimizer import get_prompt_optimizer
                self._prompt_optimizer = get_prompt_optimizer(self.data_dir, self.channel_type)
            except Exception as e:
                logger.error(f"PromptOptimizer 로드 실패: {e}")
        return self._prompt_optimizer

    @property
    def upload_scheduler(self):
        """UploadScheduler 지연 로드"""
        if self._upload_scheduler is None:
            try:
                from utils.upload_scheduler import get_upload_scheduler
                self._upload_scheduler = get_upload_scheduler(self.data_dir, self.channel_type)
            except Exception as e:
                logger.error(f"UploadScheduler 로드 실패: {e}")
        return self._upload_scheduler

    @property
    def feedback_loop(self):
        """FeedbackLoop 지연 로드 (v54.7.3: None 처리 강화)"""
        if self._feedback_loop is None:
            try:
                from utils.feedback_loop import get_feedback_loop
                instance = get_feedback_loop(self.data_dir, self.channel_type)
                # v54.7.3: None 반환 시 (순환 참조 등) 로그만 남기고 계속 None 반환
                if instance is None:
                    logger.warning(f"FeedbackLoop 인스턴스 None (순환 참조 가능)")
                else:
                    self._feedback_loop = instance
            except Exception as e:
                logger.error(f"FeedbackLoop 로드 실패: {e}")
        return self._feedback_loop

    @property
    def auto_optimizer(self):
        """AutoOptimizer 지연 로드 (v54.7.3: None 처리 강화)"""
        if self._auto_optimizer is None:
            try:
                from utils.auto_optimizer import get_auto_optimizer
                instance = get_auto_optimizer(self.data_dir, self.channel_type)
                # v54.7.3: None 반환 시 (순환 참조 등) 로그만 남기고 계속 None 반환
                if instance is None:
                    logger.warning(f"AutoOptimizer 인스턴스 None (순환 참조 가능)")
                else:
                    self._auto_optimizer = instance
            except Exception as e:
                logger.error(f"AutoOptimizer 로드 실패: {e}")
        return self._auto_optimizer

    # =========================================================
    # 상태 관리
    # =========================================================

    def _set_state(self, new_state: UtopiaState, reason: str = ""):
        """상태 변경"""
        reason = redact_sensitive_text(reason)
        old_state = self._current_state
        self._current_state = new_state
        self._save_state()

        self._add_log(f"상태 변경: {old_state.value} → {new_state.value}" + (f" ({reason})" if reason else ""))

        if self.on_state_change:
            self.on_state_change(new_state, reason)

    # =========================================================
    # 메인 엔진
    # =========================================================

    def start(self):
        """유토피아 엔진 시작"""
        if self._running:
            self._add_log("엔진이 이미 실행 중입니다.", "warning")
            return

        self._running = True
        self._engine_thread = threading.Thread(target=self._engine_loop, daemon=True)
        self._engine_thread.start()

        # 서브 스케줄러 시작
        if self.upload_scheduler:
            self.upload_scheduler.start_scheduler()

        if self.feedback_loop:
            self.feedback_loop.start_scheduler()

        # v54.7.1: 개인화 데이터 자동 수집 (백그라운드)
        self._init_personalization()

        self._add_log("유토피아 엔진 시작")
        self.config["enabled"] = True
        self._save_config()

    def _init_personalization(self):
        """개인화 데이터 초기화 및 자동 수집"""
        if not self.config.get("generation", {}).get("use_personalization", True):
            return

        def _collect_async():
            try:
                if self.prompt_optimizer:
                    status = self.prompt_optimizer.get_learning_status()
                    # 데이터가 부족하거나 24시간 이상 지났으면 수집
                    last_updated = status.get("last_updated")
                    needs_refresh = False

                    if not status.get("has_enough_data"):
                        needs_refresh = True
                    elif last_updated:
                        try:
                            last_time = datetime.fromisoformat(last_updated)
                            if (datetime.now() - last_time).total_seconds() > 86400:  # 24시간
                                needs_refresh = True
                        except Exception:
                            needs_refresh = True
                    else:
                        needs_refresh = True

                    if needs_refresh:
                        self._add_log("개인화 데이터 수집 시작...")
                        result = self.prompt_optimizer.collect_and_analyze()
                        if result.get("success"):
                            self._add_log(
                                f"개인화 분석 완료: {result.get('videos_analyzed', 0)}개 영상, "
                                f"패턴 {sum(result.get('patterns_found', {}).values())}개 발견"
                            )
                        else:
                            errors = result.get("errors", [])
                            if errors:
                                self._add_log(f"개인화 수집 실패: {errors[0]}", "warning")
            except Exception as e:
                # v54.7.2: 개인화 실패 시 상태에 기록 (사용자가 확인 가능)
                safe_error = redact_sensitive_text(e)
                self._add_log(f"개인화 초기화 오류: {safe_error}", "warning")
                self.state["personalization_error"] = safe_error
                self.state["personalization_last_attempt"] = datetime.now().isoformat()

        # 백그라운드에서 실행 (시작 지연 방지)
        threading.Thread(target=_collect_async, daemon=True).start()

    def stop(self):
        """유토피아 엔진 중지"""
        self._running = False

        # 서브 스케줄러 중지
        if self._upload_scheduler:
            self._upload_scheduler.stop_scheduler()

        if self._feedback_loop:
            self._feedback_loop.stop_scheduler()

        if self._engine_thread:
            self._engine_thread.join(timeout=5)

        self._set_state(UtopiaState.IDLE, "엔진 중지")
        self._add_log("유토피아 엔진 중지")
        self.config["enabled"] = False
        self._save_config()

    def _engine_loop(self):
        """엔진 메인 루프"""
        check_interval = 60  # 1분마다 체크

        while self._running:
            try:
                self._engine_cycle()
            except Exception as e:
                safe_error = redact_sensitive_text(e)
                self._add_log(f"엔진 사이클 오류: {safe_error}", "error")
                if self.config.get("safety", {}).get("pause_on_error"):
                    self._set_state(UtopiaState.ERROR, safe_error)
                    if self.on_error:
                        self.on_error(safe_error)

            # 대기
            for _ in range(check_interval):
                if not self._running:
                    break
                time.sleep(1)

    def _engine_cycle(self):
        """엔진 사이클 - 한 번의 체크"""
        mode = UtopiaMode(self.config.get("mode", "semi_auto"))
        now = datetime.now()

        # 1. 생성 체크
        if self._should_generate(now):
            self._run_generation()

        # 2. 검토 대기 중인 항목 처리 (semi_auto에서는 스킵)
        if mode == UtopiaMode.FULL_AUTO:
            self._process_pending_reviews()

        # 3. 모니터링 체크
        if self._should_monitor(now):
            self._run_monitoring()

        # 4. 최적화 체크
        if self.config.get("monitoring", {}).get("auto_optimize"):
            self._run_optimization()

    def _should_generate(self, now: datetime) -> bool:
        """생성이 필요한지 확인"""
        gen_config = self.config.get("generation", {})

        # 일일 목표 체크
        if self.state.get("today_generated", 0) >= gen_config.get("videos_per_day", 1):
            return False

        # 자동 생성 시간 체크
        auto_time = gen_config.get("auto_generate_time", 10)
        if now.hour != auto_time:
            return False

        # 마지막 생성 체크 (1시간 이내 생성했으면 스킵)
        last_gen = self.state.get("last_generation")
        if last_gen:
            try:
                last_time = datetime.fromisoformat(last_gen)
                if (now - last_time).total_seconds() < 3600:
                    return False
            except (ValueError, TypeError) as e:
                logger.debug(f"마지막 생성 시간 파싱 실패: {e}")

        return True

    def _should_monitor(self, now: datetime) -> bool:
        """모니터링이 필요한지 확인"""
        interval = self.config.get("monitoring", {}).get("check_interval_hours", 6)

        last_check = self.state.get("last_check")
        if not last_check:
            return True

        try:
            last_time = datetime.fromisoformat(last_check)
            hours_since = (now - last_time).total_seconds() / 3600
            return hours_since >= interval
        except Exception:
            return True

    # =========================================================
    # 콘텐츠 생성
    # =========================================================

    def _run_generation(self):
        """콘텐츠 생성 실행"""
        self._set_state(UtopiaState.GENERATING, "콘텐츠 생성 시작")
        self._add_log("콘텐츠 생성 시작")

        try:
            # 개인화 적용
            topic = None
            if self.config.get("generation", {}).get("use_personalization"):
                if self.prompt_optimizer:
                    # 최적화된 주제 가져오기
                    suggestions = self.prompt_optimizer.get_recommendations_summary()
                    self._add_log(f"개인화 추천 적용: {suggestions[:100]}...")

            # 영상 생성 (MediaFactory)
            # 실제로는 GUI를 통해 실행되거나 별도 워커에서 실행
            # 여기서는 대기열에 작업 추가

            self.state["last_generation"] = datetime.now().isoformat()
            self.state["today_generated"] = self.state.get("today_generated", 0) + 1
            self._save_state()

            self._add_log("콘텐츠 생성 완료")

            # 검토 모드 확인
            if self.config.get("upload", {}).get("require_review"):
                self._set_state(UtopiaState.REVIEWING, "검토 대기")
            else:
                self._set_state(UtopiaState.IDLE)

        except Exception as e:
            safe_error = redact_sensitive_text(e)
            self._add_log(f"콘텐츠 생성 실패: {safe_error}", "error")
            self._set_state(UtopiaState.ERROR, safe_error)

    def generate_video_now(
        self,
        topic: str = None,
        title: str = None,
        sub_title: str = None,
        auto_upload: bool = None,
        run_async: bool = True
    ) -> Dict[str, Any]:
        """
        즉시 영상 생성 (수동 트리거)

        v54.7.1: MediaFactory 실제 연동

        Args:
            topic: 주제 (없으면 자동 생성)
            title: 제목 (없으면 자동 생성)
            sub_title: 부제목
            auto_upload: 자동 업로드 여부 (설정 따름)
            run_async: 비동기 실행 (기본 True)

        Returns:
            생성 결과 또는 작업 ID
        """
        result = {
            "success": False,
            "video_path": None,
            "thumbnail_path": None,
            "error": None,
            "task_id": None
        }

        # 자동 업로드 설정 확인
        should_upload = auto_upload if auto_upload is not None else self.config.get("upload", {}).get("auto_upload", False)

        try:
            self._set_state(UtopiaState.GENERATING, "영상 생성 시작")

            # 개인화 적용
            optimized_title = title
            optimized_sub = sub_title or ""
            if self.prompt_optimizer and self.config.get("generation", {}).get("use_personalization"):
                if title:
                    opt_result = self.prompt_optimizer.optimize_title(title)
                    if opt_result.get("score", 0) > 60:  # 점수가 개선되면 적용
                        optimized_title = opt_result.get("optimized_title", title)
                        self._add_log(f"제목 최적화: 점수 {opt_result.get('score', 0):.0f}")

            # MediaFactory가 없으면 설정만 반환
            if not self.media_factory:
                self._add_log("MediaFactory를 사용할 수 없음 - 설정만 반환", "warning")
                result["success"] = True
                result["config"] = {
                    "topic": topic,
                    "title": optimized_title,
                    "sub_title": optimized_sub,
                    "auto_upload": should_upload,
                }
                self._set_state(UtopiaState.IDLE)
                return result

            # 비동기 실행
            if run_async:
                task_id = f"utopia_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                result["task_id"] = task_id

                def _generate_async():
                    try:
                        gen_result = self._execute_generation(
                            topic, optimized_title, optimized_sub, should_upload
                        )
                        if gen_result.get("success"):
                            self._add_log(f"영상 생성 완료: {optimized_title}")
                        else:
                            self._add_log(f"영상 생성 실패: {gen_result.get('error')}", "error")
                    except Exception as e:
                        safe_error = redact_sensitive_text(e)
                        self._add_log(f"비동기 생성 오류: {safe_error}", "error")
                        self._set_state(UtopiaState.ERROR, safe_error)

                threading.Thread(target=_generate_async, daemon=True).start()
                result["success"] = True
                self._add_log(f"영상 생성 작업 시작 (작업 ID: {task_id})")

            else:
                # 동기 실행
                result = self._execute_generation(
                    topic, optimized_title, optimized_sub, should_upload
                )

        except Exception as e:
            safe_error = redact_sensitive_text(e)
            result["error"] = safe_error
            self._add_log(f"즉시 생성 실패: {safe_error}", "error")
            self._set_state(UtopiaState.ERROR, safe_error)

        return result

    def _execute_generation(
        self,
        topic: str,
        title: str,
        sub_title: str,
        auto_upload: bool
    ) -> Dict[str, Any]:
        """
        실제 영상 생성 실행

        v54.7.2: MediaFactory API 연동 및 반환값 처리 개선
        - MediaFactory.produce_video_with_gui() 사용
        - JSON 파일 기반 입력 (기획안 필요)
        - 반환값: Optional[str] (영상 경로 또는 None)

        Returns:
            {
                'success': bool,
                'video_path': Optional[str],
                'thumbnail_path': Optional[str],
                'error': Optional[str],
                'description': str,
                'tags': List[str]
            }
        """
        result = {
            "success": False,
            "video_path": None,
            "thumbnail_path": None,
            "error": None,
            "description": "",
            "tags": []
        }

        try:
            # MediaFactory로 영상 생성
            # MediaFactory는 JSON 기획안 파일을 입력으로 받음
            # 기획안이 없으면 설정만 반환
            json_path = self._find_or_create_plan_json(topic, title, sub_title)

            if not json_path:
                result["error"] = "기획안 JSON 파일을 찾을 수 없음"
                self._set_state(UtopiaState.ERROR, result["error"])
                return result

            # MediaFactory.produce_video_with_gui() 호출
            # 반환값: Optional[str] - 영상 파일 경로 또는 None (실패 시)
            video_path = self.media_factory.produce_video_with_gui(
                json_path=json_path,
                thumbnail_callback=None,  # 자동화 모드에서는 콜백 없음
                progress_callback=self._on_generation_progress,
                log_callback=lambda msg: self._add_log(msg),
            )

            # v54.7.2: 결과 변환 (MediaFactory는 string만 반환)
            if video_path and isinstance(video_path, str):
                result["success"] = True
                result["video_path"] = video_path
                result["thumbnail_path"] = self._find_thumbnail_for_video(video_path)

                # 기획안에서 description/tags 추출 시도
                try:
                    with open(json_path, 'r', encoding='utf-8') as f:
                        plan_data = json.load(f)
                        result["description"] = plan_data.get("description", "")
                        result["tags"] = plan_data.get("tags", [])
                except (json.JSONDecodeError, FileNotFoundError, OSError) as e:
                    logger.debug(f"plan_data JSON 로드 실패: {e}")
            else:
                result["error"] = "영상 생성 실패"

            # v54.7.3: 중복 처리 제거 - result가 이미 최종 결과임
            if result.get("success"):
                # 상태 업데이트
                self.state["last_generation"] = datetime.now().isoformat()
                self.state["today_generated"] = self.state.get("today_generated", 0) + 1
                self._save_state()

                # 자동 업로드 또는 검토 대기
                if auto_upload and not self.config.get("upload", {}).get("require_review"):
                    # 즉시 업로드 예약
                    if self.upload_scheduler:
                        self.upload_scheduler.add_to_queue(
                            video_path=result["video_path"],
                            thumbnail_path=result["thumbnail_path"],
                            title=title,
                            description=result.get("description", ""),
                            tags=result.get("tags", []),
                        )
                        self._add_log(f"업로드 예약됨: {title}")
                else:
                    # 검토 대기열에 추가
                    self.add_to_review({
                        "video_path": result["video_path"],
                        "thumbnail_path": result["thumbnail_path"],
                        "title": title,
                        "description": result.get("description", ""),
                        "tags": result.get("tags", []),
                    })

                self._set_state(UtopiaState.IDLE)
            else:
                # result["error"]는 이미 설정되어 있음 (681라인 또는 724라인)
                if not result.get("error"):
                    result["error"] = "생성 실패"
                self._set_state(UtopiaState.ERROR, result["error"])

        except Exception as e:
            safe_error = redact_sensitive_text(e)
            result["error"] = safe_error
            self._set_state(UtopiaState.ERROR, safe_error)

        return result

    def _find_or_create_plan_json(
        self,
        topic: str,
        title: str,
        sub_title: str
    ) -> Optional[str]:
        """
        v54.7.1: 기획안 JSON 파일 찾기 또는 생성

        MediaFactory는 JSON 기획안 파일을 입력으로 받음
        - 기존 기획안이 있으면 사용
        - 없으면 자동 생성 (간단한 구조)
        """
        import glob

        # 1. 최근 기획안 파일 찾기
        plan_dir = os.path.join(self.data_dir, "plans", self.channel_type)
        if os.path.exists(plan_dir):
            json_files = glob.glob(os.path.join(plan_dir, "*.json"))
            if json_files:
                # 가장 최근 파일 반환
                latest = max(json_files, key=os.path.getmtime)
                self._add_log(f"기존 기획안 사용: {os.path.basename(latest)}")
                return latest

        # 2. 기획안이 없으면 간단한 구조 생성
        # 실제 프로덕션에서는 GPT 등으로 기획안 자동 생성 필요
        os.makedirs(plan_dir, exist_ok=True)

        plan_filename = f"utopia_auto_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        plan_path = os.path.join(plan_dir, plan_filename)

        plan_data = {
            "project_name": f"utopia_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "mode": self.channel_type,
            "title": title or topic or "자동 생성 콘텐츠",
            "sub_title": sub_title or "",
            "topic": topic or "",
            "auto_generated": True,
            "created_at": datetime.now().isoformat(),
        }

        with open(plan_path, 'w', encoding='utf-8') as f:
            json.dump(plan_data, f, ensure_ascii=False, indent=2)

        self._add_log(f"기획안 자동 생성: {plan_filename}")
        return plan_path

    def _find_thumbnail_for_video(self, video_path: str) -> Optional[str]:
        """v54.7.1: 영상에 해당하는 썸네일 찾기"""
        if not video_path:
            return None

        # 같은 디렉토리에서 썸네일 찾기
        video_dir = os.path.dirname(video_path)
        video_name = os.path.splitext(os.path.basename(video_path))[0]

        # 일반적인 썸네일 명명 패턴
        patterns = [
            f"{video_name}_thumbnail.jpg",
            f"{video_name}_thumb.jpg",
            f"thumbnail_REAL.jpg",
            f"thumbnail.jpg",
        ]

        for pattern in patterns:
            thumb_path = os.path.join(video_dir, pattern)
            if os.path.exists(thumb_path):
                return thumb_path

        return None

    def _on_generation_progress(self, message: str, percentage: int):
        """v54.7.1: 생성 진행 상황 콜백"""
        self._add_log(f"[{percentage}%] {message}")

    # =========================================================
    # 검토 및 승인
    # =========================================================

    def _process_pending_reviews(self):
        """대기 중인 검토 처리"""
        pending = self.state.get("pending_review", [])
        if not pending:
            return

        for item in pending[:]:
            # 자동 업로드
            if self.upload_scheduler:
                self.upload_scheduler.add_to_queue(
                    video_path=item.get("video_path"),
                    thumbnail_path=item.get("thumbnail_path"),
                    title=item.get("title"),
                    description=item.get("description", ""),
                    tags=item.get("tags", []),
                )
                self._add_log(f"업로드 예약: {item.get('title')}")

            pending.remove(item)

        self.state["pending_review"] = pending
        self._save_state()

    def add_to_review(self, video_data: Dict[str, Any]):
        """검토 대기열에 추가"""
        if "pending_review" not in self.state:
            self.state["pending_review"] = []

        self.state["pending_review"].append({
            **video_data,
            "added_at": datetime.now().isoformat(),
        })
        self._save_state()
        self._add_log(f"검토 대기 추가: {video_data.get('title')}")

    def approve_review(self, index: int = 0):
        """검토 승인"""
        pending = self.state.get("pending_review", [])
        if index >= len(pending):
            return False

        item = pending.pop(index)

        # 업로드 예약
        if self.upload_scheduler:
            self.upload_scheduler.add_to_queue(
                video_path=item.get("video_path"),
                thumbnail_path=item.get("thumbnail_path"),
                title=item.get("title"),
                description=item.get("description", ""),
                tags=item.get("tags", []),
            )

        self._save_state()
        self._add_log(f"검토 승인: {item.get('title')}")
        return True

    def reject_review(self, index: int = 0, reason: str = ""):
        """검토 거부"""
        pending = self.state.get("pending_review", [])
        if index >= len(pending):
            return False

        item = pending.pop(index)
        self._save_state()
        self._add_log(f"검토 거부: {item.get('title')} ({reason})")
        return True

    # =========================================================
    # 모니터링 및 최적화
    # =========================================================

    def _run_monitoring(self):
        """모니터링 실행"""
        self._set_state(UtopiaState.MONITORING, "성과 모니터링")

        try:
            if self.feedback_loop:
                # 피드백 루프 체크
                self.feedback_loop._check_all_videos()

            self.state["last_check"] = datetime.now().isoformat()
            self._save_state()

            self._add_log("모니터링 완료")
            self._set_state(UtopiaState.IDLE)

        except Exception as e:
            self._add_log(f"모니터링 실패: {e}", "error")

    def _run_optimization(self):
        """최적화 실행"""
        if not self.auto_optimizer:
            return

        try:
            self._set_state(UtopiaState.OPTIMIZING, "자동 최적화")

            result = self.auto_optimizer.run_optimization_cycle()

            if result.get("thumbnails_changed", 0) > 0:
                self._add_log(f"자동 최적화: 썸네일 {result['thumbnails_changed']}개 교체")

            self._set_state(UtopiaState.IDLE)

        except Exception as e:
            self._add_log(f"최적화 실패: {e}", "error")

    # =========================================================
    # 상태 조회
    # =========================================================

    def get_status(self) -> Dict[str, Any]:
        """현재 상태 조회"""
        return {
            "running": self._running,
            "mode": self.config.get("mode"),
            "current_state": self._current_state.value,
            "today_generated": self.state.get("today_generated", 0),
            "today_uploaded": self.state.get("today_uploaded", 0),
            "pending_review_count": len(self.state.get("pending_review", [])),
            "last_generation": self.state.get("last_generation"),
            "last_upload": self.state.get("last_upload"),
            "last_check": self.state.get("last_check"),
            # 서브시스템 상태
            "subsystems": {
                "upload_scheduler": self.upload_scheduler.is_scheduler_running() if self._upload_scheduler else False,
                "feedback_loop": self.feedback_loop.is_scheduler_running() if self._feedback_loop else False,
            },
        }

    def get_config(self) -> Dict[str, Any]:
        """설정 조회"""
        return self.config.copy()

    def update_config(self, new_config: Dict[str, Any]):
        """설정 업데이트"""
        self._deep_merge(self.config, new_config)
        self._save_config()
        self._add_log("설정 업데이트됨")

    def set_mode(self, mode: UtopiaMode):
        """모드 변경"""
        old_mode = self.config.get("mode")
        self.config["mode"] = mode.value
        self._save_config()
        self._add_log(f"모드 변경: {old_mode} → {mode.value}")

        # v54.7.1: UI 동기화 콜백
        if self.on_mode_change:
            try:
                self.on_mode_change(mode)
            except Exception as e:
                self._add_log(f"모드 변경 콜백 오류: {e}", "warning")

    def get_recent_logs(self, count: int = 50) -> List[Dict[str, Any]]:
        """최근 로그 조회"""
        return self.log[-count:]

    def is_running(self) -> bool:
        """실행 상태"""
        return self._running


# 전역 인스턴스 (v54.8.0: 멀티채널 지원)
def get_utopia_engine(
    data_dir: str = None,
    channel_type: str = "daily_life_toon",
    channel_id: str = None,
    media_factory_getter: Callable[[], Any] = None,  # v57.6.8: 의존성 주입
) -> UtopiaEngine:
    """
    UtopiaEngine 인스턴스 가져오기 (InstanceManager 경유)

    Args:
        data_dir: 기본 데이터 디렉토리
        channel_type: 채널 타입
        channel_id: 채널 고유 ID (v54.8.0 멀티채널 지원)
                    None이면 레거시 모드 (단일 채널)
        media_factory_getter: MediaFactory 인스턴스 반환 콜백 (v57.6.8)

    Returns:
        UtopiaEngine: 인스턴스
    """
    try:
        from utils.instance_manager import get_instance_manager
        return get_instance_manager().get_utopia_engine(
            data_dir, channel_type, channel_id, media_factory_getter
        )
    except ImportError:
        # 폴백: 직접 생성
        if data_dir is None:
            try:
                from config.settings import config
                data_dir = config.DATA_DIR
            except Exception:
                data_dir = "data"
        return UtopiaEngine(data_dir, channel_type, channel_id, media_factory_getter)
