# src/utils/production_stats.py
"""
생산 통계 관리자
- 일/주/월별 생산량 추적
- 성공/실패 통계
- 채널별 통계
"""
import os
import json
import logging
import threading
from datetime import datetime, timedelta
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

# v62.22: Atomic JSON write
try:
    from utils.crypto_utils import atomic_json_write
    ATOMIC_WRITE_AVAILABLE = True
except ImportError:
    ATOMIC_WRITE_AVAILABLE = False


class ProductionStats:
    """생산 통계 관리"""

    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self.stats_path = os.path.join(data_dir, "production_stats.json")
        self._lock = threading.Lock()  # v62.22: 스레드 안전성
        self.stats = self._load_stats()

    def _load_stats(self) -> Dict[str, Any]:
        """통계 파일 로드"""
        if os.path.exists(self.stats_path):
            try:
                with open(self.stats_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, FileNotFoundError, OSError) as e:
                logger.debug(f"통계 JSON 로드 실패: {e}")

        return {
            "total": {"success": 0, "failed": 0, "total_duration_minutes": 0},
            "by_channel": {},
            "by_date": {},
            "recent_projects": []
        }

    def _save_stats(self):
        """통계 저장 (v62.22: atomic write)"""
        os.makedirs(os.path.dirname(self.stats_path), exist_ok=True)
        if ATOMIC_WRITE_AVAILABLE:
            atomic_json_write(self.stats_path, self.stats)
        else:
            with open(self.stats_path, "w", encoding="utf-8") as f:
                json.dump(self.stats, f, ensure_ascii=False, indent=2)

    def record_production(self,
                          project_name: str,
                          channel: str,
                          mode: str,
                          success: bool,
                          duration_minutes: float = 0,
                          video_path: str = "",
                          topic: str = ""):
        """
        생산 결과 기록 (v62.22: 스레드 안전)

        Args:
            project_name: 프로젝트 이름
            channel: 채널 (horror, senior)
            mode: 모드 (horror, touching, makjang)
            success: 성공 여부
            duration_minutes: 영상 길이 (분)
            video_path: 영상 경로
            topic: 주제
        """
        with self._lock:
            today = datetime.now().strftime("%Y-%m-%d")
            now = datetime.now().isoformat()

            # 전체 통계
            if success:
                self.stats["total"]["success"] += 1
                self.stats["total"]["total_duration_minutes"] += duration_minutes
            else:
                self.stats["total"]["failed"] += 1

            # 채널별 통계
            channel_key = f"{channel}_{mode}" if channel == "senior" else channel
            if channel_key not in self.stats["by_channel"]:
                self.stats["by_channel"][channel_key] = {"success": 0, "failed": 0}

            if success:
                self.stats["by_channel"][channel_key]["success"] += 1
            else:
                self.stats["by_channel"][channel_key]["failed"] += 1

            # 날짜별 통계
            if today not in self.stats["by_date"]:
                self.stats["by_date"][today] = {"success": 0, "failed": 0, "duration_minutes": 0}

            if success:
                self.stats["by_date"][today]["success"] += 1
                self.stats["by_date"][today]["duration_minutes"] += duration_minutes
            else:
                self.stats["by_date"][today]["failed"] += 1

            # 최근 프로젝트 목록 (최대 50개)
            project_info = {
                "project_name": project_name,
                "channel": channel,
                "mode": mode,
                "success": success,
                "duration_minutes": duration_minutes,
                "video_path": video_path,
                "topic": topic,
                "created_at": now
            }

            self.stats["recent_projects"].insert(0, project_info)
            self.stats["recent_projects"] = self.stats["recent_projects"][:50]

            self._save_stats()

    def get_today_stats(self) -> Dict[str, Any]:
        """오늘 통계"""
        today = datetime.now().strftime("%Y-%m-%d")
        return self.stats["by_date"].get(today, {"success": 0, "failed": 0, "duration_minutes": 0})

    def get_week_stats(self) -> Dict[str, Any]:
        """이번 주 통계"""
        today = datetime.now()
        week_start = today - timedelta(days=today.weekday())

        result = {"success": 0, "failed": 0, "duration_minutes": 0}

        for i in range(7):
            date = (week_start + timedelta(days=i)).strftime("%Y-%m-%d")
            if date in self.stats["by_date"]:
                day_stats = self.stats["by_date"][date]
                result["success"] += day_stats.get("success", 0)
                result["failed"] += day_stats.get("failed", 0)
                result["duration_minutes"] += day_stats.get("duration_minutes", 0)

        return result

    def get_month_stats(self) -> Dict[str, Any]:
        """이번 달 통계"""
        today = datetime.now()
        month_prefix = today.strftime("%Y-%m")

        result = {"success": 0, "failed": 0, "duration_minutes": 0}

        for date, day_stats in self.stats["by_date"].items():
            if date.startswith(month_prefix):
                result["success"] += day_stats.get("success", 0)
                result["failed"] += day_stats.get("failed", 0)
                result["duration_minutes"] += day_stats.get("duration_minutes", 0)

        return result

    def get_total_stats(self) -> Dict[str, Any]:
        """전체 통계"""
        return self.stats["total"]

    def get_channel_stats(self) -> Dict[str, Dict[str, int]]:
        """채널별 통계"""
        return self.stats["by_channel"]

    def get_recent_projects(self, limit: int = 10) -> List[Dict[str, Any]]:
        """최근 프로젝트 목록"""
        return self.stats["recent_projects"][:limit]

    def get_daily_trend(self, days: int = 7) -> List[Dict[str, Any]]:
        """일별 트렌드 (최근 N일)"""
        today = datetime.now()
        trend = []

        for i in range(days - 1, -1, -1):
            date = (today - timedelta(days=i)).strftime("%Y-%m-%d")
            day_stats = self.stats["by_date"].get(date, {"success": 0, "failed": 0})
            trend.append({
                "date": date,
                "day": (today - timedelta(days=i)).strftime("%a"),  # 요일
                "success": day_stats.get("success", 0),
                "failed": day_stats.get("failed", 0)
            })

        return trend

    def get_success_rate(self) -> float:
        """전체 성공률"""
        total = self.stats["total"]["success"] + self.stats["total"]["failed"]
        if total == 0:
            return 0.0
        return (self.stats["total"]["success"] / total) * 100

    def estimate_time(self, quantity: int) -> str:
        """
        예상 완료 시간 계산

        Args:
            quantity: 생산 수량

        Returns:
            str: 예상 완료 시간 문자열
        """
        # 최근 10개 프로젝트의 평균 제작 시간 계산
        recent = self.get_recent_projects(10)

        if not recent:
            # 기본값: 영상 1개당 약 15분
            avg_minutes = 15
        else:
            successful = [p for p in recent if p.get("success")]
            if successful:
                avg_minutes = sum(p.get("duration_minutes", 15) for p in successful) / len(successful)
                # 제작 시간은 영상 길이의 약 1.5배로 추정
                avg_minutes = avg_minutes * 1.5
            else:
                avg_minutes = 15

        total_minutes = avg_minutes * quantity

        if total_minutes < 60:
            return f"약 {int(total_minutes)}분"
        else:
            hours = int(total_minutes // 60)
            mins = int(total_minutes % 60)
            return f"약 {hours}시간 {mins}분"
