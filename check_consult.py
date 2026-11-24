"""티원 - 구매 상담 기능 검증 (메모리 DB + 가짜 Gemini, Neon·Gemini 한도 안 씀)"""
import io
import json
import os
import sys
from datetime import timedelta

os.environ["DATABASE_URL"] = "sqlite://"  # app.py를 불러올 때 Neon에 접속하지 않게
os.environ.setdefault("SECRET_KEY", "test-secret")

import gemini_client  # noqa: E402
from app import create_app  # noqa: E402
from validators import today_kst  # noqa: E402

app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite://"})
results = []


def check(name, ok, detail=None):
    results.append(bool(ok))
    print(("[통과] " if ok else "[실패] ") + name + ("" if ok else f"  → {detail}"))


def code_of(resp):
    body = resp.get_json(silent=True) or {}
    return (body.get("error") or {}).get("code")


# ---- 가짜 Gemini: 정해둔 답을 순서대로 돌려준다 ----
calls = []
replies = []


def fake_ask(prompt, image_bytes=None, image_mime=None):
    calls.append({"prompt": prompt, "image": image_bytes, "mime": image_mime})
    reply = replies.pop(0)
    if isinstance(reply, Exception):
        raise reply
    return reply


gemini_client.ask = fake_ask


def ai(**kw):
    base = {"recognized": True, "item_name": "에어팟 프로", "price": 350000, "category": "쇼핑",
            "verdict": "CONDITIONAL", "reason": "목표가 늦어져요.", "alternatives": ["할인 때 사기"],
            "message": "조금만 참아봐!"}
    base.update(kw)
    return json.dumps(base, ensure_ascii=False)


H = {"X-Requested-With": "fetch"}


def consult(client, data=None, headers=H, **kw):
    return client.post("/api/consults", data=data or {}, headers=headers,
                       content_type="multipart/form-data", **kw)


c = app.test_client()
deadline = (today_kst() + timedelta(days=90)).isoformat()

r = consult(c, {"text": "치킨"})
check("로그인 전 상담 → 401", r.status_code == 401)

c.post("/api/auth/signup", json={"username": "tiwon01", "password": "password123"})
r = consult(c, {"text": "치킨"})
check("설정 전 상담 → 409 SETTINGS_REQUIRED", r.status_code == 409 and code_of(r) == "SETTINGS_REQUIRED")
r = c.get("/api/summary")
check("설정 전 현황 → 409", r.status_code == 409)

c.put("/api/settings", json={"focus": {"식비·배달": 20000, "편의점·마트": None},
                             "monthly_budget": 500000, "goal_name": "노트북",
                             "goal_amount": 900000, "goal_deadline": deadline, "tone": "roast"})

# ---- 입력 검사 (AI 호출 전에 걸러져야 함) ----
calls.clear()
r = consult(c, {"text": "치킨"}, headers={})
check("fetch 머리글 없으면 거절", r.status_code == 400)
r = consult(c, {"text": "  "})
check("글·사진 둘 다 없으면 400", r.status_code == 400)
r = consult(c, {"text": "치킨", "price": "이만원"})
check("가격이 숫자 아니면 400", r.status_code == 400)
r = consult(c, {"text": "가" * 501})
check("글 500자 초과 400", r.status_code == 400)
r = consult(c, {"image": (io.BytesIO(b"hello"), "a.png")})
check("이미지 아닌 파일 400 (이름이 .png여도)", r.status_code == 400)
r = consult(c, {"image": (io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"0" * (5 * 1024 * 1024)), "big.png")})
check("5MB 넘는 사진 413", r.status_code == 413 and code_of(r) == "IMAGE_TOO_LARGE")
r = consult(c, {"image": (io.BytesIO(b"0" * (7 * 1024 * 1024)), "huge.png")})
check("6MB 넘는 요청도 JSON 413", r.status_code == 413 and code_of(r) == "IMAGE_TOO_LARGE")
check("입력 오류에선 AI를 부르지 않음 (한도 절약)", len(calls) == 0, len(calls))

# ---- 정상 상담 ----
replies[:] = [ai()]
r = consult(c, {"text": "에어팟 프로 사고 싶다", "price": "350,000"})
body = r.get_json() or {}
check("글 상담 성공 201", r.status_code == 201, body)
check("응답에 판단·이유·대안·잔소리", body.get("verdict") == "CONDITIONAL" and body.get("message") == "조금만 참아봐!"
      and body.get("alternatives") == ["할인 때 사기"])
check("지연일은 코드가 계산 (35만 ÷ 하루 1만 = 35일)", body.get("delay_days") == 35, body.get("delay_days"))
check("남은 예산 50만 (아직 산 것 없음)", body.get("remaining_budget") == 500000)
p = calls[-1]["prompt"]
check("프롬프트에 예산·목표·말투·사용자 글", "500,000원" in p and "노트북" in p and "독설" in p
      and "에어팟 프로 사고 싶다" in p)
first_id = body.get("consult_id")

replies[:] = ["```json\n" + ai(item_name="샴푸", price=12000, category="편의점·마트", verdict="BUY") + "\n```"]
r = consult(c, {"text": "샴푸 떨어짐"})
check("```로 감싼 답도 처리 + 가격 AI가 찾음", r.status_code == 201 and r.get_json()["price"] == 12000)
shampoo_id = r.get_json()["consult_id"]

replies[:] = [ai(price=99000)]
r = consult(c, {"text": "에어팟", "price": "330000"})
check("사용자가 적은 가격이 AI 가격보다 우선", r.get_json()["price"] == 330000)

replies[:] = [ai(verdict="BUY", price=600000)]
r = consult(c, {"text": "모니터"})
check("예산 넘는데 BUY → 안전장치로 CONDITIONAL", r.get_json()["verdict"] == "CONDITIONAL")

replies[:] = [ai(category="택시")]
r = consult(c, {"text": "게임 아이템", "price": "10000"})
check("없는 분류는 기타로 저장", r.get_json()["category"] == "기타")

png = b"\x89PNG\r\n\x1a\n" + b"0" * 100
replies[:] = [ai(item_name="후드티", price=59000, category="쇼핑", verdict="SKIP")]
r = consult(c, {"image": (io.BytesIO(png), "cap.png")})
check("사진 상담 성공 + 입력종류 IMAGE", r.status_code == 201 and r.get_json()["input_type"] == "IMAGE")
check("사진이 Gemini에 전달됨 (png)", calls[-1]["image"] == png and calls[-1]["mime"] == "image/png")

# ---- AI 실패 상황 ----
n_before = len(c.get("/api/consults").get_json()["consults"])
replies[:] = ["잘 모르겠어요", ai(item_name="커피")]
calls.clear()
r = consult(c, {"text": "커피", "price": "4500"})
check("형식 깨진 답 → 1번 다시 물어서 성공", r.status_code == 201 and len(calls) == 2)
replies[:] = ["모름", "{깨짐"]
calls.clear()
r = consult(c, {"text": "커피", "price": "4500"})
check("두 번 다 깨지면 503 (3번은 안 부름)", r.status_code == 503 and code_of(r) == "AI_UNAVAILABLE" and len(calls) == 2)
replies[:] = [gemini_client.AIQuotaError("429")]
r = consult(c, {"text": "커피"})
check("무료 한도 초과 → 429", r.status_code == 429 and code_of(r) == "AI_QUOTA_EXCEEDED")
replies[:] = [gemini_client.AIUnavailableError("down")]
r = consult(c, {"text": "커피"})
check("Gemini 장애 → 503", r.status_code == 503)
replies[:] = ['{"recognized": false}']
r = consult(c, {"text": "ㅋㅋㅋ"})
check("상품 인식 실패 → 422", r.status_code == 422 and code_of(r) == "ITEM_NOT_RECOGNIZED")
replies[:] = [ai(price=None)]
r = consult(c, {"text": "그거"})
check("가격을 끝내 모르면 422 PRICE_REQUIRED", r.status_code == 422 and code_of(r) == "PRICE_REQUIRED")
n_after = len(c.get("/api/consults").get_json()["consults"])
check("실패한 상담은 기록에 남지 않음", n_after == n_before + 1, (n_before, n_after))

# ---- 결과 기록 + 현황 ----
r = c.patch(f"/api/consults/{first_id}/decision", json={"decision": "SKIPPED"})
check("참음 기록", r.status_code == 200 and r.get_json()["decision"] == "SKIPPED" and r.get_json()["decided_at"])
r = c.patch(f"/api/consults/{shampoo_id}/decision", json={"decision": "BOUGHT", "actual_price": "11,000"})
check("샀음 + 실제 가격 기록", r.status_code == 200 and r.get_json()["actual_price"] == 11000)
r = c.patch(f"/api/consults/{shampoo_id}/decision", json={"decision": "LATER"})
check("잘못된 결정값 400", r.status_code == 400)
r = c.patch(f"/api/consults/{shampoo_id}/decision", json={"decision": "BOUGHT", "actual_price": -1})
check("음수 실제가격 400", r.status_code == 400)
r = c.patch("/api/consults/99999/decision", json={"decision": "BOUGHT"})
check("없는 상담 404", r.status_code == 404)

s = c.get("/api/summary").get_json()
check("현황: 쓴 돈 11,000 (실제 가격 기준)", s["spent"] == 11000, s)
check("현황: 남은 예산 489,000", s["remaining_budget"] == 489000)
check("현황: 참은 돈 350,000, 진행률 38.9%", s["saved_total"] == 350000 and s["goal_progress"] == 38.9, s)
check("현황: 분류별 (편의점·마트 1회 11,000)", s["by_category"] == [{"category": "편의점·마트", "count": 1, "amount": 11000}])

replies[:] = [ai(item_name="린스", price=9000, category="편의점·마트", verdict="BUY")]
consult(c, {"text": "린스"})
p = calls[-1]["prompt"]
check("다음 상담 프롬프트에 남은 예산·최근 구매 반영", "489,000원" in p and "샴푸 11,000원" in p and "편의점·마트 1회" in p)

lst = c.get("/api/consults").get_json()
check("상담 기록: 최신순", lst["consults"][0]["item_name"] == "린스")
r = c.get("/api/consults?month=2026-13")
check("잘못된 month 400", r.status_code == 400)
r = c.get("/api/consults?month=2000-01")
check("기록 없는 달은 빈 목록", r.status_code == 200 and r.get_json()["consults"] == [])

# ---- 다른 사용자와 분리 ----
c2 = app.test_client()
c2.post("/api/auth/signup", json={"username": "tiwon02", "password": "password123"})
r = c2.patch(f"/api/consults/{shampoo_id}/decision", json={"decision": "SKIPPED"})
check("남의 상담은 기록 못 바꿈 (404)", r.status_code == 404)
r = c2.get("/api/consults")
check("남의 상담 기록은 안 보임", r.get_json()["consults"] == [])

# ---- 줄이고 싶은 지출: 꼽주기·기준 금액·세 갈래 숫자 ----
c3 = app.test_client()
c3.post("/api/auth/signup", json={"username": "tiwon03", "password": "password123"})
c3.put("/api/settings", json={"monthly_budget": 100000, "goal_name": "에어팟", "goal_amount": 300000,
                              "goal_deadline": (today_kst() + timedelta(days=30)).isoformat(),
                              "tone": "roast", "focus": {"식비·배달": 20000}})
replies[:] = [ai(item_name="치킨", price=23000, category="식비·배달", verdict="SKIP")]
b1 = consult(c3, {"text": "치킨"}).get_json()
check("줄이기로 한 지출이면 is_focus", b1["is_focus"] is True)
check("기록이 없으면 꼽주기 없음", b1["nag"] is None)
check("기준 20,000원 초과 → 3,000원 비싸다고 표시", b1["limit"] == {"amount": 20000, "over_by": 3000}, b1["limit"])
check("지금 사면: 남은 예산 100,000 → 77,000", b1["remaining_budget"] == 100000 and b1["remaining_after"] == 77000)
check("지연일 = 23,000 ÷ 하루 10,000 올림 = 3일", b1["delay_days"] == 3, b1["delay_days"])
check("아끼면: 진행률 0% → 7.7%", b1["progress_now"] == 0.0 and b1["progress_after"] == 7.7, (b1["progress_now"], b1["progress_after"]))
c3.patch(f"/api/consults/{b1['consult_id']}/decision", json={"decision": "BOUGHT"})

replies[:] = [ai(item_name="피자", price=18000, category="식비·배달", verdict="BUY")]
b2 = consult(c3, {"text": "피자"}).get_json()
check("꼽주기: 최근 14일 식비·배달 1번 23,000원", b2["nag"] == {"days": 14, "count": 1, "amount": 23000}, b2["nag"])
check("기준 이하면 기준 경고 없음 + BUY 유지", b2["limit"] is None and b2["verdict"] == "BUY")
p = calls[-1]["prompt"]
check("프롬프트에 고른 지출·기준 금액·14일 기록", "- 식비·배달 (한 번에 20,000원까지)" in p
      and "최근 14일 종류별 구매 횟수·금액: 식비·배달 1회 23,000원" in p and "치킨 23,000원" in p)

replies[:] = [ai(item_name="떡볶이", price=25000, category="식비·배달", verdict="BUY")]
b3 = consult(c3, {"text": "떡볶이"}).get_json()
check("기준 초과인데 BUY → 안전장치로 CONDITIONAL", b3["verdict"] == "CONDITIONAL" and "limit" in b3["guards"])

replies[:] = [ai(item_name="라떼", price=30000, category="카페", verdict="BUY")]
b4 = consult(c3, {"text": "라떼"}).get_json()
check("고르지 않은 지출(카페)은 꼽주기·기준 검사 없음", b4["is_focus"] is False and b4["nag"] is None
      and b4["limit"] is None and b4["verdict"] == "BUY")

with app.app_context():
    from app import _migrate_categories
    from models import Consult, User
    u3 = User.query.filter_by(username="tiwon03").first()
    db_old = Consult(user_id=u3.id, input_type="TEXT", item_name="옛날 기록", price=1000,
                     category="배달", verdict="BUY", reason="r")
    from models import db as _db
    _db.session.add(db_old)
    _db.session.commit()
    _migrate_categories()
    check("예전 종류 '배달' 기록은 서버 시작 때 '식비·배달'로 바뀜",
          _db.session.get(Consult, db_old.id).category == "식비·배달")

# ---- 화면 ----
r = c.get("/")
check("홈 화면 열림 + 상담 폼", r.status_code == 200 and b'id="consult-form"' in r.data)
r = c.get("/api/nothing")
check("없는 API 주소도 JSON 404", r.status_code == 404 and code_of(r) == "NOT_FOUND")
r = c.get("/health")
check("/health 그대로 ok", r.data == b"ok")
check("남은 가짜 답 없음 (AI 호출 횟수 예상대로)", replies == [], replies)

passed = sum(results)
print(f"\n결과: {passed}/{len(results)} 통과")
sys.exit(0 if passed == len(results) else 1)
