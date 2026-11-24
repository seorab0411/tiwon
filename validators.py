"""입력값 검사 (Flask 없이 동작하는 순수 함수 모음)."""
import re
from datetime import date, datetime, timedelta, timezone

from models import THEMES, TONES

KST = timezone(timedelta(hours=9))  # 한국은 서머타임이 없어서 +9 고정

USERNAME_RE = re.compile(r"^[a-z0-9_]{4,20}$")
MAX_BUDGET = 100_000_000          # 월 예산 최대 1억 원
MAX_GOAL_AMOUNT = 1_000_000_000   # 목표 금액 최대 10억 원


def today_kst():
    return datetime.now(KST).date()


def to_int(value):
    """정수 또는 숫자 문자열("500,000" 포함)만 정수로 바꾼다. 실패하면 None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        if re.fullmatch(r"-?\d+", text):
            return int(text)
    return None


def validate_signup(data):
    """회원가입·로그인 입력 검사. (정리된 값, 오류 목록) 반환"""
    errors = []
    username = data.get("username")
    password = data.get("password")

    username = username.strip().lower() if isinstance(username, str) else ""
    if not USERNAME_RE.fullmatch(username):
        errors.append("아이디는 영문 소문자·숫자·밑줄(_)로 4~20자여야 해요.")

    if not isinstance(password, str) or not 8 <= len(password) <= 64:
        errors.append("비밀번호는 8~64자여야 해요.")
        password = ""

    return {"username": username, "password": password}, errors


def validate_settings(data, today=None):
    """예산·목표 입력 검사. (정리된 값, 오류 목록) 반환"""
    today = today or today_kst()
    errors = []
    clean = {}

    budget = to_int(data.get("monthly_budget"))
    if budget is None or not 1 <= budget <= MAX_BUDGET:
        errors.append("월 예산은 1원 이상 1억 원 이하 숫자로 입력해 주세요.")
    clean["monthly_budget"] = budget

    goal_name = data.get("goal_name")
    goal_name = goal_name.strip() if isinstance(goal_name, str) else ""
    if not 1 <= len(goal_name) <= 50:
        errors.append("목표 이름은 1~50자로 입력해 주세요.")
    clean["goal_name"] = goal_name

    goal_amount = to_int(data.get("goal_amount"))
    if goal_amount is None or not 1 <= goal_amount <= MAX_GOAL_AMOUNT:
        errors.append("목표 금액은 1원 이상 10억 원 이하 숫자로 입력해 주세요.")
    clean["goal_amount"] = goal_amount

    deadline = None
    raw = data.get("goal_deadline")
    if isinstance(raw, str):
        try:
            deadline = date.fromisoformat(raw.strip())
        except ValueError:
            deadline = None
    if deadline is None:
        errors.append("목표 날짜를 YYYY-MM-DD 형식으로 입력해 주세요.")
    elif deadline <= today:
        errors.append("목표 날짜는 오늘 이후여야 해요.")
    clean["goal_deadline"] = deadline

    tone = data.get("tone", "friend")
    if tone not in TONES:
        errors.append("말투는 mom, roast, friend 중 하나여야 해요.")
    clean["tone"] = tone

    return clean, errors


MAX_LIMIT = 10_000_000  # 한 번 기준 금액 최대 1,000만 원


def validate_focus(value):
    """줄이고 싶은 지출 테마 검사. 입력: {테마: 기준 금액(숫자·문자·빈값)}. (정리된 값, 오류 목록)"""
    if not isinstance(value, dict) or not value:
        return {}, ["줄이고 싶은 지출을 하나 이상 골라 주세요."]
    clean, errors = {}, []
    for theme, raw in value.items():
        if theme not in THEMES:
            errors.append(f"고를 수 없는 테마예요: {theme}")
            continue
        if raw is None or (isinstance(raw, str) and raw.strip() == ""):
            clean[theme] = None
            continue
        amount = to_int(raw)
        if amount is None or not 1 <= amount <= MAX_LIMIT:
            errors.append(f"{theme} 기준 금액은 1원 이상 1,000만 원 이하 숫자로 입력해 주세요.")
            continue
        clean[theme] = amount
    return clean, errors
