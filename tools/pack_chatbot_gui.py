# tools/pack_chatbot_gui.py
# ============================================================
# ReveriePack 생성 도우미 챗봇 GUI
# Gemini Flash 기반 대화형 팩 설정 수집
# ============================================================
# v57.7.0: GUI 버전
# 실행: python tools/pack_chatbot_gui.py
# ============================================================

import os
import sys
import json
from typing import Optional, Dict

# 프로젝트 루트 추가
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "lib"))

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QLineEdit, QPushButton, QLabel, QMessageBox
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont, QTextCursor

import google.generativeai as genai
from dotenv import load_dotenv
from utils.secret_redaction import redact_sensitive_text

# .env 로드
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))


# ============================================================
# 챗봇 시스템 프롬프트
# ============================================================
SYSTEM_PROMPT = """너는 "레베리 팩 생성 도우미"야.
사용자(개발자)가 고객 요청을 전달하면, 대화를 통해 ReveriePack 생성에 필요한 정보를 수집해.

## 수집해야 할 정보

### 1. 기본 정보
- 팩 이름 (예: "해외 슬래셔 공포팩")
- 장르 (공포, 로맨스, 감동, 미스터리, 코미디 등)

### 2. 스타일 세부사항
- 배경 설정 (한국/해외, 현대/과거, 도시/시골 등)
- 분위기 키워드 (고어, 잔잔한, 긴장감, 달달한 등)
- 수위 (1~10, 장르에 따라 공포수위/로맨스수위 등)

### 3. 캐릭터 구성
- 주요 캐릭터 유형 (가족, 연인, 친구, 직장동료 등)
- 캐릭터 수 (2명, 3명, 앙상블 등)
- 특별한 캐릭터 요청 (할머니 필수, 어린이 포함 등)

### 4. 콘텐츠 설정
- 예상 영상 길이 (3분, 5분, 10분)
- 턴 수 범위 (최소~최대)
- 이미지 스타일 (애니메이션, 실사풍, 그림체 등)

### 5. 특별 요청
- 금지 요소 (욕설 금지, 폭력 묘사 제한 등)
- 필수 포함 요소 (반전 필수, 해피엔딩 등)

## 대화 규칙

1. 한 번에 1~2개 질문만 해. 너무 많이 물어보면 피곤해.
2. 선택지를 줄 때는 번호로 쉽게 선택할 수 있게 해.
3. 사용자가 애매하게 답하면 구체적으로 다시 물어봐.
4. 충분한 정보가 모이면 "설정 확정" 여부를 물어봐.
5. 확정되면 JSON 형식으로 최종 설정을 출력해.

## 출력 JSON 형식 (확정 시)

```json
{
  "pack_name": "팩 이름",
  "genre": "장르",
  "style": {
    "setting": "배경",
    "mood": ["분위기", "키워드"],
    "intensity": 7
  },
  "characters": {
    "types": ["캐릭터 유형"],
    "count": 3,
    "special": "특별 요청"
  },
  "content": {
    "duration_minutes": 5,
    "min_turns": 50,
    "max_turns": 100,
    "image_style": "이미지 스타일"
  },
  "restrictions": {
    "forbidden": ["금지 요소"],
    "required": ["필수 요소"]
  }
}
```

## 시작 인사

첫 메시지에서는 간단히 인사하고, 어떤 팩을 만들고 싶은지 물어봐.
예: "안녕하세요! 레베리 팩 생성 도우미입니다. 어떤 콘텐츠 팩을 만들어 드릴까요? 장르나 고객 요청사항을 말씀해주세요!"
"""


class ChatWorker(QThread):
    """비동기 채팅 워커"""
    response_ready = Signal(str)
    error_occurred = Signal(str)

    def __init__(self, chat, message: str):
        super().__init__()
        self.chat = chat
        self.message = message

    def run(self):
        try:
            response = self.chat.send_message(self.message)
            self.response_ready.emit(response.text)
        except Exception as e:
            self.error_occurred.emit(redact_sensitive_text(e))


class PackChatbotWindow(QMainWindow):
    """ReveriePack 생성 도우미 챗봇 GUI"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("ReveriePack 생성 도우미")
        self.setMinimumSize(700, 600)
        self.resize(800, 700)

        # API 설정
        self.api_key = os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            QMessageBox.critical(self, "오류", "GEMINI_API_KEY가 설정되지 않았습니다.")
            sys.exit(1)

        genai.configure(api_key=self.api_key)
        self.model = genai.GenerativeModel(
            model_name="gemini-2.0-flash",
            system_instruction=SYSTEM_PROMPT
        )
        self.chat = self.model.start_chat(history=[])
        self.collected_settings: Optional[Dict] = None
        self.worker: Optional[ChatWorker] = None

        self._setup_ui()
        self._start_conversation()

    def _setup_ui(self):
        """UI 구성"""
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(10)
        layout.setContentsMargins(15, 15, 15, 15)

        # 타이틀
        title = QLabel("ReveriePack 생성 도우미")
        title.setFont(QFont("맑은 고딕", 16, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel("Gemini Flash 기반 대화형 팩 설정 수집")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet("color: #666;")
        layout.addWidget(subtitle)

        # 채팅 영역
        self.chat_display = QTextEdit()
        self.chat_display.setReadOnly(True)
        self.chat_display.setFont(QFont("맑은 고딕", 11))
        self.chat_display.setStyleSheet("""
            QTextEdit {
                background-color: #f5f5f5;
                border: 1px solid #ddd;
                border-radius: 8px;
                padding: 10px;
            }
        """)
        layout.addWidget(self.chat_display, stretch=1)

        # 입력 영역
        input_layout = QHBoxLayout()

        self.input_field = QLineEdit()
        self.input_field.setFont(QFont("맑은 고딕", 11))
        self.input_field.setPlaceholderText("메시지를 입력하세요...")
        self.input_field.setStyleSheet("""
            QLineEdit {
                border: 2px solid #4CAF50;
                border-radius: 8px;
                padding: 10px;
            }
        """)
        self.input_field.returnPressed.connect(self._send_message)
        input_layout.addWidget(self.input_field, stretch=1)

        self.send_btn = QPushButton("전송")
        self.send_btn.setFont(QFont("맑은 고딕", 11, QFont.Bold))
        self.send_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 10px 25px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:disabled {
                background-color: #ccc;
            }
        """)
        self.send_btn.clicked.connect(self._send_message)
        input_layout.addWidget(self.send_btn)

        layout.addLayout(input_layout)

        # 버튼 영역
        btn_layout = QHBoxLayout()

        self.show_settings_btn = QPushButton("수집된 설정 보기")
        self.show_settings_btn.clicked.connect(self._show_settings)
        btn_layout.addWidget(self.show_settings_btn)

        self.save_btn = QPushButton("설정 저장")
        self.save_btn.clicked.connect(self._save_settings)
        btn_layout.addWidget(self.save_btn)

        self.reset_btn = QPushButton("대화 초기화")
        self.reset_btn.clicked.connect(self._reset_conversation)
        btn_layout.addWidget(self.reset_btn)

        layout.addLayout(btn_layout)

    def _append_message(self, sender: str, message: str, is_bot: bool = False):
        """채팅 메시지 추가"""
        color = "#2196F3" if is_bot else "#333"
        bg = "#e3f2fd" if is_bot else "#fff"

        html = f'''
        <div style="margin: 8px 0; padding: 10px; background-color: {bg};
                    border-radius: 8px; border-left: 4px solid {color};">
            <b style="color: {color};">{sender}</b><br/>
            <span style="white-space: pre-wrap;">{message}</span>
        </div>
        '''
        self.chat_display.append(html)
        self.chat_display.moveCursor(QTextCursor.End)

    def _start_conversation(self):
        """대화 시작"""
        self._set_input_enabled(False)
        self.worker = ChatWorker(self.chat, "시작해줘")
        self.worker.response_ready.connect(self._on_bot_response)
        self.worker.error_occurred.connect(self._on_error)
        self.worker.start()

    def _send_message(self):
        """메시지 전송"""
        message = self.input_field.text().strip()
        if not message:
            return

        self._append_message("나", message, is_bot=False)
        self.input_field.clear()
        self._set_input_enabled(False)

        self.worker = ChatWorker(self.chat, message)
        self.worker.response_ready.connect(self._on_bot_response)
        self.worker.error_occurred.connect(self._on_error)
        self.worker.start()

    def _on_bot_response(self, response: str):
        """봇 응답 처리"""
        self._append_message("도우미", response, is_bot=True)
        self._set_input_enabled(True)
        self.input_field.setFocus()

        # JSON 설정 추출
        if "```json" in response:
            self._extract_settings(response)

    def _on_error(self, error: str):
        """에러 처리"""
        self._append_message("시스템", f"오류 발생: {error}", is_bot=True)
        self._set_input_enabled(True)

    def _set_input_enabled(self, enabled: bool):
        """입력 활성화/비활성화"""
        self.input_field.setEnabled(enabled)
        self.send_btn.setEnabled(enabled)
        if not enabled:
            self.send_btn.setText("응답 중...")
        else:
            self.send_btn.setText("전송")

    def _extract_settings(self, response: str):
        """응답에서 JSON 설정 추출"""
        try:
            start = response.find("```json") + 7
            end = response.find("```", start)
            if start > 6 and end > start:
                json_str = response[start:end].strip()
                self.collected_settings = json.loads(json_str)
                QMessageBox.information(self, "설정 수집 완료",
                    "팩 설정이 수집되었습니다!\n'설정 저장' 버튼을 눌러 저장하세요.")
        except json.JSONDecodeError:
            pass

    def _show_settings(self):
        """수집된 설정 표시"""
        if self.collected_settings:
            settings_str = json.dumps(self.collected_settings, indent=2, ensure_ascii=False)
            QMessageBox.information(self, "수집된 설정", settings_str)
        else:
            QMessageBox.information(self, "설정 없음", "아직 수집된 설정이 없습니다.")

    def _save_settings(self):
        """설정 저장"""
        if not self.collected_settings:
            QMessageBox.warning(self, "저장 실패", "저장할 설정이 없습니다.")
            return

        output_path = os.path.join(PROJECT_ROOT, "data", "pack_settings_draft.json")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(self.collected_settings, f, indent=2, ensure_ascii=False)

        QMessageBox.information(self, "저장 완료", f"설정이 저장되었습니다:\n{output_path}")

    def _reset_conversation(self):
        """대화 초기화"""
        reply = QMessageBox.question(self, "대화 초기화",
            "대화를 초기화하시겠습니까?\n수집된 설정도 초기화됩니다.")

        if reply == QMessageBox.Yes:
            self.chat = self.model.start_chat(history=[])
            self.collected_settings = None
            self.chat_display.clear()
            self._start_conversation()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    window = PackChatbotWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
