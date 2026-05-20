# src/utils/batch_queue.py
"""
배치 큐 관리자
- 대기열 관리
- 작업 추가/삭제/순서 변경
- 상태 추적

v57.6.8: Thread Safety 추가 (_lock)
"""
import os
import json
import logging
import uuid
import threading
from datetime import datetime
from typing import Dict, Any, List, Optional
from enum import Enum

logger = logging.getLogger(__name__)

# v62.22: Atomic JSON write
try:
    from utils.crypto_utils import atomic_json_write
    _ATOMIC_WRITE = True
except ImportError:
    _ATOMIC_WRITE = False


class JobStatus(Enum):
    PENDING = "pending"      # 대기 중
    RUNNING = "running"      # 진행 중
    COMPLETED = "completed"  # 완료
    FAILED = "failed"        # 실패
    CANCELLED = "cancelled"  # 취소됨


class BatchQueue:
    """배치 큐 관리자 (Thread Safe)"""

    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self.queue_path = os.path.join(data_dir, "batch_queue.json")
        self._lock = threading.Lock()  # v57.6.8: Thread Safety
        self.queue = self._load_queue()
        self._current_job_id = None

    def _load_queue(self) -> List[Dict[str, Any]]:
        """큐 로드"""
        if os.path.exists(self.queue_path):
            try:
                with open(self.queue_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, FileNotFoundError, OSError) as e:
                logger.warning(f"큐 JSON 로드 실패: {e}")
        return []

    def _save_queue(self):
        """큐 저장 (내부용 - lock 밖에서 호출 금지, v62.22: atomic write)"""
        os.makedirs(os.path.dirname(self.queue_path), exist_ok=True)
        if _ATOMIC_WRITE:
            atomic_json_write(self.queue_path, self.queue)
        else:
            with open(self.queue_path, "w", encoding="utf-8") as f:
                json.dump(self.queue, f, ensure_ascii=False, indent=2)

    def add_job(self,
                channel: str,
                mode: str,
                topic_mode: str = "auto",
                manual_topic: str = "",
                auto_upload: bool = False,
                pack_id: str = "",
                prompt_mode: str = "enhanced",
                skip_thumbnail: bool = False,
                resume_from_checkpoint: bool = False,
                upload_privacy: str = "private") -> str:  # v58.3.2
        """
        작업 추가

        Args:
            channel: 채널 타입 (senior, horror)
            mode: 모드 (makjang, touching, horror)
            topic_mode: 주제 모드 (auto, manual)
            manual_topic: 수동 주제
            auto_upload: 자동 업로드 여부
            pack_id: v58.3 팩 ID (예: senior_makjang)
            prompt_mode: v58.3 프롬프트 모드 (enhanced, classic)
            skip_thumbnail: v58.3.2 썸네일 팝업 건너뛰기
            resume_from_checkpoint: 실패 시 체크포인트부터 재개
            upload_privacy: v58.3.2 업로드 공개 설정 (private, unlisted, public)

        Returns:
            str: 작업 ID
        """
        job_id = str(uuid.uuid4())[:8]

        job = {
            "id": job_id,
            "channel": channel,
            "mode": mode,
            "topic_mode": topic_mode,
            "manual_topic": manual_topic,
            "topic": manual_topic,
            "auto_upload": auto_upload,
            "pack_id": pack_id or f"{channel}_{mode}",  # v58.3
            "prompt_mode": prompt_mode,  # v58.3
            "skip_thumbnail": skip_thumbnail,  # v58.3.2
            "resume_from_checkpoint": resume_from_checkpoint,
            "upload_privacy": upload_privacy,  # v58.3.2
            "json_path": "",
            "project_name": "",
            "retry_count": 0,
            "retry_of": None,
            "status": JobStatus.PENDING.value,
            "created_at": datetime.now().isoformat(),
            "started_at": None,
            "completed_at": None,
            "result": None,
            "error": None
        }

        with self._lock:  # v57.6.8: Thread Safety
            self.queue.append(job)
            self._save_queue()

        return job_id

    def add_batch(self,
                  channel: str,
                  mode: str,
                  quantity: int,
                  topic_mode: str = "auto",
                  manual_topic: str = "",
                  auto_upload: bool = False,
                  pack_id: str = "",
                  prompt_mode: str = "enhanced",
                  skip_thumbnail: bool = False,
                  resume_from_checkpoint: bool = False,
                  upload_privacy: str = "private") -> List[str]:  # v58.3.2
        """
        여러 작업 일괄 추가

        Args:
            channel: 채널 타입
            mode: 모드
            quantity: 수량
            topic_mode: 주제 모드
            manual_topic: 수동 주제
            auto_upload: 자동 업로드
            pack_id: v58.3 팩 ID
            prompt_mode: v58.3 프롬프트 모드
            skip_thumbnail: v58.3.2 썸네일 팝업 건너뛰기
            resume_from_checkpoint: 실패 시 체크포인트부터 재개
            upload_privacy: v58.3.2 업로드 공개 설정

        Returns:
            List[str]: 작업 ID 목록
        """
        job_ids = []
        for i in range(quantity):
            # 수동 주제인 경우 번호 붙이기
            topic = manual_topic
            if topic_mode == "manual" and quantity > 1:
                topic = f"{manual_topic} #{i + 1}"

            job_id = self.add_job(
                channel, mode, topic_mode, topic, auto_upload,
                pack_id=pack_id, prompt_mode=prompt_mode,
                skip_thumbnail=skip_thumbnail,
                resume_from_checkpoint=resume_from_checkpoint,
                upload_privacy=upload_privacy  # v58.3.2
            )
            job_ids.append(job_id)

        return job_ids

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """작업 조회"""
        for job in self.queue:
            if job["id"] == job_id:
                return job
        return None

    def get_pending_jobs(self) -> List[Dict[str, Any]]:
        """대기 중인 작업 목록"""
        return [j for j in self.queue if j["status"] == JobStatus.PENDING.value]

    def get_next_job(self) -> Optional[Dict[str, Any]]:
        """다음 실행할 작업"""
        pending = self.get_pending_jobs()
        return pending[0] if pending else None

    def get_all_jobs(self) -> List[Dict[str, Any]]:
        """모든 작업 목록"""
        return self.queue.copy()

    def get_failed_jobs(self) -> List[Dict[str, Any]]:
        """Return failed jobs for retry UI."""
        return [j for j in self.queue if j["status"] == JobStatus.FAILED.value]

    def update_job(self, job_id: str, **updates) -> bool:
        """Update persisted metadata for an existing job."""
        if not updates:
            return False

        with self._lock:
            for job in self.queue:
                if job["id"] == job_id:
                    job.update(updates)
                    self._save_queue()
                    return True
        return False

    def start_job(self, job_id: str) -> bool:
        """작업 시작"""
        with self._lock:  # v57.6.8: Thread Safety
            for job in self.queue:
                if job["id"] == job_id:
                    job["status"] = JobStatus.RUNNING.value
                    job["started_at"] = datetime.now().isoformat()
                    self._current_job_id = job_id
                    self._save_queue()
                    return True
        return False

    def complete_job(self, job_id: str, result: Dict[str, Any] = None) -> bool:
        """작업 완료"""
        with self._lock:  # v57.6.8: Thread Safety
            for job in self.queue:
                if job["id"] == job_id:
                    job["status"] = JobStatus.COMPLETED.value
                    job["completed_at"] = datetime.now().isoformat()
                    job["result"] = result
                    if self._current_job_id == job_id:
                        self._current_job_id = None
                    self._save_queue()
                    return True
        return False

    def fail_job(self, job_id: str, error: str = None) -> bool:
        """작업 실패"""
        with self._lock:  # v57.6.8: Thread Safety
            for job in self.queue:
                if job["id"] == job_id:
                    job["status"] = JobStatus.FAILED.value
                    job["completed_at"] = datetime.now().isoformat()
                    job["error"] = error
                    if self._current_job_id == job_id:
                        self._current_job_id = None
                    self._save_queue()
                    return True
        return False

    def retry_job(self, job_id: str) -> Optional[str]:
        """Clone a failed job back into the pending queue for retry."""
        with self._lock:
            source_job = None
            for job in self.queue:
                if job["id"] == job_id:
                    source_job = job
                    break

            if not source_job or source_job["status"] != JobStatus.FAILED.value:
                return None

            new_job_id = str(uuid.uuid4())[:8]
            retry_topic = source_job.get("topic") or source_job.get("manual_topic", "")

            retry_job = {
                **source_job,
                "id": new_job_id,
                "status": JobStatus.PENDING.value,
                "created_at": datetime.now().isoformat(),
                "started_at": None,
                "completed_at": None,
                "result": None,
                "error": None,
                "resume_from_checkpoint": bool(source_job.get("resume_from_checkpoint", False)),
                "retry_count": int(source_job.get("retry_count", 0)) + 1,
                "retry_of": source_job["id"],
            }

            if retry_topic:
                retry_job["topic"] = retry_topic
                retry_job["manual_topic"] = retry_topic
                retry_job["topic_mode"] = "manual"

            source_job["retried_at"] = datetime.now().isoformat()
            source_job["retry_job_id"] = new_job_id
            self.queue.append(retry_job)
            self._save_queue()
            return new_job_id

    def cancel_job(self, job_id: str) -> bool:
        """작업 취소"""
        with self._lock:  # v57.6.8: Thread Safety
            for job in self.queue:
                if job["id"] == job_id:
                    if job["status"] == JobStatus.PENDING.value:
                        job["status"] = JobStatus.CANCELLED.value
                        self._save_queue()
                        return True
        return False

    def remove_job(self, job_id: str) -> bool:
        """작업 삭제 (완료/실패/취소된 것만)"""
        with self._lock:  # v57.6.8: Thread Safety
            for i, job in enumerate(self.queue):
                if job["id"] == job_id:
                    if job["status"] in [JobStatus.COMPLETED.value, JobStatus.FAILED.value, JobStatus.CANCELLED.value]:
                        self.queue.pop(i)
                        self._save_queue()
                        return True
        return False

    def move_job_up(self, job_id: str) -> bool:
        """작업 순서 위로"""
        with self._lock:  # v57.6.8: Thread Safety
            for i, job in enumerate(self.queue):
                if job["id"] == job_id and job["status"] == JobStatus.PENDING.value:
                    if i > 0 and self.queue[i - 1]["status"] == JobStatus.PENDING.value:
                        self.queue[i], self.queue[i - 1] = self.queue[i - 1], self.queue[i]
                        self._save_queue()
                        return True
        return False

    def move_job_down(self, job_id: str) -> bool:
        """작업 순서 아래로"""
        with self._lock:  # v57.6.8: Thread Safety
            for i, job in enumerate(self.queue):
                if job["id"] == job_id and job["status"] == JobStatus.PENDING.value:
                    if i < len(self.queue) - 1 and self.queue[i + 1]["status"] == JobStatus.PENDING.value:
                        self.queue[i], self.queue[i + 1] = self.queue[i + 1], self.queue[i]
                        self._save_queue()
                        return True
        return False

    def clear_completed(self):
        """완료된 작업들 정리"""
        with self._lock:  # v57.6.8: Thread Safety
            self.queue = [j for j in self.queue if j["status"] not in
                          [JobStatus.COMPLETED.value, JobStatus.FAILED.value, JobStatus.CANCELLED.value]]
            self._save_queue()

    def get_queue_summary(self) -> Dict[str, int]:
        """큐 요약"""
        summary = {
            "pending": 0,
            "running": 0,
            "completed": 0,
            "failed": 0,
            "cancelled": 0,
            "total": len(self.queue)
        }

        for job in self.queue:
            status = job["status"]
            if status in summary:
                summary[status] += 1

        return summary

    def get_current_job(self) -> Optional[Dict[str, Any]]:
        """현재 실행 중인 작업"""
        if self._current_job_id:
            return self.get_job(self._current_job_id)
        return None

    def is_queue_empty(self) -> bool:
        """대기열이 비었는지"""
        return len(self.get_pending_jobs()) == 0

    def cancel_all_pending(self):
        """모든 대기 중인 작업 취소"""
        for job in self.queue:
            if job["status"] == JobStatus.PENDING.value:
                job["status"] = JobStatus.CANCELLED.value
        self._save_queue()
