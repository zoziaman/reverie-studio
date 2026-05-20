# tests/test_thumbnail_maker.py
"""
v63.0 Phase 1: ThumbnailMaker 유닛 테스트

thumbnail_maker.py의 핵심 경로 테스트:
- 초기화
- _apply_vram_safety() VRAM 안전 보정
- 테스트 썸네일 생성 (SD 목)
- 텍스트 오버레이 (Pillow 목)
"""
import os
import pytest
from unittest.mock import patch, MagicMock


class TestThumbnailMakerInit:
    """초기화 테스트"""

    def test_init(self):
        from pipeline.thumbnail_maker import ThumbnailMaker
        tm = ThumbnailMaker(
            sd_url="http://127.0.0.1:7860",
            data_dir="/data",
            assets_dir="/assets",
        )
        assert tm.sd_url == "http://127.0.0.1:7860"
        assert tm.data_dir == "/data"
        assert tm.assets_dir == "/assets"
        assert tm.W == 1920
        assert tm.H == 1080

    def test_init_custom(self):
        from pipeline.thumbnail_maker import ThumbnailMaker
        tm = ThumbnailMaker(
            sd_url="http://127.0.0.1:7860/",
            data_dir="/data",
            assets_dir="/assets",
            font_path="malgunbd.ttf",
            video_width=1280,
            video_height=720,
        )
        assert tm.sd_url == "http://127.0.0.1:7860"
        assert tm.W == 1280
        assert tm.H == 720
        assert tm.font_path == "malgunbd.ttf"


class TestVRAMSafety:
    """_apply_vram_safety 테스트"""

    @patch('pipeline.thumbnail_maker.config')
    def test_clamp_dimensions(self, mock_config):
        from pipeline.thumbnail_maker import ThumbnailMaker

        mock_config.clamp_sd_dimensions.return_value = (512, 512)
        mock_config.clamp_sd_steps.return_value = 15
        mock_config.is_low_vram.return_value = False

        tm = ThumbnailMaker(sd_url="http://x", data_dir="/d", assets_dir="/a")
        payload = {"width": 1024, "height": 1024, "steps": 30}
        result = tm._apply_vram_safety(payload)

        assert result["width"] == 512
        assert result["height"] == 512
        assert result["steps"] == 15

    @patch('pipeline.thumbnail_maker.config')
    def test_low_vram_disables_hr(self, mock_config):
        from pipeline.thumbnail_maker import ThumbnailMaker

        mock_config.clamp_sd_dimensions.return_value = (512, 288)
        mock_config.clamp_sd_steps.return_value = 20
        mock_config.is_low_vram.return_value = True

        tm = ThumbnailMaker(sd_url="http://x", data_dir="/d", assets_dir="/a")
        payload = {"width": 768, "height": 432, "steps": 20, "enable_hr": True, "batch_size": 2}
        result = tm._apply_vram_safety(payload)

        assert result["enable_hr"] is False
        assert result["batch_size"] == 1
        assert result["n_iter"] == 1

    @patch('pipeline.thumbnail_maker.config')
    def test_zero_dimensions_skip(self, mock_config):
        """width/height가 0이면 clamp 안 함"""
        from pipeline.thumbnail_maker import ThumbnailMaker

        mock_config.is_low_vram.return_value = False

        tm = ThumbnailMaker(sd_url="http://x", data_dir="/d", assets_dir="/a")
        payload = {"width": 0, "height": 0, "steps": 0}
        result = tm._apply_vram_safety(payload)

        mock_config.clamp_sd_dimensions.assert_not_called()
        mock_config.clamp_sd_steps.assert_not_called()

    @patch('pipeline.thumbnail_maker.config')
    def test_original_not_mutated(self, mock_config):
        """원본 payload가 변경되지 않는지"""
        from pipeline.thumbnail_maker import ThumbnailMaker

        mock_config.clamp_sd_dimensions.return_value = (512, 512)
        mock_config.clamp_sd_steps.return_value = 15
        mock_config.is_low_vram.return_value = False

        tm = ThumbnailMaker(sd_url="http://x", data_dir="/d", assets_dir="/a")
        original = {"width": 1024, "height": 1024, "steps": 30}
        result = tm._apply_vram_safety(original)

        assert original["width"] == 1024  # 원본 불변
        assert result["width"] == 512  # 결과는 변경됨
