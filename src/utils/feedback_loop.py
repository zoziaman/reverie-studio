# src/utils/feedback_loop.py
"""
v54.7.2: 피드백 루프 시스템 (FeedbackLoop)

업로드 후 성과를 자동으로 추적하고 학습하는 시스템

기능:
1. 업로드 후 성과 자동 추적 (24시간, 48시간, 7일)
2. 성과 분석 및 패턴 학습
3. 자동 개선 제안 생성
4. 썸네일/제목 자동 교체 트리거
5. 성과 리포트 생성
6. v54.7.1: 썸네일 변경 이력 단일 소스
7. v54.7.2: Thread Safety 강화

"유토피아" 시스템의 학습 엔진
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


class PerformanceGrade(Enum):
    """성과 등급"""
    EXCELLENT = "excellent"   # 상위 10%
    GOOD = "good"             # 상위 30%
    AVERAGE = "average"       # 중간 40%
    BELOW_AVERAGE = "below"   # 하위 20%
    POOR = "poor"             # 하위 5%


class FeedbackLoop:
    """
    피드백 루프 시스템

    업로드 → 성과 추적 → 분석 → 학습 → 개선
    """

    # 추적 타임라인 (업로드 후 시간)
    TRACKING_MILESTONES = [1, 6, 24, 48, 168]  # 1시간, 6시간, 24시간, 48시간, 7일

    # 성과 기준 (CTR 기준)
    PERFORMANCE_THRESHOLDS = {
        "excellent": 8.0,  # CTR 8% 이상
        "good": 5.0,       # CTR 5% 이상
        "average": 3.0,    # CTR 3% 이상
        "below": 1.5,      # CTR 1.5% 이상
        "poor": 0,         # CTR 1.5% 미만
    }

    def __init__(self, data_dir: str, channel_type: str = "daily_life_toon"):
        self.data_dir = data_dir
        self.channel_type = channel_type

        # v54.7.2: Thread Safety를 위한 lock
        self._lock = threading.Lock()

        # 데이터 경로
        self.feedback_dir = os.path.join(data_dir, "feedback")
        os.makedirs(self.feedback_dir, exist_ok=True)

        self.tracking_path = os.path.join(self.feedback_dir, "tracking.json")
        self.analysis_path = os.path.join(self.feedback_dir, "analysis.json")
        self.learnings_path = os.path.join(self.feedback_dir, "learnings.json")

        # 데이터 로드
        self.tracking = self._load_tracking()
        self.analysis = self._load_analysis()
        self.learnings = self._load_learnings()

        # 스케줄러
        self._scheduler_running = False
        self._scheduler_thread = None
        self._check_interval = 30  # 기본값

        # 콜백
        self.on_poor_performance: Optional[Callable[[Dict], None]] = None
        self.on_milestone_reached: Optional[Callable[[str, int, Dict], None]] = None
        self.on_log: Optional[Callable[[str], None]] = None

    # =========================================================
    # 데이터 로드/저장
    # =========================================================

    def _load_tracking(self) -> Dict[str, Any]:
        """추적 데이터 로드"""
        if os.path.exists(self.tracking_path):
            try:
                with open(self.tracking_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"추적 데이터 로드 실패: {e}")
        return {"videos": {}, "last_check": None}

    def _save_tracking(self):
        """추적 데이터 저장"""
        try:
            with open(self.tracking_path, 'w', encoding='utf-8') as f:
                json.dump(self.tracking, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"추적 데이터 저장 실패: {e}")

    def _load_analysis(self) -> Dict[str, Any]:
        """분석 데이터 로드"""
        if os.path.exists(self.analysis_path):
            try:
                with open(self.analysis_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"분석 데이터 로드 실패: {e}")
        return {"total_analyzed": 0, "by_grade": {}, "trends": []}

    def _save_analysis(self):
        """분석 데이터 저장"""
        try:
            with open(self.analysis_path, 'w', encoding='utf-8') as f:
                json.dump(self.analysis, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"분석 데이터 저장 실패: {e}")

    def _load_learnings(self) -> Dict[str, Any]:
        """학습 데이터 로드"""
        if os.path.exists(self.learnings_path):
            try:
                with open(self.learnings_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"학습 데이터 로드 실패: {e}")
        return {
            "successful_patterns": [],
            "failed_patterns": [],
            "optimal_upload_times": {},
            "title_keywords_performance": {},
            "thumbnail_styles_performance": {},
        }

    def _save_learnings(self):
        """학습 데이터 저장"""
        try:
            with open(self.learnings_path, 'w', encoding='utf-8') as f:
                json.dump(self.learnings, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"학습 데이터 저장 실패: {e}")

    def _log(self, message: str, level: str = "info"):
        """로그 기록"""
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
    # 영상 추적 등록
    # =========================================================

    def register_video(
        self,
        video_id: str,
        title: str,
        upload_time: datetime = None,
        metadata: Dict = None
    ):
        """
        영상 추적 등록

        업로드 직후 호출하여 성과 추적 시작
        """
        if upload_time is None:
            upload_time = datetime.now()

        video_data = {
            "video_id": video_id,
            "title": title,
            "upload_time": upload_time.isoformat(),
            "registered_at": datetime.now().isoformat(),
            "metadata": metadata or {},
            "milestones": {},  # {hour: {views, ctr, retention, ...}}
            "current_grade": None,
            "actions_taken": [],
            "is_active": True,
        }

        self.tracking["videos"][video_id] = video_data
        self._save_tracking()

        self._log(f"영상 추적 등록: {title} ({video_id})")

        return video_data

    def unregister_video(self, video_id: str):
        """영상 추적 해제"""
        if video_id in self.tracking["videos"]:
            self.tracking["videos"][video_id]["is_active"] = False
            self._save_tracking()
            self._log(f"영상 추적 해제: {video_id}")

    # =========================================================
    # 성과 수집
    # =========================================================

    def collect_performance(self, video_id: str) -> Optional[Dict[str, Any]]:
        """
        영상 성과 수집

        YouTube Analytics API에서 성과 데이터 가져오기
        """
        try:
            from utils.youtube_analytics import YouTubeAnalytics
            analytics = YouTubeAnalytics(self.data_dir, self.channel_type)

            if not analytics.is_authenticated():
                self._log("YouTube Analytics 인증 필요", "warning")
                return None

            # v54.7.3: 올바른 메서드명 사용
            performance = analytics.get_video_ctr_and_retention(video_id)

            if performance:
                return {
                    "views": performance.get("views", 0),
                    "ctr": performance.get("ctr", 0),
                    "avg_view_duration": performance.get("avg_view_duration", 0),
                    "avg_view_percentage": performance.get("avg_view_percentage", 0),
                    "likes": performance.get("likes", 0),
                    "comments": performance.get("comments", 0),
                    "shares": performance.get("shares", 0),
                    "impressions": performance.get("impressions", 0),
                    "collected_at": datetime.now().isoformat(),
                }

        except Exception as e:
            self._log(f"성과 수집 실패 ({video_id}): {e}", "error")

        return None

    def check_milestone(self, video_id: str) -> Optional[int]:
        """
        영상의 현재 마일스톤 확인

        Returns:
            도달한 마일스톤 시간 (시간), 없으면 None
        """
        video = self.tracking["videos"].get(video_id)
        if not video or not video.get("is_active"):
            return None

        upload_time = datetime.fromisoformat(video["upload_time"])
        hours_since_upload = (datetime.now() - upload_time).total_seconds() / 3600

        # 아직 도달하지 않은 가장 가까운 마일스톤 찾기
        for milestone in self.TRACKING_MILESTONES:
            if milestone not in video.get("milestones", {}):
                if hours_since_upload >= milestone:
                    return milestone

        return None

    def record_milestone(self, video_id: str, milestone_hour: int, performance: Dict):
        """마일스톤 성과 기록 (v54.7.3: Thread Safe)"""
        with self._lock:
            if video_id not in self.tracking["videos"]:
                return

            video = self.tracking["videos"][video_id]

            if "milestones" not in video:
                video["milestones"] = {}

            video["milestones"][str(milestone_hour)] = {
                **performance,
                "recorded_at": datetime.now().isoformat(),
            }

            # 성과 등급 업데이트
            ctr = performance.get("ctr", 0)
            video["current_grade"] = self._calculate_grade(ctr)

            self._save_tracking()
            video_title = video.get('title', video_id)

        self._log(f"마일스톤 기록: {video_title} - {milestone_hour}시간 (CTR: {ctr:.2f}%)")

        # 콜백
        if self.on_milestone_reached:
            self.on_milestone_reached(video_id, milestone_hour, performance)

        # 성과 분석
        self._analyze_performance(video_id, milestone_hour, performance)

    def _calculate_grade(self, ctr: float) -> str:
        """CTR 기반 성과 등급 계산"""
        if ctr >= self.PERFORMANCE_THRESHOLDS["excellent"]:
            return PerformanceGrade.EXCELLENT.value
        elif ctr >= self.PERFORMANCE_THRESHOLDS["good"]:
            return PerformanceGrade.GOOD.value
        elif ctr >= self.PERFORMANCE_THRESHOLDS["average"]:
            return PerformanceGrade.AVERAGE.value
        elif ctr >= self.PERFORMANCE_THRESHOLDS["below"]:
            return PerformanceGrade.BELOW_AVERAGE.value
        else:
            return PerformanceGrade.POOR.value

    # =========================================================
    # 성과 분석
    # =========================================================

    def _analyze_performance(self, video_id: str, milestone_hour: int, performance: Dict):
        """성과 분석 및 학습"""
        video = self.tracking["videos"].get(video_id)
        if not video:
            return

        ctr = performance.get("ctr", 0)
        grade = video.get("current_grade")

        # 통계 업데이트
        self.analysis["total_analyzed"] = self.analysis.get("total_analyzed", 0) + 1

        if "by_grade" not in self.analysis:
            self.analysis["by_grade"] = {}

        if grade not in self.analysis["by_grade"]:
            self.analysis["by_grade"][grade] = 0
        self.analysis["by_grade"][grade] += 1

        # 트렌드 기록
        if "trends" not in self.analysis:
            self.analysis["trends"] = []

        self.analysis["trends"].append({
            "video_id": video_id,
            "title": video.get("title"),
            "milestone": milestone_hour,
            "ctr": ctr,
            "grade": grade,
            "timestamp": datetime.now().isoformat(),
        })

        # 최근 100개만 유지
        self.analysis["trends"] = self.analysis["trends"][-100:]

        self._save_analysis()

        # 학습 데이터 업데이트
        self._update_learnings(video, grade, performance)

        # 저성과 알림
        if grade in [PerformanceGrade.POOR.value, PerformanceGrade.BELOW_AVERAGE.value]:
            if milestone_hour >= 24:  # 24시간 이후
                self._handle_poor_performance(video_id, video, performance)

    def _update_learnings(self, video: Dict, grade: str, performance: Dict):
        """학습 데이터 업데이트"""
        title = video.get("title", "")
        upload_time = datetime.fromisoformat(video["upload_time"])
        metadata = video.get("metadata", {})

        # 업로드 시간 성과 기록
        hour_key = str(upload_time.hour)
        day_key = str(upload_time.weekday())
        time_key = f"{day_key}_{hour_key}"

        if "optimal_upload_times" not in self.learnings:
            self.learnings["optimal_upload_times"] = {}

        if time_key not in self.learnings["optimal_upload_times"]:
            self.learnings["optimal_upload_times"][time_key] = {
                "total": 0,
                "avg_ctr": 0,
                "videos": [],
            }

        time_data = self.learnings["optimal_upload_times"][time_key]
        time_data["total"] += 1
        time_data["avg_ctr"] = (
            (time_data["avg_ctr"] * (time_data["total"] - 1) + performance.get("ctr", 0))
            / time_data["total"]
        )
        time_data["videos"].append({
            "video_id": video["video_id"],
            "ctr": performance.get("ctr", 0),
            "grade": grade,
        })
        time_data["videos"] = time_data["videos"][-20:]  # 최근 20개만

        # 제목 키워드 성과 기록
        self._analyze_title_keywords(title, grade, performance)

        # 성공/실패 패턴 기록
        is_success = grade in [PerformanceGrade.EXCELLENT.value, PerformanceGrade.GOOD.value]

        pattern = {
            "title": title,
            "upload_hour": upload_time.hour,
            "upload_day": upload_time.weekday(),
            "ctr": performance.get("ctr", 0),
            "retention": performance.get("avg_view_percentage", 0),
            "grade": grade,
            "metadata": metadata,
            "timestamp": datetime.now().isoformat(),
        }

        if is_success:
            self.learnings["successful_patterns"].append(pattern)
            self.learnings["successful_patterns"] = self.learnings["successful_patterns"][-50:]
        else:
            self.learnings["failed_patterns"].append(pattern)
            self.learnings["failed_patterns"] = self.learnings["failed_patterns"][-50:]

        self._save_learnings()

    def _analyze_title_keywords(self, title: str, grade: str, performance: Dict):
        """제목 키워드 성과 분석"""
        import re

        # 한글/영어 단어 추출
        words = re.findall(r'[가-힣]+|[a-zA-Z]+', title)
        words = [w for w in words if len(w) >= 2]  # 2글자 이상

        if "title_keywords_performance" not in self.learnings:
            self.learnings["title_keywords_performance"] = {}

        ctr = performance.get("ctr", 0)
        is_success = grade in [PerformanceGrade.EXCELLENT.value, PerformanceGrade.GOOD.value]

        for word in words:
            if word not in self.learnings["title_keywords_performance"]:
                self.learnings["title_keywords_performance"][word] = {
                    "count": 0,
                    "total_ctr": 0,
                    "success_count": 0,
                }

            kw_data = self.learnings["title_keywords_performance"][word]
            kw_data["count"] += 1
            kw_data["total_ctr"] += ctr
            if is_success:
                kw_data["success_count"] += 1

    def _handle_poor_performance(self, video_id: str, video: Dict, performance: Dict):
        """저성과 영상 처리"""
        self._log(f"저성과 감지: {video['title']} (CTR: {performance.get('ctr', 0):.2f}%)", "warning")

        # 이미 액션을 취한 경우 스킵
        actions = video.get("actions_taken", [])
        if any(a.get("type") == "thumbnail_change" for a in actions):
            return

        # 콜백 호출
        if self.on_poor_performance:
            self.on_poor_performance({
                "video_id": video_id,
                "video": video,
                "performance": performance,
                "suggestion": "썸네일 교체 권장",
            })

    # =========================================================
    # 자동 개선
    # =========================================================

    def trigger_auto_improvement(self, video_id: str) -> Dict[str, Any]:
        """
        자동 개선 트리거

        저성과 영상에 대해 자동으로 개선 액션 실행
        """
        video = self.tracking["videos"].get(video_id)
        if not video:
            return {"success": False, "error": "영상을 찾을 수 없습니다."}

        result = {"success": False, "actions": []}

        try:
            from utils.auto_optimizer import get_auto_optimizer
            optimizer = get_auto_optimizer(self.data_dir, self.channel_type)

            # 썸네일 교체 실행 (public API 사용)
            change_result = optimizer.execute_thumbnail_change(
                video_id=video_id,
                title=video.get("title", ""),
                reason="피드백 루프 - 저성과 자동 개선"
            )

            if change_result.get("success"):
                # 액션 기록
                video["actions_taken"].append({
                    "type": "thumbnail_change",
                    "timestamp": datetime.now().isoformat(),
                    "result": change_result,
                })
                self._save_tracking()

                result["success"] = True
                result["actions"].append("thumbnail_change")
                self._log(f"자동 개선 완료: {video['title']} - 썸네일 교체")
            else:
                result["error"] = redact_sensitive_text(change_result.get("error", "썸네일 교체 실패"))

        except Exception as e:
            safe_error = redact_sensitive_text(e)
            result["error"] = safe_error
            self._log(f"자동 개선 실패: {safe_error}", "error")

        return result

    def record_thumbnail_change(
        self,
        video_id: str,
        old_thumbnail: str,
        new_thumbnail: str,
        reason: str = ""
    ):
        """
        v54.7.1: 썸네일 교체 기록 (v54.7.2: Thread Safe)

        FeedbackLoop의 추적 데이터에 썸네일 교체 이력 추가
        이 메서드가 썸네일 변경 이력의 단일 소스임
        """
        with self._lock:
            video = self.tracking["videos"].get(video_id)
            if not video:
                # 영상이 추적 중이 아닌 경우, 새로 추가
                self.tracking["videos"][video_id] = {
                    "video_id": video_id,
                    "title": "",
                    "is_active": False,  # 추적 시작 전이므로 비활성
                    "thumbnail_changes": [],
                    "added_at": datetime.now().isoformat(),
                }
                video = self.tracking["videos"][video_id]

            if "thumbnail_changes" not in video:
                video["thumbnail_changes"] = []

            video["thumbnail_changes"].append({
                "old": old_thumbnail,
                "new": new_thumbnail,
                "reason": reason,
                "changed_at": datetime.now().isoformat(),
            })

            # 최대 10개 기록 유지
            video["thumbnail_changes"] = video["thumbnail_changes"][-10:]

            self._save_tracking()

            # v54.7.3: log_title을 lock 안에서 추출 (데이터 일관성 보장)
            # _log() 자체는 lock 밖에서 실행 (I/O 지연 방지)
            log_title = video.get('title', video_id)

        self._log(f"썸네일 교체 기록: {log_title}")

    # =========================================================
    # 리포트 생성
    # =========================================================

    def generate_report(self, days: int = 7) -> Dict[str, Any]:
        """
        성과 리포트 생성

        Args:
            days: 분석 기간 (일)

        Returns:
            리포트 데이터
        """
        cutoff = datetime.now() - timedelta(days=days)

        # 기간 내 영상 필터링
        videos = []
        for vid, data in self.tracking["videos"].items():
            try:
                upload_time = datetime.fromisoformat(data["upload_time"])
                if upload_time >= cutoff:
                    videos.append(data)
            except (ValueError, TypeError) as e:
                logger.debug(f"날짜 파싱 실패: {e}")

        if not videos:
            return {
                "period_days": days,
                "total_videos": 0,
                "message": "분석할 영상이 없습니다.",
            }

        # 통계 계산
        grades = [v.get("current_grade") for v in videos if v.get("current_grade")]
        ctrs = []
        retentions = []

        for v in videos:
            milestones = v.get("milestones", {})
            if "24" in milestones:
                ctrs.append(milestones["24"].get("ctr", 0))
                retentions.append(milestones["24"].get("avg_view_percentage", 0))

        grade_counts = {}
        for g in grades:
            grade_counts[g] = grade_counts.get(g, 0) + 1

        # 최고/최저 성과 영상
        sorted_by_ctr = sorted(videos, key=lambda x: x.get("milestones", {}).get("24", {}).get("ctr", 0), reverse=True)

        report = {
            "period_days": days,
            "total_videos": len(videos),
            "grade_distribution": grade_counts,
            "average_ctr": sum(ctrs) / len(ctrs) if ctrs else 0,
            "average_retention": sum(retentions) / len(retentions) if retentions else 0,
            "best_performers": sorted_by_ctr[:3] if sorted_by_ctr else [],
            "worst_performers": sorted_by_ctr[-3:] if len(sorted_by_ctr) >= 3 else [],
            "improvements_made": sum(1 for v in videos if v.get("actions_taken")),
            "generated_at": datetime.now().isoformat(),
        }

        # 인사이트 생성
        report["insights"] = self._generate_insights(report, videos)

        return report

    def _generate_insights(self, report: Dict, videos: List) -> List[str]:
        """인사이트 생성"""
        insights = []

        avg_ctr = report.get("average_ctr", 0)
        grade_dist = report.get("grade_distribution", {})

        # CTR 인사이트
        if avg_ctr >= 5:
            insights.append(f"평균 CTR {avg_ctr:.1f}%로 우수한 성과입니다!")
        elif avg_ctr >= 3:
            insights.append(f"평균 CTR {avg_ctr:.1f}%로 양호한 수준입니다.")
        else:
            insights.append(f"평균 CTR {avg_ctr:.1f}%로 개선이 필요합니다.")

        # 등급 분포 인사이트
        excellent = grade_dist.get("excellent", 0)
        good = grade_dist.get("good", 0)
        poor = grade_dist.get("poor", 0)

        success_rate = (excellent + good) / len(videos) * 100 if videos else 0

        if success_rate >= 50:
            insights.append(f"성공률 {success_rate:.0f}%로 좋은 편입니다.")
        else:
            insights.append(f"성공률 {success_rate:.0f}%로 개선이 필요합니다.")

        # 최적 업로드 시간 인사이트
        if self.learnings.get("optimal_upload_times"):
            best_time = max(
                self.learnings["optimal_upload_times"].items(),
                key=lambda x: x[1].get("avg_ctr", 0)
            )
            day, hour = best_time[0].split("_")
            day_names = ["월", "화", "수", "목", "금", "토", "일"]
            insights.append(f"최적 업로드 시간: {day_names[int(day)]}요일 {hour}시 (평균 CTR {best_time[1]['avg_ctr']:.1f}%)")

        return insights

    def get_report_text(self, days: int = 7) -> str:
        """텍스트 형식 리포트"""
        report = self.generate_report(days)

        text = f"""
📊 성과 리포트 (최근 {days}일)
{'='*40}

📹 총 영상 수: {report.get('total_videos', 0)}개
📈 평균 CTR: {report.get('average_ctr', 0):.2f}%
⏱️ 평균 시청률: {report.get('average_retention', 0):.1f}%
🔧 개선 조치: {report.get('improvements_made', 0)}건

📊 등급 분포:
"""
        grade_names = {
            "excellent": "🏆 우수",
            "good": "👍 양호",
            "average": "📊 보통",
            "below": "⚠️ 미흡",
            "poor": "❌ 부진",
        }

        for grade, count in report.get("grade_distribution", {}).items():
            text += f"  {grade_names.get(grade, grade)}: {count}개\n"

        text += f"\n💡 인사이트:\n"
        for insight in report.get("insights", []):
            text += f"  • {insight}\n"

        text += f"\n{'='*40}\n생성: {datetime.now().strftime('%Y-%m-%d %H:%M')}"

        return text

    # =========================================================
    # 스케줄러
    # =========================================================

    def start_scheduler(self, check_interval_minutes: int = 30):
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
        self._check_interval = check_interval_minutes
        self._scheduler_thread = threading.Thread(target=self._scheduler_loop, daemon=True)
        self._scheduler_thread.start()
        self._log(f"피드백 루프 스케줄러 시작 (간격: {check_interval_minutes}분)")

    def stop_scheduler(self):
        """스케줄러 중지"""
        self._scheduler_running = False
        if self._scheduler_thread:
            self._scheduler_thread.join(timeout=5)
        self._log("피드백 루프 스케줄러 중지")

    def _scheduler_loop(self):
        """
        스케줄러 루프

        v54.7.2: 대기 로직 명확화
        - self._check_interval은 분(minutes) 단위
        - 대기 시간은 초(seconds)로 변환하여 사용
        """
        # 분 → 초 변환
        check_interval_seconds = self._check_interval * 60

        while self._scheduler_running:
            try:
                self._check_all_videos()
            except Exception as e:
                self._log(f"스케줄러 오류: {e}", "error")

            # 대기 (1초 간격으로 취소 확인하며 대기)
            for _ in range(check_interval_seconds):
                if not self._scheduler_running:
                    break
                time.sleep(1)

    def _check_all_videos(self):
        """모든 활성 영상 확인 (v54.7.3: Thread Safe)"""
        # v54.7.3: lock으로 tracking 데이터 보호
        with self._lock:
            self.tracking["last_check"] = datetime.now().isoformat()
            videos_snapshot = list(self.tracking["videos"].items())

        failed_videos = []

        for video_id, video in videos_snapshot:
            if not video.get("is_active"):
                continue

            try:
                # 마일스톤 확인
                milestone = self.check_milestone(video_id)

                if milestone:
                    # 성과 수집
                    performance = self.collect_performance(video_id)

                    if performance:
                        self.record_milestone(video_id, milestone, performance)
                    else:
                        # 수집 실패 시 재시도 횟수 기록
                        with self._lock:
                            video_data = self.tracking["videos"].get(video_id)
                            if video_data:
                                retry_count = video_data.get("_retry_count", 0) + 1
                                video_data["_retry_count"] = retry_count

                                if retry_count >= 3:
                                    # 3회 실패 시 비활성화
                                    video_data["is_active"] = False
                                    self._log(f"성과 수집 3회 실패, 추적 중지: {video_data.get('title', video_id)}", "warning")
                                else:
                                    failed_videos.append((video_id, video_data.get('title', '')))

            except Exception as e:
                self._log(f"영상 체크 오류 ({video_id}): {e}", "error")
                failed_videos.append((video_id, str(e)))

        # 실패 영상이 있으면 로깅
        if failed_videos:
            self._log(f"체크 실패 영상 {len(failed_videos)}개 (다음 사이클에 재시도)")

        with self._lock:
            self._save_tracking()

    def is_scheduler_running(self) -> bool:
        """스케줄러 실행 상태"""
        return self._scheduler_running

    # =========================================================
    # 상태 조회
    # =========================================================

    def get_status(self) -> Dict[str, Any]:
        """현재 상태 조회"""
        active_videos = sum(
            1 for v in self.tracking["videos"].values()
            if v.get("is_active")
        )

        return {
            "scheduler_running": self._scheduler_running,
            "total_tracked": len(self.tracking["videos"]),
            "active_tracking": active_videos,
            "total_analyzed": self.analysis.get("total_analyzed", 0),
            "last_check": self.tracking.get("last_check"),
            "successful_patterns_count": len(self.learnings.get("successful_patterns", [])),
            "failed_patterns_count": len(self.learnings.get("failed_patterns", [])),
        }

    def get_tracked_videos(self, active_only: bool = True) -> List[Dict[str, Any]]:
        """추적 중인 영상 목록"""
        videos = list(self.tracking["videos"].values())

        if active_only:
            videos = [v for v in videos if v.get("is_active")]

        # 최신순 정렬
        videos.sort(key=lambda x: x.get("upload_time", ""), reverse=True)

        return videos

    def get_learnings_summary(self) -> Dict[str, Any]:
        """학습 데이터 요약"""
        # 최고 성과 키워드
        keywords = self.learnings.get("title_keywords_performance", {})
        top_keywords = sorted(
            [(k, v["total_ctr"] / v["count"] if v["count"] > 0 else 0)
             for k, v in keywords.items() if v["count"] >= 3],
            key=lambda x: x[1],
            reverse=True
        )[:10]

        # 최적 업로드 시간
        times = self.learnings.get("optimal_upload_times", {})
        best_times = sorted(
            [(k, v["avg_ctr"]) for k, v in times.items() if v["total"] >= 2],
            key=lambda x: x[1],
            reverse=True
        )[:5]

        day_names = ["월", "화", "수", "목", "금", "토", "일"]
        formatted_times = []
        for time_key, ctr in best_times:
            day, hour = time_key.split("_")
            formatted_times.append(f"{day_names[int(day)]}요일 {hour}시 (CTR {ctr:.1f}%)")

        return {
            "top_keywords": top_keywords,
            "best_upload_times": formatted_times,
            "total_successful_patterns": len(self.learnings.get("successful_patterns", [])),
            "total_failed_patterns": len(self.learnings.get("failed_patterns", [])),
        }


# 전역 인스턴스 (v54.7.1: InstanceManager 사용)
def get_feedback_loop(data_dir: str = None, channel_type: str = "daily_life_toon") -> FeedbackLoop:
    """FeedbackLoop 인스턴스 가져오기 (InstanceManager 경유)"""
    try:
        from utils.instance_manager import get_instance_manager
        return get_instance_manager().get_feedback_loop(data_dir, channel_type)
    except ImportError:
        # 폴백: 직접 생성
        if data_dir is None:
            try:
                from config.settings import config
                data_dir = config.DATA_DIR
            except Exception:
                data_dir = "data"
        return FeedbackLoop(data_dir, channel_type)
