# src/utils/prompt_optimizer.py
"""
v54.3: 개인화된 프롬프트 최적화 시스템 (PromptOptimizer)

사용자별 채널 데이터를 분석하여 콘텐츠 생성 시 최적화된 프롬프트를 제안

기능:
1. 채널 성과 데이터 수집 및 분석
2. 고성과 패턴 추출 (제목, 키워드, 감정, 썸네일 스타일)
3. 프롬프트 자동 보정/개선 추천
4. 실시간 개인화 적용

v54.3.1: 채널 ID 기반 완전 개인화
- 카테고리가 아닌 실제 YouTube 채널 ID로 데이터 분리
- 같은 카테고리여도 채널마다 다른 최적화 적용

v57.6.8: Thread Safety 추가 (_lock)

"유토피아" 시스템의 학습 엔진
"""
import os
import json
import logging
import re
import threading
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from collections import Counter

from utils.secret_redaction import redact_sensitive_text

logger = logging.getLogger(__name__)


class PromptOptimizer:
    """
    개인화된 프롬프트 최적화 엔진

    v54.3.1: 채널 ID 기반 완전 개인화
    - 실제 YouTube 채널 ID로 데이터 분리
    - 같은 카테고리여도 채널마다 완전히 다른 최적화
    """

    # 분석에 필요한 최소 영상 수
    MIN_VIDEOS_FOR_ANALYSIS = 10

    # 고성과/저성과 구분 비율 (상위 20%, 하위 20%)
    PERFORMANCE_PERCENTILE = 0.2

    def __init__(self, data_dir: str, channel_type: str = "daily_life_toon", channel_id: str = None):
        self.data_dir = data_dir
        self.channel_type = channel_type
        self.channel_id = channel_id  # v54.3.1: 실제 YouTube 채널 ID
        self._lock = threading.Lock()  # v57.6.8: Thread Safety

        # 개인화 데이터 경로
        self.personalization_dir = os.path.join(data_dir, "personalization")
        os.makedirs(self.personalization_dir, exist_ok=True)

        # v54.3.1: 채널 ID가 있으면 채널 ID 기반, 없으면 타입 기반 (하위호환)
        if self.channel_id:
            # 채널 ID 기반 완전 개인화 (추천)
            self.channel_data_path = os.path.join(
                self.personalization_dir,
                f"channel_{self.channel_id}_optimization.json"
            )
            logger.info(f"[PromptOptimizer] 채널 ID 기반 개인화: {self.channel_id}")
        else:
            # 카테고리 기반 (하위호환, 비추천)
            self.channel_data_path = os.path.join(
                self.personalization_dir,
                f"{channel_type}_optimization_data.json"
            )
            logger.info(f"[PromptOptimizer] 카테고리 기반 (채널 ID 없음): {channel_type}")

        # 학습 데이터 로드
        self.channel_data = self._load_channel_data()

    def _load_channel_data(self) -> Dict[str, Any]:
        """채널별 학습 데이터 로드"""
        default_data = {
            "channel_type": self.channel_type,
            "channel_id": self.channel_id,        # v54.3.1: 실제 YouTube 채널 ID
            "channel_name": "",                   # v54.3.1: 채널 이름
            "last_updated": None,
            "total_videos_analyzed": 0,

            # 성과 패턴 (학습됨)
            "patterns": {
                # 제목 패턴
                "title": {
                    "high_performance_keywords": [],      # 고성과 키워드
                    "low_performance_keywords": [],       # 저성과 키워드
                    "optimal_length_range": [30, 50],     # 최적 제목 길이
                    "high_performance_formats": [],       # 고성과 제목 포맷 (예: "~하면 생기는 일")
                },

                # 감정 패턴
                "emotion": {
                    "high_performance": [],               # 고성과 감정 유형
                    "low_performance": [],                # 저성과 감정 유형
                },

                # 썸네일 패턴
                "thumbnail": {
                    "high_performance_styles": [],        # 고성과 스타일 (REAL/ART)
                    "high_performance_emotions": [],      # 고성과 표정
                    "optimal_text_length": [5, 15],       # 최적 텍스트 길이
                },

                # 스크립트 패턴
                "script": {
                    "optimal_length_range": [800, 1500],  # 최적 스크립트 길이 (음절)
                    "high_performance_hooks": [],         # 고성과 오프닝 훅
                    "high_performance_endings": [],       # 고성과 엔딩
                },

                # 업로드 시간 패턴
                "upload_time": {
                    "best_hours": [],                     # 최적 업로드 시간
                    "best_days": [],                      # 최적 업로드 요일
                },
            },

            # 성과 통계
            "stats": {
                "avg_ctr": 0.0,
                "avg_retention": 0.0,
                "avg_views_24h": 0,
                "top_video_ids": [],                      # 상위 성과 영상
                "bottom_video_ids": [],                   # 하위 성과 영상
            },

            # 원본 영상 데이터 (학습용)
            "video_records": [],                          # 최근 100개 영상 데이터
        }

        if os.path.exists(self.channel_data_path):
            try:
                with open(self.channel_data_path, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                    # 깊은 병합
                    self._deep_merge(default_data, loaded)
                    return default_data
            except Exception as e:
                logger.warning(f"채널 데이터 로드 실패: {redact_sensitive_text(e)}")

        return default_data

    def _save_channel_data(self):
        """채널 데이터 저장 (Thread Safe)"""
        with self._lock:  # v57.6.8: Thread Safety
            try:
                self.channel_data["last_updated"] = datetime.now().isoformat()
                with open(self.channel_data_path, 'w', encoding='utf-8') as f:
                    json.dump(self.channel_data, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.error(f"채널 데이터 저장 실패: {redact_sensitive_text(e)}")

    def _deep_merge(self, base: dict, update: dict):
        """딕셔너리 깊은 병합"""
        for key, value in update.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._deep_merge(base[key], value)
            else:
                base[key] = value

    # =========================================================
    # 핵심 기능 1: 데이터 수집 및 분석
    # =========================================================

    def collect_and_analyze(self, force_refresh: bool = False) -> Dict[str, Any]:
        """
        채널 데이터 수집 및 분석

        YouTube Analytics에서 데이터를 가져와 패턴을 학습
        v54.3.1: 채널 ID 자동 감지 및 개인화

        Returns:
            분석 결과 요약
        """
        from utils.youtube_analytics import YouTubeAnalytics

        result = {
            "success": False,
            "videos_analyzed": 0,
            "patterns_found": {},
            "errors": [],
            "channel_id": None
        }

        try:
            analytics = YouTubeAnalytics(self.data_dir, self.channel_type)

            if not analytics.is_authenticated():
                result["errors"].append("YouTube 인증 필요")
                return result

            # v54.3.1: 채널 ID 자동 감지 및 개인화 파일 경로 업데이트
            if not self.channel_id:
                try:
                    channel_info = analytics.get_channel_stats()
                    if channel_info and channel_info.get('channel_id'):
                        self.channel_id = channel_info['channel_id']
                        # 채널 ID 기반으로 경로 업데이트
                        self.channel_data_path = os.path.join(
                            self.personalization_dir,
                            f"channel_{self.channel_id}_optimization.json"
                        )
                        # 기존 데이터가 있으면 로드
                        self.channel_data = self._load_channel_data()
                        self.channel_data["channel_id"] = self.channel_id
                        self.channel_data["channel_name"] = channel_info.get('title', '')
                        logger.info(f"[PromptOptimizer] 채널 감지됨: {self.channel_id} ({channel_info.get('title', '')})")
                except Exception as e:
                    logger.warning(f"채널 ID 감지 실패: {redact_sensitive_text(e)}")

            result["channel_id"] = self.channel_id

            # 최근 영상 데이터 가져오기
            videos = analytics.get_recent_videos(max_results=50)

            if len(videos) < self.MIN_VIDEOS_FOR_ANALYSIS:
                result["errors"].append(f"분석에 필요한 최소 영상 수 부족 ({len(videos)}/{self.MIN_VIDEOS_FOR_ANALYSIS})")
                return result

            # 성과 지표별로 영상 분류
            classified = self._classify_videos_by_performance(videos)

            # 패턴 분석
            self._analyze_title_patterns(classified)
            self._analyze_emotion_patterns(classified)
            self._analyze_thumbnail_patterns(classified)
            self._analyze_upload_time_patterns(classified)

            # 통계 업데이트
            self._update_stats(videos)

            # 영상 기록 저장 (최근 100개)
            self.channel_data["video_records"] = videos[:100]
            self.channel_data["total_videos_analyzed"] = len(videos)

            # 저장
            self._save_channel_data()

            result["success"] = True
            result["videos_analyzed"] = len(videos)
            result["patterns_found"] = {
                "title_keywords": len(self.channel_data["patterns"]["title"]["high_performance_keywords"]),
                "emotions": len(self.channel_data["patterns"]["emotion"]["high_performance"]),
                "upload_times": len(self.channel_data["patterns"]["upload_time"]["best_hours"]),
            }

            logger.info(f"채널 분석 완료: {len(videos)}개 영상, 패턴 {sum(result['patterns_found'].values())}개 발견")

        except Exception as e:
            safe_error = redact_sensitive_text(e)
            logger.error(f"채널 분석 오류: {safe_error}")
            result["errors"].append(safe_error)

        return result

    def _classify_videos_by_performance(self, videos: List[Dict]) -> Dict[str, List[Dict]]:
        """성과별 영상 분류"""
        # 조회수 기준 정렬
        sorted_by_views = sorted(videos, key=lambda x: x.get('view_count', 0), reverse=True)

        # 상위/하위 20%
        cutoff = max(1, int(len(videos) * self.PERFORMANCE_PERCENTILE))

        return {
            "top": sorted_by_views[:cutoff],
            "bottom": sorted_by_views[-cutoff:],
            "all": videos
        }

    def _analyze_title_patterns(self, classified: Dict[str, List[Dict]]):
        """제목 패턴 분석"""
        patterns = self.channel_data["patterns"]["title"]

        # 고성과 영상 제목에서 키워드 추출
        top_keywords = self._extract_keywords([v.get('title', '') for v in classified["top"]])
        bottom_keywords = self._extract_keywords([v.get('title', '') for v in classified["bottom"]])

        # 고성과에만 있는 키워드 (저성과에 없는)
        high_only = [k for k in top_keywords if k not in bottom_keywords[:10]]
        low_only = [k for k in bottom_keywords if k not in top_keywords[:10]]

        patterns["high_performance_keywords"] = high_only[:20]
        patterns["low_performance_keywords"] = low_only[:20]

        # 제목 길이 분석
        top_lengths = [len(v.get('title', '')) for v in classified["top"]]
        if top_lengths:
            patterns["optimal_length_range"] = [
                min(top_lengths),
                max(top_lengths)
            ]

        # 제목 포맷 분석 (예: "~하면 생기는 일", "절대 ~하지 마세요")
        patterns["high_performance_formats"] = self._extract_title_formats(classified["top"])

    def _analyze_emotion_patterns(self, classified: Dict[str, List[Dict]]):
        """감정 패턴 분석"""
        patterns = self.channel_data["patterns"]["emotion"]

        # 제목에서 감정 키워드 추출
        emotion_keywords = {
            "공포": ["무서운", "소름", "공포", "귀신", "유령", "저주"],
            "충격": ["충격", "경악", "소름", "믿기힘든", "실화"],
            "미스터리": ["미스터리", "미해결", "비밀", "숨겨진", "진실"],
            "슬픔": ["슬픈", "눈물", "비극", "안타까운"],
            "분노": ["분노", "화나는", "역겨운"],
        }

        top_emotions = Counter()
        bottom_emotions = Counter()

        for video in classified["top"]:
            title = video.get('title', '')
            for emotion, keywords in emotion_keywords.items():
                if any(kw in title for kw in keywords):
                    top_emotions[emotion] += 1

        for video in classified["bottom"]:
            title = video.get('title', '')
            for emotion, keywords in emotion_keywords.items():
                if any(kw in title for kw in keywords):
                    bottom_emotions[emotion] += 1

        patterns["high_performance"] = [e for e, _ in top_emotions.most_common(3)]
        patterns["low_performance"] = [e for e, _ in bottom_emotions.most_common(3)]

    def _analyze_thumbnail_patterns(self, classified: Dict[str, List[Dict]]):
        """썸네일 패턴 분석"""
        # 실제 썸네일 스타일은 별도 메타데이터에서 분석 필요
        # 현재는 기본값 유지
        pass

    def _analyze_upload_time_patterns(self, classified: Dict[str, List[Dict]]):
        """업로드 시간 패턴 분석"""
        patterns = self.channel_data["patterns"]["upload_time"]

        top_hours = Counter()
        top_days = Counter()

        for video in classified["top"]:
            published_at = video.get('published_at', '')
            if published_at:
                try:
                    dt = datetime.fromisoformat(published_at.replace('Z', '+00:00'))
                    top_hours[dt.hour] += 1
                    top_days[dt.weekday()] += 1  # 0=월요일
                except (ValueError, TypeError) as e:
                    logger.debug(f"날짜 파싱 실패: {e}")

        # 상위 3개 시간대
        patterns["best_hours"] = [h for h, _ in top_hours.most_common(3)]
        patterns["best_days"] = [d for d, _ in top_days.most_common(3)]

    def _extract_keywords(self, titles: List[str]) -> List[str]:
        """제목에서 키워드 추출 (v54.7.1: 다국어 지원)"""
        keywords = []

        # 불용어 (제외할 단어) - 한국어 + 영어
        stopwords = {
            # 한국어 조사/접속사
            '은', '는', '이', '가', '을', '를', '에', '의', '로', '으로',
            '와', '과', '도', '만', '까지', '부터', '에서', '한', '하는',
            '그', '저', '이런', '저런', '그런', '어떤', '있는', '없는',
            '되는', '하면', '되면', '있으면', '없으면',
            # 영어 불용어
            'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been',
            'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will',
            'would', 'could', 'should', 'may', 'might', 'must', 'shall',
            'can', 'need', 'dare', 'ought', 'used', 'to', 'of', 'in',
            'for', 'on', 'with', 'at', 'by', 'from', 'as', 'into',
            'through', 'during', 'before', 'after', 'above', 'below',
            'between', 'under', 'again', 'further', 'then', 'once',
            'here', 'there', 'when', 'where', 'why', 'how', 'all',
            'each', 'few', 'more', 'most', 'other', 'some', 'such',
            'no', 'nor', 'not', 'only', 'own', 'same', 'so', 'than',
            'too', 'very', 'just', 'and', 'but', 'if', 'or', 'because',
            'this', 'that', 'these', 'those', 'what', 'which', 'who',
            'whom', 'whose', 'it', 'its', 'you', 'your', 'he', 'him',
            'his', 'she', 'her', 'we', 'our', 'they', 'them', 'their',
        }

        for title in titles:
            # 한글/영문/숫자 조합 단어 추출 (v54.7.1: 숫자 포함 단어도 추출)
            words = re.findall(r'[가-힣]+|[a-zA-Z0-9]+', title)
            for word in words:
                word_lower = word.lower()
                # 최소 2글자, 불용어 제외, 순수 숫자 제외
                if len(word) >= 2 and word_lower not in stopwords and not word.isdigit():
                    keywords.append(word_lower if word.isascii() else word)

        # 빈도순 정렬
        counter = Counter(keywords)
        return [word for word, _ in counter.most_common(30)]

    def _extract_title_formats(self, videos: List[Dict]) -> List[str]:
        """제목 포맷 패턴 추출"""
        formats = []

        # 일반적인 제목 패턴
        patterns = [
            (r'절대.+마세요', "절대 ~하지 마세요"),
            (r'.+하면.+일', "~하면 생기는 일"),
            (r'.+의\s*비밀', "~의 비밀"),
            (r'실화.+', "실화: ~"),
            (r'.+했더니', "~했더니"),
            (r'왜.+일까', "왜 ~일까"),
        ]

        format_counts = Counter()

        for video in videos:
            title = video.get('title', '')
            for pattern, format_name in patterns:
                if re.search(pattern, title):
                    format_counts[format_name] += 1

        return [f for f, _ in format_counts.most_common(5)]

    def _update_stats(self, videos: List[Dict]):
        """통계 업데이트"""
        stats = self.channel_data["stats"]

        if not videos:
            return

        # 평균 계산
        views = [v.get('view_count', 0) for v in videos]
        stats["avg_views_24h"] = sum(views) / len(views) if views else 0

        # 상위/하위 영상 ID
        sorted_videos = sorted(videos, key=lambda x: x.get('view_count', 0), reverse=True)
        stats["top_video_ids"] = [v.get('video_id') for v in sorted_videos[:5]]
        stats["bottom_video_ids"] = [v.get('video_id') for v in sorted_videos[-5:]]

    # =========================================================
    # 핵심 기능 2: 프롬프트 최적화 제안
    # =========================================================

    def optimize_title(self, original_title: str) -> Dict[str, Any]:
        """
        제목 최적화 제안

        Args:
            original_title: 원본 제목

        Returns:
            {
                'optimized_title': str,      # 최적화된 제목
                'suggestions': List[str],    # 개선 제안
                'score': float,              # 예상 성과 점수 (0-100)
                'keywords_added': List[str], # 추가된 고성과 키워드
                'keywords_avoided': List[str] # 제거된 저성과 키워드
            }
        """
        patterns = self.channel_data["patterns"]["title"]

        result = {
            "original_title": original_title,
            "optimized_title": original_title,
            "suggestions": [],
            "score": 50.0,
            "keywords_added": [],
            "keywords_avoided": []
        }

        # 1. 고성과 키워드 확인
        high_keywords = patterns.get("high_performance_keywords", [])
        low_keywords = patterns.get("low_performance_keywords", [])

        found_high = [kw for kw in high_keywords if kw in original_title]
        found_low = [kw for kw in low_keywords if kw in original_title]

        # 2. 점수 계산
        score = 50.0
        score += len(found_high) * 10  # 고성과 키워드당 +10점
        score -= len(found_low) * 5     # 저성과 키워드당 -5점

        # 제목 길이 점수
        optimal_range = patterns.get("optimal_length_range", [30, 50])
        title_len = len(original_title)
        if optimal_range[0] <= title_len <= optimal_range[1]:
            score += 10
        elif title_len < optimal_range[0]:
            result["suggestions"].append(f"제목이 짧습니다. 최적 길이: {optimal_range[0]}-{optimal_range[1]}자")
        else:
            result["suggestions"].append(f"제목이 깁니다. 최적 길이: {optimal_range[0]}-{optimal_range[1]}자")

        result["score"] = min(100, max(0, score))

        # 3. 개선 제안
        if not found_high and high_keywords:
            result["suggestions"].append(f"고성과 키워드 추가 추천: {', '.join(high_keywords[:3])}")

        if found_low:
            result["suggestions"].append(f"저성과 키워드 발견: {', '.join(found_low)}")
            result["keywords_avoided"] = found_low

        # 4. 최적화된 제목 생성 (간단한 버전)
        optimized = original_title

        # 저성과 키워드가 있으면 고성과 키워드로 대체 시도
        for low_kw in found_low[:1]:  # 첫 번째만
            if high_keywords:
                for high_kw in high_keywords[:3]:
                    if high_kw not in optimized:
                        # 단순 대체 (실제로는 문맥 고려 필요)
                        # optimized = optimized.replace(low_kw, high_kw)
                        result["suggestions"].append(f"'{low_kw}' 대신 '{high_kw}' 사용 고려")
                        break

        result["optimized_title"] = optimized
        result["keywords_added"] = found_high

        return result

    def optimize_thumbnail_prompt(
        self,
        title: str,
        sub_title: str,
        category: str,
        current_prompt: str = ""
    ) -> Dict[str, Any]:
        """
        썸네일 프롬프트 최적화

        Args:
            title: 메인 제목
            sub_title: 서브 제목
            category: 카테고리
            current_prompt: 현재 프롬프트 (있으면)

        Returns:
            최적화된 프롬프트 및 제안
        """
        patterns = self.channel_data["patterns"]["thumbnail"]
        emotion_patterns = self.channel_data["patterns"]["emotion"]

        result = {
            "optimized_prompt": current_prompt,
            "suggestions": [],
            "recommended_style": "REAL",  # 기본값
            "recommended_emotion": "fear",
        }

        # 1. 스타일 추천
        high_styles = patterns.get("high_performance_styles", [])
        if high_styles:
            result["recommended_style"] = high_styles[0]

        # 2. 감정 추천
        high_emotions = emotion_patterns.get("high_performance", [])
        if high_emotions:
            emotion_map = {
                "공포": "fear",
                "충격": "shock",
                "미스터리": "mystery",
                "슬픔": "sadness",
            }
            result["recommended_emotion"] = emotion_map.get(high_emotions[0], "fear")

        # 3. 텍스트 길이 제안
        optimal_text = patterns.get("optimal_text_length", [5, 15])
        if len(sub_title) < optimal_text[0]:
            result["suggestions"].append(f"서브 제목이 짧습니다. 권장: {optimal_text[0]}-{optimal_text[1]}자")
        elif len(sub_title) > optimal_text[1]:
            result["suggestions"].append(f"서브 제목이 깁니다. 권장: {optimal_text[0]}-{optimal_text[1]}자")

        # 4. 프롬프트 개선
        prompt_additions = []

        # 고성과 감정 반영
        if result["recommended_emotion"] == "fear":
            prompt_additions.append("intense fear expression")
        elif result["recommended_emotion"] == "shock":
            prompt_additions.append("shocked and terrified expression")

        if current_prompt:
            result["optimized_prompt"] = current_prompt
            if prompt_additions:
                result["optimized_prompt"] += ", " + ", ".join(prompt_additions)

        return result

    def optimize_script_prompt(
        self,
        title: str,
        category: str,
        base_prompt: str = ""
    ) -> Dict[str, Any]:
        """
        스크립트 생성 프롬프트 최적화

        Args:
            title: 제목
            category: 카테고리
            base_prompt: 기본 프롬프트

        Returns:
            최적화된 프롬프트 및 제안
        """
        patterns = self.channel_data["patterns"]["script"]
        title_patterns = self.channel_data["patterns"]["title"]

        result = {
            "optimized_prompt": base_prompt,
            "suggestions": [],
            "recommended_hooks": [],
            "recommended_length": 1000,
        }

        # 1. 최적 길이 추천
        length_range = patterns.get("optimal_length_range", [800, 1500])
        result["recommended_length"] = (length_range[0] + length_range[1]) // 2

        # 2. 오프닝 훅 추천
        high_hooks = patterns.get("high_performance_hooks", [])
        if high_hooks:
            result["recommended_hooks"] = high_hooks[:3]
            result["suggestions"].append(f"효과적인 오프닝: {', '.join(high_hooks[:2])}")

        # 3. 고성과 키워드 포함 권장
        high_keywords = title_patterns.get("high_performance_keywords", [])
        if high_keywords:
            result["suggestions"].append(f"스토리에 포함하면 좋은 요소: {', '.join(high_keywords[:5])}")

        # 4. 프롬프트 보강
        if base_prompt:
            additions = []

            # 길이 가이드
            additions.append(f"스크립트 길이는 {result['recommended_length']}자 내외로 작성")

            # 훅 가이드
            if result["recommended_hooks"]:
                additions.append(f"오프닝에서 청자의 관심을 끄는 훅 사용")

            result["optimized_prompt"] = base_prompt + "\n\n[최적화 가이드]\n- " + "\n- ".join(additions)

        return result

    def get_optimal_upload_time(self) -> Dict[str, Any]:
        """
        최적 업로드 시간 추천

        Returns:
            {
                'recommended_hour': int,      # 추천 시간 (0-23)
                'recommended_day': int,       # 추천 요일 (0=월요일)
                'confidence': float,          # 신뢰도 (0-1)
                'reason': str                 # 이유
            }
        """
        patterns = self.channel_data["patterns"]["upload_time"]

        best_hours = patterns.get("best_hours", [])
        best_days = patterns.get("best_days", [])

        result = {
            "recommended_hour": 18,  # 기본값: 오후 6시
            "recommended_day": 5,    # 기본값: 토요일
            "confidence": 0.3,
            "reason": "기본 추천 (데이터 부족)"
        }

        if best_hours:
            result["recommended_hour"] = best_hours[0]
            result["confidence"] += 0.3

        if best_days:
            result["recommended_day"] = best_days[0]
            result["confidence"] += 0.3

        if best_hours and best_days:
            day_names = ["월", "화", "수", "목", "금", "토", "일"]
            result["reason"] = f"고성과 영상 분석 결과: {day_names[best_days[0]]}요일 {best_hours[0]}시 업로드 추천"
            result["confidence"] = min(0.9, result["confidence"])

        return result

    # =========================================================
    # 핵심 기능 3: 전체 프로젝트 최적화
    # =========================================================

    def optimize_project(
        self,
        title: str,
        sub_title: str,
        category: str,
        script_prompt: str = "",
        thumbnail_prompt: str = ""
    ) -> Dict[str, Any]:
        """
        프로젝트 전체 최적화

        새 콘텐츠 생성 전 호출하여 모든 요소를 최적화

        Returns:
            {
                'title': {...},           # 제목 최적화 결과
                'thumbnail': {...},       # 썸네일 최적화 결과
                'script': {...},          # 스크립트 최적화 결과
                'upload_time': {...},     # 업로드 시간 추천
                'overall_score': float,   # 전체 예상 점수
                'warnings': [],           # 경고 메시지
            }
        """
        result = {
            "title": self.optimize_title(title),
            "thumbnail": self.optimize_thumbnail_prompt(title, sub_title, category, thumbnail_prompt),
            "script": self.optimize_script_prompt(title, category, script_prompt),
            "upload_time": self.get_optimal_upload_time(),
            "overall_score": 0.0,
            "warnings": [],
            "has_enough_data": self.channel_data["total_videos_analyzed"] >= self.MIN_VIDEOS_FOR_ANALYSIS
        }

        # 전체 점수 계산
        title_score = result["title"]["score"]
        upload_confidence = result["upload_time"]["confidence"] * 100

        result["overall_score"] = (title_score + upload_confidence) / 2

        # 경고
        if not result["has_enough_data"]:
            result["warnings"].append(
                f"학습 데이터 부족: {self.channel_data['total_videos_analyzed']}/{self.MIN_VIDEOS_FOR_ANALYSIS}개 영상"
            )

        if result["title"]["keywords_avoided"]:
            result["warnings"].append("제목에 저성과 키워드가 포함되어 있습니다")

        return result

    def record_video_performance(
        self,
        video_id: str,
        title: str,
        views: int,
        ctr: float,
        retention: float,
        metadata: Dict = None
    ):
        """
        영상 성과 기록 (수동 학습용)

        사용자가 직접 영상 성과를 입력하여 학습에 반영
        """
        record = {
            "video_id": video_id,
            "title": title,
            "view_count": views,
            "ctr": ctr,
            "retention": retention,
            "recorded_at": datetime.now().isoformat(),
            "metadata": metadata or {}
        }

        # 기록 추가
        self.channel_data["video_records"].append(record)

        # 최근 100개만 유지
        if len(self.channel_data["video_records"]) > 100:
            self.channel_data["video_records"] = self.channel_data["video_records"][-100:]

        self._save_channel_data()

        logger.info(f"영상 성과 기록 완료: {title}")

    # =========================================================
    # 유틸리티
    # =========================================================

    def get_learning_status(self) -> Dict[str, Any]:
        """학습 상태 조회"""
        patterns = self.channel_data["patterns"]

        return {
            "channel_type": self.channel_type,
            "channel_id": self.channel_data.get("channel_id"),       # v54.3.1
            "channel_name": self.channel_data.get("channel_name"),   # v54.3.1
            "last_updated": self.channel_data.get("last_updated"),
            "total_videos_analyzed": self.channel_data["total_videos_analyzed"],
            "has_enough_data": self.channel_data["total_videos_analyzed"] >= self.MIN_VIDEOS_FOR_ANALYSIS,
            "is_personalized": bool(self.channel_data.get("channel_id")),  # v54.3.1: 진정한 개인화 여부
            "patterns": {
                "title_keywords": len(patterns["title"]["high_performance_keywords"]),
                "emotions": len(patterns["emotion"]["high_performance"]),
                "upload_hours": len(patterns["upload_time"]["best_hours"]),
                "title_formats": len(patterns["title"]["high_performance_formats"]),
            },
            "stats": self.channel_data["stats"]
        }

    def get_recommendations_summary(self) -> str:
        """학습된 패턴 기반 추천 요약 (텍스트)"""
        patterns = self.channel_data["patterns"]

        # v54.3.1: 채널 정보 표시
        channel_name = self.channel_data.get("channel_name", "")
        channel_id = self.channel_data.get("channel_id", "")

        if channel_name:
            header = f"📊 [{channel_name}] 개인화 최적화"
        elif channel_id:
            header = f"📊 [{channel_id[:12]}...] 개인화 최적화"
        else:
            header = "📊 개인화 최적화 추천 요약 (공용)"

        lines = [header, "=" * 40]

        if not channel_id:
            lines.append("⚠️ 채널 분석을 실행하면 완전한 개인화가 적용됩니다.")
            lines.append("")

        # 제목 추천
        high_kw = patterns["title"]["high_performance_keywords"]
        if high_kw:
            lines.append(f"\n📌 고성과 키워드: {', '.join(high_kw[:5])}")

        low_kw = patterns["title"]["low_performance_keywords"]
        if low_kw:
            lines.append(f"⚠️ 피해야 할 키워드: {', '.join(low_kw[:5])}")

        formats = patterns["title"]["high_performance_formats"]
        if formats:
            lines.append(f"\n🏷️ 효과적인 제목 포맷:")
            for fmt in formats[:3]:
                lines.append(f"   • {fmt}")

        # 감정 추천
        emotions = patterns["emotion"]["high_performance"]
        if emotions:
            lines.append(f"\n😱 고성과 감정: {', '.join(emotions)}")

        # 업로드 시간
        hours = patterns["upload_time"]["best_hours"]
        days = patterns["upload_time"]["best_days"]
        day_names = ["월", "화", "수", "목", "금", "토", "일"]

        if hours:
            lines.append(f"\n⏰ 최적 업로드 시간: {hours[0]}시")
        if days:
            lines.append(f"📅 최적 업로드 요일: {day_names[days[0]]}요일")

        return "\n".join(lines)

    def export_patterns(self) -> Dict[str, Any]:
        """학습된 패턴 내보내기"""
        return {
            "exported_at": datetime.now().isoformat(),
            "channel_type": self.channel_type,
            "patterns": self.channel_data["patterns"],
            "stats": self.channel_data["stats"],
        }

    def import_patterns(self, data: Dict[str, Any]):
        """패턴 가져오기 (다른 채널에서)"""
        if "patterns" in data:
            self._deep_merge(self.channel_data["patterns"], data["patterns"])
            self._save_channel_data()
            logger.info("패턴 가져오기 완료")


# 전역 인스턴스 (v54.7.1: InstanceManager 사용)
def get_prompt_optimizer(
    data_dir: str = None,
    channel_type: str = "daily_life_toon",
    channel_id: str = None
) -> PromptOptimizer:
    """
    PromptOptimizer 인스턴스 가져오기 (InstanceManager 경유)

    v54.3.1: 채널 ID 기반 완전 개인화 지원
    - channel_id가 있으면 채널별 완전 분리
    - 없으면 channel_type으로 폴백 (하위호환)

    Args:
        data_dir: 데이터 디렉토리
        channel_type: 채널 타입 (horror/senior)
        channel_id: 실제 YouTube 채널 ID (권장)
    """
    try:
        from utils.instance_manager import get_instance_manager
        return get_instance_manager().get_prompt_optimizer(data_dir, channel_type, channel_id)
    except ImportError:
        # 폴백: 직접 생성
        if data_dir is None:
            try:
                from config.settings import config
                data_dir = config.DATA_DIR
            except Exception:
                data_dir = "data"
        return PromptOptimizer(data_dir, channel_type, channel_id)
