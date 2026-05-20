# src/utils/i18n.py
"""
다국어 지원 모듈 (Internationalization)

라이센스 타입에 따른 언어 잠금:
- A (전체): 모든 언어 사용 가능
- H/T/M (제한): 한국어만 사용 가능

지원 언어:
- ko: 한국어 (기본)
- en: 영어
- ja: 일본어
"""

import os
import json
from typing import Dict, Optional

# 현재 언어
_current_lang = "ko"

# 라이센스별 사용 가능 언어
LICENSE_LANGUAGES = {
    'A': ['ko', 'en', 'ja'],  # 전체 이용: 모든 언어
    'H': ['ko'],               # 공포: 한국어만
    'T': ['ko'],               # 감동: 한국어만
    'M': ['ko'],               # 막장: 한국어만
}

# 언어 이름
LANGUAGE_NAMES = {
    'ko': '한국어',
    'en': 'English',
    'ja': '日本語',
}

# 번역 데이터
TRANSLATIONS: Dict[str, Dict[str, str]] = {
    # ===== 공통 =====
    "app_title": {
        "ko": "Reverie Automation",
        "en": "Reverie Automation",
        "ja": "Reverie Automation",
    },
    "license_required": {
        "ko": "라이센스가 필요합니다",
        "en": "License Required",
        "ja": "ライセンスが必要です",
    },
    "license_invalid": {
        "ko": "유효하지 않은 라이센스입니다",
        "en": "Invalid License",
        "ja": "無効なライセンスです",
    },
    "license_expired": {
        "ko": "라이센스가 만료되었습니다",
        "en": "License Expired",
        "ja": "ライセンスの有効期限が切れました",
    },
    "license_input": {
        "ko": "라이센스 키 입력",
        "en": "Enter License Key",
        "ja": "ライセンスキーを入力",
    },
    "confirm": {
        "ko": "확인",
        "en": "OK",
        "ja": "確認",
    },
    "cancel": {
        "ko": "취소",
        "en": "Cancel",
        "ja": "キャンセル",
    },
    "save": {
        "ko": "저장",
        "en": "Save",
        "ja": "保存",
    },
    "delete": {
        "ko": "삭제",
        "en": "Delete",
        "ja": "削除",
    },
    "edit": {
        "ko": "수정",
        "en": "Edit",
        "ja": "編集",
    },
    "close": {
        "ko": "닫기",
        "en": "Close",
        "ja": "閉じる",
    },
    "settings": {
        "ko": "설정",
        "en": "Settings",
        "ja": "設定",
    },
    "language": {
        "ko": "언어",
        "en": "Language",
        "ja": "言語",
    },
    "language_locked": {
        "ko": "이 언어는 전체 이용 라이센스(A)가 필요합니다",
        "en": "This language requires Full License (A)",
        "ja": "この言語にはフルライセンス(A)が必要です",
    },

    # ===== 메인 화면 =====
    "main_title": {
        "ko": "YouTube 영상 자동화",
        "en": "YouTube Video Automation",
        "ja": "YouTube動画自動化",
    },
    "channel_select": {
        "ko": "채널 선택",
        "en": "Select Channel",
        "ja": "チャンネル選択",
    },
    "horror_channel": {
        "ko": "공포 채널",
        "en": "Horror Channel",
        "ja": "ホラーチャンネル",
    },
    "senior_channel": {
        "ko": "시니어 채널",
        "en": "Senior Channel",
        "ja": "シニアチャンネル",
    },
    "mode_select": {
        "ko": "모드 선택",
        "en": "Select Mode",
        "ja": "モード選択",
    },
    "horror_mode": {
        "ko": "공포",
        "en": "Horror",
        "ja": "ホラー",
    },
    "touching_mode": {
        "ko": "감동",
        "en": "Touching",
        "ja": "感動",
    },
    "makjang_mode": {
        "ko": "막장",
        "en": "Makjang",
        "ja": "マクチャン",
    },

    # ===== 시나리오 =====
    "scenario": {
        "ko": "시나리오",
        "en": "Scenario",
        "ja": "シナリオ",
    },
    "scenario_title": {
        "ko": "시나리오 제목",
        "en": "Scenario Title",
        "ja": "シナリオタイトル",
    },
    "scenario_generate": {
        "ko": "시나리오 생성",
        "en": "Generate Scenario",
        "ja": "シナリオ生成",
    },
    "scenario_edit": {
        "ko": "시나리오 수정",
        "en": "Edit Scenario",
        "ja": "シナリオ編集",
    },
    "generating": {
        "ko": "생성 중...",
        "en": "Generating...",
        "ja": "生成中...",
    },

    # ===== 영상 제작 =====
    "video_production": {
        "ko": "영상 제작",
        "en": "Video Production",
        "ja": "動画制作",
    },
    "start_production": {
        "ko": "제작 시작",
        "en": "Start Production",
        "ja": "制作開始",
    },
    "stop_production": {
        "ko": "제작 중지",
        "en": "Stop Production",
        "ja": "制作停止",
    },
    "production_complete": {
        "ko": "제작 완료!",
        "en": "Production Complete!",
        "ja": "制作完了！",
    },
    "production_failed": {
        "ko": "제작 실패",
        "en": "Production Failed",
        "ja": "制作失敗",
    },

    # ===== 썸네일 =====
    "thumbnail": {
        "ko": "썸네일",
        "en": "Thumbnail",
        "ja": "サムネイル",
    },
    "thumbnail_generate": {
        "ko": "썸네일 생성",
        "en": "Generate Thumbnail",
        "ja": "サムネイル生成",
    },
    "thumbnail_preview": {
        "ko": "썸네일 미리보기",
        "en": "Thumbnail Preview",
        "ja": "サムネイルプレビュー",
    },

    # ===== 자막 =====
    "subtitle": {
        "ko": "자막",
        "en": "Subtitle",
        "ja": "字幕",
    },
    "subtitle_settings": {
        "ko": "자막 설정",
        "en": "Subtitle Settings",
        "ja": "字幕設定",
    },

    # ===== 업로드 =====
    "upload": {
        "ko": "업로드",
        "en": "Upload",
        "ja": "アップロード",
    },
    "upload_youtube": {
        "ko": "YouTube 업로드",
        "en": "Upload to YouTube",
        "ja": "YouTubeにアップロード",
    },
    "upload_complete": {
        "ko": "업로드 완료!",
        "en": "Upload Complete!",
        "ja": "アップロード完了！",
    },

    # ===== 배치/큐 =====
    "batch_queue": {
        "ko": "배치 큐",
        "en": "Batch Queue",
        "ja": "バッチキュー",
    },
    "add_to_queue": {
        "ko": "큐에 추가",
        "en": "Add to Queue",
        "ja": "キューに追加",
    },
    "queue_manager": {
        "ko": "큐 관리",
        "en": "Queue Manager",
        "ja": "キュー管理",
    },

    # ===== 템플릿 =====
    "template": {
        "ko": "템플릿",
        "en": "Template",
        "ja": "テンプレート",
    },
    "save_template": {
        "ko": "템플릿 저장",
        "en": "Save Template",
        "ja": "テンプレート保存",
    },
    "load_template": {
        "ko": "템플릿 불러오기",
        "en": "Load Template",
        "ja": "テンプレート読み込み",
    },

    # ===== 통계 =====
    "statistics": {
        "ko": "통계",
        "en": "Statistics",
        "ja": "統計",
    },
    "dashboard": {
        "ko": "대시보드",
        "en": "Dashboard",
        "ja": "ダッシュボード",
    },
    "total_videos": {
        "ko": "총 영상 수",
        "en": "Total Videos",
        "ja": "総動画数",
    },

    # ===== 오류 메시지 =====
    "error": {
        "ko": "오류",
        "en": "Error",
        "ja": "エラー",
    },
    "error_api_key": {
        "ko": "API 키가 설정되지 않았습니다",
        "en": "API key is not set",
        "ja": "APIキーが設定されていません",
    },
    "error_network": {
        "ko": "네트워크 연결을 확인하세요",
        "en": "Check your network connection",
        "ja": "ネットワーク接続を確認してください",
    },
    "error_file_not_found": {
        "ko": "파일을 찾을 수 없습니다",
        "en": "File not found",
        "ja": "ファイルが見つかりません",
    },

    # ===== 성공 메시지 =====
    "success": {
        "ko": "성공",
        "en": "Success",
        "ja": "成功",
    },
    "saved_successfully": {
        "ko": "저장되었습니다",
        "en": "Saved successfully",
        "ja": "保存されました",
    },
}


def get_current_lang() -> str:
    """현재 언어 반환"""
    return _current_lang


def set_lang(lang: str, license_type: str = 'A') -> bool:
    """
    언어 설정 (라이센스 검사 포함)

    Args:
        lang: 설정할 언어 코드 (ko, en, ja)
        license_type: 라이센스 타입 (A, H, T, M)

    Returns:
        bool: 설정 성공 여부
    """
    global _current_lang

    # 지원하는 언어인지 확인
    if lang not in LANGUAGE_NAMES:
        return False

    # 라이센스별 사용 가능 언어 확인
    allowed_langs = LICENSE_LANGUAGES.get(license_type, ['ko'])

    if lang not in allowed_langs:
        return False

    _current_lang = lang
    return True


def get_available_languages(license_type: str = 'A') -> list:
    """
    라이센스 타입에 따른 사용 가능 언어 목록

    Args:
        license_type: 라이센스 타입

    Returns:
        list: 사용 가능한 언어 코드 리스트
    """
    return LICENSE_LANGUAGES.get(license_type, ['ko'])


def is_language_available(lang: str, license_type: str) -> bool:
    """언어 사용 가능 여부 확인"""
    return lang in LICENSE_LANGUAGES.get(license_type, ['ko'])


def t(key: str, **kwargs) -> str:
    """
    번역 문자열 반환

    Args:
        key: 번역 키
        **kwargs: 포맷 인자

    Returns:
        str: 번역된 문자열

    Example:
        t("hello")  # "안녕하세요" (한국어일 때)
        t("welcome", name="홍길동")  # "환영합니다, 홍길동님"
    """
    if key not in TRANSLATIONS:
        return key

    translation = TRANSLATIONS[key].get(_current_lang)

    if translation is None:
        # 현재 언어에 번역이 없으면 한국어 사용
        translation = TRANSLATIONS[key].get('ko', key)

    # 포맷 인자 적용
    if kwargs:
        try:
            translation = translation.format(**kwargs)
        except KeyError:
            pass

    return translation


def get_all_translations() -> Dict[str, Dict[str, str]]:
    """모든 번역 데이터 반환"""
    return TRANSLATIONS.copy()


def add_translation(key: str, translations: Dict[str, str]):
    """
    번역 추가

    Args:
        key: 번역 키
        translations: {"ko": "한국어", "en": "English", "ja": "日本語"}
    """
    TRANSLATIONS[key] = translations


# 언어 설정 저장/로드
def save_language_setting(data_dir: str):
    """언어 설정 파일에 저장"""
    settings_path = os.path.join(data_dir, "language_settings.json")
    os.makedirs(data_dir, exist_ok=True)

    with open(settings_path, 'w', encoding='utf-8') as f:
        json.dump({"language": _current_lang}, f)


def load_language_setting(data_dir: str, license_type: str = 'A') -> str:
    """언어 설정 파일에서 로드"""
    global _current_lang

    settings_path = os.path.join(data_dir, "language_settings.json")

    if os.path.exists(settings_path):
        try:
            with open(settings_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                lang = data.get("language", "ko")

                # 라이센스로 사용 가능한지 확인
                if is_language_available(lang, license_type):
                    _current_lang = lang
                else:
                    _current_lang = "ko"
        except Exception:
            _current_lang = "ko"

    return _current_lang


# ============================================================
# 테스트
# ============================================================
if __name__ == "__main__":
    print("=" * 50)
    print("다국어 지원 테스트")
    print("=" * 50)

    # 한국어 테스트
    set_lang("ko", "A")
    print(f"\n[한국어] {t('app_title')}")
    print(f"  - {t('main_title')}")
    print(f"  - {t('scenario_generate')}")

    # 영어 테스트
    if set_lang("en", "A"):
        print(f"\n[English] {t('app_title')}")
        print(f"  - {t('main_title')}")
        print(f"  - {t('scenario_generate')}")
    else:
        print("\n[English] 영어 사용 불가 (라이센스 제한)")

    # 제한 라이센스로 영어 시도
    print("\n[제한 라이센스(H)로 영어 시도]")
    if set_lang("en", "H"):
        print("  성공 - 영어로 전환됨")
    else:
        print("  실패 - 한국어만 사용 가능")

    # 사용 가능 언어 확인
    print("\n[라이센스별 사용 가능 언어]")
    for l_type in ['A', 'H', 'T', 'M']:
        langs = get_available_languages(l_type)
        lang_names = [LANGUAGE_NAMES[l] for l in langs]
        print(f"  {l_type}: {', '.join(lang_names)}")
