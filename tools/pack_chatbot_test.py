# tools/pack_chatbot_test.py
# ============================================================
# ReveriePack 생성 도우미 챗봇 테스트
# Gemini Flash 기반 대화형 팩 설정 수집
# ============================================================
# v57.7.0: 초기 테스트 버전
# 실행: python tools/pack_chatbot_test.py
# ============================================================

import os
import sys
import json
import io
from typing import Optional, List, Dict, Any

def _configure_console_encoding() -> None:
    """Configure UTF-8 streams only when running the CLI directly."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    elif hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    elif hasattr(sys.stdin, "buffer"):
        sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace")

# 프로젝트 루트 추가
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "lib"))

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
예: "안녕하세요! 레베리 팩 생성 도우미입니다. 🎬 어떤 콘텐츠 팩을 만들어 드릴까요? 장르나 고객 요청사항을 말씀해주세요!"
"""


class PackChatbot:
    """ReveriePack 생성 도우미 챗봇"""

    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY가 설정되지 않았습니다. .env 파일을 확인하세요.")

        genai.configure(api_key=self.api_key)

        # Gemini Flash 모델 사용 (빠르고 저렴)
        self.model = genai.GenerativeModel(
            model_name="gemini-2.0-flash",
            system_instruction=SYSTEM_PROMPT
        )

        # 대화 히스토리
        self.chat = self.model.start_chat(history=[])
        self.collected_settings: Optional[Dict] = None

    def send_message(self, user_input: str) -> str:
        """사용자 메시지 전송 및 응답 받기"""
        try:
            response = self.chat.send_message(user_input)
            assistant_response = response.text

            # JSON 설정이 포함되어 있는지 확인
            if "```json" in assistant_response:
                self._extract_settings(assistant_response)

            return assistant_response

        except Exception as e:
            safe_error = redact_sensitive_text(e)
            return f"❌ 오류 발생: {safe_error}"

    def _extract_settings(self, response: str) -> None:
        """응답에서 JSON 설정 추출"""
        try:
            start = response.find("```json") + 7
            end = response.find("```", start)
            if start > 6 and end > start:
                json_str = response[start:end].strip()
                self.collected_settings = json.loads(json_str)
                print("\n" + "="*50)
                print("✅ 설정이 수집되었습니다!")
                print("="*50)
        except json.JSONDecodeError:
            pass  # JSON 파싱 실패 시 무시

    def get_collected_settings(self) -> Optional[Dict]:
        """수집된 설정 반환"""
        return self.collected_settings

    def start_conversation(self) -> str:
        """대화 시작 (첫 인사)"""
        return self.send_message("시작해줘")


def main():
    """메인 함수 - CLI 대화 인터페이스"""
    _configure_console_encoding()

    print("="*60)
    print("🎬 ReveriePack 생성 도우미 챗봇 테스트")
    print("="*60)
    print("종료하려면 'quit' 또는 'exit' 입력")
    print("설정 확인하려면 'show' 입력")
    print("="*60 + "\n")

    try:
        chatbot = PackChatbot()
    except ValueError as e:
        print(f"❌ 초기화 실패: {e}")
        return

    # 첫 인사
    print("🤖 챗봇:", chatbot.start_conversation())
    print()

    # 대화 루프
    while True:
        try:
            user_input = input("👤 나: ").strip()

            if not user_input:
                continue

            if user_input.lower() in ['quit', 'exit', '종료']:
                print("\n👋 대화를 종료합니다.")
                break

            if user_input.lower() == 'show':
                settings = chatbot.get_collected_settings()
                if settings:
                    print("\n📋 현재 수집된 설정:")
                    print(json.dumps(settings, indent=2, ensure_ascii=False))
                else:
                    print("\n📋 아직 수집된 설정이 없습니다.")
                print()
                continue

            # 챗봇 응답
            response = chatbot.send_message(user_input)
            print(f"\n🤖 챗봇: {response}\n")

        except KeyboardInterrupt:
            print("\n\n👋 대화를 종료합니다.")
            break
        except Exception as e:
            print(f"\n❌ 오류: {e}\n")

    # 최종 설정 출력
    final_settings = chatbot.get_collected_settings()
    if final_settings:
        print("\n" + "="*60)
        print("📦 최종 수집된 팩 설정:")
        print("="*60)
        print(json.dumps(final_settings, indent=2, ensure_ascii=False))

        # 파일로 저장 여부
        save = input("\n💾 이 설정을 파일로 저장할까요? (y/n): ").strip().lower()
        if save == 'y':
            output_path = os.path.join(PROJECT_ROOT, "data", "pack_settings_draft.json")
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(final_settings, indent=2, ensure_ascii=False, fp=f)
            print(f"✅ 저장됨: {output_path}")


if __name__ == "__main__":
    main()
