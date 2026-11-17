"""티원 - Gemini API 연결 테스트 (확인용, 서비스 코드 아님)"""
import os
import sys

from dotenv import load_dotenv
from google import genai

load_dotenv()

api_key = os.environ.get("GEMINI_API_KEY", "").strip()
model_name = os.environ.get("GEMINI_MODEL", "").strip()

if not api_key or api_key.startswith("나중에"):
    print("[실패] .env에 GEMINI_API_KEY가 없어요.")
    sys.exit(1)

client = genai.Client(api_key=api_key)

# 1) 내 키로 쓸 수 있는 Flash 모델 목록 확인
try:
    flash_models = [
        m.name.replace("models/", "")
        for m in client.models.list()
        if "flash" in m.name
        and "generateContent" in (getattr(m, "supported_actions", None) or [])
    ]
except Exception as e:
    print("[실패] 모델 목록을 못 가져왔어요. 키가 틀렸거나 인터넷 문제예요.")
    print("상세:", e)
    sys.exit(1)

print("사용 가능한 Flash 모델:")
for name in flash_models:
    print(" -", name)

if not model_name:
    print("\n.env에 GEMINI_MODEL=위 목록 중 하나 를 추가하고 다시 실행하세요.")
    sys.exit(0)

if model_name not in flash_models:
    print(f"\n[주의] {model_name} 은(는) 목록에 없어요. 철자를 확인하세요.")
    sys.exit(1)

# 2) 실제 요청 1번 보내기
try:
    response = client.models.generate_content(
        model=model_name,
        contents="한 문장으로 자기소개 해줘.",
    )
    print("\n[성공] Gemini 응답:", response.text)
except Exception as e:
    print("\n[실패] 요청 중 오류:", e)
    sys.exit(1)