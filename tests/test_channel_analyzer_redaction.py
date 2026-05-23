import logging

from insight.channel_analyzer import (
    ChannelAnalyzer,
    ChannelAnalysis,
    CommentAnalysis,
    TitlePattern,
    UploadPattern,
    VideoStats,
)


def _minimal_channel_analysis() -> ChannelAnalysis:
    top_video = VideoStats(
        video_id="video-1",
        title="Top story",
        description="",
        published_at="2026-01-01T00:00:00Z",
        view_count=1000,
        like_count=100,
        comment_count=10,
        duration_seconds=60,
        thumbnail_url="",
    )
    return ChannelAnalysis(
        channel_id="channel-1",
        channel_title="Channel",
        channel_description="",
        subscriber_count=100,
        total_view_count=1000,
        total_video_count=1,
        channel_created_at="2026-01-01T00:00:00Z",
        thumbnail_url="",
        upload_pattern=UploadPattern(
            avg_videos_per_week=1.0,
            best_upload_day="Monday",
            best_upload_hour=12,
        ),
        title_pattern=TitlePattern(
            common_keywords=[("story", 3)],
            common_patterns=["numbered hook"],
            avg_title_length=10.0,
        ),
        comment_analysis=CommentAnalysis(
            sentiment_positive=0.8,
            fan_characteristics="engaged",
            common_requests=["more"],
        ),
        top_videos_by_views=[top_video],
    )


def test_generate_strategy_report_redacts_gemini_failure_in_return_and_log(caplog):
    api_key = "AIza" + ("p" * 32)

    class FakeGemini:
        def generate(self, prompt):
            raise RuntimeError(f"request failed for ?key={api_key}")

    analyzer = ChannelAnalyzer.__new__(ChannelAnalyzer)
    analyzer.gemini = FakeGemini()

    caplog.set_level(logging.ERROR)

    report = analyzer.generate_strategy_report(_minimal_channel_analysis())

    assert api_key not in report
    assert api_key not in caplog.text
    assert "key=<redacted>" in report
    assert "key=<redacted>" in caplog.text
