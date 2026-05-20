# tests/test_scene_analyzer.py
"""
v63.0 Phase 1: SceneAnalyzer 유닛 테스트

scene_analyzer.py의 핵심 경로 테스트:
- 데이터 클래스 (CharacterState, SceneAnalysisResult)
- SceneAnalyzer 초기화
- to_dict() 직렬화
- 분석 결과 구조 검증
"""
import os
import pytest
from unittest.mock import patch, MagicMock


class TestCharacterState:
    """CharacterState 데이터클래스 테스트"""

    def test_defaults(self):
        from modules_pro.scene_analyzer import CharacterState
        cs = CharacterState()
        assert cs.id == ""
        assert cs.name == ""
        assert cs.emotion == "neutral"
        assert cs.action == ""
        assert cs.is_speaker is False

    def test_custom_values(self):
        from modules_pro.scene_analyzer import CharacterState
        cs = CharacterState(id="grandma", name="할머니", emotion="sad", action="crying", is_speaker=True)
        assert cs.id == "grandma"
        assert cs.emotion == "sad"
        assert cs.is_speaker is True


class TestSceneAnalysisResult:
    """SceneAnalysisResult 데이터클래스 테스트"""

    def test_defaults(self):
        from modules_pro.scene_analyzer import SceneAnalysisResult
        sar = SceneAnalysisResult()
        assert sar.scene_id == ""
        assert sar.dialogue_index == 0
        assert sar.characters == []
        assert sar.tension_level == 5
        assert sar.image_action == "new"
        assert sar.sd_prompt == ""

    def test_to_dict(self):
        from modules_pro.scene_analyzer import SceneAnalysisResult, CharacterState
        sar = SceneAnalysisResult(
            scene_id="scene_001",
            dialogue_index=0,
            characters=[CharacterState(id="grandma", name="할머니", emotion="sad")],
            location="거실",
            time_of_day="night",
            atmosphere="tense",
            tension_level=7,
            sd_prompt="elderly woman crying in dark living room",
        )
        d = sar.to_dict()
        assert d["scene_id"] == "scene_001"
        assert len(d["characters"]) == 1
        assert d["characters"][0]["id"] == "grandma"
        assert d["characters"][0]["emotion"] == "sad"
        assert d["tension_level"] == 7
        assert d["sd_prompt"] == "elderly woman crying in dark living room"

    def test_to_dict_empty_characters(self):
        from modules_pro.scene_analyzer import SceneAnalysisResult
        sar = SceneAnalysisResult(scene_id="empty")
        d = sar.to_dict()
        assert d["characters"] == []

    def test_to_dict_multiple_characters(self):
        from modules_pro.scene_analyzer import SceneAnalysisResult, CharacterState
        sar = SceneAnalysisResult(
            characters=[
                CharacterState(id="grandma", emotion="angry"),
                CharacterState(id="grandpa", emotion="scared"),
                CharacterState(id="narrator", is_speaker=True),
            ]
        )
        d = sar.to_dict()
        assert len(d["characters"]) == 3


class TestSceneAnalyzerInit:
    """SceneAnalyzer 초기화 테스트"""

    def test_init_with_gemini_client(self):
        from modules_pro.scene_analyzer import SceneAnalyzer
        mock_client = MagicMock()
        sa = SceneAnalyzer(gemini_client=mock_client)
        assert sa.gemini_client is mock_client

    def test_init_without_args(self):
        from modules_pro.scene_analyzer import SceneAnalyzer
        sa = SceneAnalyzer()
        assert sa.gemini_client is None
        assert sa.character_definitions == []
        assert sa.art_style == SceneAnalyzer.DEFAULT_ART_STYLE

    def test_init_with_art_style(self):
        from modules_pro.scene_analyzer import SceneAnalyzer
        custom_style = {"art_style_prefix": "watercolor,", "good_examples": []}
        sa = SceneAnalyzer(art_style_config=custom_style)
        assert sa.art_style["art_style_prefix"] == "watercolor,"

    def test_init_with_dict_characters(self):
        """dict 형태 캐릭터 정의 → list 변환"""
        from modules_pro.scene_analyzer import SceneAnalyzer
        char_dict = {"grandma": {"base": "elderly woman"}}
        sa = SceneAnalyzer(character_definitions=char_dict)
        assert isinstance(sa.character_definitions, list)


class TestSceneKeywords:
    """씬 키워드 관련 테스트"""

    def test_scene_keywords_list(self):
        from modules_pro.scene_analyzer import SceneAnalysisResult
        sar = SceneAnalysisResult(
            scene_keywords=["dark", "rain", "abandoned"],
            camera_shot="close-up",
            key_props=["knife", "letter"],
        )
        assert "dark" in sar.scene_keywords
        assert sar.camera_shot == "close-up"
        assert len(sar.key_props) == 2

    def test_continuity_hint(self):
        from modules_pro.scene_analyzer import SceneAnalysisResult
        sar = SceneAnalysisResult(
            continuity_hint="same room as previous scene",
            outfit_hint="same dark dress",
        )
        assert "same room" in sar.continuity_hint
        assert "dark dress" in sar.outfit_hint
