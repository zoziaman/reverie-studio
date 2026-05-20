# src/utils/youtube_analytics.py
"""
YouTube Analytics 연동 (v54 Enhanced)
- 업로드된 영상 조회수/좋아요 확인
- 채널 통계
- [v54 신규] CTR, 평균 시청시간, 이탈 분석
- [v54 신규] 트래픽 소스 분석
- [v54 신규] 성과 패턴 분석 (Gemini 연동)
"""
import os
import pickle
import json
import logging
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# v62.22: Fernet 토큰 암호화 (youtube_uploader.py와 동일 키 공유)
try:
    from utils.crypto_utils import (
        derive_fernet_key, fernet_encrypt_bytes, fernet_decrypt_bytes,
        FERNET_AVAILABLE
    )
    from utils.hardware_id import get_hardware_id as _get_hw_id
    _ANALYTICS_FERNET_KEY = derive_fernet_key(_get_hw_id()) if FERNET_AVAILABLE else None
except ImportError:
    FERNET_AVAILABLE = False
    _ANALYTICS_FERNET_KEY = None


def _analytics_load_pickle(path: str):
    """v62.22: Fernet 암호화된 pickle 로드 (레거시 자동 마이그레이션)"""
    # Case 1: Fernet 토큰
    if FERNET_AVAILABLE and _ANALYTICS_FERNET_KEY:
        try:
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read().strip()
            if content.startswith('gAAAAA'):
                decrypted = fernet_decrypt_bytes(content.encode('utf-8'), _ANALYTICS_FERNET_KEY)
                return pickle.loads(decrypted)
        except Exception:
            pass
    # Case 2: 레거시 바이너리 pickle + 자동 마이그레이션
    try:
        with open(path, 'rb') as f:
            creds = pickle.load(f)
        if FERNET_AVAILABLE and _ANALYTICS_FERNET_KEY:
            try:
                _analytics_save_pickle(path, creds)
                logger.info(f"[Analytics] pickle → Fernet 마이그레이션: {path}")
            except Exception:
                pass
        return creds
    except Exception as e:
        logger.error(f"[Analytics] 토큰 로드 실패: {e}")
        return None


def _analytics_save_pickle(path: str, creds):
    """v62.22: Fernet 암호화된 pickle 저장"""
    if FERNET_AVAILABLE and _ANALYTICS_FERNET_KEY:
        raw_bytes = pickle.dumps(creds)
        encrypted = fernet_encrypt_bytes(raw_bytes, _ANALYTICS_FERNET_KEY)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(encrypted.decode('utf-8'))
    else:
        with open(path, 'wb') as f:
            pickle.dump(creds, f)


class YouTubeAnalytics:
    """
    YouTube 분석 연동

    v54.7.2: API 호출 최적화 (캐싱 추가)
    """

    def __init__(self, data_dir: str, channel_type: str = "daily_life_toon"):
        self.data_dir = data_dir
        self.channel_type = channel_type

        # v54: 채널별 토큰 분리
        token_map = {
            "horror": "youtube_token_horror.pickle",
            "senior": "youtube_token_senior.pickle",
        }
        token_filename = token_map.get(channel_type, "youtube_token.pickle")

        self.token_path = os.path.join(data_dir, token_filename)
        self.credentials_path = os.path.join(data_dir, "credentials.json")
        self.service = None
        self.analytics_service = None  # v54: YouTube Analytics API

        # v54.7.2: 캐싱
        self._channel_id_cache: Optional[str] = None
        self._channel_avg_views_cache: Optional[Tuple[float, datetime]] = None  # (값, 캐시시간)
        self._cache_ttl_hours = 1  # 캐시 유효시간 (시간)

    def _get_service(self):
        """YouTube API 서비스 초기화"""
        if self.service:
            return self.service

        if not os.path.exists(self.token_path):
            return None

        try:
            from google.oauth2.credentials import Credentials
            from google.auth.transport.requests import Request
            from googleapiclient.discovery import build

            # v62.22: Fernet 암호화 pickle 지원
            creds = _analytics_load_pickle(self.token_path)

            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
                _analytics_save_pickle(self.token_path, creds)

            # youtube.readonly 스코프로 조회 전용 서비스 생성
            self.service = build('youtube', 'v3', credentials=creds)
            return self.service

        except Exception as e:
            logger.error(f"YouTube API 초기화 실패: {e}")
            return None

    def is_authenticated(self) -> bool:
        """인증 여부 확인"""
        return os.path.exists(self.token_path)

    def get_channel_stats(self) -> Optional[Dict[str, Any]]:
        """채널 통계 가져오기"""
        service = self._get_service()
        if not service:
            return None

        try:
            request = service.channels().list(
                part='snippet,statistics',
                mine=True
            )
            response = request.execute()

            if response['items']:
                channel = response['items'][0]
                stats = channel['statistics']
                return {
                    'channel_id': channel['id'],
                    'title': channel['snippet']['title'],
                    'description': channel['snippet'].get('description', ''),
                    'thumbnail': channel['snippet']['thumbnails'].get('default', {}).get('url', ''),
                    'subscriber_count': int(stats.get('subscriberCount', 0)),
                    'video_count': int(stats.get('videoCount', 0)),
                    'view_count': int(stats.get('viewCount', 0)),
                    'retrieved_at': datetime.now().isoformat()
                }

            return None

        except Exception as e:
            logger.error(f"채널 통계 조회 실패: {e}")
            return None

    def get_video_stats(self, video_id: str) -> Optional[Dict[str, Any]]:
        """영상 통계 가져오기"""
        service = self._get_service()
        if not service:
            return None

        try:
            request = service.videos().list(
                part='snippet,statistics,contentDetails',
                id=video_id
            )
            response = request.execute()

            if response['items']:
                video = response['items'][0]
                stats = video['statistics']
                snippet = video['snippet']

                return {
                    'video_id': video_id,
                    'title': snippet['title'],
                    'description': snippet.get('description', '')[:200],
                    'published_at': snippet['publishedAt'],
                    'thumbnail': snippet['thumbnails'].get('medium', {}).get('url', ''),
                    'view_count': int(stats.get('viewCount', 0)),
                    'like_count': int(stats.get('likeCount', 0)),
                    'comment_count': int(stats.get('commentCount', 0)),
                    'duration': video['contentDetails'].get('duration', ''),
                    'retrieved_at': datetime.now().isoformat()
                }

            return None

        except Exception as e:
            logger.error(f"영상 통계 조회 실패: {e}")
            return None

    def get_recent_videos(self, max_results: int = 10) -> List[Dict[str, Any]]:
        """최근 업로드 영상 목록"""
        service = self._get_service()
        if not service:
            return []

        try:
            # 채널 ID 가져오기
            channel_response = service.channels().list(
                part='contentDetails',
                mine=True
            ).execute()

            if not channel_response['items']:
                return []

            uploads_playlist_id = channel_response['items'][0]['contentDetails']['relatedPlaylists']['uploads']

            # 최근 업로드 목록
            playlist_response = service.playlistItems().list(
                part='snippet,contentDetails',
                playlistId=uploads_playlist_id,
                maxResults=max_results
            ).execute()

            videos = []
            video_ids = []

            for item in playlist_response.get('items', []):
                video_ids.append(item['contentDetails']['videoId'])

            # 영상 상세 정보 가져오기
            if video_ids:
                videos_response = service.videos().list(
                    part='snippet,statistics,contentDetails',
                    id=','.join(video_ids)
                ).execute()

                for video in videos_response.get('items', []):
                    stats = video['statistics']
                    snippet = video['snippet']

                    videos.append({
                        'video_id': video['id'],
                        'title': snippet['title'],
                        'published_at': snippet['publishedAt'],
                        'thumbnail': snippet['thumbnails'].get('medium', {}).get('url', ''),
                        'view_count': int(stats.get('viewCount', 0)),
                        'like_count': int(stats.get('likeCount', 0)),
                        'comment_count': int(stats.get('commentCount', 0)),
                        'duration': video['contentDetails'].get('duration', '')
                    })

            return videos

        except Exception as e:
            logger.error(f"최근 영상 조회 실패: {e}")
            return []

    def get_video_performance_summary(self, video_ids: List[str]) -> Dict[str, Any]:
        """여러 영상의 성과 요약"""
        total_views = 0
        total_likes = 0
        total_comments = 0

        for video_id in video_ids:
            stats = self.get_video_stats(video_id)
            if stats:
                total_views += stats['view_count']
                total_likes += stats['like_count']
                total_comments += stats['comment_count']

        avg_views = total_views / len(video_ids) if video_ids else 0
        avg_likes = total_likes / len(video_ids) if video_ids else 0

        return {
            'video_count': len(video_ids),
            'total_views': total_views,
            'total_likes': total_likes,
            'total_comments': total_comments,
            'avg_views': int(avg_views),
            'avg_likes': int(avg_likes),
            'engagement_rate': (total_likes / total_views * 100) if total_views > 0 else 0
        }

    @staticmethod
    def format_duration(iso_duration: str) -> str:
        """ISO 8601 duration을 읽기 쉬운 형식으로 변환"""
        import re

        match = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', iso_duration)
        if not match:
            return iso_duration

        hours, minutes, seconds = match.groups()
        hours = int(hours) if hours else 0
        minutes = int(minutes) if minutes else 0
        seconds = int(seconds) if seconds else 0

        if hours > 0:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        else:
            return f"{minutes}:{seconds:02d}"

    @staticmethod
    def format_number(num: int) -> str:
        """숫자를 읽기 쉬운 형식으로"""
        if num >= 1000000:
            return f"{num / 1000000:.1f}M"
        elif num >= 1000:
            return f"{num / 1000:.1f}K"
        else:
            return str(num)

    # =========================================================
    # v54: YouTube Analytics API 연동 (CTR, 시청시간, 이탈분석)
    # =========================================================

    def _get_analytics_service(self):
        """YouTube Analytics API 서비스 초기화"""
        if self.analytics_service:
            return self.analytics_service

        if not os.path.exists(self.token_path):
            return None

        try:
            from google.oauth2.credentials import Credentials
            from google.auth.transport.requests import Request
            from googleapiclient.discovery import build

            # v62.22: Fernet 암호화 pickle 지원
            creds = _analytics_load_pickle(self.token_path)

            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
                _analytics_save_pickle(self.token_path, creds)

            # youtubeAnalytics API (v2)
            self.analytics_service = build('youtubeAnalytics', 'v2', credentials=creds)
            return self.analytics_service

        except Exception as e:
            logger.error(f"YouTube Analytics API 초기화 실패: {e}")
            return None

    def get_channel_id(self) -> Optional[str]:
        """
        현재 인증된 채널 ID 가져오기

        v54.7.2: 캐싱 적용 (채널 ID는 변경되지 않으므로)
        """
        # 캐시 확인
        if self._channel_id_cache:
            return self._channel_id_cache

        service = self._get_service()
        if not service:
            return None

        try:
            response = service.channels().list(
                part='id',
                mine=True
            ).execute()

            if response['items']:
                self._channel_id_cache = response['items'][0]['id']
                return self._channel_id_cache
            return None
        except Exception as e:
            logger.error(f"채널 ID 조회 실패: {e}")
            return None

    def get_video_ctr_and_retention(
        self,
        video_id: str,
        start_date: str = None,
        end_date: str = None
    ) -> Optional[Dict[str, Any]]:
        """
        v54: 영상의 CTR과 시청 지속시간 분석

        Returns:
            {
                'video_id': str,
                'impressions': int,          # 노출수
                'clicks': int,               # 클릭수 (실제 조회)
                'ctr': float,                # 클릭률 (%)
                'avg_view_duration': float,  # 평균 시청시간 (초)
                'avg_view_percentage': float, # 평균 시청 비율 (%)
                'views': int,                # 조회수
                'watch_time_minutes': float, # 총 시청시간 (분)
            }
        """
        analytics = self._get_analytics_service()
        channel_id = self.get_channel_id()

        if not analytics or not channel_id:
            logger.warning("Analytics API 또는 채널 ID 없음")
            return None

        # 기본 날짜 범위: 최근 28일
        if not end_date:
            end_date = datetime.now().strftime('%Y-%m-%d')
        if not start_date:
            start_date = (datetime.now() - timedelta(days=28)).strftime('%Y-%m-%d')

        try:
            response = analytics.reports().query(
                ids=f'channel=={channel_id}',
                startDate=start_date,
                endDate=end_date,
                metrics='views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage',
                dimensions='video',
                filters=f'video=={video_id}',
                sort='-views'
            ).execute()

            if response.get('rows') and len(response['rows']) > 0:
                row = response['rows'][0]
                views = int(row[1])
                watch_time_minutes = float(row[2])
                avg_view_duration = float(row[3])
                avg_view_percentage = float(row[4])

                # v54.7.3: CTR 데이터 추가 시도
                # YouTube Analytics API에서 impressions/CTR은 별도 호출 필요
                impressions = 0
                ctr = 0.0
                try:
                    ctr_data = self.get_video_impressions_ctr(video_id, start_date, end_date)
                    if ctr_data:
                        impressions = ctr_data.get('impressions', 0)
                        ctr = ctr_data.get('ctr', 0.0)
                except Exception as ctr_err:
                    logger.debug(f"CTR 데이터 조회 실패 (무시됨): {ctr_err}")

                return {
                    'video_id': video_id,
                    'views': views,
                    'watch_time_minutes': watch_time_minutes,
                    'avg_view_duration': avg_view_duration,
                    'avg_view_percentage': avg_view_percentage,
                    # v54.7.3: CTR 관련 필드 추가
                    'impressions': impressions,
                    'ctr': ctr,
                }

            return None

        except Exception as e:
            logger.error(f"영상 분석 데이터 조회 실패: {e}")
            return None

    def get_video_impressions_ctr(
        self,
        video_id: str,
        start_date: str = None,
        end_date: str = None
    ) -> Optional[Dict[str, Any]]:
        """
        v54: 영상의 노출수와 CTR 조회

        Note: impressions/ctr은 YouTube Studio에서만 보이는 경우가 많음
              API 제한으로 일부 데이터 접근 불가능할 수 있음
        """
        analytics = self._get_analytics_service()
        channel_id = self.get_channel_id()

        if not analytics or not channel_id:
            return None

        if not end_date:
            end_date = datetime.now().strftime('%Y-%m-%d')
        if not start_date:
            start_date = (datetime.now() - timedelta(days=28)).strftime('%Y-%m-%d')

        try:
            # 노출수/CTR은 특정 권한 필요 - 시도해봄
            response = analytics.reports().query(
                ids=f'channel=={channel_id}',
                startDate=start_date,
                endDate=end_date,
                metrics='annotationImpressions,annotationClickableImpressions,annotationClickThroughRate',
                dimensions='video',
                filters=f'video=={video_id}'
            ).execute()

            if response.get('rows'):
                row = response['rows'][0]
                return {
                    'video_id': video_id,
                    'impressions': int(row[1]) if len(row) > 1 else 0,
                    'clickable_impressions': int(row[2]) if len(row) > 2 else 0,
                    'ctr': float(row[3]) if len(row) > 3 else 0,
                }
            return None

        except Exception as e:
            # 권한 부족 등으로 실패 가능
            logger.warning(f"CTR 데이터 조회 실패 (권한 부족 가능): {e}")
            return None

    def get_traffic_sources(
        self,
        video_id: str = None,
        start_date: str = None,
        end_date: str = None
    ) -> List[Dict[str, Any]]:
        """
        v54: 트래픽 소스 분석

        Returns:
            [
                {'source': 'SUGGESTED', 'views': 1000, 'percentage': 45.2},
                {'source': 'SEARCH', 'views': 500, 'percentage': 22.6},
                ...
            ]
        """
        analytics = self._get_analytics_service()
        channel_id = self.get_channel_id()

        if not analytics or not channel_id:
            return []

        if not end_date:
            end_date = datetime.now().strftime('%Y-%m-%d')
        if not start_date:
            start_date = (datetime.now() - timedelta(days=28)).strftime('%Y-%m-%d')

        try:
            filters = f'video=={video_id}' if video_id else None

            query_params = {
                'ids': f'channel=={channel_id}',
                'startDate': start_date,
                'endDate': end_date,
                'metrics': 'views,estimatedMinutesWatched',
                'dimensions': 'insightTrafficSourceType',
                'sort': '-views',
            }
            if filters:
                query_params['filters'] = filters

            response = analytics.reports().query(**query_params).execute()

            results = []
            total_views = sum(int(row[1]) for row in response.get('rows', []))

            for row in response.get('rows', []):
                source = row[0]
                views = int(row[1])
                watch_time = float(row[2])

                results.append({
                    'source': source,
                    'views': views,
                    'watch_time_minutes': watch_time,
                    'percentage': round(views / total_views * 100, 1) if total_views > 0 else 0
                })

            return results

        except Exception as e:
            logger.error(f"트래픽 소스 조회 실패: {e}")
            return []

    def get_audience_retention(
        self,
        video_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        v54: 시청자 이탈 지점 분석

        Note: 상세 retention curve는 API로 직접 접근 어려움
              대안으로 평균 시청 비율로 추정
        """
        # 기본 시청 데이터로 분석
        video_data = self.get_video_ctr_and_retention(video_id)
        video_stats = self.get_video_stats(video_id)

        if not video_data or not video_stats:
            return None

        # 영상 길이 파싱 (ISO 8601)
        duration_str = video_stats.get('duration', 'PT0S')
        duration_seconds = self._parse_duration(duration_str)

        avg_view_duration = video_data.get('avg_view_duration', 0)
        avg_view_percentage = video_data.get('avg_view_percentage', 0)

        # 이탈 지점 추정
        if duration_seconds > 0 and avg_view_duration > 0:
            # 평균 이탈 시점 계산
            avg_drop_point = avg_view_duration

            # 초반 이탈 여부 판단 (30초 이내 이탈률 높으면 후킹 문제)
            early_drop = avg_view_duration < 30 and avg_view_percentage < 30

            return {
                'video_id': video_id,
                'duration_seconds': duration_seconds,
                'avg_view_duration': avg_view_duration,
                'avg_view_percentage': avg_view_percentage,
                'estimated_drop_point': avg_drop_point,
                'early_drop_warning': early_drop,
                'diagnosis': self._diagnose_retention(avg_view_percentage, avg_view_duration)
            }

        return None

    def _parse_duration(self, iso_duration: str) -> int:
        """ISO 8601 duration을 초로 변환"""
        import re
        match = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', iso_duration)
        if not match:
            return 0

        hours = int(match.group(1)) if match.group(1) else 0
        minutes = int(match.group(2)) if match.group(2) else 0
        seconds = int(match.group(3)) if match.group(3) else 0

        return hours * 3600 + minutes * 60 + seconds

    def _diagnose_retention(self, avg_percentage: float, avg_duration: float) -> str:
        """시청 지속률 진단"""
        if avg_percentage >= 50:
            return "양호 - 절반 이상 시청"
        elif avg_percentage >= 30:
            return "보통 - 개선 여지 있음"
        elif avg_duration < 15:
            return "위험 - 초반 15초 이내 이탈 (후킹 문제)"
        elif avg_duration < 30:
            return "주의 - 초반 30초 이내 이탈 (콘텐츠 기대 불일치)"
        else:
            return "저조 - 중반 이탈 많음 (스토리 몰입 부족)"

    # =========================================================
    # v54: 종합 성과 분석 리포트
    # =========================================================

    def get_comprehensive_report(
        self,
        video_ids: List[str] = None,
        days: int = 28
    ) -> Dict[str, Any]:
        """
        v54: 종합 성과 분석 리포트

        Args:
            video_ids: 분석할 영상 ID 목록 (None이면 최근 영상)
            days: 분석 기간 (일)

        Returns:
            {
                'period': {'start': str, 'end': str},
                'channel_stats': {...},
                'video_performances': [...],
                'traffic_sources': [...],
                'top_performers': [...],
                'worst_performers': [...],
                'insights': [...],
            }
        """
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

        # 영상 목록
        if not video_ids:
            recent_videos = self.get_recent_videos(max_results=20)
            video_ids = [v['video_id'] for v in recent_videos]

        # 채널 통계
        channel_stats = self.get_channel_stats()

        # 각 영상 성과
        video_performances = []
        for vid in video_ids:
            perf = self.get_video_ctr_and_retention(vid, start_date, end_date)
            stats = self.get_video_stats(vid)
            retention = self.get_audience_retention(vid)

            if perf and stats:
                video_performances.append({
                    'video_id': vid,
                    'title': stats.get('title', ''),
                    'published_at': stats.get('published_at', ''),
                    'views': perf.get('views', 0),
                    'avg_view_duration': perf.get('avg_view_duration', 0),
                    'avg_view_percentage': perf.get('avg_view_percentage', 0),
                    'likes': stats.get('like_count', 0),
                    'comments': stats.get('comment_count', 0),
                    'retention_diagnosis': retention.get('diagnosis', '') if retention else '',
                    'early_drop_warning': retention.get('early_drop_warning', False) if retention else False,
                })

        # 트래픽 소스 (채널 전체)
        traffic_sources = self.get_traffic_sources(start_date=start_date, end_date=end_date)

        # 성과 순위
        sorted_by_views = sorted(video_performances, key=lambda x: x['views'], reverse=True)
        top_performers = sorted_by_views[:3] if len(sorted_by_views) >= 3 else sorted_by_views
        worst_performers = sorted_by_views[-3:] if len(sorted_by_views) >= 3 else []

        # 인사이트 생성
        insights = self._generate_insights(video_performances, traffic_sources)

        return {
            'period': {'start': start_date, 'end': end_date, 'days': days},
            'channel_stats': channel_stats,
            'video_count': len(video_performances),
            'video_performances': video_performances,
            'traffic_sources': traffic_sources,
            'top_performers': top_performers,
            'worst_performers': worst_performers,
            'insights': insights,
            'generated_at': datetime.now().isoformat()
        }

    def _generate_insights(
        self,
        performances: List[Dict],
        traffic_sources: List[Dict]
    ) -> List[str]:
        """성과 데이터 기반 인사이트 생성"""
        insights = []

        if not performances:
            return ["데이터 부족 - 최소 1개 이상의 영상이 필요합니다."]

        # 평균 계산
        avg_views = sum(p['views'] for p in performances) / len(performances)
        avg_retention = sum(p['avg_view_percentage'] for p in performances) / len(performances)

        # 조회수 인사이트
        if avg_views < 100:
            insights.append("⚠️ 평균 조회수 100 미만 - 노출이 부족합니다. 제목/썸네일 개선 필요.")
        elif avg_views < 500:
            insights.append("📊 평균 조회수 100~500 - 성장 중. CTR 개선에 집중하세요.")
        else:
            insights.append("✅ 평균 조회수 500+ - 양호한 성과입니다.")

        # 시청 지속률 인사이트
        if avg_retention < 30:
            insights.append("🚨 평균 시청률 30% 미만 - 초반 후킹 또는 콘텐츠 품질 점검 필요.")
        elif avg_retention < 50:
            insights.append("📉 평균 시청률 30~50% - 개선 여지 있음. 스토리 몰입도 강화 필요.")
        else:
            insights.append("✅ 평균 시청률 50%+ - 좋은 시청 유지율입니다.")

        # 초반 이탈 경고
        early_drop_count = sum(1 for p in performances if p.get('early_drop_warning', False))
        if early_drop_count > len(performances) * 0.3:
            insights.append(f"🔴 {early_drop_count}개 영상에서 초반 이탈 감지 - 후킹 개선 급선무!")

        # 트래픽 소스 인사이트
        if traffic_sources:
            top_source = traffic_sources[0] if traffic_sources else None
            if top_source:
                if top_source['source'] == 'SUGGESTED':
                    insights.append("📺 추천 트래픽이 주력 - 알고리즘이 영상을 밀어주고 있습니다.")
                elif top_source['source'] == 'SEARCH':
                    insights.append("🔍 검색 트래픽이 주력 - SEO 최적화가 잘 되어있습니다.")
                elif top_source['source'] == 'BROWSE':
                    insights.append("🏠 홈/구독 트래픽 - 충성 구독자가 많습니다.")
                elif top_source['source'] == 'EXT_URL':
                    insights.append("🔗 외부 링크 트래픽 - SNS/커뮤니티 홍보 효과 있음.")

        return insights

    # =========================================================
    # v54: Gemini 연동 심층 분석
    # =========================================================

    def analyze_with_gemini(
        self,
        report: Dict[str, Any],
        api_key: str = None
    ) -> Optional[str]:
        """
        v54: Gemini로 성과 데이터 심층 분석

        Args:
            report: get_comprehensive_report() 결과
            api_key: Gemini API 키 (없으면 config에서 가져옴)

        Returns:
            분석 결과 텍스트
        """
        try:
            from config.settings import config
            from utils.gemini_compat import configure_gemini, get_gemini_model

            if not api_key:
                api_key = config.GEMINI_API_KEY

            if not configure_gemini(api_key):
                return None
            model = get_gemini_model("gemini-3-flash-preview")
            if model is None:
                return None

            # 리포트 요약
            summary = {
                'period': report.get('period', {}),
                'video_count': report.get('video_count', 0),
                'channel_stats': report.get('channel_stats', {}),
                'top_3': report.get('top_performers', []),
                'worst_3': report.get('worst_performers', []),
                'traffic_sources': report.get('traffic_sources', [])[:5],
                'auto_insights': report.get('insights', []),
            }

            prompt = f"""당신은 YouTube 채널 성장 전문가입니다.
아래 채널 성과 데이터를 분석하고, 구체적인 개선 방안을 제시해주세요.

[채널 성과 데이터]
{json.dumps(summary, ensure_ascii=False, indent=2)}

다음 형식으로 분석해주세요:

## 📊 현황 진단
(데이터 기반 현재 상태 요약)

## 🔴 핵심 문제점
(가장 시급한 문제 1~3개)

## ✅ 즉시 개선 가능한 것
(바로 적용할 수 있는 액션 아이템)

## 📈 중장기 전략
(채널 성장을 위한 방향)

## 💡 콘텐츠 제안
(성과 좋은 영상 패턴 기반 추천)

한국어로 답변해주세요. 구체적인 수치와 예시를 포함해주세요.
"""

            response = model.generate_content(prompt)
            return response.text

        except Exception as e:
            logger.error(f"Gemini 분석 실패: {e}")
            return None

    def save_report(self, report: Dict[str, Any], filename: str = None) -> str:
        """리포트를 JSON 파일로 저장"""
        if not filename:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"analytics_report_{self.channel_type}_{timestamp}.json"

        filepath = os.path.join(self.data_dir, "reports", filename)
        os.makedirs(os.path.dirname(filepath), exist_ok=True)

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        logger.info(f"리포트 저장: {filepath}")
        return filepath

    # =========================================================
    # v54.1: 자동 썸네일 교체 시스템
    # =========================================================

    def get_videos_needing_thumbnail_change(
        self,
        ctr_threshold: float = 2.0,
        min_impressions: int = 100,
        min_age_hours: int = 24,
        max_age_hours: int = 168  # 7일
    ) -> List[Dict[str, Any]]:
        """
        v54.1: 썸네일 교체가 필요한 영상 목록 조회

        조건:
        - CTR이 threshold 미만
        - 최소 impressions 이상 노출
        - 업로드 후 min_age_hours ~ max_age_hours 사이

        Returns:
            [
                {
                    'video_id': str,
                    'title': str,
                    'published_at': str,
                    'age_hours': float,
                    'views': int,
                    'avg_view_percentage': float,
                    'estimated_ctr': float,  # 조회수/노출 추정
                    'reason': str,  # 교체 필요 이유
                },
                ...
            ]
        """
        videos_to_change = []

        # 최근 영상 가져오기
        recent_videos = self.get_recent_videos(max_results=20)

        for video in recent_videos:
            video_id = video['video_id']
            title = video['title']
            published_at = video.get('published_at', '')

            # 업로드 시간 계산
            try:
                pub_time = datetime.fromisoformat(published_at.replace('Z', '+00:00'))
                age_hours = (datetime.now(pub_time.tzinfo) - pub_time).total_seconds() / 3600
            except Exception:
                age_hours = 0

            # 시간 범위 체크
            if age_hours < min_age_hours or age_hours > max_age_hours:
                continue

            # 성과 데이터 조회
            perf = self.get_video_ctr_and_retention(video_id)
            if not perf:
                continue

            views = perf.get('views', 0)
            avg_view_percentage = perf.get('avg_view_percentage', 0)

            # 노출 대비 조회수로 CTR 추정 (실제 CTR은 API 제한으로 어려움)
            # 대안: 평균 시청률이 낮으면 썸네일/제목 문제로 판단
            estimated_ctr = 0

            # 조건: 조회수가 적고 시청률도 낮으면 썸네일 문제 가능성
            needs_change = False
            reason = ""

            # 조건 1: 시청률이 매우 낮음 (클릭은 했지만 바로 이탈)
            if avg_view_percentage < 20 and views > min_impressions:
                needs_change = True
                reason = f"시청률 {avg_view_percentage:.1f}% (기대 불일치 - 썸네일과 내용 불일치 가능)"

            # 조건 2: 채널 평균 대비 조회수가 현저히 낮음
            # (평균 조회수의 50% 미만이면 썸네일/제목 어필 부족)
            channel_avg = self._get_channel_average_views()
            if channel_avg > 0 and views < channel_avg * 0.3:
                needs_change = True
                reason = f"채널 평균의 {views/channel_avg*100:.0f}% (노출 대비 클릭 부족)"

            # 조건 3: 초반 이탈이 심함
            retention = self.get_audience_retention(video_id)
            if retention and retention.get('early_drop_warning'):
                needs_change = True
                reason = f"초반 이탈 경고 (15초 이내 이탈 - 후킹/썸네일 문제)"

            if needs_change:
                videos_to_change.append({
                    'video_id': video_id,
                    'title': title,
                    'published_at': published_at,
                    'age_hours': round(age_hours, 1),
                    'views': views,
                    'avg_view_percentage': avg_view_percentage,
                    'estimated_ctr': estimated_ctr,
                    'reason': reason,
                })

        return videos_to_change

    def _get_channel_average_views(self) -> float:
        """채널 평균 조회수 계산 (최근 10개 영상 기준)"""
        try:
            recent = self.get_recent_videos(max_results=10)
            if not recent:
                return 0

            total_views = sum(v.get('view_count', 0) for v in recent)
            return total_views / len(recent)
        except Exception:
            return 0

    def get_thumbnail_change_history(self) -> List[Dict[str, Any]]:
        """썸네일 교체 히스토리 조회"""
        history_path = os.path.join(self.data_dir, "thumbnail_change_history.json")

        if os.path.exists(history_path):
            with open(history_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return []

    def record_thumbnail_change(
        self,
        video_id: str,
        old_thumbnail: str,
        new_thumbnail: str,
        reason: str
    ):
        """
        썸네일 교체 기록 저장

        [DEPRECATED v54.7.1]
        이 메서드는 하위 호환성을 위해 유지되지만,
        새로운 코드에서는 FeedbackLoop.record_thumbnail_change()를 사용하세요.

        썸네일 변경 이력의 단일 소스는 FeedbackLoop입니다.

        v54.7.3: 폴백 제거 - FeedbackLoop 위임만 수행 (데이터 분산 방지)
        """
        # v54.7.1: FeedbackLoop으로 위임 (v54.7.3: 폴백 제거)
        try:
            from utils.feedback_loop import get_feedback_loop
            feedback_loop = get_feedback_loop(self.data_dir, self.channel_type)
            feedback_loop.record_thumbnail_change(
                video_id=video_id,
                old_thumbnail=old_thumbnail,
                new_thumbnail=new_thumbnail,
                reason=reason
            )
            logger.info(f"썸네일 교체 기록 (FeedbackLoop 위임): {video_id}")
        except Exception as e:
            # v54.7.3: 폴백 제거 - 데이터 분산 방지를 위해 로깅만 수행
            logger.error(
                f"썸네일 교체 기록 실패 (FeedbackLoop 불가): {video_id} - {e}. "
                f"FeedbackLoop.record_thumbnail_change()를 직접 호출하세요."
            )

    def suggest_thumbnail_style(self, video_id: str) -> Dict[str, Any]:
        """
        v54.1: 새 썸네일 스타일 제안

        현재 썸네일이 REAL이면 ART 제안, 반대도 마찬가지
        + 색상/밝기 조정 제안
        """
        history = self.get_thumbnail_change_history()
        video_history = [h for h in history if h['video_id'] == video_id]

        # 이전에 교체한 적 있는지 확인
        change_count = len(video_history)

        # 기본 제안
        suggestion = {
            'video_id': video_id,
            'change_count': change_count,
            'suggestions': []
        }

        if change_count == 0:
            # 첫 교체: 스타일 변경
            suggestion['suggestions'].append({
                'type': 'style_change',
                'description': 'REAL → ART 또는 ART → REAL 스타일 변경',
                'priority': 'high'
            })
        elif change_count == 1:
            # 두 번째: 색상/텍스트 변경
            suggestion['suggestions'].append({
                'type': 'color_change',
                'description': '텍스트 색상 변경 (빨간색 → 노란색/흰색)',
                'priority': 'medium'
            })
            suggestion['suggestions'].append({
                'type': 'brightness_change',
                'description': '배경 밝기 조정 (더 어둡게/밝게)',
                'priority': 'medium'
            })
        else:
            # 세 번째 이상: 완전히 새로운 배경
            suggestion['suggestions'].append({
                'type': 'full_regenerate',
                'description': '완전히 새로운 배경 이미지로 재생성',
                'priority': 'high'
            })

        # 공통 제안
        suggestion['suggestions'].append({
            'type': 'title_change',
            'description': '제목/서브텍스트 위치 또는 크기 조정',
            'priority': 'low'
        })

        return suggestion
