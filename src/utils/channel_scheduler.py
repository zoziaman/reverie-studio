# src/utils/channel_scheduler.py
"""
v56: 멀티채널 스케줄러

100개 채널의 Utopia 엔진을 효율적으로 관리하고 스케줄링

기능:
1. 채널 우선순위 기반 작업 순서 결정
2. 리소스 관리 (GPU 메모리, API 호출 제한)
3. 자동 로드 밸런싱
4. 채널별 성과 추적 및 우선순위 자동 조절

"100개 채널을 혼자서 관리하는 AI 매니저"
"""
import os
import json
import logging
import threading
import time
from typing import Dict, Any, List, Optional, Tuple, Callable
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from enum import Enum
from queue import PriorityQueue
import heapq

logger = logging.getLogger(__name__)


class SchedulerState(Enum):
    """스케줄러 상태"""
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"


class TaskType(Enum):
    """작업 유형"""
    GENERATE = "generate"           # 영상 생성
    UPLOAD = "upload"               # 업로드
    OPTIMIZE = "optimize"           # 썸네일 최적화
    ANALYZE = "analyze"             # 성과 분석
    MAINTENANCE = "maintenance"     # 유지보수 (토큰 갱신 등)


class TaskPriority(Enum):
    """작업 우선순위"""
    CRITICAL = 0    # 즉시 실행 (토큰 만료 등)
    HIGH = 1        # 높음 (업로드 예약 시간 임박)
    NORMAL = 2      # 보통
    LOW = 3         # 낮음 (최적화, 분석)
    BACKGROUND = 4  # 백그라운드


@dataclass(order=True)
class ScheduledTask:
    """스케줄된 작업"""
    priority: int                           # 정렬용 우선순위
    scheduled_time: datetime = field(compare=False)  # 예정 시간
    channel_id: str = field(compare=False)  # 채널 ID
    task_type: str = field(compare=False)   # 작업 유형
    task_data: Dict = field(default_factory=dict, compare=False)  # 작업 데이터
    task_id: str = field(default="", compare=False)  # 작업 ID
    retry_count: int = field(default=0, compare=False)  # 재시도 횟수
    max_retries: int = field(default=3, compare=False)  # 최대 재시도

    def __post_init__(self):
        if not self.task_id:
            self.task_id = f"{self.channel_id}_{self.task_type}_{datetime.now().strftime('%Y%m%d%H%M%S')}"


@dataclass
class ChannelStatus:
    """채널 상태"""
    channel_id: str
    display_name: str
    channel_type: str
    is_active: bool = True
    priority: int = 50                      # 0-100 (높을수록 우선)
    last_activity: Optional[str] = None     # 마지막 활동 시간
    pending_tasks: int = 0                  # 대기 중인 작업 수
    videos_today: int = 0                   # 오늘 생성한 영상 수
    daily_limit: int = 3                    # 일일 생성 제한
    error_count: int = 0                    # 연속 오류 횟수
    performance_score: float = 50.0         # 성과 점수 (자동 조절용)


class ChannelScheduler:
    """
    멀티채널 스케줄러

    100개 채널의 작업을 효율적으로 스케줄링하고 실행
    """

    # 리소스 제한
    MAX_CONCURRENT_TASKS = 2        # 동시 실행 작업 수 (GPU 메모리 고려)
    MAX_DAILY_VIDEOS_TOTAL = 50     # 전체 일일 영상 생성 제한
    API_RATE_LIMIT_DELAY = 2.0      # API 호출 간 최소 딜레이 (초)

    # 자동 우선순위 조절
    AUTO_PRIORITY_ENABLED = True
    PRIORITY_BOOST_THRESHOLD = 70   # 성과 점수 이상이면 우선순위 상승
    PRIORITY_DROP_THRESHOLD = 30    # 성과 점수 이하면 우선순위 하락

    def __init__(self, data_dir: str):
        """
        Args:
            data_dir: 데이터 디렉토리
        """
        self.data_dir = data_dir
        self.state_path = os.path.join(data_dir, "scheduler_state.json")

        self._lock = threading.RLock()
        self._state = SchedulerState.IDLE
        self._task_queue: List[ScheduledTask] = []  # 힙 큐
        self._running_tasks: Dict[str, ScheduledTask] = {}
        self._channel_status: Dict[str, ChannelStatus] = {}

        # 스레드
        self._scheduler_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # 콜백
        self._task_handlers: Dict[str, Callable] = {}
        self._on_task_complete: Optional[Callable] = None
        self._on_task_error: Optional[Callable] = None

        # 통계
        self._stats = {
            'tasks_completed': 0,
            'tasks_failed': 0,
            'videos_generated_today': 0,
            'last_reset_date': datetime.now().strftime('%Y-%m-%d')
        }

        self._load_state()
        self._init_channels()

    def _init_channels(self):
        """채널 레지스트리에서 채널 정보 로드"""
        try:
            from utils.channel_registry import get_channel_registry
            registry = get_channel_registry(self.data_dir)
            channels = registry.get_all_channels()

            for channel in channels:
                if channel.channel_id not in self._channel_status:
                    self._channel_status[channel.channel_id] = ChannelStatus(
                        channel_id=channel.channel_id,
                        display_name=channel.display_name,
                        channel_type=channel.channel_type,
                        is_active=channel.is_active,
                        priority=channel.priority
                    )

            logger.info(f"채널 {len(self._channel_status)}개 로드됨")

        except Exception as e:
            logger.warning(f"채널 레지스트리 로드 실패: {e}")

    def _load_state(self):
        """상태 로드"""
        if os.path.exists(self.state_path):
            try:
                with open(self.state_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self._stats = data.get('stats', self._stats)

                    # 날짜 변경 시 일일 통계 리셋
                    today = datetime.now().strftime('%Y-%m-%d')
                    if self._stats.get('last_reset_date') != today:
                        self._stats['videos_generated_today'] = 0
                        self._stats['last_reset_date'] = today

                    # 채널 상태 복원
                    for ch_id, ch_data in data.get('channels', {}).items():
                        self._channel_status[ch_id] = ChannelStatus(**ch_data)

            except Exception as e:
                logger.error(f"상태 로드 실패: {e}")

    def _save_state(self):
        """상태 저장"""
        with self._lock:
            data = {
                'stats': self._stats,
                'channels': {k: asdict(v) for k, v in self._channel_status.items()},
                'updated_at': datetime.now().isoformat()
            }
            try:
                os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
                with open(self.state_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.error(f"상태 저장 실패: {e}")

    # =========================================================
    # 작업 관리
    # =========================================================

    def schedule_task(
        self,
        channel_id: str,
        task_type: TaskType,
        scheduled_time: datetime = None,
        priority: TaskPriority = TaskPriority.NORMAL,
        task_data: Dict = None
    ) -> str:
        """
        작업 스케줄링

        Args:
            channel_id: 채널 ID
            task_type: 작업 유형
            scheduled_time: 예정 시간 (None이면 즉시)
            priority: 우선순위
            task_data: 작업 데이터

        Returns:
            작업 ID
        """
        if scheduled_time is None:
            scheduled_time = datetime.now()

        task = ScheduledTask(
            priority=priority.value,
            scheduled_time=scheduled_time,
            channel_id=channel_id,
            task_type=task_type.value,
            task_data=task_data or {}
        )

        with self._lock:
            heapq.heappush(self._task_queue, task)

            # 채널 상태 업데이트
            if channel_id in self._channel_status:
                self._channel_status[channel_id].pending_tasks += 1

        logger.info(f"작업 스케줄됨: {task.task_id} ({task_type.value})")
        return task.task_id

    def cancel_task(self, task_id: str) -> bool:
        """작업 취소"""
        with self._lock:
            for i, task in enumerate(self._task_queue):
                if task.task_id == task_id:
                    self._task_queue.pop(i)
                    heapq.heapify(self._task_queue)

                    if task.channel_id in self._channel_status:
                        self._channel_status[task.channel_id].pending_tasks -= 1

                    logger.info(f"작업 취소됨: {task_id}")
                    return True
        return False

    def get_pending_tasks(self, channel_id: str = None) -> List[Dict]:
        """대기 중인 작업 목록"""
        with self._lock:
            tasks = self._task_queue.copy()

            if channel_id:
                tasks = [t for t in tasks if t.channel_id == channel_id]

            return [
                {
                    'task_id': t.task_id,
                    'channel_id': t.channel_id,
                    'task_type': t.task_type,
                    'scheduled_time': t.scheduled_time.isoformat(),
                    'priority': t.priority
                }
                for t in sorted(tasks, key=lambda x: (x.priority, x.scheduled_time))
            ]

    # =========================================================
    # 스케줄러 실행
    # =========================================================

    def start(self):
        """스케줄러 시작"""
        if self._state == SchedulerState.RUNNING:
            logger.warning("스케줄러가 이미 실행 중입니다")
            return

        self._stop_event.clear()
        self._state = SchedulerState.RUNNING

        self._scheduler_thread = threading.Thread(
            target=self._scheduler_loop,
            daemon=True,
            name="ChannelScheduler"
        )
        self._scheduler_thread.start()
        logger.info("멀티채널 스케줄러 시작됨")

    def stop(self):
        """스케줄러 중지"""
        if self._state != SchedulerState.RUNNING:
            return

        self._state = SchedulerState.STOPPING
        self._stop_event.set()

        if self._scheduler_thread:
            self._scheduler_thread.join(timeout=10)

        self._state = SchedulerState.IDLE
        self._save_state()
        logger.info("멀티채널 스케줄러 중지됨")

    def pause(self):
        """일시 정지"""
        if self._state == SchedulerState.RUNNING:
            self._state = SchedulerState.PAUSED
            logger.info("스케줄러 일시 정지")

    def resume(self):
        """재개"""
        if self._state == SchedulerState.PAUSED:
            self._state = SchedulerState.RUNNING
            logger.info("스케줄러 재개")

    def _scheduler_loop(self):
        """스케줄러 메인 루프"""
        while not self._stop_event.is_set():
            try:
                if self._state == SchedulerState.PAUSED:
                    time.sleep(1)
                    continue

                # 실행할 작업 찾기
                task = self._get_next_task()

                if task:
                    self._execute_task(task)
                    time.sleep(self.API_RATE_LIMIT_DELAY)
                else:
                    time.sleep(5)  # 대기 중인 작업 없으면 5초 대기

            except Exception as e:
                logger.error(f"스케줄러 루프 오류: {e}")
                time.sleep(10)

    def _get_next_task(self) -> Optional[ScheduledTask]:
        """다음 실행할 작업 가져오기"""
        with self._lock:
            # 동시 실행 제한 체크
            if len(self._running_tasks) >= self.MAX_CONCURRENT_TASKS:
                return None

            # 일일 생성 제한 체크
            if self._stats['videos_generated_today'] >= self.MAX_DAILY_VIDEOS_TOTAL:
                # 생성 작업은 스킵, 다른 작업은 허용
                pass

            now = datetime.now()

            # 힙에서 실행 가능한 작업 찾기
            while self._task_queue:
                task = self._task_queue[0]

                # 예정 시간 확인
                if task.scheduled_time > now:
                    return None  # 아직 시간 안 됨

                # 채널 활성화 확인
                ch_status = self._channel_status.get(task.channel_id)
                if ch_status and not ch_status.is_active:
                    heapq.heappop(self._task_queue)
                    continue

                # 일일 제한 확인 (생성 작업)
                if task.task_type == TaskType.GENERATE.value:
                    if self._stats['videos_generated_today'] >= self.MAX_DAILY_VIDEOS_TOTAL:
                        heapq.heappop(self._task_queue)
                        continue

                    if ch_status and ch_status.videos_today >= ch_status.daily_limit:
                        heapq.heappop(self._task_queue)
                        continue

                # 작업 가져오기
                heapq.heappop(self._task_queue)
                return task

            return None

    def _execute_task(self, task: ScheduledTask):
        """작업 실행"""
        task_id = task.task_id
        self._running_tasks[task_id] = task

        try:
            logger.info(f"작업 실행: {task_id} ({task.task_type})")

            # 핸들러 호출
            handler = self._task_handlers.get(task.task_type)
            if handler:
                result = handler(task.channel_id, task.task_data)

                # 성공 처리
                self._on_task_success(task, result)
            else:
                logger.warning(f"핸들러 없음: {task.task_type}")

        except Exception as e:
            logger.error(f"작업 실행 오류: {task_id} - {e}")
            self._on_task_failure(task, str(e))

        finally:
            self._running_tasks.pop(task_id, None)

    def _on_task_success(self, task: ScheduledTask, result: Any):
        """작업 성공 처리"""
        with self._lock:
            self._stats['tasks_completed'] += 1

            ch_status = self._channel_status.get(task.channel_id)
            if ch_status:
                ch_status.pending_tasks = max(0, ch_status.pending_tasks - 1)
                ch_status.last_activity = datetime.now().isoformat()
                ch_status.error_count = 0

                if task.task_type == TaskType.GENERATE.value:
                    ch_status.videos_today += 1
                    self._stats['videos_generated_today'] += 1

            self._save_state()

        if self._on_task_complete:
            self._on_task_complete(task, result)

    def _on_task_failure(self, task: ScheduledTask, error: str):
        """작업 실패 처리"""
        with self._lock:
            self._stats['tasks_failed'] += 1

            ch_status = self._channel_status.get(task.channel_id)
            if ch_status:
                ch_status.pending_tasks = max(0, ch_status.pending_tasks - 1)
                ch_status.error_count += 1

                # 연속 오류 시 우선순위 하락
                if ch_status.error_count >= 3:
                    ch_status.priority = max(0, ch_status.priority - 10)

            # 재시도
            if task.retry_count < task.max_retries:
                task.retry_count += 1
                task.scheduled_time = datetime.now() + timedelta(minutes=5 * task.retry_count)
                heapq.heappush(self._task_queue, task)
                logger.info(f"작업 재시도 예약: {task.task_id} ({task.retry_count}/{task.max_retries})")

            self._save_state()

        if self._on_task_error:
            self._on_task_error(task, error)

    # =========================================================
    # 핸들러 등록
    # =========================================================

    def register_handler(self, task_type: TaskType, handler: Callable):
        """작업 핸들러 등록"""
        self._task_handlers[task_type.value] = handler
        logger.info(f"핸들러 등록됨: {task_type.value}")

    def on_complete(self, callback: Callable):
        """완료 콜백 등록"""
        self._on_task_complete = callback

    def on_error(self, callback: Callable):
        """오류 콜백 등록"""
        self._on_task_error = callback

    # =========================================================
    # 채널 관리
    # =========================================================

    def set_channel_priority(self, channel_id: str, priority: int):
        """채널 우선순위 설정"""
        with self._lock:
            if channel_id in self._channel_status:
                self._channel_status[channel_id].priority = max(0, min(100, priority))
                self._save_state()

    def set_channel_active(self, channel_id: str, is_active: bool):
        """채널 활성화/비활성화"""
        with self._lock:
            if channel_id in self._channel_status:
                self._channel_status[channel_id].is_active = is_active
                self._save_state()

    def set_daily_limit(self, channel_id: str, limit: int):
        """일일 생성 제한 설정"""
        with self._lock:
            if channel_id in self._channel_status:
                self._channel_status[channel_id].daily_limit = max(0, limit)
                self._save_state()

    def update_performance_score(self, channel_id: str, score: float):
        """성과 점수 업데이트 (자동 우선순위 조절)"""
        with self._lock:
            if channel_id not in self._channel_status:
                return

            ch = self._channel_status[channel_id]
            ch.performance_score = score

            if self.AUTO_PRIORITY_ENABLED:
                if score >= self.PRIORITY_BOOST_THRESHOLD:
                    ch.priority = min(100, ch.priority + 5)
                elif score <= self.PRIORITY_DROP_THRESHOLD:
                    ch.priority = max(0, ch.priority - 5)

            self._save_state()

    def get_channel_status(self, channel_id: str) -> Optional[Dict]:
        """채널 상태 조회"""
        with self._lock:
            if channel_id in self._channel_status:
                return asdict(self._channel_status[channel_id])
        return None

    def get_all_channel_status(self) -> List[Dict]:
        """모든 채널 상태"""
        with self._lock:
            return [asdict(ch) for ch in self._channel_status.values()]

    # =========================================================
    # 상태 조회
    # =========================================================

    def get_status(self) -> Dict[str, Any]:
        """스케줄러 상태"""
        with self._lock:
            return {
                'state': self._state.value,
                'pending_tasks': len(self._task_queue),
                'running_tasks': len(self._running_tasks),
                'total_channels': len(self._channel_status),
                'active_channels': sum(1 for ch in self._channel_status.values() if ch.is_active),
                'stats': self._stats.copy(),
                'running_task_ids': list(self._running_tasks.keys())
            }

    def get_stats(self) -> Dict[str, Any]:
        """통계"""
        with self._lock:
            return {
                **self._stats,
                'pending_tasks': len(self._task_queue),
                'channels_by_priority': self._get_channels_by_priority()
            }

    def _get_channels_by_priority(self) -> Dict[str, int]:
        """우선순위별 채널 수"""
        result = {'high': 0, 'medium': 0, 'low': 0}
        for ch in self._channel_status.values():
            if ch.priority >= 70:
                result['high'] += 1
            elif ch.priority >= 30:
                result['medium'] += 1
            else:
                result['low'] += 1
        return result


# 싱글톤
_channel_scheduler: Optional[ChannelScheduler] = None
_channel_scheduler_lock = threading.Lock()


def get_channel_scheduler(data_dir: str = None) -> ChannelScheduler:
    """ChannelScheduler 싱글톤 (Thread-safe)"""
    global _channel_scheduler

    if _channel_scheduler is None:
        with _channel_scheduler_lock:
            if _channel_scheduler is None:  # Double-check locking
                if data_dir is None:
                    data_dir = "data"
                _channel_scheduler = ChannelScheduler(data_dir)

    return _channel_scheduler
