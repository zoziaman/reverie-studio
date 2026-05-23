from insight.style_analyzer import StyleAnalyzer


def test_analyze_style_with_gemini_redacts_api_key_in_error(monkeypatch, tmp_path):
    api_key = "AIza" + ("s" * 32)
    grid_path = tmp_path / "grid.jpg"
    grid_path.write_bytes(b"fake-image")

    def fail_post(*args, **kwargs):
        raise RuntimeError(
            "vision request failed for url: "
            f"https://generativelanguage.googleapis.com/v1beta/models/model:generateContent?key={api_key}"
        )

    monkeypatch.setattr("insight.style_analyzer.requests.post", fail_post)

    analyzer = StyleAnalyzer(api_key, work_dir=tmp_path)
    result = analyzer.analyze_style_with_gemini(
        {"title": "test", "channel_title": "channel"},
        grid_image_path=grid_path,
    )

    assert api_key not in result["error"]
    assert "key=<redacted>" in result["error"]


def test_customize_tts_guide_with_gemini_redacts_api_key_in_error(monkeypatch, tmp_path):
    api_key = "AIza" + ("t" * 32)

    def fail_post(*args, **kwargs):
        raise RuntimeError(
            "tts request failed for url: "
            f"https://generativelanguage.googleapis.com/v1beta/models/model:generateContent?key={api_key}"
        )

    monkeypatch.setattr("insight.style_analyzer.requests.post", fail_post)

    analyzer = StyleAnalyzer(api_key, work_dir=tmp_path)
    result = analyzer._customize_tts_guide_with_gemini(
        {"title": "test", "description": "desc"},
        {
            "voice_gender": "female",
            "voice_age": "adult",
            "voice_tone": "calm",
            "required_emotions": ["calm"],
            "sample_scripts": {"calm": "hello"},
            "recording_tips": ["steady"],
        },
    )

    assert api_key not in result["error"]
    assert "key=<redacted>" in result["error"]
