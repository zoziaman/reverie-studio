# src/modules_pro/youtube_uploader.py
"""
YouTube 자동 업로드 모듈
- OAuth 인증
- 영상 업로드
- 썸네일 첨부
- 제목/설명/태그 자동 생성
- [v54.1] 썸네일 교체 API
"""
import os
import pickle
import logging
import random
import time
from typing import Any, Dict
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from utils.secret_redaction import redact_sensitive_text

logger = logging.getLogger(__name__)

# v62.22: Fernet 토큰 암호화 (pickle 직접 노출 방지)
try:
    from utils.crypto_utils import (
        derive_fernet_key, fernet_encrypt_bytes, fernet_decrypt_bytes,
        FERNET_AVAILABLE
    )
    from utils.hardware_id import get_hardware_id as _get_hw_id
    _UPLOAD_FERNET_KEY = derive_fernet_key(_get_hw_id()) if FERNET_AVAILABLE else None
except ImportError:
    FERNET_AVAILABLE = False
    _UPLOAD_FERNET_KEY = None


def _load_encrypted_pickle(path: str):
    """
    v62.22: Fernet 암호화된 pickle 로드 (레거시 평문 pickle 자동 마이그레이션)

    동작:
    1. 텍스트로 읽기 시도 → gAAAAA 시작이면 Fernet 복호화 → pickle.loads
    2. 실패 시 바이너리 pickle (레거시) → 성공 시 Fernet으로 자동 마이그레이션
    """
    # Case 1: Fernet 암호화된 토큰
    if FERNET_AVAILABLE and _UPLOAD_FERNET_KEY:
        try:
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read().strip()
            if content.startswith('gAAAAA'):
                decrypted = fernet_decrypt_bytes(content.encode('utf-8'), _UPLOAD_FERNET_KEY)
                return pickle.loads(decrypted)
        except Exception:
            pass  # Fernet 실패 → 레거시 폴백

    # Case 2: 레거시 바이너리 pickle
    try:
        with open(path, 'rb') as f:
            creds = pickle.load(f)
        # 자동 마이그레이션: Fernet으로 재저장
        if FERNET_AVAILABLE and _UPLOAD_FERNET_KEY:
            try:
                _save_encrypted_pickle(path, creds)
                logger.info(f"[YouTube] pickle → Fernet 자동 마이그레이션 완료: {path}")
            except Exception as e:
                logger.warning(f"[YouTube] pickle 마이그레이션 실패: {redact_sensitive_text(e)}")
        return creds
    except Exception as e:
        logger.error(f"[YouTube] 토큰 로드 실패: {redact_sensitive_text(e)}")
        return None


def _save_encrypted_pickle(path: str, creds):
    """
    v62.22: Fernet 암호화된 pickle 저장

    Fernet 사용 가능 → 암호화 텍스트로 저장
    Fernet 미사용 → 레거시 바이너리 pickle
    """
    if FERNET_AVAILABLE and _UPLOAD_FERNET_KEY:
        raw_bytes = pickle.dumps(creds)
        encrypted = fernet_encrypt_bytes(raw_bytes, _UPLOAD_FERNET_KEY)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(encrypted.decode('utf-8'))
    else:
        with open(path, 'wb') as f:
            pickle.dump(creds, f)


class YouTubeUploader:
    """
    YouTube 업로드 관리자

    v53: 채널별 토큰 분리 지원
    - Horror 채널: youtube_token_horror.pickle
    - Senior 채널: youtube_token_senior.pickle

    v54.1: 썸네일 교체 API 추가
    """

    # v54.1: 썸네일 교체도 가능하도록 스코프 확장
    SCOPES = [
        'https://www.googleapis.com/auth/youtube.upload',
        'https://www.googleapis.com/auth/youtube.force-ssl',  # 썸네일 업데이트용
    ]

    # 채널 타입 매핑
    CHANNEL_TOKEN_MAP = {
        "horror": "youtube_token_horror.pickle",
        "senior": "youtube_token_senior.pickle",
        "touching": "youtube_token_senior.pickle",  # 시니어와 동일
        "makjang": "youtube_token_horror.pickle",   # 공포와 동일 (또는 별도 설정 가능)
    }

    def __init__(self, credentials_path: str = None, channel_name: str = None, channel_type: str = None):
        """
        Args:
            credentials_path: OAuth credentials.json 경로
            channel_name: 채널 이름 (표시용)
            channel_type: 채널 타입 ("horror", "senior", "touching", "makjang")
                         - 타입에 따라 다른 토큰 파일 사용
        """
        # 기본 경로 설정 (config.DATA_DIR 기반)
        try:
            from config.settings import config
            data_dir = config.DATA_DIR
        except Exception:
            data_dir = "data"

        if credentials_path:
            self.credentials_path = credentials_path
        else:
            self.credentials_path = os.path.join(data_dir, "credentials.json")

        # v53: 채널 타입에 따라 토큰 파일 분리
        self.channel_type = channel_type or "horror"  # 기본값은 horror
        token_filename = self.CHANNEL_TOKEN_MAP.get(self.channel_type, "youtube_token.pickle")
        self.token_path = os.path.join(data_dir, token_filename)

        self.service = None
        self.channel_name = channel_name

        # 로깅
        logger.info(f"[YouTube] 채널 타입: {self.channel_type}, 토큰: {token_filename}")
    
    def authenticate(self) -> bool:
        """
        Google OAuth 인증
        
        Returns:
            bool: 인증 성공 여부
        """
        creds = None
        
        # 저장된 토큰 확인 (v62.22: Fernet 암호화 지원 + 레거시 pickle 자동 마이그레이션)
        if os.path.exists(self.token_path):
            creds = _load_encrypted_pickle(self.token_path)
        
        # 토큰이 없거나 만료됨
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                # 새로 인증
                if not os.path.exists(self.credentials_path):
                    logger.error(f"[ERROR] credentials.json 파일이 없습니다: {self.credentials_path}")
                    logger.error("   Google Cloud Console에서 OAuth 클라이언트 ID를 생성하세요.")
                    return False
                
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.credentials_path, 
                    self.SCOPES
                )
                creds = flow.run_local_server(port=0)
            
            # 토큰 저장 (v62.22: Fernet 암호화)
            _save_encrypted_pickle(self.token_path, creds)
        
        # YouTube API 서비스 생성
        self.service = build('youtube', 'v3', credentials=creds)
        return True
    
    def upload_video(
        self,
        video_path: str,
        title: str,
        description: str = "",
        tags: list = None,
        category: str = "24",  # Entertainment
        privacy: str = "private",  # v53: 기본값 private로 변경 (public/private/unlisted)
        thumbnail_path: str = None,
        contains_synthetic_media: bool = True,
        made_for_kids: bool = False,
        channel_mode: str = "",
        verified_true_story: bool = False,
        policy_guard: bool = True
    ) -> dict:
        """
        영상 업로드
        
        Args:
            video_path: 영상 파일 경로
            title: 제목
            description: 설명
            tags: 태그 리스트
            category: 카테고리 ID
            privacy: 공개 설정
            thumbnail_path: 썸네일 경로 (선택)
            contains_synthetic_media: YouTube altered/synthetic content disclosure
            made_for_kids: 아동용 콘텐츠 여부
            channel_mode: 정책 가드용 채널 모드
            verified_true_story: 검증된 실화임을 별도로 확인한 경우만 True
            policy_guard: 메타데이터 정책 보정/차단 사용 여부
        
        Returns:
            dict: 업로드 결과 (video_id, url 등)
        """
        # 기본값
        if tags is None:
            tags = []
        if not description:
            description = "AI 도구를 활용해 제작한 창작 드라마입니다."

        policy_report: Dict[str, Any] = {"ok": True, "warnings": [], "errors": []}
        if policy_guard:
            from utils.youtube_policy_guard import prepare_upload_metadata

            guard_result = prepare_upload_metadata(
                title=title,
                description=description,
                tags=tags,
                channel_mode=channel_mode or self.channel_type,
                privacy=privacy,
                verified_true_story=verified_true_story,
            )
            policy_report = guard_result.as_dict()
            if not guard_result.ok:
                raise ValueError(f"YouTube 정책 가드 차단: {'; '.join(guard_result.errors)}")

            title = guard_result.title
            description = guard_result.description
            tags = guard_result.tags

            for warning in guard_result.warnings:
                logger.warning("[YouTubePolicy] %s", warning)

        if not self.service:
            if not self.authenticate():
                raise Exception("YouTube 인증 실패")
        
        # 메타데이터
        body = {
            'snippet': {
                'title': title,
                'description': description,
                'tags': tags,
                'categoryId': category
            },
            'status': {
                'privacyStatus': privacy,
                'selfDeclaredMadeForKids': bool(made_for_kids),
                'containsSyntheticMedia': bool(contains_synthetic_media)
            }
        }
        
        # 미디어 업로드
        media = MediaFileUpload(
            video_path,
            chunksize=-1,  # 한 번에 업로드
            resumable=True
        )
        
        logger.info(f"\n[UPLOAD] YouTube 업로드 시작...")
        logger.info(f"   제목: {title}")
        logger.info(f"   공개: {privacy}")

        # 업로드 요청
        request = self.service.videos().insert(
            part='snippet,status',
            body=body,
            media_body=media
        )

        # 실행 (Google 권장 지수 백오프 retry)
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = None
                while response is None:
                    status, response = request.next_chunk()
                    if status:
                        progress = int(status.progress() * 100)
                        logger.info(f"   업로드 진행: {progress}%")
                break  # 성공 시 루프 탈출
            except HttpError as e:
                if e.resp.status in [500, 502, 503, 504] and attempt < max_retries - 1:
                    delay = (2 ** attempt) * (0.5 + random.random())
                    logger.warning(f"[UPLOAD] 서버 에러 {e.resp.status}. {delay:.1f}초 후 재시도 ({attempt+1}/{max_retries})")
                    time.sleep(delay)
                    # resumable upload이므로 같은 request로 재시도 가능
                else:
                    raise
            except (ConnectionError, TimeoutError) as e:
                if attempt < max_retries - 1:
                    delay = (2 ** attempt) * (0.5 + random.random())
                    logger.warning(f"[UPLOAD] 연결 오류. {delay:.1f}초 후 재시도 ({attempt+1}/{max_retries}): {redact_sensitive_text(e)}")
                    time.sleep(delay)
                else:
                    raise

        video_id = response['id']
        video_url = f"https://www.youtube.com/watch?v={video_id}"

        logger.info(f"   [OK] 업로드 완료!")
        logger.info(f"   Video ID: {video_id}")
        logger.info(f"   URL: {video_url}")
        
        # 썸네일 업로드 (선택)
        if thumbnail_path and os.path.exists(thumbnail_path):
            self.upload_thumbnail(video_id, thumbnail_path)
        
        return {
            'video_id': video_id,
            'url': video_url,
            'title': title,
            'policy_report': policy_report
        }
    
    def upload_thumbnail(self, video_id: str, thumbnail_path: str):
        """
        썸네일 업로드 (retry 포함)

        Args:
            video_id: 영상 ID
            thumbnail_path: 썸네일 경로
        """
        logger.info(f"\n[THUMB] 썸네일 업로드 중...")

        max_retries = 2
        for attempt in range(max_retries):
            try:
                request = self.service.thumbnails().set(
                    videoId=video_id,
                    media_body=MediaFileUpload(thumbnail_path)
                )
                response = request.execute()
                logger.info(f"   [OK] 썸네일 업로드 완료!")
                return response
            except HttpError as e:
                if attempt < max_retries - 1:
                    time.sleep(3)
                    logger.warning(f"[THUMB] 재시도: {redact_sensitive_text(e)}")
                else:
                    raise
    
    def generate_title(self, top_text: str, main_text: str) -> str:
        """
        제목 자동 생성
        
        Args:
            top_text: 상단 텍스트
            main_text: 메인 제목
        
        Returns:
            str: 생성된 제목
        """
        # 이모지 제거
        import re
        top_text = re.sub(r'[^\w\s가-힣a-zA-Z0-9.,!?~\-]', '', top_text)
        main_text = re.sub(r'[^\w\s가-힣a-zA-Z0-9.,!?~\-]', '', main_text)
        
        return f"{top_text} | {main_text}"
    
    def generate_description(self, main_text: str, tags: list, channel_mode: str = "daily_life_toon") -> str:
        """
        설명 자동 생성
        
        Args:
            main_text: 메인 제목
            tags: 태그 리스트
            channel_mode: 채널 모드 (horror/touching/makjang)
        
        Returns:
            str: 생성된 설명
        """
        # 이모지 제거
        import re
        main_text = re.sub(r'[^\w\s가-힣a-zA-Z0-9.,!?~\-]', '', main_text)
        
        # 채널별 고정 해시태그: 검증되지 않은 실화/과장형 문구는 기본값에서 제외
        fixed_hashtags = {
            "daily_life_toon": ["#일상툰", "#영상툰", "#웹툰드라마", "#공감툰", "#레베리"],
            "mystery_toon": ["#미스터리툰", "#영상툰", "#웹툰드라마", "#반전", "#레베리"],
            "videotoon": ["#영상툰", "#웹툰드라마", "#AI창작", "#레베리"],
            "horror": ["#공포", "#공포드라마", "#무서운이야기", "#공포라디오", "#괴담"],
            "touching": ["#감동", "#시니어", "#인생이야기", "#힐링", "#눈물"],
            "makjang": ["#막장", "#가족드라마", "#반전드라마", "#인생드라마", "#반전"],
            "scam_alert": ["#사기예방", "#보이스피싱예방", "#시니어안전", "#금융사기주의", "#사기경보"],
            "senior_scam_alert": ["#사기예방", "#보이스피싱예방", "#시니어안전", "#금융사기주의", "#사기경보"],
        }
        
        # 기본 해시태그 (채널 모드에 따라)
        base_hashtags = fixed_hashtags.get(channel_mode, fixed_hashtags["daily_life_toon"])
        
        # 동적 해시태그 (태그에서 생성)
        dynamic_hashtags = [f"#{tag}" for tag in tags if tag]
        
        # 합치기 (중복 제거)
        all_hashtags = list(dict.fromkeys(base_hashtags + dynamic_hashtags))
        
        # 해시태그 문자열 생성
        hashtag_str = " ".join(all_hashtags)
        
        description = f"""🎬 {main_text}

이 영상은 AI 음성/이미지/편집 도구를 활용한 창작 드라마입니다.
실제 인물·사건과 다를 수 있으며, 검증되지 않은 실화로 오해되지 않도록 사례 재구성 형식으로 제작되었습니다.

📌 채널 구독과 좋아요는 큰 힘이 됩니다!
🔔 알림 설정을 켜시면 새 영상을 가장 먼저 보실 수 있습니다.

감사합니다! 😊

━━━━━━━━━━━━━━━━━━━━━━
{hashtag_str}
"""

        if channel_mode in {"scam_alert", "senior_scam_alert"}:
            description = description.replace(
                "감사합니다! 😊",
                "이 콘텐츠는 사기 예방 목적의 창작 재구성이며, 사기 수법을 따라 하도록 돕기 위한 영상이 아닙니다.\n\n감사합니다! 😊",
            )

        return description
    
    def get_channel_info(self) -> dict:
        """
        채널 정보 가져오기

        Returns:
            dict: 채널 정보 (id, title, subscriber_count 등)
        """
        if not self.service:
            if not self.authenticate():
                return None

        request = self.service.channels().list(
            part='snippet,statistics',
            mine=True
        )

        response = request.execute()

        if response['items']:
            channel = response['items'][0]
            return {
                'id': channel['id'],
                'title': channel['snippet']['title'],
                'subscribers': channel['statistics']['subscriberCount'],
                'videos': channel['statistics']['videoCount'],
                'views': channel['statistics']['viewCount']
            }

        return None

    # =========================================================
    # v54.1: 썸네일 교체 API
    # =========================================================

    def update_thumbnail(self, video_id: str, thumbnail_path: str) -> dict:
        """
        v54.1: 기존 영상의 썸네일 교체

        Args:
            video_id: 영상 ID
            thumbnail_path: 새 썸네일 경로

        Returns:
            dict: 응답 결과
        """
        if not self.service:
            if not self.authenticate():
                raise Exception("YouTube 인증 실패")

        if not os.path.exists(thumbnail_path):
            raise FileNotFoundError(f"썸네일 파일 없음: {thumbnail_path}")

        logger.info(f"\n[THUMB] 썸네일 교체 중... (video_id: {video_id})")

        try:
            request = self.service.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(thumbnail_path, mimetype='image/jpeg')
            )

            response = request.execute()
            logger.info(f"   [OK] 썸네일 교체 완료!")
            logger.info(f"썸네일 교체 성공: {video_id}")

            # v54.7.2: YouTube thumbnails.set() 응답 구조 완전 처리
            # 실제 API 응답 형식들:
            # 1. {'kind': 'youtube#thumbnailSetResponse', 'items': [{'default': {...}, 'medium': {...}}]}
            # 2. {'default': {...}, 'medium': {...}} (일부 케이스)
            # 3. 빈 응답 또는 예외적 구조
            thumbnail_url = ""
            try:
                if response:
                    # 케이스 1: items 배열 구조
                    if 'items' in response:
                        items = response.get('items', [])
                        if items and isinstance(items, list) and len(items) > 0:
                            first_item = items[0]
                            if isinstance(first_item, dict):
                                # items[0]이 thumbnail 크기별 dict인 경우
                                thumbnail_url = (
                                    first_item.get('default', {}).get('url', '') or
                                    first_item.get('medium', {}).get('url', '') or
                                    first_item.get('high', {}).get('url', '')
                                )
                    # 케이스 2: 직접 thumbnail 객체
                    elif 'default' in response or 'medium' in response:
                        thumbnail_url = (
                            response.get('default', {}).get('url', '') or
                            response.get('medium', {}).get('url', '') or
                            response.get('high', {}).get('url', '')
                        )

                    # v54.7.3: URL 추출 실패 시 디버그 로깅
                    if not thumbnail_url:
                        logger.debug(f"썸네일 URL 추출 실패. 응답 구조: {list(response.keys()) if response else 'empty'}")
            except Exception as parse_err:
                logger.warning(f"썸네일 URL 파싱 오류 (무시됨): {redact_sensitive_text(parse_err)}")

            # v54.7.3: API 호출 자체가 성공하면 썸네일은 실제로 업데이트됨
            # thumbnail_url은 확인용일 뿐, 업로드 성공 여부와 별개
            # 단, 호출자가 URL 추출 실패를 알 수 있도록 플래그 추가
            return {
                'success': True,
                'video_id': video_id,
                'thumbnail_url': thumbnail_url,
                'url_extracted': bool(thumbnail_url)  # URL 추출 성공 여부
            }

        except Exception as e:
            safe_error = redact_sensitive_text(e)
            logger.error(f"   [ERROR] 썸네일 교체 실패: {safe_error}")
            logger.error(f"썸네일 교체 실패: {video_id} - {safe_error}")
            return {
                'success': False,
                'video_id': video_id,
                'error': safe_error
            }

    def get_video_info(self, video_id: str) -> dict:
        """
        v54.1: 영상 정보 조회

        Args:
            video_id: 영상 ID

        Returns:
            dict: 영상 정보
        """
        if not self.service:
            if not self.authenticate():
                return None

        try:
            request = self.service.videos().list(
                part='snippet,statistics,contentDetails',
                id=video_id
            )

            response = request.execute()

            if response['items']:
                video = response['items'][0]
                snippet = video['snippet']
                stats = video['statistics']

                return {
                    'video_id': video_id,
                    'title': snippet['title'],
                    'description': snippet.get('description', ''),
                    'published_at': snippet['publishedAt'],
                    'thumbnail_url': snippet['thumbnails'].get('medium', {}).get('url', ''),
                    'view_count': int(stats.get('viewCount', 0)),
                    'like_count': int(stats.get('likeCount', 0)),
                    'comment_count': int(stats.get('commentCount', 0)),
                }

            return None

        except Exception as e:
            logger.error(f"영상 정보 조회 실패: {video_id} - {redact_sensitive_text(e)}")
            return None

    def update_video_metadata(
        self,
        video_id: str,
        title: str = None,
        description: str = None,
        tags: list = None
    ) -> dict:
        """
        v54.1: 영상 메타데이터 업데이트 (제목/설명/태그)

        Args:
            video_id: 영상 ID
            title: 새 제목 (None이면 변경 안함)
            description: 새 설명 (None이면 변경 안함)
            tags: 새 태그 리스트 (None이면 변경 안함)

        Returns:
            dict: 응답 결과
        """
        if not self.service:
            if not self.authenticate():
                raise Exception("YouTube 인증 실패")

        # 현재 정보 가져오기
        current_info = self.get_video_info(video_id)
        if not current_info:
            raise Exception(f"영상을 찾을 수 없음: {video_id}")

        # 업데이트할 snippet 구성
        snippet = {
            'categoryId': '24',  # Entertainment
        }

        if title:
            snippet['title'] = title
        else:
            snippet['title'] = current_info['title']

        if description:
            snippet['description'] = description
        else:
            snippet['description'] = current_info.get('description', '')

        if tags:
            snippet['tags'] = tags

        try:
            request = self.service.videos().update(
                part='snippet',
                body={
                    'id': video_id,
                    'snippet': snippet
                }
            )

            response = request.execute()
            logger.info(f"[OK] 영상 메타데이터 업데이트 완료: {video_id}")
            logger.info(f"메타데이터 업데이트 성공: {video_id}")

            return {
                'success': True,
                'video_id': video_id,
                'updated_title': response['snippet']['title']
            }

        except Exception as e:
            safe_error = redact_sensitive_text(e)
            logger.error(f"[ERROR] 메타데이터 업데이트 실패: {safe_error}")
            logger.error(f"메타데이터 업데이트 실패: {video_id} - {safe_error}")
            return {
                'success': False,
                'video_id': video_id,
                'error': safe_error
            }


# 사용 예시
if __name__ == "__main__":
    uploader = YouTubeUploader()
    
    # 인증
    if uploader.authenticate():
        logger.info("[OK] 인증 성공!")

        # 채널 정보
        info = uploader.get_channel_info()
        if info:
            logger.info(f"\n채널: {info['title']}")
            logger.info(f"구독자: {info['subscribers']}")
            logger.info(f"영상 수: {info['videos']}")

        # 업로드 (예시)
        # result = uploader.upload_video(
        #     video_path="outputs/video.mp4",
        #     title=uploader.generate_title("실화 공포", "충격적인 결말"),
        #     description=uploader.generate_description("충격적인 결말", ["공포", "실화", "미스터리"]),
        #     tags=["공포", "실화", "미스터리", "호러", "무서운이야기"],
        #     privacy="private",  # 테스트용
        #     thumbnail_path="outputs/thumbnail_REAL.jpg"
        # )
        # logger.info(f"\n업로드 완료: {result['url']}")
    else:
        logger.error("[ERROR] 인증 실패")
