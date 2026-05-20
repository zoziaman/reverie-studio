from unittest.mock import MagicMock, patch


class _FakeInsertRequest:
    def __init__(self):
        self.calls = 0

    def next_chunk(self):
        self.calls += 1
        return None, {"id": "video123"}


class _FakeVideos:
    def __init__(self):
        self.insert_body = None

    def insert(self, part, body, media_body):
        self.insert_body = body
        return _FakeInsertRequest()


class _FakeService:
    def __init__(self):
        self._videos = _FakeVideos()

    def videos(self):
        return self._videos


def test_upload_sets_synthetic_media_flag_and_sanitizes_metadata(tmp_path):
    from utils.youtube_uploader import YouTubeUploader

    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"fake mp4")

    fake_service = _FakeService()
    uploader = YouTubeUploader(channel_type="senior")
    uploader.service = fake_service

    with patch("utils.youtube_uploader.MediaFileUpload", return_value=MagicMock()):
        result = uploader.upload_video(
            video_path=str(video_path),
            title="충격 실화 | 결말",
            description="실화를 바탕으로 재구성했습니다.",
            tags=["실화", "충격"],
            privacy="private",
            channel_mode="makjang",
        )

    body = fake_service._videos.insert_body
    assert body["status"]["containsSyntheticMedia"] is True
    assert body["status"]["selfDeclaredMadeForKids"] is False
    assert "실화" not in body["snippet"]["title"]
    assert "AI 음성/이미지/편집 도구" in body["snippet"]["description"]
    assert result["policy_report"]["warnings"]


def test_upload_blocks_public_policy_errors_before_api_call(tmp_path):
    from utils.youtube_uploader import YouTubeUploader

    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"fake mp4")

    fake_service = _FakeService()
    uploader = YouTubeUploader(channel_type="senior")
    uploader.service = fake_service

    with patch("utils.youtube_uploader.MediaFileUpload", return_value=MagicMock()):
        try:
            uploader.upload_video(
                video_path=str(video_path),
                title="보이스피싱 문자 원문",
                description="010-1234-5678 계좌 123-456-789012",
                tags=["사기예방"],
                privacy="public",
                channel_mode="scam_alert",
            )
        except ValueError as exc:
            assert "YouTube 정책 가드 차단" in str(exc)
        else:
            raise AssertionError("Expected public upload to be blocked")

    assert fake_service._videos.insert_body is None
