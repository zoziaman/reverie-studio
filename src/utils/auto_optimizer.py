# src/utils/auto_optimizer.py
"""
v54.1: 자동 최적화 관리자 (AutoOptimizer)

YouTube 성과 분석 → 자동 개선 실행

기능:
1. 저조한 영상 자동 감지
2. 썸네일 자동 교체
3. 프롬프트 패턴 학습
4. 스케줄 기반 자동 실행

"유토피아" 시스템의 핵심 두뇌
"""
import os
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Callable
import threading
import time

from utils.secret_redaction import redact_sensitive_text

logger = logging.getLogger(__name__)


class AutoOptimizer:
    """
    자동 최적화 관리자

    분석 → 판단 → 실행 자동화

    v54.7.1: Thread Safety 강화
    """

    def __init__(self, data_dir: str, channel_type: str = "daily_life_toon"):
        self.data_dir = data_dir
        self.channel_type = channel_type

        # v54.7.1: Thread Safety를 위한 lock
        self._lock = threading.Lock()

        # 설정 파일 경로
        self.config_path = os.path.join(data_dir, "auto_optimizer_config.json")
        self.history_path = os.path.join(data_dir, "auto_optimizer_history.json")
        self.patterns_path = os.path.join(data_dir, "learned_patterns.json")

        # 설정 로드
        self.config = self._load_config()
        self.history = self._load_history()
        self.patterns = self._load_patterns()

        # 스케줄러
        self._scheduler_thread = None
        self._scheduler_running = False

        # 콜백
        self.on_thumbnail_regenerate: Optional[Callable] = None  # 썸네일 재생성 콜백
        self.on_log: Optional[Callable] = None  # 로그 콜백

    def _load_config(self) -> Dict[str, Any]:
        """설정 로드"""
        default_config = {
            "enabled": True,
            "check_interval_hours": 6,  # 6시간마다 체크
            "thumbnail_change": {
                "enabled": True,
                "min_age_hours": 24,  # 업로드 후 24시간 이후
                "max_age_hours": 168,  # 7일 이내
                "ctr_threshold": 2.0,  # CTR 2% 미만이면 교체
                "min_views_for_check": 50,  # 최소 50회 이상 조회된 영상만
                "max_changes_per_video": 3,  # 영상당 최대 3번까지만 교체
            },
            "title_optimization": {
                "enabled": False,  # 제목 변경은 기본 비활성화 (위험)
                "min_age_hours": 48,
            },
            "pattern_learning": {
                "enabled": True,
                "min_videos_for_pattern": 10,  # 최소 10개 영상 데이터 필요
            },
            "notifications": {
                "on_change": True,
                "on_error": True,
            }
        }

        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                    # 기본값과 병합
                    for key, value in loaded.items():
                        if isinstance(value, dict) and key in default_config:
                            default_config[key].update(value)
                        else:
                            default_config[key] = value
            except Exception as e:
                logger.warning(f"설정 로드 실패, 기본값 사용: {e}")

        return default_config

    def _save_config(self):
        """설정 저장"""
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"설정 저장 실패: {e}")

    def _load_history(self) -> List[Dict[str, Any]]:
        """히스토리 로드"""
        if os.path.exists(self.history_path):
            try:
                with open(self.history_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, FileNotFoundError, OSError) as e:
                logger.debug(f"히스토리 로드 실패: {e}")
        return []

    def _save_history(self):
        """히스토리 저장"""
        try:
            with open(self.history_path, 'w', encoding='utf-8') as f:
                json.dump(self.history[-1000:], f, ensure_ascii=False, indent=2)  # 최근 1000개만 유지
        except Exception as e:
            logger.error(f"히스토리 저장 실패: {e}")

    def _load_patterns(self) -> Dict[str, Any]:
        """학습된 패턴 로드"""
        default_patterns = {
            "successful_thumbnails": [],  # 성공한 썸네일 스타일
            "failed_thumbnails": [],  # 실패한 썸네일 스타일
            "optimal_upload_times": [],  # 최적 업로드 시간
            "top_performing_keywords": [],  # 고성과 키워드
            "low_performing_keywords": [],  # 저성과 키워드
        }

        if os.path.exists(self.patterns_path):
            try:
                with open(self.patterns_path, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                    default_patterns.update(loaded)
            except (json.JSONDecodeError, FileNotFoundError, OSError) as e:
                logger.debug(f"패턴 로드 실패: {e}")

        return default_patterns

    def _save_patterns(self):
        """패턴 저장"""
        try:
            with open(self.patterns_path, 'w', encoding='utf-8') as f:
                json.dump(self.patterns, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"패턴 저장 실패: {e}")

    def _log(self, message: str, level: str = "info"):
        """로그 기록 및 콜백"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"[{timestamp}] [{level.upper()}] {message}"

        if level == "error":
            logger.error(message)
        elif level == "warning":
            logger.warning(message)
        else:
            logger.info(message)

        if self.on_log:
            self.on_log(log_entry)

    def _record_action(self, action_type: str, video_id: str, details: Dict):
        """액션 기록 (v54.7.1: Thread Safe)"""
        with self._lock:
            self.history.append({
                "timestamp": datetime.now().isoformat(),
                "action_type": action_type,
                "video_id": video_id,
                "channel_type": self.channel_type,
                "details": details
            })
            self._save_history()

    # =========================================================
    # 핵심 기능: 분석 및 자동 실행
    # =========================================================

    def run_optimization_cycle(self) -> Dict[str, Any]:
        """
        최적화 사이클 실행

        1. 분석 필요 영상 조회
        2. 썸네일 교체 필요 영상 처리
        3. 패턴 학습 업데이트
        4. 결과 리턴

        Returns:
            {
                'analyzed': int,
                'thumbnails_changed': int,
                'patterns_updated': bool,
                'errors': [],
                'details': []
            }
        """
        from utils.youtube_analytics import YouTubeAnalytics
        from utils.youtube_uploader import YouTubeUploader

        result = {
            'timestamp': datetime.now().isoformat(),
            'analyzed': 0,
            'thumbnails_changed': 0,
            'patterns_updated': False,
            'errors': [],
            'details': []
        }

        if not self.config.get('enabled', True):
            self._log("AutoOptimizer가 비활성화 상태입니다.", "warning")
            return result

        self._log(f"최적화 사이클 시작 (채널: {self.channel_type})")

        try:
            # 1. Analytics 초기화
            analytics = YouTubeAnalytics(self.data_dir, self.channel_type)

            if not analytics.is_authenticated():
                self._log("YouTube 인증 필요", "error")
                result['errors'].append("YouTube 인증 필요")
                return result

            # 2. 썸네일 교체 필요 영상 조회
            thumb_config = self.config.get('thumbnail_change', {})

            if thumb_config.get('enabled', True):
                videos_to_change = analytics.get_videos_needing_thumbnail_change(
                    ctr_threshold=thumb_config.get('ctr_threshold', 2.0),
                    min_impressions=thumb_config.get('min_views_for_check', 50),
                    min_age_hours=thumb_config.get('min_age_hours', 24),
                    max_age_hours=thumb_config.get('max_age_hours', 168)
                )

                result['analyzed'] = len(videos_to_change)

                # 3. 각 영상 처리
                for video in videos_to_change:
                    video_id = video['video_id']
                    title = video['title']
                    reason = video['reason']

                    # 이미 많이 교체했는지 확인
                    change_count = self._get_change_count(video_id)
                    max_changes = thumb_config.get('max_changes_per_video', 3)

                    if change_count >= max_changes:
                        self._log(f"[{title}] 최대 교체 횟수 도달 ({change_count}/{max_changes})", "warning")
                        continue

                    # 썸네일 교체 실행
                    change_result = self._execute_thumbnail_change(video_id, title, reason)

                    if change_result.get('success'):
                        result['thumbnails_changed'] += 1
                        result['details'].append({
                            'video_id': video_id,
                            'title': title,
                            'action': 'thumbnail_changed',
                            'reason': reason
                        })
                    else:
                        result['errors'].append(f"{title}: {change_result.get('error', '알 수 없는 오류')}")

            # 4. 패턴 학습
            if self.config.get('pattern_learning', {}).get('enabled', True):
                self._update_patterns(analytics)
                result['patterns_updated'] = True

            self._log(f"최적화 사이클 완료: 분석 {result['analyzed']}개, 교체 {result['thumbnails_changed']}개")

        except Exception as e:
            safe_error = redact_sensitive_text(e)
            self._log(f"최적화 사이클 오류: {safe_error}", "error")
            result['errors'].append(safe_error)

        return result

    def _get_change_count(self, video_id: str) -> int:
        """해당 영상의 썸네일 교체 횟수"""
        return sum(1 for h in self.history
                   if h.get('video_id') == video_id
                   and h.get('action_type') == 'thumbnail_change')

    def _execute_thumbnail_change(
        self,
        video_id: str,
        title: str,
        reason: str
    ) -> Dict[str, Any]:
        """
        썸네일 교체 실행

        1. 새 썸네일 생성 (콜백 사용)
        2. YouTube에 업로드
        3. 기록 저장
        """
        from utils.youtube_uploader import YouTubeUploader
        from utils.youtube_analytics import YouTubeAnalytics

        self._log(f"[{title}] 썸네일 교체 시작 - 사유: {reason}")

        try:
            # 1. 새 썸네일 생성
            if self.on_thumbnail_regenerate:
                new_thumb_path = self.on_thumbnail_regenerate(video_id, title)
            else:
                # 기본 경로에서 대체 썸네일 찾기
                new_thumb_path = self._find_alternative_thumbnail(video_id)

            if not new_thumb_path or not os.path.exists(new_thumb_path):
                return {'success': False, 'error': '대체 썸네일을 찾을 수 없음'}

            # 2. YouTube에 업로드
            uploader = YouTubeUploader(channel_type=self.channel_type)
            result = uploader.update_thumbnail(video_id, new_thumb_path)

            if result.get('success'):
                # v54.7.2: FeedbackLoop을 썸네일 변경 이력의 유일한 소스로 사용
                # AutoOptimizer는 더 이상 자체 history에 썸네일 변경을 기록하지 않음
                # 대신 FeedbackLoop에만 기록하여 데이터 일관성 보장

                # v54.7.3: InstanceManager를 통해 FeedbackLoop 접근 (순환 참조 방지)
                # 데이터 일관성을 위해 FeedbackLoop에만 기록 (폴백 없음)
                history_recorded = False
                try:
                    from utils.instance_manager import get_instance_manager
                    manager = get_instance_manager()
                    feedback_loop = manager.get_feedback_loop(self.data_dir, self.channel_type)
                    if feedback_loop:
                        feedback_loop.record_thumbnail_change(
                            video_id=video_id,
                            old_thumbnail='',  # 이전 썸네일 (필요시 조회)
                            new_thumbnail=new_thumb_path,
                            reason=reason
                        )
                        logger.info(f"썸네일 변경 이력 기록: {video_id}")
                        history_recorded = True
                    else:
                        # v54.7.3: 순환 참조 감지 - 폴백 제거, 로깅만 수행
                        # 데이터 분산 방지를 위해 자체 기록하지 않음
                        logger.error(f"FeedbackLoop 순환 참조로 썸네일 변경 이력 미기록: {video_id}")
                except Exception as fb_err:
                    # v54.7.3: 예외 발생 시에도 폴백 제거 - 로깅만 수행
                    logger.error(f"FeedbackLoop 기록 실패 (이력 미기록): {video_id} - {fb_err}")

                self._log(f"[{title}] 썸네일 교체 완료!")
                return {'success': True, 'history_recorded': history_recorded}
            else:
                return {'success': False, 'error': result.get('error', '업로드 실패')}

        except Exception as e:
            safe_error = redact_sensitive_text(e)
            self._log(f"[{title}] 썸네일 교체 실패: {safe_error}", "error")
            return {'success': False, 'error': safe_error}

    def _find_alternative_thumbnail(self, video_id: str) -> Optional[str]:
        """대체 썸네일 찾기"""
        thumb_dir = os.path.join(self.data_dir, "thumbnails")

        if not os.path.exists(thumb_dir):
            return None

        # 프로젝트별 썸네일 검색
        # 패턴: {project_name}_REAL.jpg, {project_name}_ART.jpg
        for filename in os.listdir(thumb_dir):
            if filename.endswith(('_REAL.jpg', '_ART.jpg')):
                # 현재 사용중인 것과 다른 스타일 선택
                if '_REAL' in filename:
                    alt_filename = filename.replace('_REAL', '_ART')
                else:
                    alt_filename = filename.replace('_ART', '_REAL')

                alt_path = os.path.join(thumb_dir, alt_filename)
                if os.path.exists(alt_path):
                    return alt_path

        return None

    def _update_patterns(self, analytics):
        """성과 패턴 학습 업데이트"""
        try:
            # 최근 영상 데이터 가져오기
            recent_videos = analytics.get_recent_videos(max_results=30)

            if len(recent_videos) < 10:
                return  # 데이터 부족

            # 조회수 기준 상위/하위 구분
            sorted_videos = sorted(recent_videos, key=lambda x: x.get('view_count', 0), reverse=True)

            top_videos = sorted_videos[:5]
            bottom_videos = sorted_videos[-5:]

            # 키워드 패턴 분석 (제목에서 추출)
            top_keywords = self._extract_keywords([v['title'] for v in top_videos])
            bottom_keywords = self._extract_keywords([v['title'] for v in bottom_videos])

            # 패턴 업데이트
            self.patterns['top_performing_keywords'] = top_keywords[:20]
            self.patterns['low_performing_keywords'] = bottom_keywords[:20]

            # 업로드 시간 패턴
            # NOTE: 시간대별 성과 분석 미구현. 타임스탬프 로그 축적 후 구현 예정

            self._save_patterns()
            self._log("패턴 학습 업데이트 완료")

        except Exception as e:
            self._log(f"패턴 학습 오류: {e}", "warning")

    def _extract_keywords(self, titles: List[str]) -> List[str]:
        """제목에서 키워드 추출"""
        import re
        keywords = []

        for title in titles:
            # 한글/영문 단어만 추출
            words = re.findall(r'[가-힣a-zA-Z]+', title)
            keywords.extend([w for w in words if len(w) >= 2])

        # 빈도 계산
        from collections import Counter
        counter = Counter(keywords)

        # 상위 키워드 반환
        return [word for word, count in counter.most_common(20)]

    # =========================================================
    # 스케줄러
    # =========================================================

    def start_scheduler(self):
        """자동 스케줄러 시작"""
        if self._scheduler_running:
            self._log("스케줄러가 이미 실행 중입니다.", "warning")
            return

        self._scheduler_running = True
        self._scheduler_thread = threading.Thread(target=self._scheduler_loop, daemon=True)
        self._scheduler_thread.start()
        self._log("자동 최적화 스케줄러 시작")

    def stop_scheduler(self):
        """스케줄러 중지"""
        self._scheduler_running = False
        if self._scheduler_thread:
            self._scheduler_thread.join(timeout=5)
        self._log("자동 최적화 스케줄러 중지")

    def _scheduler_loop(self):
        """스케줄러 루프"""
        interval_hours = self.config.get('check_interval_hours', 6)
        interval_seconds = interval_hours * 3600

        while self._scheduler_running:
            try:
                # 최적화 실행
                result = self.run_optimization_cycle()

                # 결과 로깅
                if result.get('thumbnails_changed', 0) > 0:
                    self._log(f"자동 최적화: {result['thumbnails_changed']}개 썸네일 교체됨")

            except Exception as e:
                self._log(f"스케줄러 오류: {e}", "error")

            # 대기
            for _ in range(interval_seconds):
                if not self._scheduler_running:
                    break
                time.sleep(1)

    # =========================================================
    # 유틸리티
    # =========================================================

    def get_status(self) -> Dict[str, Any]:
        """현재 상태 조회 (v54.7.1: Thread Safe)"""
        with self._lock:
            return {
                'enabled': self.config.get('enabled', True),
                'scheduler_running': self._scheduler_running,
                'channel_type': self.channel_type,
                'check_interval_hours': self.config.get('check_interval_hours', 6),
                'total_actions': len(self.history),
                'recent_actions': list(self.history[-10:]),  # 복사본 반환
                'patterns_learned': {
                    'top_keywords': len(self.patterns.get('top_performing_keywords', [])),
                    'low_keywords': len(self.patterns.get('low_performing_keywords', [])),
                }
            }

    def get_config(self) -> Dict[str, Any]:
        """현재 설정 조회 (v54.7.1: Thread Safe)"""
        with self._lock:
            return self.config.copy()

    def update_config(self, new_config: Dict[str, Any]):
        """설정 업데이트"""
        for key, value in new_config.items():
            if isinstance(value, dict) and key in self.config:
                self.config[key].update(value)
            else:
                self.config[key] = value

        self._save_config()
        self._log("설정 업데이트됨")

    def set_enabled(self, enabled: bool):
        """활성화/비활성화"""
        self.config['enabled'] = enabled
        self._save_config()

        if enabled:
            self._log("AutoOptimizer 활성화됨")
        else:
            self._log("AutoOptimizer 비활성화됨")

    def execute_thumbnail_change(
        self,
        video_id: str,
        title: str = "",
        reason: str = "수동 요청"
    ) -> Dict[str, Any]:
        """
        썸네일 교체 실행 (Public API)

        FeedbackLoop 등 외부 모듈에서 호출 가능

        Args:
            video_id: YouTube 영상 ID
            title: 영상 제목 (로깅용)
            reason: 교체 사유

        Returns:
            {'success': bool, 'error': str (실패시)}
        """
        return self._execute_thumbnail_change(video_id, title, reason)

    def get_improvement_suggestions(self) -> List[Dict[str, Any]]:
        """개선 제안 조회 (학습된 패턴 기반)"""
        suggestions = []

        # 고성과 키워드 제안
        top_keywords = self.patterns.get('top_performing_keywords', [])
        if top_keywords:
            suggestions.append({
                'type': 'keyword',
                'priority': 'high',
                'title': '고성과 키워드 활용',
                'description': f"다음 키워드가 포함된 영상이 좋은 성과를 보입니다: {', '.join(top_keywords[:5])}"
            })

        # 저성과 키워드 경고
        low_keywords = self.patterns.get('low_performing_keywords', [])
        if low_keywords:
            suggestions.append({
                'type': 'keyword',
                'priority': 'medium',
                'title': '피해야 할 키워드',
                'description': f"다음 키워드는 성과가 낮았습니다: {', '.join(low_keywords[:5])}"
            })

        # 썸네일 교체 기록 분석
        thumb_changes = [h for h in self.history if h.get('action_type') == 'thumbnail_change']
        if len(thumb_changes) > 3:
            suggestions.append({
                'type': 'thumbnail',
                'priority': 'medium',
                'title': '썸네일 스타일 재검토',
                'description': f"최근 {len(thumb_changes)}번의 썸네일 교체가 있었습니다. 기본 썸네일 스타일을 재검토해보세요."
            })

        return suggestions


# 전역 인스턴스 (v54.7.1: InstanceManager 사용)
def get_auto_optimizer(data_dir: str = None, channel_type: str = "daily_life_toon") -> AutoOptimizer:
    """AutoOptimizer 인스턴스 가져오기 (InstanceManager 경유)"""
    try:
        from utils.instance_manager import get_instance_manager
        return get_instance_manager().get_auto_optimizer(data_dir, channel_type)
    except ImportError:
        # 폴백: 직접 생성
        if data_dir is None:
            try:
                from config.settings import config
                data_dir = config.DATA_DIR
            except Exception:
                data_dir = "data"
        return AutoOptimizer(data_dir, channel_type)
