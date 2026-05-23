# src/utils/upload_scheduler.py
"""
v54.4 → v54.5: 자동 업로드 스케줄링 시스템 (UploadScheduler)

제작 완료된 영상을 대기열에 추가하고, 최적의 시간에 자동 업로드

기능:
1. 업로드 대기열 관리
2. 최적 시간 자동 예약
3. 스케줄러 기반 자동 업로드
4. 업로드 상태 모니터링
5. 실패 시 재시도
6. v54.5: 업로드 완료 후 피드백 루프 자동 등록

"유토피아" 시스템의 배포 엔진
"""
import os
import json
import logging
import threading
import time
import random
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Callable
from enum import Enum

from utils.secret_redaction import redact_sensitive_text

logger = logging.getLogger(__name__)


class UploadStatus(Enum):
    """업로드 상태"""
    PENDING = "pending"           # 대기 중
    SCHEDULED = "scheduled"       # 예약됨
    UPLOADING = "uploading"       # 업로드 중
    COMPLETED = "completed"       # 완료
    FAILED = "failed"             # 실패
    CANCELLED = "cancelled"       # 취소됨


class UploadScheduler:
    """
    자동 업로드 스케줄러

    영상 제작 완료 → 대기열 추가 → 최적 시간에 자동 업로드

    v54.7.3: Thread Safety 강화
    """

    # 기본 업로드 시간 (학습 데이터 없을 때)
    DEFAULT_UPLOAD_HOURS = [18, 19, 20]  # 오후 6-8시
    DEFAULT_UPLOAD_DAYS = [4, 5, 6]      # 금, 토, 일

    def __init__(self, data_dir: str, channel_type: str = "daily_life_toon"):
        self.data_dir = data_dir
        self.channel_type = channel_type

        # v54.7.3: Thread Safety를 위한 lock
        self._lock = threading.Lock()

        # 데이터 파일 경로
        self.queue_path = os.path.join(data_dir, "upload_queue.json")
        self.history_path = os.path.join(data_dir, "upload_history.json")
        self.config_path = os.path.join(data_dir, "upload_scheduler_config.json")

        # 데이터 로드
        self.queue = self._load_queue()
        self.history = self._load_history()
        self.config = self._load_config()

        # 스케줄러 상태
        self._scheduler_running = False
        self._scheduler_thread = None

        # 콜백
        self.on_upload_start: Optional[Callable[[Dict], None]] = None
        self.on_upload_complete: Optional[Callable[[Dict], None]] = None
        self.on_upload_fail: Optional[Callable[[Dict, str], None]] = None
        self.on_log: Optional[Callable[[str], None]] = None

    # =========================================================
    # 데이터 로드/저장
    # =========================================================

    def _load_queue(self) -> List[Dict[str, Any]]:
        """대기열 로드"""
        if os.path.exists(self.queue_path):
            try:
                with open(self.queue_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"대기열 로드 실패: {e}")
        return []

    def _save_queue(self):
        """대기열 저장"""
        try:
            with open(self.queue_path, 'w', encoding='utf-8') as f:
                json.dump(self.queue, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"대기열 저장 실패: {e}")

    def _load_history(self) -> List[Dict[str, Any]]:
        """업로드 히스토리 로드"""
        if os.path.exists(self.history_path):
            try:
                with open(self.history_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"히스토리 로드 실패: {e}")
        return []

    def _save_history(self):
        """히스토리 저장 (최근 100개만)"""
        try:
            with open(self.history_path, 'w', encoding='utf-8') as f:
                json.dump(self.history[-100:], f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"히스토리 저장 실패: {e}")

    def _load_config(self) -> Dict[str, Any]:
        """설정 로드"""
        default_config = {
            "enabled": True,
            "auto_schedule": True,          # 자동으로 최적 시간 예약
            "check_interval_minutes": 5,    # 스케줄러 체크 간격 (분)
            "max_retries": 3,               # 실패 시 최대 재시도
            "retry_delay_minutes": 30,      # 재시도 대기 시간
            "daily_upload_limit": 2,        # 일일 업로드 제한: 대량 업로드처럼 보이지 않게 보수적으로 운용
            "min_gap_hours": 8,             # 업로드 간 최소 간격 (시간)
            "preferred_hours": [18, 19, 20],  # 선호 업로드 시간
            "preferred_days": [4, 5, 6],      # 선호 업로드 요일
            "policy_safe_uploads": True,
        }

        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                    default_config.update(loaded)
            except Exception as e:
                logger.warning(f"설정 로드 실패: {e}")

        if default_config.get("policy_safe_uploads", True):
            default_config["daily_upload_limit"] = min(int(default_config.get("daily_upload_limit", 2) or 2), 2)
            default_config["min_gap_hours"] = max(int(default_config.get("min_gap_hours", 8) or 8), 8)

        return default_config

    def _save_config(self):
        """설정 저장"""
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"설정 저장 실패: {e}")

    def _log(self, message: str, level: str = "info"):
        """로그 기록"""
        message = redact_sensitive_text(message)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"[{timestamp}] {message}"

        if level == "error":
            logger.error(message)
        elif level == "warning":
            logger.warning(message)
        else:
            logger.info(message)

        if self.on_log:
            self.on_log(log_entry)

    # =========================================================
    # 대기열 관리
    # =========================================================

    def add_to_queue(
        self,
        video_path: str,
        thumbnail_path: str,
        title: str,
        description: str = "",
        tags: List[str] = None,
        category: str = "24",  # Entertainment
        scheduled_time: datetime = None,
        metadata: Dict = None
    ) -> Dict[str, Any]:
        """
        업로드 대기열에 추가

        Args:
            video_path: 영상 파일 경로
            thumbnail_path: 썸네일 경로
            title: 제목
            description: 설명
            tags: 태그 리스트
            category: YouTube 카테고리 ID
            scheduled_time: 예약 시간 (None이면 자동 계산)
            metadata: 추가 메타데이터

        Returns:
            추가된 아이템 정보
        """
        # 파일 존재 확인
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"영상 파일 없음: {video_path}")

        # 예약 시간 계산
        if scheduled_time is None and self.config.get("auto_schedule", True):
            scheduled_time = self._calculate_optimal_time()

        policy_metadata = {
            "contains_synthetic_media": True,
            "verified_true_story": False,
            "human_reviewed": False,
            "channel_mode": self.channel_type,
            "privacy": "private",
        }
        policy_metadata.update(metadata or {})

        # v54.7.3: Thread Safety - lock 사용
        with self._lock:
            # 대기열 아이템 생성
            item = {
                "id": f"upload_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{len(self.queue)}",
                "video_path": video_path,
                "thumbnail_path": thumbnail_path,
                "title": title,
                "description": description,
                "tags": tags or [],
                "category": category,
                "channel_type": self.channel_type,
                "status": UploadStatus.SCHEDULED.value if scheduled_time else UploadStatus.PENDING.value,
                "scheduled_time": scheduled_time.isoformat() if scheduled_time else None,
                "created_at": datetime.now().isoformat(),
                "retry_count": 0,
                "metadata": policy_metadata,
                "video_id": None,  # 업로드 후 설정
                "error": None,
            }

            self.queue.append(item)
            self._save_queue()

        self._log(f"대기열 추가: {title} (예약: {scheduled_time.strftime('%m/%d %H:%M') if scheduled_time else '즉시'})")

        return item

    def remove_from_queue(self, item_id: str) -> bool:
        """대기열에서 제거 (v54.7.3: Thread Safe)"""
        with self._lock:
            for i, item in enumerate(self.queue):
                if item["id"] == item_id:
                    removed = self.queue.pop(i)
                    removed["status"] = UploadStatus.CANCELLED.value
                    self.history.append(removed)
                    self._save_queue()
                    self._save_history()
                    self._log(f"대기열 제거: {removed['title']}")
                    return True
        return False

    def update_schedule(self, item_id: str, new_time: datetime) -> bool:
        """예약 시간 변경 (v54.7.3: Thread Safe)"""
        with self._lock:
            for item in self.queue:
                if item["id"] == item_id:
                    item["scheduled_time"] = new_time.isoformat()
                    item["status"] = UploadStatus.SCHEDULED.value
                    self._save_queue()
                    self._log(f"예약 변경: {item['title']} → {new_time.strftime('%m/%d %H:%M')}")
                    return True
        return False

    def get_queue(self) -> List[Dict[str, Any]]:
        """대기열 조회 (v54.7.3: Thread Safe)"""
        with self._lock:
            return list(self.queue)  # 복사본 반환

    def get_pending_count(self) -> int:
        """대기 중인 항목 수 (v54.7.3: Thread Safe)"""
        with self._lock:
            return sum(1 for item in self.queue
                       if item["status"] in [UploadStatus.PENDING.value, UploadStatus.SCHEDULED.value])

    def clear_completed(self):
        """완료된 항목 정리 (v54.7.3: Thread Safe)"""
        with self._lock:
            completed = [item for item in self.queue
                         if item["status"] in [UploadStatus.COMPLETED.value, UploadStatus.CANCELLED.value]]
            self.history.extend(completed)
            self.queue = [item for item in self.queue
                          if item["status"] not in [UploadStatus.COMPLETED.value, UploadStatus.CANCELLED.value]]
            self._save_queue()
            self._save_history()

    # =========================================================
    # 최적 시간 계산
    # =========================================================

    def _calculate_optimal_time(self) -> datetime:
        """
        최적 업로드 시간 계산

        1. 개인화 데이터가 있으면 학습된 시간 사용
        2. 없으면 기본값 사용
        3. 일일 제한 및 간격 고려
        """
        now = datetime.now()

        # v54.7.1: 개인화된 최적 시간 가져오기 (PromptOptimizer + FeedbackLoop)
        preferred_hours = self.config.get("preferred_hours", self.DEFAULT_UPLOAD_HOURS)
        preferred_days = self.config.get("preferred_days", self.DEFAULT_UPLOAD_DAYS)

        try:
            # 1차: PromptOptimizer에서 최적 시간 가져오기
            from utils.prompt_optimizer import get_prompt_optimizer
            optimizer = get_prompt_optimizer(self.data_dir, self.channel_type)
            upload_rec = optimizer.get_optimal_upload_time()

            if upload_rec.get("confidence", 0) > 0.5:
                preferred_hours = [upload_rec.get("recommended_hour", 18)]
                preferred_days = [upload_rec.get("recommended_day", 5)]

            # 2차: FeedbackLoop에서 학습된 시간 패턴 보강
            try:
                from utils.feedback_loop import get_feedback_loop
                feedback = get_feedback_loop(self.data_dir, self.channel_type)
                if not feedback:
                    raise ValueError("FeedbackLoop 인스턴스 없음")
                learnings = feedback.get_learnings_summary()

                # 고성과 업로드 시간이 있으면 추가
                best_times = learnings.get("best_upload_times", [])
                if best_times:
                    # "토요일 18시 (CTR 5.2%)" 형식에서 시간 추출
                    import re
                    for time_str in best_times[:2]:  # 상위 2개만
                        match = re.search(r'(\d+)시', time_str)
                        if match:
                            hour = int(match.group(1))
                            if hour not in preferred_hours:
                                preferred_hours.append(hour)
            except (ValueError, TypeError) as e:
                logger.debug(f"FeedbackLoop 학습 시간 패턴 파싱 실패: {e}")

        except (ValueError, TypeError) as e:
            logger.debug(f"스케줄 파싱 실패: {e}")

        # 오늘부터 7일간 확인
        min_gap_hours = self.config.get("min_gap_hours", 4)
        daily_limit = self.config.get("daily_upload_limit", 5)

        for day_offset in range(7):
            check_date = now + timedelta(days=day_offset)

            # 선호 요일 확인
            if check_date.weekday() not in preferred_days:
                continue

            # 해당 날짜의 기존 예약 확인
            scheduled_on_date = self._get_scheduled_on_date(check_date.date())
            if len(scheduled_on_date) >= daily_limit:
                continue

            # 선호 시간 중 가능한 시간 찾기
            for hour in preferred_hours:
                candidate = check_date.replace(hour=hour, minute=0, second=0, microsecond=0)

                # 과거 시간 건너뛰기
                if candidate <= now:
                    continue

                # 기존 예약과 간격 확인
                if self._check_time_gap(candidate, min_gap_hours):
                    # v62.40: 업로드 타이밍 jitter — 분/초 랜덤화 (봇 패턴 감지 방지)
                    # 매 업로드가 정시(:00:00)에 예약되면 자동화 감지 리스크 증가
                    jitter_min = random.randint(0, 59)
                    jitter_sec = random.randint(0, 59)
                    candidate = candidate.replace(minute=jitter_min, second=jitter_sec)
                    logger.debug(f"[UploadScheduler] jitter 적용: {candidate.strftime('%H:%M:%S')}")
                    return candidate

        # 적절한 시간이 없으면 내일 기본 시간 (v62.40: jitter 포함)
        tomorrow = now + timedelta(days=1)
        jitter_min = random.randint(0, 59)
        jitter_sec = random.randint(0, 59)
        return tomorrow.replace(hour=18, minute=jitter_min, second=jitter_sec, microsecond=0)

    def _get_scheduled_on_date(self, date) -> List[Dict]:
        """특정 날짜에 예약된 항목 조회 (v54.7.3: Thread Safe)"""
        with self._lock:
            result = []
            for item in self.queue:
                if item["scheduled_time"]:
                    scheduled = datetime.fromisoformat(item["scheduled_time"])
                    if scheduled.date() == date:
                        result.append(item)
            return result

    def _check_time_gap(self, candidate: datetime, min_gap_hours: int) -> bool:
        """기존 예약과 시간 간격 확인 (v54.7.3: Thread Safe)"""
        with self._lock:
            for item in self.queue:
                if item["scheduled_time"]:
                    scheduled = datetime.fromisoformat(item["scheduled_time"])
                    gap = abs((candidate - scheduled).total_seconds() / 3600)
                    if gap < min_gap_hours:
                        return False
            return True

    # =========================================================
    # 업로드 실행
    # =========================================================

    def _execute_upload(self, item: Dict[str, Any]) -> bool:
        """
        업로드 실행

        Returns:
            성공 여부
        """
        from utils.youtube_uploader import YouTubeUploader

        item["status"] = UploadStatus.UPLOADING.value
        self._save_queue()

        self._log(f"업로드 시작: {item['title']}")

        if self.on_upload_start:
            self.on_upload_start(item)

        try:
            uploader = YouTubeUploader(channel_type=self.channel_type)

            if not uploader.authenticate():
                raise Exception("YouTube 인증 실패")

            # 업로드 실행
            # v54.7.3: YouTubeUploader는 'category' 파라미터 사용 (category_id 아님)
            result = uploader.upload_video(
                video_path=item["video_path"],
                title=item["title"],
                description=item["description"],
                tags=item["tags"],
                thumbnail_path=item["thumbnail_path"],
                category=item.get("category", "24"),
                privacy=(item.get("metadata") or {}).get("privacy", "private"),
                contains_synthetic_media=(item.get("metadata") or {}).get("contains_synthetic_media", True),
                verified_true_story=(item.get("metadata") or {}).get("verified_true_story", False),
                channel_mode=(item.get("metadata") or {}).get("channel_mode", self.channel_type),
            )

            # v54.7.3: YouTubeUploader는 'video_id' 키를 사용함
            if result and result.get("video_id"):
                # 성공
                item["status"] = UploadStatus.COMPLETED.value
                item["video_id"] = result["video_id"]
                item["uploaded_at"] = datetime.now().isoformat()
                item["error"] = None

                self._save_queue()
                self._log(f"업로드 완료: {item['title']} (ID: {result['video_id']})")

                # v54.5: 피드백 루프에 자동 등록 (반드시 실행)
                self._register_to_feedback_loop(result["video_id"], item)

                # v54.7.3: 콜백 예외 처리 - 콜백 실패해도 업로드 성공 처리는 유지
                if self.on_upload_complete:
                    try:
                        self.on_upload_complete(item)
                    except Exception as cb_err:
                        self._log(f"업로드 완료 콜백 오류 (무시됨): {cb_err}", "warning")

                return True
            else:
                raise Exception("업로드 응답에 video_id가 없음")

        except Exception as e:
            error_msg = redact_sensitive_text(e)
            item["error"] = error_msg
            item["retry_count"] += 1

            max_retries = self.config.get("max_retries", 3)

            if item["retry_count"] < max_retries:
                # 재시도 예약
                retry_delay = self.config.get("retry_delay_minutes", 30)
                retry_time = datetime.now() + timedelta(minutes=retry_delay)
                item["scheduled_time"] = retry_time.isoformat()
                item["status"] = UploadStatus.SCHEDULED.value
                self._log(f"업로드 실패, 재시도 예약: {item['title']} ({item['retry_count']}/{max_retries})", "warning")
            else:
                # 최대 재시도 초과
                item["status"] = UploadStatus.FAILED.value
                self._log(f"업로드 최종 실패: {item['title']} - {error_msg}", "error")

            self._save_queue()

            # v54.7.3: 콜백 예외 처리
            if self.on_upload_fail:
                try:
                    self.on_upload_fail(item, error_msg)
                except Exception as cb_err:
                    self._log(f"업로드 실패 콜백 오류 (무시됨): {cb_err}", "warning")

            return False

    def _register_to_feedback_loop(self, video_id: str, item: Dict[str, Any]) -> bool:
        """
        피드백 루프에 영상 등록 - v54.5
        v54.7.3: 등록 실패 시 item에 플래그 추가하여 추적
                 None 반환 처리 추가

        Returns:
            bool: 등록 성공 여부
        """
        try:
            from utils.feedback_loop import get_feedback_loop
            feedback = get_feedback_loop(self.data_dir, self.channel_type)

            # v54.7.3: None 체크 (InstanceManager 순환 참조 대응)
            if feedback is None:
                self._log("FeedbackLoop 인스턴스 없음 (순환 참조 가능)", "warning")
                item["feedback_registered"] = False
                item["feedback_error"] = "FeedbackLoop 인스턴스 None"
                self._save_queue()
                return False

            feedback.register_video(
                video_id=video_id,
                title=item.get("title", ""),
                upload_time=datetime.now(),
                metadata={
                    "tags": item.get("tags", []),
                    "category": item.get("category", ""),
                    "scheduled_time": item.get("scheduled_time"),
                }
            )
            self._log(f"피드백 루프 등록: {item['title']}")
            item["feedback_registered"] = True
            return True

        except Exception as e:
            safe_error = redact_sensitive_text(e)
            self._log(f"피드백 루프 등록 실패: {safe_error}", "warning")
            # v54.7.3: 등록 실패를 item에 기록하여 나중에 재시도 가능
            item["feedback_registered"] = False
            item["feedback_error"] = safe_error
            self._save_queue()  # 상태 저장
            return False

    def upload_now(self, item_id: str) -> bool:
        """즉시 업로드 (v54.7.3: Thread Safe)"""
        with self._lock:
            target_item = None
            for item in self.queue:
                if item["id"] == item_id:
                    target_item = item
                    break

        if target_item:
            return self._execute_upload(target_item)
        return False

    # =========================================================
    # 스케줄러
    # =========================================================

    def start_scheduler(self):
        """스케줄러 시작"""
        # v54.7.1: 이중 시작 방지 강화
        if self._scheduler_running:
            self._log("스케줄러가 이미 실행 중", "warning")
            return

        # 스레드가 아직 살아있으면 대기
        if self._scheduler_thread and self._scheduler_thread.is_alive():
            self._log("이전 스케줄러 스레드가 아직 실행 중", "warning")
            return

        self._scheduler_running = True
        self._scheduler_thread = threading.Thread(target=self._scheduler_loop, daemon=True)
        self._scheduler_thread.start()
        self._log("업로드 스케줄러 시작")

    def stop_scheduler(self):
        """스케줄러 중지"""
        self._scheduler_running = False
        if self._scheduler_thread:
            self._scheduler_thread.join(timeout=5)
        self._log("업로드 스케줄러 중지")

    def _scheduler_loop(self):
        """스케줄러 루프"""
        check_interval = self.config.get("check_interval_minutes", 5) * 60

        while self._scheduler_running:
            try:
                self._check_scheduled_uploads()
            except Exception as e:
                self._log(f"스케줄러 오류: {e}", "error")

            # 대기
            for _ in range(check_interval):
                if not self._scheduler_running:
                    break
                time.sleep(1)

    def _check_scheduled_uploads(self):
        """예약된 업로드 확인 및 실행 (v54.7.3: Thread Safe)"""
        now = datetime.now()

        # v54.7.3: lock으로 큐 복사 후 순회 (race condition 방지)
        with self._lock:
            queue_snapshot = list(self.queue)

        for item in queue_snapshot:
            if item["status"] != UploadStatus.SCHEDULED.value:
                continue

            if not item["scheduled_time"]:
                continue

            scheduled = datetime.fromisoformat(item["scheduled_time"])

            # 예약 시간이 지났으면 업로드 실행
            if scheduled <= now:
                self._log(f"예약 업로드 실행: {item['title']}")
                self._execute_upload(item)

    def is_scheduler_running(self) -> bool:
        """스케줄러 실행 상태"""
        return self._scheduler_running

    # =========================================================
    # 상태 조회
    # =========================================================

    def get_status(self) -> Dict[str, Any]:
        """현재 상태 조회 (v54.7.3: Thread Safe)"""
        with self._lock:
            queue_snapshot = list(self.queue)

        pending = sum(1 for item in queue_snapshot if item["status"] == UploadStatus.PENDING.value)
        scheduled = sum(1 for item in queue_snapshot if item["status"] == UploadStatus.SCHEDULED.value)
        uploading = sum(1 for item in queue_snapshot if item["status"] == UploadStatus.UPLOADING.value)
        completed = sum(1 for item in queue_snapshot if item["status"] == UploadStatus.COMPLETED.value)
        failed = sum(1 for item in queue_snapshot if item["status"] == UploadStatus.FAILED.value)

        # 다음 예약
        next_scheduled = None
        for item in queue_snapshot:
            if item["status"] == UploadStatus.SCHEDULED.value and item["scheduled_time"]:
                scheduled_time = datetime.fromisoformat(item["scheduled_time"])
                if next_scheduled is None or scheduled_time < next_scheduled:
                    next_scheduled = scheduled_time

        return {
            "scheduler_running": self._scheduler_running,
            "queue_count": len(self.queue),
            "pending": pending,
            "scheduled": scheduled,
            "uploading": uploading,
            "completed": completed,
            "failed": failed,
            "next_scheduled": next_scheduled.isoformat() if next_scheduled else None,
            "next_scheduled_display": next_scheduled.strftime("%m/%d %H:%M") if next_scheduled else "없음",
            "today_uploaded": self._get_today_upload_count(),
            "daily_limit": self.config.get("daily_upload_limit", 5),
        }

    def _get_today_upload_count(self) -> int:
        """오늘 업로드된 영상 수"""
        today = datetime.now().date()
        count = 0

        for item in self.queue + self.history:
            if item.get("uploaded_at"):
                uploaded = datetime.fromisoformat(item["uploaded_at"])
                if uploaded.date() == today:
                    count += 1

        return count

    def get_config(self) -> Dict[str, Any]:
        """설정 조회"""
        return self.config.copy()

    def update_config(self, new_config: Dict[str, Any]):
        """설정 업데이트"""
        self.config.update(new_config)
        self._save_config()
        self._log("설정 업데이트됨")

    def get_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        """업로드 히스토리 조회"""
        return self.history[-limit:]


# 전역 인스턴스 (v54.7.1: InstanceManager 사용)
def get_upload_scheduler(data_dir: str = None, channel_type: str = "daily_life_toon") -> UploadScheduler:
    """UploadScheduler 인스턴스 가져오기 (InstanceManager 경유)"""
    try:
        from utils.instance_manager import get_instance_manager
        return get_instance_manager().get_upload_scheduler(data_dir, channel_type)
    except ImportError:
        # 폴백: 직접 생성
        if data_dir is None:
            try:
                from config.settings import config
                data_dir = config.DATA_DIR
            except Exception:
                data_dir = "data"
        return UploadScheduler(data_dir, channel_type)
