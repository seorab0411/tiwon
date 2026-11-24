"""티원 - 로그인·설정 기능 검증 (메모리 DB에서만 실행, Neon은 건드리지 않음)"""
import os
import sys
from datetime import timedelta

os.environ["DATABASE_URL"] = "sqlite://"  # app.py를 불러올 때 Neon에 접속하지 않게
os.environ.setdefault("SECRET_KEY", "test-secret")

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


future = (today_kst() + timedelta(days=90)).isoformat()
good_settings = {"monthly_budget": "500,000", "goal_name": "노트북",
                 "goal_amount": 1500000, "goal_deadline": future, "tone": "mom",
                 "focus": {"식비·배달": "20,000", "게임": ""}}

c = app.test_client()

# 1) 로그인 전
r = c.get("/health")
check("/health는 로그인 없이 ok", r.status_code == 200 and r.data == b"ok")
r = c.get("/")
check("로그인 전 홈 → 로그인 화면으로 이동", r.status_code == 302 and "/login" in r.location)
r = c.get("/login")
check("로그인 화면 열림", r.status_code == 200 and "로그인".encode() in r.data)
r = c.get("/api/settings")
check("로그인 전 설정 API → 401", r.status_code == 401 and code_of(r) == "UNAUTHORIZED")

# 2) 회원가입
r = c.post("/api/auth/signup", data="username=a&password=b")
check("JSON이 아니면 거절", r.status_code == 400, r.status_code)
r = c.post("/api/auth/signup", json={"username": "ab", "password": "12345678"})
check("짧은 아이디 거절", r.status_code == 400 and code_of(r) == "INVALID_INPUT")
r = c.post("/api/auth/signup", json={"username": "tiwon01", "password": "123"})
check("짧은 비밀번호 거절", r.status_code == 400)
r = c.post("/api/auth/signup", json={"username": "tiwon01", "password": "password123",
                                     "password_confirm": "password12"})
check("비밀번호 확인이 다르면 가입 거절", r.status_code == 400 and code_of(r) == "PASSWORD_MISMATCH")
r = c.post("/api/auth/signup", json={"username": "  TiWon01 ", "password": "password123",
                                     "password_confirm": "password123"})
check("회원가입 성공 (아이디는 소문자로 정리)",
      r.status_code == 201 and r.get_json()["username"] == "tiwon01", r.get_json())
with app.app_context():
    from models import User
    stored = User.query.filter_by(username="tiwon01").first()
    check("비밀번호는 원문이 아니라 해시로 저장",
          stored is not None and stored.password_hash != "password123")

# 3) 가입 직후 자동 로그인 + 설정 전
r = c.get("/")
check("설정 전 홈 → 설정 화면으로 이동", r.status_code == 302 and "/settings" in r.location)
r = c.get("/settings")
check("설정 화면 열림", r.status_code == 200 and "예산".encode() in r.data)
r = c.get("/api/settings")
check("설정 전 조회 → 404", r.status_code == 404)

# 4) 설정 저장
r = c.put("/api/settings", json={**good_settings, "goal_deadline": today_kst().isoformat()})
check("목표 날짜가 오늘이면 거절", r.status_code == 400)
r = c.put("/api/settings", json={**good_settings, "monthly_budget": "abc"})
check("예산이 숫자가 아니면 거절", r.status_code == 400)
r = c.put("/api/settings", json={**good_settings, "monthly_budget": True})
check("예산에 true 들어오면 거절", r.status_code == 400)
r = c.put("/api/settings", json={k: v for k, v in good_settings.items() if k != "focus"})
check("줄이고 싶은 지출을 안 고르면 거절", r.status_code == 400)
r = c.put("/api/settings", json={**good_settings, "focus": {}})
check("줄이고 싶은 지출이 빈 목록이면 거절", r.status_code == 400)
r = c.put("/api/settings", json={**good_settings, "focus": {"택시": 1000}})
check("없는 테마는 거절", r.status_code == 400)
r = c.put("/api/settings", json={**good_settings, "focus": {"게임": "-5"}})
check("기준 금액이 음수면 거절", r.status_code == 400)
r = c.put("/api/settings", json={**good_settings, "tone": "angry"})
check("없는 말투 거절", r.status_code == 400)
r = c.put("/api/settings", json=good_settings)
body = r.get_json() or {}
check("설정 저장 성공 (\"500,000\" → 500000)",
      r.status_code == 200 and body.get("monthly_budget") == 500000, body)
r = c.put("/api/settings", json={**good_settings, "goal_name": "아이패드"})
check("다시 저장하면 수정 (행 추가 아님)",
      r.status_code == 200 and r.get_json()["goal_name"] == "아이패드")
with app.app_context():
    from models import Setting
    check("설정은 1행만 존재", Setting.query.count() == 1, Setting.query.count())
r = c.get("/")
check("설정 후 홈 열림 + 목표 표시", r.status_code == 200 and "아이패드".encode() in r.data)
r = c.get("/settings")
check("설정 화면에 저장값 채워짐", "500000".encode() in r.data and b'value="mom" selected' in r.data)
check("설정 화면에 고른 테마 체크·기준 금액 채워짐",
      'value="식비·배달" checked'.encode() in r.data and 'value="20000"'.encode() in r.data
      and 'value="카페" checked'.encode() not in r.data)
r = c.get("/api/settings")
check("설정 조회에 테마·기준 금액 포함",
      r.get_json().get("focus") == {"식비·배달": 20000, "게임": None}, r.get_json())
r = c.put("/api/settings", json={**good_settings, "goal_name": "아이패드", "focus": {"카페": 4500}})
check("테마를 바꾸면 예전 테마는 지워짐", r.get_json().get("focus") == {"카페": 4500}, r.get_json())
with app.app_context():
    from models import FocusTheme
    check("테마 행도 바꾼 것만 남음", FocusTheme.query.count() == 1)

# 5) 로그아웃 / 로그인
r = c.post("/api/auth/logout")
check("로그아웃", r.status_code == 200)
r = c.get("/api/settings")
check("로그아웃 후 설정 API → 401", r.status_code == 401)
r = c.post("/api/auth/login", json={"username": "tiwon01", "password": "wrongpass1"})
check("틀린 비밀번호 → 401", r.status_code == 401 and code_of(r) == "INVALID_CREDENTIALS")
r = c.post("/api/auth/login", json={"username": "nobody", "password": "wrongpass1"})
check("없는 아이디도 같은 오류 (아이디 존재 여부 숨김)",
      r.status_code == 401 and code_of(r) == "INVALID_CREDENTIALS")
r = c.post("/api/auth/login", json={"username": "TIWON01", "password": "password123"})
check("로그인 성공 (대문자로 입력해도)", r.status_code == 200)
r = c.get("/api/settings")
check("로그인 후 내 설정 조회", r.status_code == 200 and r.get_json()["goal_name"] == "아이패드")
r = c.get("/login")
check("로그인 상태에서 로그인 화면 → 홈으로", r.status_code == 302)

# 6) 다른 사용자와 데이터 분리
c2 = app.test_client()
r = c2.post("/api/auth/signup", json={"username": "tiwon01", "password": "password123"})
check("같은 아이디 중복 가입 → 409", r.status_code == 409 and code_of(r) == "USERNAME_TAKEN")
c2.post("/api/auth/signup", json={"username": "tiwon02", "password": "password123"})
r = c2.get("/api/settings")
check("다른 사용자는 내 설정을 못 봄", r.status_code == 404)

passed = sum(results)
print(f"\n결과: {passed}/{len(results)} 통과")
sys.exit(0 if passed == len(results) else 1)
