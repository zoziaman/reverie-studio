# Reverie Insight - 트렌드 수집기
# Version: 1.0.0

"""
YouTube 트렌드 수집기

국가별 인기 동영상을 수집하고 메타데이터를 저장합니다.
"""

import os
import json
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, asdict
from pathlib import Path

# Google API
try:
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    YOUTUBE_API_AVAILABLE = True
except ImportError:
    YOUTUBE_API_AVAILABLE = False

logger = logging.getLogger(__name__)


# ============================================================
# 지원 국가 목록
# ============================================================

SUPPORTED_COUNTRIES = {
    "KR": {"name": "한국", "name_en": "South Korea"},
    "US": {"name": "미국", "name_en": "United States"},
    "JP": {"name": "일본", "name_en": "Japan"},
    "TW": {"name": "대만", "name_en": "Taiwan"},
    "VN": {"name": "베트남", "name_en": "Vietnam"},
    "TH": {"name": "태국", "name_en": "Thailand"},
    "ID": {"name": "인도네시아", "name_en": "Indonesia"},
    "PH": {"name": "필리핀", "name_en": "Philippines"},
    "GB": {"name": "영국", "name_en": "United Kingdom"},
    "DE": {"name": "독일", "name_en": "Germany"},
    "FR": {"name": "프랑스", "name_en": "France"},
    "BR": {"name": "브라질", "name_en": "Brazil"},
    "MX": {"name": "멕시코", "name_en": "Mexico"},
    "IN": {"name": "인도", "name_en": "India"},
}

# YouTube 카테고리 (우리가 관심있는 것들)
VIDEO_CATEGORIES = {
    "1": "Film & Animation",
    "10": "Music",
    "15": "Pets & Animals",
    "17": "Sports",
    "20": "Gaming",
    "22": "People & Blogs",
    "23": "Comedy",
    "24": "Entertainment",
    "25": "News & Politics",
    "26": "Howto & Style",
    "27": "Education",
    "28": "Science & Technology",
}

# Faceless 콘텐츠가 많은 카테고리
FACELESS_FRIENDLY_CATEGORIES = ["1", "24", "27", "28"]  # Film, Entertainment, Education, Science


# ============================================================
# 데이터 클래스
# ============================================================

@dataclass
class VideoMetadata:
    """수집된 영상 메타데이터"""
    video_id: str
    title: str
    description: str
    channel_id: str
    channel_title: str
    published_at: str
    thumbnail_url: str
    thumbnail_high_url: str
    view_count: int
    like_count: int
    comment_count: int
    duration: str
    category_id: str
    category_name: str
    tags: List[str]
    country_code: str
    collected_at: str

    # 분석용 필드 (나중에 채워짐)
    content_type: Optional[str] = None  # REAL / FACELESS
    style_type: Optional[str] = None    # silhouette, slideshow, etc.
    feasibility_score: Optional[int] = None
    can_replicate: Optional[bool] = None


@dataclass
class CollectionResult:
    """수집 결과"""
    country_code: str
    country_name: str
    collected_at: str
    total_videos: int
    videos: List[VideoMetadata]
    errors: List[str]


# ============================================================
# 트렌드 수집기
# ============================================================

class TrendCollector:
    """YouTube 트렌드 수집기"""

    def __init__(self, api_key: str, data_dir: str = None):
        """
        Args:
            api_key: YouTube Data API v3 키
            data_dir: 데이터 저장 디렉토리 (기본: ./data/insight)
        """
        if not YOUTUBE_API_AVAILABLE:
            raise ImportError("google-api-python-client 패키지가 필요합니다. pip install google-api-python-client")

        self.api_key = api_key
        self.youtube = build('youtube', 'v3', developerKey=api_key)

        # 데이터 저장 경로
        if data_dir is None:
            base_dir = Path(__file__).parent.parent.parent  # src/insight -> project root
            data_dir = base_dir / "data" / "insight"
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"TrendCollector 초기화 완료. 데이터 저장 경로: {self.data_dir}")

    def get_supported_countries(self) -> Dict[str, Dict]:
        """지원 국가 목록 반환"""
        return SUPPORTED_COUNTRIES.copy()

    def collect_trending(
        self,
        country_code: str = "KR",
        max_results: int = 50,
        category_id: Optional[str] = None,
        save_to_file: bool = True
    ) -> CollectionResult:
        """
        특정 국가의 인기 동영상 수집

        Args:
            country_code: 국가 코드 (KR, US, JP 등)
            max_results: 수집할 최대 영상 수 (최대 50)
            category_id: 특정 카테고리만 수집 (None이면 전체)
            save_to_file: 결과를 파일로 저장할지 여부

        Returns:
            CollectionResult: 수집 결과
        """
        country_code = country_code.upper()

        if country_code not in SUPPORTED_COUNTRIES:
            raise ValueError(f"지원하지 않는 국가 코드: {country_code}. 지원 국가: {list(SUPPORTED_COUNTRIES.keys())}")

        country_info = SUPPORTED_COUNTRIES[country_code]
        collected_at = datetime.now().isoformat()
        videos = []
        errors = []

        logger.info(f"[{country_code}] {country_info['name']} 트렌드 수집 시작 (max: {max_results})")

        try:
            # 인기 동영상 목록 가져오기
            request = self.youtube.videos().list(
                part="snippet,contentDetails,statistics",
                chart="mostPopular",
                regionCode=country_code,
                maxResults=min(max_results, 50),
                videoCategoryId=category_id
            )
            response = request.execute()

            for item in response.get('items', []):
                try:
                    video = self._parse_video_item(item, country_code)
                    videos.append(video)
                except Exception as e:
                    error_msg = f"영상 파싱 오류 (ID: {item.get('id', 'unknown')}): {e}"
                    logger.warning(error_msg)
                    errors.append(error_msg)

            logger.info(f"[{country_code}] {len(videos)}개 영상 수집 완료")

        except HttpError as e:
            error_msg = f"YouTube API 오류: {e}"
            logger.error(error_msg)
            errors.append(error_msg)
        except Exception as e:
            error_msg = f"수집 중 오류: {e}"
            logger.error(error_msg)
            errors.append(error_msg)

        # 결과 생성
        result = CollectionResult(
            country_code=country_code,
            country_name=country_info['name'],
            collected_at=collected_at,
            total_videos=len(videos),
            videos=videos,
            errors=errors
        )

        # 파일 저장
        if save_to_file and videos:
            self._save_result(result)

        return result

    def collect_multiple_countries(
        self,
        country_codes: List[str],
        max_results_per_country: int = 50,
        category_id: Optional[str] = None
    ) -> Dict[str, CollectionResult]:
        """
        여러 국가의 트렌드 수집

        Args:
            country_codes: 국가 코드 리스트
            max_results_per_country: 국가당 최대 영상 수
            category_id: 특정 카테고리만 수집

        Returns:
            Dict[country_code, CollectionResult]
        """
        results = {}

        for code in country_codes:
            try:
                result = self.collect_trending(
                    country_code=code,
                    max_results=max_results_per_country,
                    category_id=category_id
                )
                results[code] = result
            except Exception as e:
                logger.error(f"[{code}] 수집 실패: {e}")
                results[code] = CollectionResult(
                    country_code=code,
                    country_name=SUPPORTED_COUNTRIES.get(code, {}).get('name', code),
                    collected_at=datetime.now().isoformat(),
                    total_videos=0,
                    videos=[],
                    errors=[str(e)]
                )

        return results

    def collect_faceless_friendly(
        self,
        country_code: str = "KR",
        max_results: int = 50
    ) -> CollectionResult:
        """
        Faceless 콘텐츠가 많은 카테고리에서만 수집
        (Film & Animation, Entertainment, Education, Science & Technology)

        Args:
            country_code: 국가 코드
            max_results: 최대 영상 수

        Returns:
            CollectionResult
        """
        all_videos = []
        all_errors = []

        per_category = max_results // len(FACELESS_FRIENDLY_CATEGORIES)

        for cat_id in FACELESS_FRIENDLY_CATEGORIES:
            try:
                result = self.collect_trending(
                    country_code=country_code,
                    max_results=per_category,
                    category_id=cat_id,
                    save_to_file=False
                )
                all_videos.extend(result.videos)
                all_errors.extend(result.errors)
            except Exception as e:
                all_errors.append(f"카테고리 {cat_id} 수집 실패: {e}")

        # 중복 제거 (video_id 기준)
        seen_ids = set()
        unique_videos = []
        for v in all_videos:
            if v.video_id not in seen_ids:
                seen_ids.add(v.video_id)
                unique_videos.append(v)

        country_info = SUPPORTED_COUNTRIES.get(country_code, {"name": country_code})

        result = CollectionResult(
            country_code=country_code,
            country_name=country_info['name'],
            collected_at=datetime.now().isoformat(),
            total_videos=len(unique_videos),
            videos=unique_videos,
            errors=all_errors
        )

        self._save_result(result)
        return result

    def _parse_video_item(self, item: Dict, country_code: str) -> VideoMetadata:
        """YouTube API 응답을 VideoMetadata로 변환"""
        snippet = item.get('snippet', {})
        statistics = item.get('statistics', {})
        content_details = item.get('contentDetails', {})
        thumbnails = snippet.get('thumbnails', {})

        # 썸네일 URL (고화질 우선)
        thumb_default = thumbnails.get('default', {}).get('url', '')
        thumb_high = thumbnails.get('high', {}).get('url', '') or \
                     thumbnails.get('medium', {}).get('url', '') or \
                     thumb_default

        # 카테고리 이름
        cat_id = snippet.get('categoryId', '')
        cat_name = VIDEO_CATEGORIES.get(cat_id, 'Unknown')

        return VideoMetadata(
            video_id=item.get('id', ''),
            title=snippet.get('title', ''),
            description=snippet.get('description', '')[:500],  # 설명 500자 제한
            channel_id=snippet.get('channelId', ''),
            channel_title=snippet.get('channelTitle', ''),
            published_at=snippet.get('publishedAt', ''),
            thumbnail_url=thumb_default,
            thumbnail_high_url=thumb_high,
            view_count=int(statistics.get('viewCount', 0)),
            like_count=int(statistics.get('likeCount', 0)),
            comment_count=int(statistics.get('commentCount', 0)),
            duration=content_details.get('duration', ''),
            category_id=cat_id,
            category_name=cat_name,
            tags=snippet.get('tags', [])[:20],  # 태그 20개 제한
            country_code=country_code,
            collected_at=datetime.now().isoformat()
        )

    def _save_result(self, result: CollectionResult) -> Path:
        """수집 결과를 JSON 파일로 저장"""
        # 파일명: trending_KR_20260126_143022.json
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"trending_{result.country_code}_{timestamp}.json"
        filepath = self.data_dir / filename

        # dataclass를 dict로 변환
        data = {
            "country_code": result.country_code,
            "country_name": result.country_name,
            "collected_at": result.collected_at,
            "total_videos": result.total_videos,
            "errors": result.errors,
            "videos": [asdict(v) for v in result.videos]
        }

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        logger.info(f"결과 저장: {filepath}")
        return filepath

    def load_latest_result(self, country_code: str) -> Optional[CollectionResult]:
        """가장 최근 수집 결과 로드"""
        pattern = f"trending_{country_code}_*.json"
        files = sorted(self.data_dir.glob(pattern), reverse=True)

        if not files:
            return None

        latest_file = files[0]
        return self.load_result_from_file(latest_file)

    def load_result_from_file(self, filepath: Path) -> CollectionResult:
        """파일에서 수집 결과 로드"""
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)

        videos = [VideoMetadata(**v) for v in data.get('videos', [])]

        return CollectionResult(
            country_code=data.get('country_code', ''),
            country_name=data.get('country_name', ''),
            collected_at=data.get('collected_at', ''),
            total_videos=data.get('total_videos', 0),
            videos=videos,
            errors=data.get('errors', [])
        )

    def get_collection_history(self, country_code: str = None) -> List[Dict]:
        """수집 히스토리 조회"""
        if country_code:
            pattern = f"trending_{country_code}_*.json"
        else:
            pattern = "trending_*.json"

        files = sorted(self.data_dir.glob(pattern), reverse=True)

        history = []
        for f in files[:20]:  # 최근 20개만
            try:
                with open(f, 'r', encoding='utf-8') as fp:
                    data = json.load(fp)
                    history.append({
                        "filename": f.name,
                        "country_code": data.get('country_code'),
                        "country_name": data.get('country_name'),
                        "collected_at": data.get('collected_at'),
                        "total_videos": data.get('total_videos'),
                        "filepath": str(f)
                    })
            except (json.JSONDecodeError, KeyError, OSError):
                pass

        return history


# ============================================================
# CLI 테스트용
# ============================================================

def main():
    """CLI 테스트"""
    import sys

    # API 키 확인
    api_key = os.environ.get('YOUTUBE_API_KEY')
    if not api_key:
        print("환경변수 YOUTUBE_API_KEY가 설정되지 않았습니다.")
        print("사용법: set YOUTUBE_API_KEY=your_api_key")
        sys.exit(1)

    collector = TrendCollector(api_key)

    print("\n=== Reverie Insight - 트렌드 수집기 ===\n")
    print("지원 국가:")
    for code, info in SUPPORTED_COUNTRIES.items():
        print(f"  {code}: {info['name']} ({info['name_en']})")

    print("\n한국 트렌드 수집 중...")
    result = collector.collect_trending("KR", max_results=10)

    print(f"\n수집 완료: {result.total_videos}개")
    print("\n상위 5개 영상:")
    for i, video in enumerate(result.videos[:5], 1):
        print(f"  {i}. [{video.category_name}] {video.title[:50]}...")
        print(f"     조회수: {video.view_count:,} | 채널: {video.channel_title}")
        print()


if __name__ == "__main__":
    main()
