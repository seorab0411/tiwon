"""티원 - 테이블 검증 (메모리 DB에서만 실행, Neon은 건드리지 않음)"""
import sys
from datetime import date

from flask import Flask
from sqlalchemy import event, inspect
from sqlalchemy.exc import IntegrityError

from models import Consult, Setting, User, db

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite://"
db.init_app(app)

results = []


def check(name, ok):
    results.append(bool(ok))
    print(("[통과] " if ok else "[실패] ") + name)


def must_fail(name, row, expected):
    """row 저장이 expected 이유로 막히는지 확인"""
    try:
        db.session.add(row)
        db.session.commit()
        check(name, False)
    except IntegrityError as e:
        db.session.rollback()
        ok = expected in str(e.orig)
        check(name if ok else f"{name} (다른 이유로 막힘: {e.orig})", ok)


with app.app_context():
    # SQLite는 외래키 검사가 기본으로 꺼져 있어서 켜준다 (PostgreSQL은 항상 켜짐)
    @event.listens_for(db.engine, "connect")
    def _fk_on(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    db.engine.dispose()
    db.create_all()

    tables = set(inspect(db.engine).get_table_names())
    check("테이블 3개 생성 (users, settings, consults)",
          {"users", "settings", "consults"} <= tables)

    u = User(username="tiwon01", password_hash="hash")
    u2 = User(username="tiwon02", password_hash="hash")
    db.session.add_all([u, u2])
    db.session.commit()
    check("사용자 저장 + 가입일 자동 입력", u.id is not None and u.created_at is not None)

    s = Setting(user_id=u.id, monthly_budget=500000, goal_name="노트북",
                goal_amount=1500000, goal_deadline=date(2027, 2, 28))
    db.session.add(s)
    db.session.commit()
    check("예산·목표 저장 + 말투 기본값 friend", s.tone == "friend")

    c = Consult(user_id=u.id, input_type="TEXT", item_name="에어팟 프로", price=350000,
                category="전자기기", verdict="CONDITIONAL", reason="목표가 21일 늦어져요.",
                alternatives=["할인 때 구매", "중고 확인"], delay_days=21)
    db.session.add(c)
    db.session.commit()
    cid = c.id
    db.session.expire_all()
    c = db.session.get(Consult, cid)
    check("상담 저장 + 대안 목록 그대로 읽힘", c.alternatives == ["할인 때 구매", "중고 확인"])
    check("결정 전 decision은 빈값", c.decision is None)

    c.decision, c.actual_price = "SKIPPED", 350000
    db.session.commit()
    check("참음 기록 저장", db.session.get(Consult, cid).decision == "SKIPPED")

    def consult(**kw):
        base = dict(user_id=u.id, input_type="TEXT", item_name="a", price=1,
                    verdict="BUY", reason="r")
        base.update(kw)
        return Consult(**base)

    def setting(**kw):
        base = dict(user_id=u2.id, monthly_budget=1, goal_name="g",
                    goal_amount=1, goal_deadline=date(2027, 1, 1))
        base.update(kw)
        return Setting(**base)

    must_fail("같은 아이디 중복 가입 막힘",
              User(username="tiwon01", password_hash="x"), "UNIQUE")
    must_fail("잘못된 판단값 막힘", consult(verdict="MAYBE"), "ck_consults_verdict")
    must_fail("잘못된 결정값 막힘", consult(decision="LATER"), "ck_consults_decision")
    must_fail("잘못된 입력 종류 막힘", consult(input_type="VOICE"), "ck_consults_input_type")
    must_fail("음수 가격 막힘", consult(price=-1), "ck_consults_price")
    must_fail("없는 사용자 상담 막힘", consult(user_id=999), "FOREIGN KEY")
    must_fail("예산 0원 막힘", setting(monthly_budget=0), "ck_settings_budget")
    must_fail("잘못된 말투 막힘", setting(tone="angry"), "ck_settings_tone")
    must_fail("한 사람당 설정 1개만", setting(user_id=u.id), "UNIQUE")

    db.session.delete(db.session.get(User, u.id))
    db.session.commit()
    check("사용자 삭제 시 설정·상담도 함께 삭제",
          db.session.query(Setting).filter_by(user_id=u.id).count() == 0
          and db.session.query(Consult).count() == 0)

passed = sum(results)
print(f"\n결과: {passed}/{len(results)} 통과")
sys.exit(0 if passed == len(results) else 1)
