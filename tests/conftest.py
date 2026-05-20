# tests/conftest.py
"""
pytest-qt 설정 파일
PySide6 GUI 자동 테스트 환경 구성
"""
import sys
import os
import pytest

# 프로젝트 경로 추가
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'lib'))

os.environ.setdefault("REVERIE_SECRET_KEY", "TEST_REVERIE_SECRET")


@pytest.fixture(scope="session")
def qapp_args():
    """QApplication 실행 인자"""
    return ["--platform", "offscreen"]  # headless 모드 (CI 환경용)


@pytest.fixture
def project_root():
    """프로젝트 루트 경로"""
    return PROJECT_ROOT


@pytest.fixture
def data_dir(tmp_path):
    """테스트용 임시 data 디렉토리"""
    data = tmp_path / "data"
    data.mkdir()
    return str(data)


@pytest.fixture
def config_dir(tmp_path):
    """테스트용 임시 config 디렉토리"""
    config = tmp_path / "config"
    config.mkdir()
    return str(config)
