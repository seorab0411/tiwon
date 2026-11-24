"""티원 DB 테이블 정의 (기능명세서 '데이터 모델' 기준)."""
from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

TONES = ("mom", "roast", "friend")
VERDICTS = ("BUY", "CONDITIONAL", "SKIP")
DECISIONS = ("BOUGHT", "SKIPPED")
INPUT_TYPES = ("IMAGE", "TEXT")
# 사용자가 "줄이고 싶은 지출"로 고를 수 있는 테마 (= 상담 기록의 종류)
THEMES = ("식비·배달", "카페", "쇼핑", "게임", "편의점·마트", "술·유흥", "구독 서비스", "담배")
CATEGORIES = THEMES + ("기타",)
# 예전 7개 종류로 저장된 기록을 새 종류로 옮길 때 쓰는 표
LEGACY_CATEGORIES = {"식비": "식비·배달", "배달": "식비·배달", "전자기기": "쇼핑", "생필품": "편의점·마트"}


def now_utc():
    return datetime.now(timezone.utc)


def _in(column, values):
    """CHECK 제약 문장 만들기: column IN ('a', 'b')"""
    joined = ", ".join(f"'{v}'" for v in values)
    return f"{column} IN ({joined})"


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(30), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=now_utc)

    setting = db.relationship(
        "Setting", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    consults = db.relationship(
        "Consult", back_populates="user", cascade="all, delete-orphan"
    )
    focus_themes = db.relationship(
        "FocusTheme", back_populates="user", cascade="all, delete-orphan"
    )

    def focus_map(self):
        """{테마: 한 번 기준 금액 또는 None} — 사용자가 고른 '줄이고 싶은 지출'"""
        return {f.category: f.limit_amount for f in self.focus_themes}


class Setting(db.Model):
    """예산·목표 (사용자당 1행)"""
    __tablename__ = "settings"
    __table_args__ = (
        db.CheckConstraint("monthly_budget > 0", name="ck_settings_budget"),
        db.CheckConstraint("goal_amount > 0", name="ck_settings_goal_amount"),
        db.CheckConstraint(_in("tone", TONES), name="ck_settings_tone"),
    )

    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    monthly_budget = db.Column(db.Integer, nullable=False)
    goal_name = db.Column(db.String(50), nullable=False)
    goal_amount = db.Column(db.Integer, nullable=False)
    goal_deadline = db.Column(db.Date, nullable=False)
    tone = db.Column(db.String(10), nullable=False, default="friend")
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=now_utc, onupdate=now_utc
    )

    user = db.relationship("User", back_populates="setting")


class Consult(db.Model):
    """구매 상담 기록"""
    __tablename__ = "consults"
    __table_args__ = (
        db.CheckConstraint(_in("input_type", INPUT_TYPES), name="ck_consults_input_type"),
        db.CheckConstraint(_in("verdict", VERDICTS), name="ck_consults_verdict"),
        db.CheckConstraint(
            "decision IS NULL OR " + _in("decision", DECISIONS), name="ck_consults_decision"
        ),
        db.CheckConstraint("price >= 0", name="ck_consults_price"),
        db.CheckConstraint(
            "actual_price IS NULL OR actual_price >= 0", name="ck_consults_actual_price"
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    input_type = db.Column(db.String(10), nullable=False)
    item_name = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Integer, nullable=False)
    category = db.Column(db.String(20), nullable=False, default="기타")
    verdict = db.Column(db.String(15), nullable=False)
    reason = db.Column(db.Text, nullable=False)
    alternatives = db.Column(db.JSON, nullable=False, default=list)
    delay_days = db.Column(db.Integer)
    decision = db.Column(db.String(10))
    actual_price = db.Column(db.Integer)
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=now_utc, index=True
    )
    decided_at = db.Column(db.DateTime(timezone=True))

    user = db.relationship("User", back_populates="consults")


class FocusTheme(db.Model):
    """사용자가 집중해서 줄이고 싶다고 고른 지출 테마 (1개 이상). 기준 금액은 선택"""
    __tablename__ = "focus_themes"
    # 테마 이름은 DB 제약 대신 코드(validators.validate_focus)에서 검사한다.
    # 그래야 나중에 테마를 추가해도 이미 만든 Neon 테이블을 고칠 필요가 없다.
    __table_args__ = (
        db.CheckConstraint("limit_amount IS NULL OR limit_amount > 0", name="ck_focus_limit"),
    )

    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    category = db.Column(db.String(20), primary_key=True)
    limit_amount = db.Column(db.Integer)  # 한 번에 쓸 기준 금액 (없으면 None)

    user = db.relationship("User", back_populates="focus_themes")
