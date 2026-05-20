import os
import google.generativeai as genai
from dotenv import load_dotenv

# 1. .env 파일 로드
load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")

print("="*50)
print("🔍 [Gemini API 진단 도구]")
print(f"🔑 감지된 API Key: {api_key[:10]}... (가림)")
print("="*50)

if not api_key:
    print("🚨 [오류] .env 파일에 API Key가 없습니다!")
    exit()

# 2. 설정
try:
    genai.configure(api_key=api_key)
except Exception as e:
    print(f"🚨 [설정 오류] {e}")
    exit()

# 3. 사용 가능한 모델 목록 조회
print("\n📡 구글 서버에 '사용 가능한 모델 목록'을 요청합니다...")
try:
    available_models = []
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            print(f"   ✅ 발견: {m.name}")
            available_models.append(m.name)
    
    if not available_models:
        print("\n❌ [심각] 사용 가능한 모델이 하나도 없습니다.")
        print("   👉 원인 1: API Key가 무료 할당량을 초과했습니다.")
        print("   👉 원인 2: API Key가 만료되었거나 잘못되었습니다.")
        print("   👉 해결: 구글 AI Studio에서 새 키를 발급받으세요.")
    else:
        print(f"\n🎉 총 {len(available_models)}개의 모델을 사용할 수 있습니다.")
        
        # 4. 테스트 생성 시도
        target_model = available_models[0].replace("models/", "")
        print(f"\n🧪 '{target_model}' 모델로 테스트 생성을 시도합니다...")
        model = genai.GenerativeModel(target_model)
        response = model.generate_content("Hello, are you working?")
        print(f"   💬 응답: {response.text}")
        print("\n✨ [진단 결과] API는 정상입니다. 위 모델명을 코드에 적용하세요.")

except Exception as e:
    print(f"\n🚨 [연결 실패] 오류 내용:\n{e}")