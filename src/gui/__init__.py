# Reverie GUI - 사용자 인터페이스
# Version: 40.0.0

"""
Reverie Automation GUI 패키지

CustomTkinter 기반 GUI 컴포넌트 모음

주요 컴포넌트 (사용자 GUI):
- main_window.py: 메인 윈도우 (v40: Insight/Factory 제거)
- tab_subtitle.py: 자막 탭 (SRT 편집)
- tab_thumbnail.py: 썸네일 탭 (미리보기)
- scenario_editor.py: 대본 편집기 (씬 편집)
- settings_manager.py: 설정 관리자 (API, 모델)

다이얼로그:
- setup_wizard.py: 초기 설정 마법사
- training_wizard.py: TTS 훈련 마법사
- model_manager_dialog.py: SD/LoRA 모델 관리
- template_dialog.py: 템플릿 관리
- queue_manager_dialog.py: 배치 큐 관리
- branding_dialog.py: 브랜딩 설정

관리자 전용 도구 (license_generator_gui.py):
- Insight 탭: 트렌드 분석, AI 분석, 딥 분석
- Factory 탭: 채널 팩 설계, .revpack 생성
- 라이센스 생성기

v40 변경사항:
- Insight/Factory 탭은 관리자 GUI에서만 사용
- 사용자 GUI는 .revpack 기반 영상 생산만 지원
"""

__version__ = "40.0.0"