# Reverie Insight - 트렌드 리포터
# Version: 1.3.0

"""
트렌드 리포트 + 경쟁자 분석

주간/월간 트렌드 리포트 자동 생성, 경쟁 채널 약점 분석,
시즌별 트렌드 알림, 황금 구역 자동 추출
"""

import os
import json
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, asdict, field
from pathlib import Path
from collections import Counter, defaultdict
from enum import Enum

from utils.gemini_compat import GEMINI_AVAILABLE, configure_gemini, get_gemini_model

# 내부 모듈
from .trend_collector import (
    VideoMetadata, CollectionResult, TrendCollector,
    SUPPORTED_COUNTRIES, VIDEO_CATEGORIES, FACELESS_FRIENDLY_CATEGORIES
)

logger = logging.getLogger(__name__)


# ============================================================
# 시즌/이벤트 캘린더
# ============================================================

class SeasonalEvent:
    """시즌 이벤트 정의"""

    # 월별 트렌드 이벤트 (글로벌 + 한국)
    EVENTS = {
        1: [
            {"name": "New Year", "name_kr": "새해", "genres": ["emotional", "motivational", "lifestyle"]},
            {"name": "Winter Horror", "name_kr": "겨울 공포", "genres": ["horror", "mystery"]},
        ],
        2: [
            {"name": "Valentine's Day", "name_kr": "발렌타인데이", "genres": ["romance", "emotional"]},
            {"name": "Lunar New Year", "name_kr": "설날", "genres": ["family", "tradition", "emotional"]},
        ],
        3: [
            {"name": "Spring Break", "name_kr": "봄방학", "genres": ["entertainment", "comedy"]},
            {"name": "Women's Day", "name_kr": "세계 여성의 날", "genres": ["documentary", "emotional"]},
        ],
        4: [
            {"name": "Cherry Blossom", "name_kr": "벚꽃 시즌", "genres": ["romance", "emotional", "asmr"]},
            {"name": "Spring Cleaning", "name_kr": "봄맞이 정리", "genres": ["lifestyle", "howto"]},
        ],
        5: [
            {"name": "Children's Day", "name_kr": "어린이날", "genres": ["kids", "family", "entertainment"]},
            {"name": "Mother's Day", "name_kr": "어버이날", "genres": ["emotional", "family"]},
        ],
        6: [
            {"name": "Summer Preview", "name_kr": "여름 프리뷰", "genres": ["horror", "mystery", "travel"]},
            {"name": "Graduation", "name_kr": "졸업 시즌", "genres": ["emotional", "motivational"]},
        ],
        7: [
            {"name": "Summer Horror Special", "name_kr": "여름 공포 특집", "genres": ["horror", "mystery", "urban_legend"]},
            {"name": "Vacation", "name_kr": "휴가 시즌", "genres": ["travel", "asmr", "relaxing"]},
        ],
        8: [
            {"name": "Summer Peak", "name_kr": "한여름", "genres": ["horror", "mystery", "entertainment"]},
            {"name": "Back to School", "name_kr": "개학", "genres": ["education", "student_life"]},
        ],
        9: [
            {"name": "Chuseok", "name_kr": "추석", "genres": ["family", "tradition", "emotional"]},
            {"name": "Fall Season", "name_kr": "가을 시즌", "genres": ["emotional", "romance", "mystery"]},
        ],
        10: [
            {"name": "Halloween", "name_kr": "할로윈", "genres": ["horror", "mystery", "supernatural"]},
            {"name": "Autumn Mystery", "name_kr": "가을 미스터리", "genres": ["mystery", "thriller"]},
        ],
        11: [
            {"name": "Pepero Day", "name_kr": "빼빼로데이", "genres": ["romance", "comedy"]},
            {"name": "Black Friday", "name_kr": "블랙프라이데이", "genres": ["tech", "review", "shopping"]},
        ],
        12: [
            {"name": "Christmas", "name_kr": "크리스마스", "genres": ["emotional", "romance", "family"]},
            {"name": "Year End", "name_kr": "연말", "genres": ["emotional", "recap", "motivational"]},
            {"name": "Winter Tales", "name_kr": "겨울 이야기", "genres": ["mystery", "emotional", "supernatural"]},
        ],
    }

    @classmethod
    def get_current_events(cls) -> List[Dict]:
        """현재 시기의 이벤트 반환"""
        current_month = datetime.now().month
        return cls.EVENTS.get(current_month, [])

    @classmethod
    def get_upcoming_events(cls, days_ahead: int = 30) -> List[Dict]:
        """앞으로 N일 내 이벤트 반환"""
        current = datetime.now()
        end_date = current + timedelta(days=days_ahead)

        events = []
        check_month = current.month

        # 현재 월 + 다음 월 체크
        while check_month <= end_date.month or (check_month == 12 and end_date.month < current.month):
            month_events = cls.EVENTS.get(check_month, [])
            for event in month_events:
                events.append({**event, "month": check_month})
            check_month = (check_month % 12) + 1
            if check_month == current.month:
                break

        return events

    @classmethod
    def get_recommended_genres(cls) -> List[str]:
        """현재 시기 추천 장르"""
        events = cls.get_current_events()
        genres = set()
        for event in events:
            genres.update(event.get("genres", []))
        return list(genres)


# ============================================================
# 데이터 클래스
# ============================================================

@dataclass
class GenreRanking:
    """장르별 순위"""
    genre: str
    genre_kr: str
    video_count: int
    total_views: int
    avg_views: int
    top_videos: List[Dict]  # top 3 videos
    feasibility_avg: float  # 평균 가성비 점수

@dataclass
class CompetitorAnalysis:
    """경쟁 채널 분석"""
    channel_id: str
    channel_name: str
    video_count: int
    total_views: int
    avg_views: int
    main_genre: str
    strengths: List[str]
    weaknesses: List[str]
    niche_opportunities: List[str]  # 틈새 전략
    threat_level: str  # LOW, MEDIUM, HIGH

@dataclass
class GoldenZoneVideo:
    """황금 구역 영상 (조회수 높음 + 복제 쉬움)"""
    video_id: str
    title: str
    channel_name: str
    view_count: int
    feasibility_score: int
    style_type: str
    clone_difficulty: str  # EASY, MEDIUM
    recommended_sd_model: str
    keywords: List[str]

@dataclass
class TrendReport:
    """트렌드 리포트"""
    report_id: str
    report_type: str  # "weekly" or "monthly"
    period_start: str
    period_end: str
    generated_at: str

    # 요약 통계
    total_videos_analyzed: int
    countries_analyzed: List[str]

    # 장르 순위
    genre_rankings: List[GenreRanking]

    # 황금 구역
    golden_zone_videos: List[GoldenZoneVideo]

    # 경쟁자 분석
    competitor_analyses: List[CompetitorAnalysis]

    # 시즌 알림
    current_season_events: List[Dict]
    recommended_genres: List[str]

    # 키워드 트렌드
    trending_keywords: List[Dict]  # {"keyword": str, "count": int, "growth": float}

    # AI 인사이트
    ai_summary: str
    ai_recommendations: List[str]


# ============================================================
# 장르 매핑
# ============================================================

GENRE_MAPPING = {
    # YouTube 카테고리 -> 내부 장르
    "Film & Animation": "entertainment",
    "Music": "music",
    "Pets & Animals": "pets",
    "Sports": "sports",
    "Gaming": "gaming",
    "People & Blogs": "lifestyle",
    "Comedy": "comedy",
    "Entertainment": "entertainment",
    "News & Politics": "news",
    "Howto & Style": "howto",
    "Education": "education",
    "Science & Technology": "tech",
}

GENRE_KR_NAMES = {
    "horror": "공포",
    "mystery": "미스터리",
    "entertainment": "엔터테인먼트",
    "education": "교육",
    "news": "뉴스",
    "comedy": "코미디",
    "emotional": "감동",
    "romance": "로맨스",
    "tech": "테크/과학",
    "gaming": "게임",
    "music": "음악",
    "lifestyle": "라이프스타일",
    "howto": "하우투",
    "pets": "동물",
    "sports": "스포츠",
    "documentary": "다큐멘터리",
    "asmr": "ASMR",
    "supernatural": "초자연",
    "urban_legend": "도시괴담",
    "thriller": "스릴러",
}


# ============================================================
# 트렌드 리포터
# ============================================================

class TrendReporter:
    """트렌드 리포트 생성기"""

    def __init__(
        self,
        gemini_api_key: str = None,
        data_dir: str = None
    ):
        """
        Args:
            gemini_api_key: Gemini API 키 (없으면 환경변수에서)
            data_dir: 데이터 저장 디렉토리
        """
        # Gemini 초기화
        self.gemini_api_key = gemini_api_key or os.environ.get('GEMINI_API_KEY')
        self.gemini_model = None

        if GEMINI_AVAILABLE and self.gemini_api_key:
            try:
                if configure_gemini(self.gemini_api_key):
                    self.gemini_model = get_gemini_model("gemini-1.5-flash")
                logger.info("Gemini 모델 초기화 완료")
            except Exception as e:
                logger.warning(f"Gemini 초기화 실패: {e}")

        # 데이터 디렉토리
        if data_dir is None:
            base_dir = Path(__file__).parent.parent.parent
            data_dir = base_dir / "data" / "insight"
        self.data_dir = Path(data_dir)
        self.reports_dir = self.data_dir / "reports"
        self.reports_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"TrendReporter 초기화 완료. 리포트 경로: {self.reports_dir}")

    # --------------------------------------------------------
    # 리포트 생성
    # --------------------------------------------------------

    def generate_weekly_report(
        self,
        videos: List[VideoMetadata],
        countries: List[str] = None
    ) -> TrendReport:
        """
        주간 트렌드 리포트 생성

        Args:
            videos: 분석할 영상 목록 (필터링 완료된 것)
            countries: 분석 대상 국가 목록

        Returns:
            TrendReport
        """
        return self._generate_report(
            videos=videos,
            report_type="weekly",
            countries=countries,
            period_days=7
        )

    def generate_monthly_report(
        self,
        videos: List[VideoMetadata],
        countries: List[str] = None
    ) -> TrendReport:
        """
        월간 트렌드 리포트 생성
        """
        return self._generate_report(
            videos=videos,
            report_type="monthly",
            countries=countries,
            period_days=30
        )

    def _generate_report(
        self,
        videos: List[VideoMetadata],
        report_type: str,
        countries: List[str],
        period_days: int
    ) -> TrendReport:
        """리포트 생성 내부 메서드"""
        now = datetime.now()
        period_start = (now - timedelta(days=period_days)).isoformat()
        period_end = now.isoformat()

        report_id = f"{report_type}_{now.strftime('%Y%m%d_%H%M%S')}"

        if countries is None:
            countries = list(set(v.country_code for v in videos))

        logger.info(f"리포트 생성 시작: {report_type}, {len(videos)}개 영상, 국가: {countries}")

        # 1. 장르 순위 분석
        genre_rankings = self._analyze_genre_rankings(videos)

        # 2. 황금 구역 추출
        golden_zone = self._extract_golden_zone(videos)

        # 3. 경쟁자 분석
        competitors = self._analyze_competitors(videos)

        # 4. 시즌 이벤트
        current_events = SeasonalEvent.get_current_events()
        recommended_genres = SeasonalEvent.get_recommended_genres()

        # 5. 키워드 트렌드
        trending_keywords = self._extract_trending_keywords(videos)

        # 6. AI 인사이트 (Gemini)
        ai_summary, ai_recommendations = self._generate_ai_insights(
            videos, genre_rankings, golden_zone, current_events
        )

        report = TrendReport(
            report_id=report_id,
            report_type=report_type,
            period_start=period_start,
            period_end=period_end,
            generated_at=now.isoformat(),
            total_videos_analyzed=len(videos),
            countries_analyzed=countries,
            genre_rankings=genre_rankings,
            golden_zone_videos=golden_zone,
            competitor_analyses=competitors,
            current_season_events=current_events,
            recommended_genres=recommended_genres,
            trending_keywords=trending_keywords,
            ai_summary=ai_summary,
            ai_recommendations=ai_recommendations
        )

        # 저장
        self._save_report(report)

        logger.info(f"리포트 생성 완료: {report_id}")
        return report

    # --------------------------------------------------------
    # 장르 분석
    # --------------------------------------------------------

    def _analyze_genre_rankings(self, videos: List[VideoMetadata]) -> List[GenreRanking]:
        """장르별 순위 분석"""
        genre_stats = defaultdict(lambda: {
            "count": 0,
            "views": 0,
            "feasibility_scores": [],
            "videos": []
        })

        for video in videos:
            # 카테고리 -> 장르 변환
            genre = GENRE_MAPPING.get(video.category_name, "entertainment")

            genre_stats[genre]["count"] += 1
            genre_stats[genre]["views"] += video.view_count

            if video.feasibility_score is not None:
                genre_stats[genre]["feasibility_scores"].append(video.feasibility_score)

            genre_stats[genre]["videos"].append({
                "video_id": video.video_id,
                "title": video.title,
                "views": video.view_count,
                "channel": video.channel_title
            })

        # 순위 계산 (조회수 기준)
        rankings = []
        for genre, stats in genre_stats.items():
            if stats["count"] == 0:
                continue

            avg_views = stats["views"] // stats["count"]

            # 가성비 평균
            feasibility_avg = 0.0
            if stats["feasibility_scores"]:
                feasibility_avg = sum(stats["feasibility_scores"]) / len(stats["feasibility_scores"])

            # Top 3 영상
            top_videos = sorted(stats["videos"], key=lambda x: x["views"], reverse=True)[:3]

            rankings.append(GenreRanking(
                genre=genre,
                genre_kr=GENRE_KR_NAMES.get(genre, genre),
                video_count=stats["count"],
                total_views=stats["views"],
                avg_views=avg_views,
                top_videos=top_videos,
                feasibility_avg=feasibility_avg
            ))

        # 총 조회수 기준 정렬
        rankings.sort(key=lambda x: x.total_views, reverse=True)

        return rankings

    # --------------------------------------------------------
    # 황금 구역 추출
    # --------------------------------------------------------

    def _extract_golden_zone(
        self,
        videos: List[VideoMetadata],
        min_views: int = 100000,
        min_feasibility: int = 70
    ) -> List[GoldenZoneVideo]:
        """
        황금 구역 영상 추출
        조건: 조회수 높음 (>100K) + 복제 쉬움 (feasibility >= 70)
        """
        golden = []

        for video in videos:
            # 조건 체크
            if video.view_count < min_views:
                continue
            if video.feasibility_score is None or video.feasibility_score < min_feasibility:
                continue
            if not video.can_replicate:
                continue

            # 난이도 판정
            difficulty = "EASY" if video.feasibility_score >= 85 else "MEDIUM"

            # 키워드 추출 (제목 + 태그)
            keywords = self._extract_keywords_from_video(video)

            # SD 모델 추천 (style_type 기반)
            sd_model = self._recommend_sd_model(video.style_type)

            golden.append(GoldenZoneVideo(
                video_id=video.video_id,
                title=video.title,
                channel_name=video.channel_title,
                view_count=video.view_count,
                feasibility_score=video.feasibility_score,
                style_type=video.style_type or "unknown",
                clone_difficulty=difficulty,
                recommended_sd_model=sd_model,
                keywords=keywords
            ))

        # 조회수 기준 정렬
        golden.sort(key=lambda x: x.view_count, reverse=True)

        return golden[:20]  # 상위 20개

    def _extract_keywords_from_video(self, video: VideoMetadata) -> List[str]:
        """영상에서 키워드 추출"""
        keywords = []

        # 태그에서 추출
        if video.tags:
            keywords.extend(video.tags[:5])

        # 제목에서 주요 단어 추출 (간단한 방식)
        title_words = video.title.replace("[", " ").replace("]", " ").split()
        for word in title_words:
            # 2글자 이상, 특수문자 제외
            clean_word = ''.join(c for c in word if c.isalnum())
            if len(clean_word) >= 2 and clean_word not in keywords:
                keywords.append(clean_word)
                if len(keywords) >= 10:
                    break

        return keywords[:10]

    def _recommend_sd_model(self, style_type: str) -> str:
        """스타일 기반 SD 모델 추천"""
        model_map = {
            "silhouette": "realisticVision_v51",
            "2d_anime": "animePastelDream_v2",
            "2d_illustration": "dreamshaper_8",
            "ai_generated": "realisticVision_v51",
            "pixel_art": "pixelArtDiffusion",
            "lo-fi": "lofi_v1",
            "slideshow": "realisticVision_v51",
        }
        return model_map.get(style_type, "realisticVision_v51")

    # --------------------------------------------------------
    # 경쟁자 분석
    # --------------------------------------------------------

    def _analyze_competitors(
        self,
        videos: List[VideoMetadata],
        min_videos: int = 2
    ) -> List[CompetitorAnalysis]:
        """경쟁 채널 분석"""
        channel_stats = defaultdict(lambda: {
            "channel_name": "",
            "videos": [],
            "views": 0,
            "genres": []
        })

        # 채널별 통계 집계
        for video in videos:
            ch_id = video.channel_id
            channel_stats[ch_id]["channel_name"] = video.channel_title
            channel_stats[ch_id]["videos"].append(video)
            channel_stats[ch_id]["views"] += video.view_count

            genre = GENRE_MAPPING.get(video.category_name, "entertainment")
            channel_stats[ch_id]["genres"].append(genre)

        # 분석
        analyses = []
        for ch_id, stats in channel_stats.items():
            if len(stats["videos"]) < min_videos:
                continue

            video_count = len(stats["videos"])
            avg_views = stats["views"] // video_count

            # 주력 장르
            genre_counter = Counter(stats["genres"])
            main_genre = genre_counter.most_common(1)[0][0] if genre_counter else "unknown"

            # 강점/약점/틈새 분석
            strengths, weaknesses, niches = self._analyze_channel_swot(stats["videos"])

            # 위협 수준
            threat = self._calculate_threat_level(avg_views, video_count)

            analyses.append(CompetitorAnalysis(
                channel_id=ch_id,
                channel_name=stats["channel_name"],
                video_count=video_count,
                total_views=stats["views"],
                avg_views=avg_views,
                main_genre=main_genre,
                strengths=strengths,
                weaknesses=weaknesses,
                niche_opportunities=niches,
                threat_level=threat
            ))

        # 총 조회수 기준 정렬
        analyses.sort(key=lambda x: x.total_views, reverse=True)

        return analyses[:10]  # 상위 10개 채널

    def _analyze_channel_swot(
        self,
        videos: List[VideoMetadata]
    ) -> Tuple[List[str], List[str], List[str]]:
        """채널 강점/약점/틈새 분석"""
        strengths = []
        weaknesses = []
        niches = []

        if not videos:
            return strengths, weaknesses, niches

        avg_views = sum(v.view_count for v in videos) // len(videos)
        avg_feasibility = 0
        feasible_count = 0

        for v in videos:
            if v.feasibility_score:
                avg_feasibility += v.feasibility_score
                feasible_count += 1

        if feasible_count > 0:
            avg_feasibility //= feasible_count

        # 강점 분석
        if avg_views > 500000:
            strengths.append("높은 평균 조회수 (50만+)")
        elif avg_views > 100000:
            strengths.append("안정적인 조회수 (10만+)")

        if len(videos) >= 5:
            strengths.append("꾸준한 업로드 빈도")

        # 약점 분석
        if avg_feasibility < 50:
            weaknesses.append("복제 난이도 높음 (우리 기회)")

        if avg_views < 50000:
            weaknesses.append("낮은 조회수 (시장 검증 부족)")

        # 스타일 다양성 체크
        styles = set(v.style_type for v in videos if v.style_type)
        if len(styles) <= 1:
            weaknesses.append("스타일 단조로움")
            niches.append("다양한 비주얼 스타일로 차별화 가능")

        # 틈새 기회
        genres = set(GENRE_MAPPING.get(v.category_name, "entertainment") for v in videos)
        if "horror" not in genres and "mystery" not in genres:
            niches.append("공포/미스터리 콘텐츠 부재 - 진입 기회")

        if avg_feasibility >= 70:
            niches.append("복제 가능한 스타일 - 벤치마킹 추천")

        return strengths, weaknesses, niches

    def _calculate_threat_level(self, avg_views: int, video_count: int) -> str:
        """위협 수준 계산"""
        score = 0

        if avg_views > 1000000:
            score += 3
        elif avg_views > 500000:
            score += 2
        elif avg_views > 100000:
            score += 1

        if video_count >= 5:
            score += 1

        if score >= 3:
            return "HIGH"
        elif score >= 2:
            return "MEDIUM"
        else:
            return "LOW"

    # --------------------------------------------------------
    # 키워드 트렌드
    # --------------------------------------------------------

    def _extract_trending_keywords(
        self,
        videos: List[VideoMetadata],
        top_n: int = 20
    ) -> List[Dict]:
        """트렌딩 키워드 추출"""
        keyword_counter = Counter()

        for video in videos:
            # 태그에서
            for tag in video.tags:
                if len(tag) >= 2:
                    keyword_counter[tag.lower()] += 1

            # 제목에서 (간단한 토큰화)
            words = video.title.replace("[", " ").replace("]", " ").split()
            for word in words:
                clean = ''.join(c for c in word if c.isalnum())
                if len(clean) >= 2:
                    keyword_counter[clean.lower()] += 1

        # 상위 키워드
        top_keywords = keyword_counter.most_common(top_n)

        return [
            {
                "keyword": kw,
                "count": count,
                "growth": 0.0  # NOTE: 성장률 placeholder. 기간별 이력 데이터 축적 후 구현
            }
            for kw, count in top_keywords
        ]

    # --------------------------------------------------------
    # AI 인사이트 (Gemini)
    # --------------------------------------------------------

    def _generate_ai_insights(
        self,
        videos: List[VideoMetadata],
        genre_rankings: List[GenreRanking],
        golden_zone: List[GoldenZoneVideo],
        current_events: List[Dict]
    ) -> Tuple[str, List[str]]:
        """Gemini를 활용한 AI 인사이트 생성"""

        if not self.gemini_model:
            return self._generate_fallback_insights(genre_rankings, golden_zone, current_events)

        # 프롬프트 구성
        prompt = self._build_insight_prompt(videos, genre_rankings, golden_zone, current_events)

        try:
            response = self.gemini_model.generate_content(prompt)
            text = response.text

            # 파싱 (간단한 방식)
            lines = text.strip().split("\n")
            summary = ""
            recommendations = []

            in_summary = False
            in_recommendations = False

            for line in lines:
                line = line.strip()
                if "요약" in line or "Summary" in line:
                    in_summary = True
                    in_recommendations = False
                    continue
                elif "추천" in line or "Recommendation" in line:
                    in_summary = False
                    in_recommendations = True
                    continue

                if in_summary and line:
                    summary += line + " "
                elif in_recommendations and line.startswith(("-", "•", "*", "1", "2", "3")):
                    rec = line.lstrip("-•* 0123456789.)")
                    if rec:
                        recommendations.append(rec)

            if not summary:
                summary = text[:500]  # fallback

            if not recommendations:
                recommendations = ["AI 분석 결과를 확인하세요."]

            return summary.strip(), recommendations[:5]

        except Exception as e:
            logger.warning(f"Gemini 인사이트 생성 실패: {e}")
            return self._generate_fallback_insights(genre_rankings, golden_zone, current_events)

    def _build_insight_prompt(
        self,
        videos: List[VideoMetadata],
        genre_rankings: List[GenreRanking],
        golden_zone: List[GoldenZoneVideo],
        current_events: List[Dict]
    ) -> str:
        """AI 인사이트 프롬프트 생성"""

        # 장르 순위 요약
        genre_summary = "\n".join([
            f"- {r.genre_kr}: {r.video_count}개, 평균 {r.avg_views:,}뷰"
            for r in genre_rankings[:5]
        ])

        # 황금 구역 요약
        golden_summary = "\n".join([
            f"- {g.title[:30]}... ({g.view_count:,}뷰, 난이도: {g.clone_difficulty})"
            for g in golden_zone[:5]
        ])

        # 시즌 이벤트
        events_str = ", ".join([e["name_kr"] for e in current_events]) if current_events else "없음"

        prompt = f"""당신은 YouTube 트렌드 분석 전문가입니다.
다음 데이터를 분석하고 AI 콘텐츠 제작자를 위한 인사이트를 제공하세요.

## 분석 데이터

### 장르별 순위 (상위 5개)
{genre_summary}

### 황금 구역 영상 (고조회수 + 복제 용이)
{golden_summary}

### 현재 시즌 이벤트
{events_str}

### 총 분석 영상 수
{len(videos)}개

## 요청사항

1. **요약**: 현재 트렌드를 2-3문장으로 요약하세요.
2. **추천**: AI 콘텐츠 제작자가 지금 만들면 좋을 콘텐츠 3-5개를 구체적으로 추천하세요.

응답 형식:
## 요약
[요약 내용]

## 추천
- [추천 1]
- [추천 2]
- [추천 3]
"""
        return prompt

    def _generate_fallback_insights(
        self,
        genre_rankings: List[GenreRanking],
        golden_zone: List[GoldenZoneVideo],
        current_events: List[Dict]
    ) -> Tuple[str, List[str]]:
        """Gemini 없을 때 폴백 인사이트"""

        # 요약
        top_genre = genre_rankings[0] if genre_rankings else None
        summary = ""

        if top_genre:
            summary = f"현재 {top_genre.genre_kr} 장르가 가장 인기입니다 (평균 {top_genre.avg_views:,}뷰). "

        if golden_zone:
            summary += f"복제 가능한 황금 구역 영상 {len(golden_zone)}개를 발견했습니다. "

        if current_events:
            event_names = [e["name_kr"] for e in current_events[:2]]
            summary += f"현재 시즌: {', '.join(event_names)}."

        if not summary:
            summary = "트렌드 데이터를 분석했습니다."

        # 추천
        recommendations = []

        if current_events:
            for event in current_events[:2]:
                genres = event.get("genres", [])[:2]
                if genres:
                    recommendations.append(
                        f"{event['name_kr']} 시즌에 맞는 {'/'.join(genres)} 콘텐츠 제작"
                    )

        if golden_zone:
            top_golden = golden_zone[0]
            recommendations.append(
                f"황금 구역 벤치마킹: '{top_golden.title[:20]}...' 스타일 참고"
            )

        if top_genre and top_genre.feasibility_avg >= 70:
            recommendations.append(
                f"{top_genre.genre_kr} 장르 진입 추천 (가성비 점수 {top_genre.feasibility_avg:.0f})"
            )

        if not recommendations:
            recommendations = ["수집된 트렌드 데이터를 확인하세요."]

        return summary, recommendations

    # --------------------------------------------------------
    # 저장/로드
    # --------------------------------------------------------

    def _save_report(self, report: TrendReport) -> Path:
        """리포트 저장"""
        filename = f"report_{report.report_id}.json"
        filepath = self.reports_dir / filename

        # dataclass를 dict로 변환
        data = {
            "report_id": report.report_id,
            "report_type": report.report_type,
            "period_start": report.period_start,
            "period_end": report.period_end,
            "generated_at": report.generated_at,
            "total_videos_analyzed": report.total_videos_analyzed,
            "countries_analyzed": report.countries_analyzed,
            "genre_rankings": [asdict(r) for r in report.genre_rankings],
            "golden_zone_videos": [asdict(g) for g in report.golden_zone_videos],
            "competitor_analyses": [asdict(c) for c in report.competitor_analyses],
            "current_season_events": report.current_season_events,
            "recommended_genres": report.recommended_genres,
            "trending_keywords": report.trending_keywords,
            "ai_summary": report.ai_summary,
            "ai_recommendations": report.ai_recommendations,
        }

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        logger.info(f"리포트 저장: {filepath}")
        return filepath

    def load_report(self, report_id: str) -> Optional[TrendReport]:
        """리포트 로드"""
        filepath = self.reports_dir / f"report_{report_id}.json"

        if not filepath.exists():
            return None

        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)

        return TrendReport(
            report_id=data["report_id"],
            report_type=data["report_type"],
            period_start=data["period_start"],
            period_end=data["period_end"],
            generated_at=data["generated_at"],
            total_videos_analyzed=data["total_videos_analyzed"],
            countries_analyzed=data["countries_analyzed"],
            genre_rankings=[GenreRanking(**r) for r in data["genre_rankings"]],
            golden_zone_videos=[GoldenZoneVideo(**g) for g in data["golden_zone_videos"]],
            competitor_analyses=[CompetitorAnalysis(**c) for c in data["competitor_analyses"]],
            current_season_events=data["current_season_events"],
            recommended_genres=data["recommended_genres"],
            trending_keywords=data["trending_keywords"],
            ai_summary=data["ai_summary"],
            ai_recommendations=data["ai_recommendations"],
        )

    def list_reports(self, report_type: str = None) -> List[Dict]:
        """저장된 리포트 목록"""
        pattern = "report_*.json"
        files = sorted(self.reports_dir.glob(pattern), reverse=True)

        reports = []
        for f in files[:20]:
            try:
                with open(f, 'r', encoding='utf-8') as fp:
                    data = json.load(fp)
                    if report_type and data.get("report_type") != report_type:
                        continue
                    reports.append({
                        "report_id": data.get("report_id"),
                        "report_type": data.get("report_type"),
                        "generated_at": data.get("generated_at"),
                        "total_videos": data.get("total_videos_analyzed"),
                        "filepath": str(f)
                    })
            except (json.JSONDecodeError, KeyError, OSError):
                pass

        return reports

    # --------------------------------------------------------
    # 트렌드 매트릭스 뷰
    # --------------------------------------------------------

    def get_trend_matrix(
        self,
        videos: List[VideoMetadata]
    ) -> Dict[str, List[VideoMetadata]]:
        """
        트렌드 vs 제작가능 매트릭스

        Returns:
            {
                "golden": [...],      # 고조회수 + 복제가능
                "regret": [...],      # 고조회수 + 복제불가
                "practice": [...],    # 저조회수 + 복제가능
                "ignore": [...]       # 저조회수 + 복제불가
            }
        """
        matrix = {
            "golden": [],    # 황금 구역
            "regret": [],    # 아쉬운 구역 (DROP)
            "practice": [],  # 연습용
            "ignore": []     # 무시
        }

        view_threshold = 100000  # 10만 뷰 기준
        feasibility_threshold = 70  # 가성비 70점 기준

        for video in videos:
            high_views = video.view_count >= view_threshold
            high_feasibility = (video.feasibility_score or 0) >= feasibility_threshold
            can_replicate = video.can_replicate or False

            if high_views and high_feasibility and can_replicate:
                matrix["golden"].append(video)
            elif high_views and (not high_feasibility or not can_replicate):
                matrix["regret"].append(video)
            elif not high_views and high_feasibility and can_replicate:
                matrix["practice"].append(video)
            else:
                matrix["ignore"].append(video)

        # 각 구역 정렬
        for key in matrix:
            matrix[key].sort(key=lambda v: v.view_count, reverse=True)

        return matrix

    # --------------------------------------------------------
    # 시즌 알림
    # --------------------------------------------------------

    def get_seasonal_recommendations(self) -> Dict:
        """현재 시즌 기반 추천"""
        current_events = SeasonalEvent.get_current_events()
        upcoming_events = SeasonalEvent.get_upcoming_events(days_ahead=30)
        recommended_genres = SeasonalEvent.get_recommended_genres()

        return {
            "current_month": datetime.now().month,
            "current_events": current_events,
            "upcoming_events": upcoming_events,
            "recommended_genres": recommended_genres,
            "genre_names_kr": {g: GENRE_KR_NAMES.get(g, g) for g in recommended_genres}
        }


# ============================================================
# 유틸리티 함수
# ============================================================

def format_report_summary(report: TrendReport) -> str:
    """리포트 요약 문자열 생성"""
    lines = [
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"📊 트렌드 리포트: {report.report_type.upper()}",
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"생성일: {report.generated_at[:10]}",
        f"분석 영상: {report.total_videos_analyzed}개",
        f"분석 국가: {', '.join(report.countries_analyzed)}",
        "",
        "📈 장르 TOP 5:",
    ]

    for i, genre in enumerate(report.genre_rankings[:5], 1):
        lines.append(f"  {i}. {genre.genre_kr}: {genre.video_count}개 (평균 {genre.avg_views:,}뷰)")

    lines.append("")
    lines.append("🏆 황금 구역 TOP 3:")

    for i, golden in enumerate(report.golden_zone_videos[:3], 1):
        lines.append(f"  {i}. {golden.title[:40]}...")
        lines.append(f"     {golden.view_count:,}뷰 | {golden.clone_difficulty} | {golden.style_type}")

    if report.current_season_events:
        lines.append("")
        lines.append("🎃 현재 시즌:")
        for event in report.current_season_events:
            lines.append(f"  • {event['name_kr']}: {', '.join(event['genres'][:3])}")

    lines.append("")
    lines.append("💡 AI 추천:")
    for rec in report.ai_recommendations[:3]:
        lines.append(f"  • {rec}")

    lines.append("")
    lines.append(f"📝 요약: {report.ai_summary[:200]}...")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    return "\n".join(lines)


# ============================================================
# CLI 테스트
# ============================================================

def main():
    """CLI 테스트"""
    print("\n=== Reverie Insight - 트렌드 리포터 ===\n")

    # 시즌 추천 테스트
    reporter = TrendReporter()

    seasonal = reporter.get_seasonal_recommendations()
    print(f"현재 월: {seasonal['current_month']}월")
    print(f"\n현재 시즌 이벤트:")
    for event in seasonal["current_events"]:
        print(f"  • {event['name_kr']}: {', '.join(event['genres'][:3])}")

    print(f"\n추천 장르: {', '.join(seasonal['recommended_genres'])}")

    print("\n다가오는 이벤트 (30일 내):")
    for event in seasonal["upcoming_events"][:5]:
        print(f"  • [{event['month']}월] {event['name_kr']}")


if __name__ == "__main__":
    main()
