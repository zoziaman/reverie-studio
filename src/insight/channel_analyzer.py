# Reverie Insight - 채널 분석기
# Version: 1.8.0

"""
YouTube 채널 심층 분석 모듈

채널 URL을 입력하면:
1. 채널 기본 정보 수집 (구독자, 총 조회수, 영상 수)
2. 모든 영상 목록 및 통계 수집
3. 댓글 감성 분석 (Gemini AI)
4. 업로드 패턴 분석 (요일, 시간대)
5. 제목/썸네일 패턴 분석
6. AI 전략 리포트 생성

→ Factory로 전송하여 "채널 클론 팩" 생성 가능
"""

import os
import sys
import re
import json
import urllib.parse
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, field, asdict
from collections import Counter
import statistics

# YouTube API
try:
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    YOUTUBE_API_AVAILABLE = True
except ImportError:
    YOUTUBE_API_AVAILABLE = False

# Gemini AI
from utils.gemini_compat import GEMINI_AVAILABLE, configure_gemini, get_gemini_model
from utils.secret_redaction import redact_sensitive_text

# 로거
try:
    from utils.logger import get_logger
    logger = get_logger("channel_analyzer")
except ImportError:
    import logging
    logger = logging.getLogger("channel_analyzer")


class GeminiClient:
    def __init__(self, api_key: str, model_name: str = "gemini-3-flash-preview"):
        if not configure_gemini(api_key):
            raise RuntimeError("Gemini API 초기화 실패")
        self.model = get_gemini_model(model_name)
        if self.model is None:
            raise RuntimeError("Gemini 모델을 불러오지 못했습니다.")

    def generate(self, prompt: str) -> str:
        response = self.model.generate_content(prompt)
        return response.text if hasattr(response, "text") else str(response)


# ============================================================
# 데이터 클래스
# ============================================================

@dataclass
class VideoStats:
    """영상 통계"""
    video_id: str
    title: str
    description: str
    published_at: str
    view_count: int
    like_count: int
    comment_count: int
    duration_seconds: int
    thumbnail_url: str
    tags: List[str] = field(default_factory=list)

    # 분석 결과
    title_keywords: List[str] = field(default_factory=list)
    performance_score: float = 0.0  # 채널 평균 대비 성과


@dataclass
class UploadPattern:
    """업로드 패턴"""
    avg_videos_per_week: float
    best_upload_day: str  # 요일
    best_upload_hour: int  # 시간
    upload_day_distribution: Dict[str, int] = field(default_factory=dict)
    upload_hour_distribution: Dict[int, int] = field(default_factory=dict)
    upload_frequency_trend: str = "stable"  # increasing, decreasing, stable


@dataclass
class TitlePattern:
    """제목 패턴"""
    common_keywords: List[Tuple[str, int]] = field(default_factory=list)
    common_patterns: List[str] = field(default_factory=list)  # "절대 ~하지 마세요", "실화입니다" 등
    avg_title_length: float = 0.0
    emoji_usage_rate: float = 0.0
    number_usage_rate: float = 0.0


@dataclass
class CommentAnalysis:
    """댓글 분석"""
    total_comments_analyzed: int = 0
    sentiment_positive: float = 0.0
    sentiment_negative: float = 0.0
    sentiment_neutral: float = 0.0
    common_requests: List[str] = field(default_factory=list)  # 시청자 요청
    common_praise: List[str] = field(default_factory=list)  # 칭찬 포인트
    common_criticism: List[str] = field(default_factory=list)  # 비판 포인트
    fan_characteristics: str = ""  # 팬층 특성


@dataclass
class ChannelAnalysis:
    """채널 전체 분석 결과"""
    # 기본 정보
    channel_id: str
    channel_title: str
    channel_description: str
    subscriber_count: int
    total_view_count: int
    total_video_count: int
    channel_created_at: str
    thumbnail_url: str

    # 분석 결과
    videos: List[VideoStats] = field(default_factory=list)
    upload_pattern: Optional[UploadPattern] = None
    title_pattern: Optional[TitlePattern] = None
    comment_analysis: Optional[CommentAnalysis] = None

    # 성과 지표
    avg_views_per_video: float = 0.0
    avg_likes_per_video: float = 0.0
    avg_comments_per_video: float = 0.0
    engagement_rate: float = 0.0  # (좋아요+댓글) / 조회수

    # TOP 영상
    top_videos_by_views: List[VideoStats] = field(default_factory=list)
    top_videos_by_engagement: List[VideoStats] = field(default_factory=list)

    # AI 전략 리포트
    ai_strategy_report: str = ""
    clone_recommendations: Dict[str, Any] = field(default_factory=dict)

    # 메타
    analyzed_at: str = ""
    analyzer_version: str = "1.8.0"


# ============================================================
# 채널 분석기 클래스
# ============================================================

class ChannelAnalyzer:
    """YouTube 채널 심층 분석기"""

    VERSION = "1.8.0"

    def __init__(self, youtube_api_key: str, gemini_api_key: str = None):
        """
        Args:
            youtube_api_key: YouTube Data API 키
            gemini_api_key: Gemini API 키 (AI 분석용, 선택)
        """
        if not YOUTUBE_API_AVAILABLE:
            raise ImportError("google-api-python-client가 필요합니다.")

        self.youtube_api_key = youtube_api_key
        self.gemini_api_key = gemini_api_key

        # YouTube API 클라이언트
        self.youtube = build('youtube', 'v3', developerKey=youtube_api_key)

        # Gemini 클라이언트
        self.gemini = None
        if gemini_api_key and GEMINI_AVAILABLE:
            try:
                self.gemini = GeminiClient(gemini_api_key)
            except Exception as e:
                logger.warning(f"Gemini 초기화 실패: {redact_sensitive_text(e)}")

        logger.info(f"[ChannelAnalyzer] v{self.VERSION} 초기화 완료")

    # ============================================================
    # 채널 URL 파싱
    # ============================================================

    def extract_channel_id(self, url_or_id: str) -> Optional[str]:
        """
        채널 URL 또는 핸들에서 채널 ID 추출

        지원 형식:
        - https://www.youtube.com/channel/UC...
        - https://www.youtube.com/@handle (한글 포함)
        - https://www.youtube.com/c/CustomName
        - UC... (직접 ID)
        """
        url_or_id = url_or_id.strip()

        # URL 디코딩 (한글 핸들 지원)
        url_or_id = urllib.parse.unquote(url_or_id)

        # 이미 채널 ID인 경우
        if url_or_id.startswith('UC') and len(url_or_id) == 24:
            return url_or_id

        # /channel/UC... 형식
        match = re.search(r'/channel/(UC[a-zA-Z0-9_-]{22})', url_or_id)
        if match:
            return match.group(1)

        # @handle 형식 (한글, 영문, 숫자, 언더스코어 지원)
        match = re.search(r'/@([^/?&]+)', url_or_id)
        if match:
            handle = match.group(1)
            return self._resolve_handle_to_id(handle)

        # /c/CustomName 형식
        match = re.search(r'/c/([^/?&]+)', url_or_id)
        if match:
            custom_name = match.group(1)
            return self._resolve_custom_url_to_id(custom_name)

        # @handle만 입력한 경우
        if url_or_id.startswith('@'):
            return self._resolve_handle_to_id(url_or_id[1:])

        return None

    def _resolve_handle_to_id(self, handle: str) -> Optional[str]:
        """@handle을 채널 ID로 변환"""
        try:
            # forHandle 파라미터로 검색
            response = self.youtube.channels().list(
                part='id',
                forHandle=handle
            ).execute()

            if response.get('items'):
                return response['items'][0]['id']

            # 검색으로 시도
            search_response = self.youtube.search().list(
                part='snippet',
                q=f"@{handle}",
                type='channel',
                maxResults=1
            ).execute()

            if search_response.get('items'):
                return search_response['items'][0]['snippet']['channelId']

        except HttpError as e:
            logger.error(f"Handle 변환 실패: {e}")

        return None

    def _resolve_custom_url_to_id(self, custom_name: str) -> Optional[str]:
        """커스텀 URL을 채널 ID로 변환"""
        try:
            search_response = self.youtube.search().list(
                part='snippet',
                q=custom_name,
                type='channel',
                maxResults=5
            ).execute()

            for item in search_response.get('items', []):
                if custom_name.lower() in item['snippet']['title'].lower():
                    return item['snippet']['channelId']

            # 첫 번째 결과 반환
            if search_response.get('items'):
                return search_response['items'][0]['snippet']['channelId']

        except HttpError as e:
            logger.error(f"커스텀 URL 변환 실패: {e}")

        return None

    # ============================================================
    # 채널 정보 수집
    # ============================================================

    def get_channel_info(self, channel_id: str) -> Optional[Dict[str, Any]]:
        """채널 기본 정보 수집"""
        try:
            response = self.youtube.channels().list(
                part='snippet,statistics,contentDetails,brandingSettings',
                id=channel_id
            ).execute()

            if not response.get('items'):
                return None

            item = response['items'][0]
            snippet = item['snippet']
            stats = item['statistics']

            return {
                'channel_id': channel_id,
                'title': snippet.get('title', ''),
                'description': snippet.get('description', ''),
                'custom_url': snippet.get('customUrl', ''),
                'published_at': snippet.get('publishedAt', ''),
                'thumbnail_url': snippet.get('thumbnails', {}).get('high', {}).get('url', ''),
                'subscriber_count': int(stats.get('subscriberCount', 0)),
                'view_count': int(stats.get('viewCount', 0)),
                'video_count': int(stats.get('videoCount', 0)),
                'uploads_playlist_id': item.get('contentDetails', {}).get('relatedPlaylists', {}).get('uploads', ''),
            }

        except HttpError as e:
            logger.error(f"채널 정보 수집 실패: {e}")
            return None

    def get_all_videos(
        self,
        uploads_playlist_id: str,
        max_videos: int = 100,
        progress_callback=None
    ) -> List[Dict[str, Any]]:
        """채널의 모든 영상 목록 수집"""
        videos = []
        next_page_token = None

        while len(videos) < max_videos:
            try:
                response = self.youtube.playlistItems().list(
                    part='snippet,contentDetails',
                    playlistId=uploads_playlist_id,
                    maxResults=min(50, max_videos - len(videos)),
                    pageToken=next_page_token
                ).execute()

                for item in response.get('items', []):
                    video_id = item['contentDetails']['videoId']
                    snippet = item['snippet']

                    videos.append({
                        'video_id': video_id,
                        'title': snippet.get('title', ''),
                        'description': snippet.get('description', ''),
                        'published_at': snippet.get('publishedAt', ''),
                        'thumbnail_url': snippet.get('thumbnails', {}).get('high', {}).get('url', ''),
                    })

                if progress_callback:
                    progress_callback(len(videos), max_videos, "영상 목록 수집")

                next_page_token = response.get('nextPageToken')
                if not next_page_token:
                    break

            except HttpError as e:
                logger.error(f"영상 목록 수집 실패: {e}")
                break

        return videos

    def get_video_statistics(
        self,
        video_ids: List[str],
        progress_callback=None
    ) -> Dict[str, Dict[str, Any]]:
        """영상들의 상세 통계 수집"""
        stats = {}

        # 50개씩 배치 처리 (API 제한)
        for i in range(0, len(video_ids), 50):
            batch = video_ids[i:i+50]

            try:
                response = self.youtube.videos().list(
                    part='statistics,contentDetails',
                    id=','.join(batch)
                ).execute()

                for item in response.get('items', []):
                    vid = item['id']
                    s = item.get('statistics', {})
                    cd = item.get('contentDetails', {})

                    # ISO 8601 duration 파싱
                    duration = self._parse_duration(cd.get('duration', 'PT0S'))

                    stats[vid] = {
                        'view_count': int(s.get('viewCount', 0)),
                        'like_count': int(s.get('likeCount', 0)),
                        'comment_count': int(s.get('commentCount', 0)),
                        'duration_seconds': duration,
                    }

                if progress_callback:
                    progress_callback(min(i+50, len(video_ids)), len(video_ids), "통계 수집")

            except HttpError as e:
                logger.error(f"영상 통계 수집 실패: {e}")

        return stats

    def _parse_duration(self, duration_str: str) -> int:
        """ISO 8601 duration을 초로 변환"""
        match = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', duration_str)
        if not match:
            return 0

        hours = int(match.group(1) or 0)
        minutes = int(match.group(2) or 0)
        seconds = int(match.group(3) or 0)

        return hours * 3600 + minutes * 60 + seconds

    # ============================================================
    # 댓글 수집
    # ============================================================

    def get_video_comments(
        self,
        video_id: str,
        max_comments: int = 100
    ) -> List[Dict[str, Any]]:
        """영상의 댓글 수집"""
        comments = []
        next_page_token = None

        while len(comments) < max_comments:
            try:
                response = self.youtube.commentThreads().list(
                    part='snippet',
                    videoId=video_id,
                    maxResults=min(100, max_comments - len(comments)),
                    pageToken=next_page_token,
                    textFormat='plainText',
                    order='relevance'
                ).execute()

                for item in response.get('items', []):
                    snippet = item['snippet']['topLevelComment']['snippet']
                    comments.append({
                        'text': snippet.get('textDisplay', ''),
                        'like_count': snippet.get('likeCount', 0),
                        'published_at': snippet.get('publishedAt', ''),
                    })

                next_page_token = response.get('nextPageToken')
                if not next_page_token:
                    break

            except HttpError as e:
                # 댓글 비활성화된 영상
                if 'commentsDisabled' in str(e):
                    break
                logger.warning(f"댓글 수집 실패 ({video_id}): {e}")
                break

        return comments

    # ============================================================
    # 패턴 분석
    # ============================================================

    def analyze_upload_pattern(self, videos: List[VideoStats]) -> UploadPattern:
        """업로드 패턴 분석"""
        if not videos:
            return UploadPattern(
                avg_videos_per_week=0,
                best_upload_day="",
                best_upload_hour=0
            )

        # 날짜별 분포
        day_counter = Counter()  # 요일
        hour_counter = Counter()  # 시간대
        dates = []

        day_names = ['월', '화', '수', '목', '금', '토', '일']

        for video in videos:
            try:
                dt = datetime.fromisoformat(video.published_at.replace('Z', '+00:00'))
                day_counter[day_names[dt.weekday()]] += 1
                hour_counter[dt.hour] += 1
                dates.append(dt)
            except (ValueError, TypeError):
                continue

        # 주당 평균 업로드
        if len(dates) >= 2:
            date_range = (max(dates) - min(dates)).days
            weeks = max(1, date_range / 7)
            avg_per_week = len(videos) / weeks
        else:
            avg_per_week = len(videos)

        # 최적 요일/시간
        best_day = day_counter.most_common(1)[0][0] if day_counter else ""
        best_hour = hour_counter.most_common(1)[0][0] if hour_counter else 0

        # 트렌드 분석 (최근 vs 과거)
        if len(dates) >= 10:
            mid = len(dates) // 2
            recent_dates = dates[:mid]
            old_dates = dates[mid:]

            recent_interval = (max(recent_dates) - min(recent_dates)).days / len(recent_dates) if len(recent_dates) > 1 else 7
            old_interval = (max(old_dates) - min(old_dates)).days / len(old_dates) if len(old_dates) > 1 else 7

            if recent_interval < old_interval * 0.8:
                trend = "increasing"
            elif recent_interval > old_interval * 1.2:
                trend = "decreasing"
            else:
                trend = "stable"
        else:
            trend = "stable"

        return UploadPattern(
            avg_videos_per_week=round(avg_per_week, 2),
            best_upload_day=best_day,
            best_upload_hour=best_hour,
            upload_day_distribution=dict(day_counter),
            upload_hour_distribution=dict(hour_counter),
            upload_frequency_trend=trend
        )

    def analyze_title_pattern(self, videos: List[VideoStats]) -> TitlePattern:
        """제목 패턴 분석"""
        if not videos:
            return TitlePattern()

        titles = [v.title for v in videos]

        # 키워드 추출 (2글자 이상)
        all_words = []
        for title in titles:
            # 한글, 영문 단어 추출
            words = re.findall(r'[가-힣]{2,}|[a-zA-Z]{3,}', title)
            all_words.extend([w.lower() for w in words])

        # 불용어 제거
        stopwords = {'이것', '저것', '그것', '하는', '되는', '있는', '없는', '하다', '되다',
                     'the', 'and', 'for', 'that', 'this', 'with', 'you', 'are'}
        filtered_words = [w for w in all_words if w not in stopwords]

        word_counts = Counter(filtered_words).most_common(20)

        # 패턴 감지
        patterns = []
        pattern_checks = [
            (r'절대.*마세요|절대.*마라', "절대 ~하지 마세요"),
            (r'실화|실제|레알', "실화/실제 강조"),
            (r'충격|경악|소름', "충격/소름 유발"),
            (r'\d+가지|\d+개|\d+선', "숫자 리스트"),
            (r'이유|비밀|진실', "이유/비밀 궁금증"),
            (r'꿀팁|방법|노하우', "정보/팁 제공"),
            (r'후기|리뷰|솔직', "후기/리뷰"),
        ]

        for pattern, name in pattern_checks:
            count = sum(1 for t in titles if re.search(pattern, t, re.IGNORECASE))
            if count >= len(titles) * 0.1:  # 10% 이상 사용
                patterns.append(f"{name} ({count}회)")

        # 평균 길이
        avg_length = statistics.mean([len(t) for t in titles]) if titles else 0

        # 이모지 사용률
        emoji_pattern = re.compile(r'[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF]')
        emoji_rate = sum(1 for t in titles if emoji_pattern.search(t)) / len(titles) if titles else 0

        # 숫자 사용률
        number_rate = sum(1 for t in titles if re.search(r'\d', t)) / len(titles) if titles else 0

        return TitlePattern(
            common_keywords=word_counts,
            common_patterns=patterns,
            avg_title_length=round(avg_length, 1),
            emoji_usage_rate=round(emoji_rate, 2),
            number_usage_rate=round(number_rate, 2)
        )

    # ============================================================
    # AI 분석 (Gemini)
    # ============================================================

    def analyze_comments_with_ai(
        self,
        comments: List[Dict[str, Any]],
        channel_title: str
    ) -> CommentAnalysis:
        """AI로 댓글 감성 분석"""
        if not self.gemini or not comments:
            return CommentAnalysis()

        # 상위 댓글 샘플링 (좋아요 순)
        sorted_comments = sorted(comments, key=lambda x: x.get('like_count', 0), reverse=True)
        sample = sorted_comments[:50]

        comments_text = "\n".join([f"- {c['text'][:200]}" for c in sample])

        prompt = f"""다음은 YouTube 채널 "{channel_title}"의 인기 댓글들입니다.

댓글들:
{comments_text}

다음 형식으로 분석해주세요 (JSON):
{{
    "sentiment": {{
        "positive": 0.0-1.0,
        "negative": 0.0-1.0,
        "neutral": 0.0-1.0
    }},
    "common_requests": ["시청자들이 자주 요청하는 것 3개"],
    "common_praise": ["자주 칭찬받는 점 3개"],
    "common_criticism": ["자주 지적받는 점 3개 (없으면 빈 배열)"],
    "fan_characteristics": "팬층 특성 한 문장"
}}

JSON만 출력하세요."""

        try:
            if hasattr(self.gemini, 'generate'):
                response = self.gemini.generate(prompt)
            else:
                response = self.gemini.generate_content(prompt)
                response = response.text

            # JSON 파싱
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                data = json.loads(json_match.group())

                return CommentAnalysis(
                    total_comments_analyzed=len(sample),
                    sentiment_positive=data.get('sentiment', {}).get('positive', 0),
                    sentiment_negative=data.get('sentiment', {}).get('negative', 0),
                    sentiment_neutral=data.get('sentiment', {}).get('neutral', 0),
                    common_requests=data.get('common_requests', []),
                    common_praise=data.get('common_praise', []),
                    common_criticism=data.get('common_criticism', []),
                    fan_characteristics=data.get('fan_characteristics', '')
                )

        except Exception as e:
            logger.error(f"댓글 AI 분석 실패: {redact_sensitive_text(e)}")

        return CommentAnalysis(total_comments_analyzed=len(sample))

    def generate_strategy_report(self, analysis: ChannelAnalysis) -> str:
        """AI 전략 리포트 생성"""
        if not self.gemini:
            return "Gemini API가 없어 전략 리포트를 생성할 수 없습니다."

        # 분석 데이터 요약
        top_videos = "\n".join([
            f"- {v.title} (조회수: {v.view_count:,})"
            for v in analysis.top_videos_by_views[:5]
        ])

        keywords = ", ".join([k for k, _ in analysis.title_pattern.common_keywords[:10]]) if analysis.title_pattern else ""
        patterns = "\n".join(analysis.title_pattern.common_patterns) if analysis.title_pattern else ""

        prompt = f"""YouTube 채널 분석 결과를 바탕으로 이 채널을 벤치마킹하려는 크리에이터를 위한 전략 리포트를 작성해주세요.

## 채널 정보
- 채널명: {analysis.channel_title}
- 구독자: {analysis.subscriber_count:,}명
- 총 영상: {analysis.total_video_count}개
- 평균 조회수: {analysis.avg_views_per_video:,.0f}

## 업로드 패턴
- 주당 평균: {analysis.upload_pattern.avg_videos_per_week}개
- 최적 요일: {analysis.upload_pattern.best_upload_day}요일
- 최적 시간: {analysis.upload_pattern.best_upload_hour}시
- 트렌드: {analysis.upload_pattern.upload_frequency_trend}

## 제목 패턴
- 자주 쓰는 키워드: {keywords}
- 사용 패턴:
{patterns}
- 평균 제목 길이: {analysis.title_pattern.avg_title_length if analysis.title_pattern else 0}자

## TOP 영상
{top_videos}

## 댓글 분석
- 긍정 비율: {analysis.comment_analysis.sentiment_positive:.0%}
- 팬층 특성: {analysis.comment_analysis.fan_characteristics}
- 자주 요청: {', '.join(analysis.comment_analysis.common_requests[:3])}

---

다음 내용을 포함하여 전략 리포트를 작성해주세요:

1. **채널 핵심 성공 요인** (3가지)
2. **콘텐츠 공식** (이 채널이 반복하는 패턴)
3. **차별화 포인트** (경쟁 채널 대비)
4. **벤치마킹 전략** (따라하려면?)
5. **추천 콘텐츠 주제** (5개)
6. **주의사항** (함정)

한국어로, 실용적이고 구체적으로 작성해주세요."""

        try:
            if hasattr(self.gemini, 'generate'):
                response = self.gemini.generate(prompt)
            else:
                response = self.gemini.generate_content(prompt)
                response = response.text

            return response

        except Exception as e:
            safe_error = redact_sensitive_text(e)
            logger.error(f"전략 리포트 생성 실패: {safe_error}")
            return f"전략 리포트 생성 실패: {safe_error}"

    # ============================================================
    # 메인 분석 함수
    # ============================================================

    def analyze_channel(
        self,
        channel_url_or_id: str,
        max_videos: int = 50,
        analyze_comments: bool = True,
        generate_report: bool = True,
        progress_callback=None
    ) -> Optional[ChannelAnalysis]:
        """
        채널 전체 분석 실행

        Args:
            channel_url_or_id: 채널 URL, @핸들, 또는 채널 ID
            max_videos: 분석할 최대 영상 수
            analyze_comments: 댓글 분석 여부
            generate_report: AI 전략 리포트 생성 여부
            progress_callback: 진행 콜백 (current, total, stage)

        Returns:
            ChannelAnalysis 또는 None
        """

        # 1. 채널 ID 추출
        if progress_callback:
            progress_callback(0, 100, "채널 ID 확인")

        channel_id = self.extract_channel_id(channel_url_or_id)
        if not channel_id:
            logger.error(f"채널 ID를 찾을 수 없습니다: {channel_url_or_id}")
            return None

        logger.info(f"[ChannelAnalyzer] 채널 분석 시작: {channel_id}")

        # 2. 채널 기본 정보
        if progress_callback:
            progress_callback(5, 100, "채널 정보 수집")

        channel_info = self.get_channel_info(channel_id)
        if not channel_info:
            return None

        # 3. 영상 목록 수집
        if progress_callback:
            progress_callback(10, 100, "영상 목록 수집")

        videos_raw = self.get_all_videos(
            channel_info['uploads_playlist_id'],
            max_videos=max_videos,
            progress_callback=lambda c, t, s: progress_callback(10 + int(20 * c / t), 100, s) if progress_callback else None
        )

        if not videos_raw:
            logger.warning("영상을 찾을 수 없습니다")
            return None

        # 4. 영상 통계 수집
        if progress_callback:
            progress_callback(30, 100, "영상 통계 수집")

        video_ids = [v['video_id'] for v in videos_raw]
        stats = self.get_video_statistics(
            video_ids,
            progress_callback=lambda c, t, s: progress_callback(30 + int(20 * c / t), 100, s) if progress_callback else None
        )

        # 5. VideoStats 객체 생성
        videos: List[VideoStats] = []
        for v in videos_raw:
            vid = v['video_id']
            s = stats.get(vid, {})

            videos.append(VideoStats(
                video_id=vid,
                title=v['title'],
                description=v['description'][:500],
                published_at=v['published_at'],
                view_count=s.get('view_count', 0),
                like_count=s.get('like_count', 0),
                comment_count=s.get('comment_count', 0),
                duration_seconds=s.get('duration_seconds', 0),
                thumbnail_url=v['thumbnail_url'],
            ))

        # 6. 기본 통계 계산
        if progress_callback:
            progress_callback(50, 100, "통계 분석")

        avg_views = statistics.mean([v.view_count for v in videos]) if videos else 0
        avg_likes = statistics.mean([v.like_count for v in videos]) if videos else 0
        avg_comments = statistics.mean([v.comment_count for v in videos]) if videos else 0

        total_engagement = sum(v.like_count + v.comment_count for v in videos)
        total_views = sum(v.view_count for v in videos)
        engagement_rate = total_engagement / total_views if total_views > 0 else 0

        # 성과 점수 계산
        for video in videos:
            if avg_views > 0:
                video.performance_score = video.view_count / avg_views

        # TOP 영상
        top_by_views = sorted(videos, key=lambda x: x.view_count, reverse=True)[:10]
        top_by_engagement = sorted(
            videos,
            key=lambda x: (x.like_count + x.comment_count) / max(x.view_count, 1),
            reverse=True
        )[:10]

        # 7. 패턴 분석
        if progress_callback:
            progress_callback(60, 100, "패턴 분석")

        upload_pattern = self.analyze_upload_pattern(videos)
        title_pattern = self.analyze_title_pattern(videos)

        # 8. 댓글 분석
        comment_analysis = CommentAnalysis()
        if analyze_comments and self.gemini:
            if progress_callback:
                progress_callback(70, 100, "댓글 수집")

            # TOP 영상 3개의 댓글 수집
            all_comments = []
            for video in top_by_views[:3]:
                comments = self.get_video_comments(video.video_id, max_comments=50)
                all_comments.extend(comments)

            if all_comments:
                if progress_callback:
                    progress_callback(80, 100, "댓글 AI 분석")

                comment_analysis = self.analyze_comments_with_ai(
                    all_comments,
                    channel_info['title']
                )

        # 9. 분석 결과 조립
        analysis = ChannelAnalysis(
            channel_id=channel_id,
            channel_title=channel_info['title'],
            channel_description=channel_info['description'][:500],
            subscriber_count=channel_info['subscriber_count'],
            total_view_count=channel_info['view_count'],
            total_video_count=channel_info['video_count'],
            channel_created_at=channel_info['published_at'],
            thumbnail_url=channel_info['thumbnail_url'],
            videos=videos,
            upload_pattern=upload_pattern,
            title_pattern=title_pattern,
            comment_analysis=comment_analysis,
            avg_views_per_video=avg_views,
            avg_likes_per_video=avg_likes,
            avg_comments_per_video=avg_comments,
            engagement_rate=engagement_rate,
            top_videos_by_views=top_by_views,
            top_videos_by_engagement=top_by_engagement,
            analyzed_at=datetime.now().isoformat(),
        )

        # 10. AI 전략 리포트
        if generate_report and self.gemini:
            if progress_callback:
                progress_callback(90, 100, "AI 전략 리포트 생성")

            analysis.ai_strategy_report = self.generate_strategy_report(analysis)

        if progress_callback:
            progress_callback(100, 100, "분석 완료")

        logger.info(f"[ChannelAnalyzer] 분석 완료: {channel_info['title']} ({len(videos)}개 영상)")

        return analysis

    # ============================================================
    # 내보내기
    # ============================================================

    def export_to_json(self, analysis: ChannelAnalysis, output_path: str) -> bool:
        """분석 결과를 JSON으로 내보내기"""
        try:
            # dataclass를 dict로 변환
            data = asdict(analysis)

            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2, default=str)

            logger.info(f"[ChannelAnalyzer] JSON 내보내기 완료: {output_path}")
            return True

        except Exception as e:
            logger.error(f"JSON 내보내기 실패: {e}")
            return False

    def to_clone_recipe_data(self, analysis: ChannelAnalysis) -> Dict[str, Any]:
        """Factory로 전송할 채널 클론 데이터 생성"""
        return {
            "source_type": "channel_analysis",
            "channel_id": analysis.channel_id,
            "channel_title": analysis.channel_title,
            "channel_type": self._detect_channel_type(analysis),
            "style_type": self._detect_style_type(analysis),
            "metadata": {
                "subscriber_count": analysis.subscriber_count,
                "avg_views": analysis.avg_views_per_video,
                "upload_frequency": analysis.upload_pattern.avg_videos_per_week if analysis.upload_pattern else 0,
            },
            "content_formula": {
                "title_keywords": [k for k, _ in analysis.title_pattern.common_keywords[:10]] if analysis.title_pattern else [],
                "title_patterns": analysis.title_pattern.common_patterns if analysis.title_pattern else [],
                "best_upload_day": analysis.upload_pattern.best_upload_day if analysis.upload_pattern else "",
                "best_upload_hour": analysis.upload_pattern.best_upload_hour if analysis.upload_pattern else 12,
            },
            "top_videos": [
                {
                    "title": v.title,
                    "views": v.view_count,
                    "thumbnail_url": v.thumbnail_url,
                }
                for v in analysis.top_videos_by_views[:5]
            ],
            "ai_strategy": analysis.ai_strategy_report,
        }

    def _detect_channel_type(self, analysis: ChannelAnalysis) -> str:
        """채널 유형 자동 감지"""
        keywords = [k.lower() for k, _ in analysis.title_pattern.common_keywords[:20]] if analysis.title_pattern else []
        title_lower = analysis.channel_title.lower()
        desc_lower = analysis.channel_description.lower()

        # 키워드 기반 분류
        horror_keywords = ['공포', '무서운', '괴담', '귀신', 'horror', '소름', '실화']
        cooking_keywords = ['요리', '레시피', '맛집', '먹방', 'cook', 'recipe']
        tech_keywords = ['리뷰', '언박싱', '테크', 'tech', 'review', '추천']
        education_keywords = ['강의', '배우기', '공부', '교육', 'learn', 'tutorial']

        for kw in horror_keywords:
            if kw in keywords or kw in title_lower or kw in desc_lower:
                return "horror"

        for kw in cooking_keywords:
            if kw in keywords or kw in title_lower or kw in desc_lower:
                return "cooking"

        for kw in tech_keywords:
            if kw in keywords or kw in title_lower or kw in desc_lower:
                return "tech_review"

        for kw in education_keywords:
            if kw in keywords or kw in title_lower or kw in desc_lower:
                return "education"

        return "general"

    def _detect_style_type(self, analysis: ChannelAnalysis) -> str:
        """스타일 유형 자동 감지"""
        # 평균 영상 길이로 판단
        avg_duration = statistics.mean([v.duration_seconds for v in analysis.videos]) if analysis.videos else 0

        if avg_duration < 60:
            return "shorts"
        elif avg_duration < 300:
            return "short_form"
        elif avg_duration < 900:
            return "mid_form"
        else:
            return "long_form"


# ============================================================
# 테스트
# ============================================================

if __name__ == "__main__":
    print(f"ChannelAnalyzer v{ChannelAnalyzer.VERSION}")
    print(f"YouTube API: {'사용 가능' if YOUTUBE_API_AVAILABLE else '사용 불가'}")
    print(f"Gemini AI: {'사용 가능' if GEMINI_AVAILABLE else '사용 불가'}")
