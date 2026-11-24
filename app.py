import os
import secrets
import time
from datetime import timedelta

from dotenv import load_dotenv
from flask import Flask, g, redirect, render_template, request, url_for
from sqlalchemy.exc import OperationalError

import auth
import consults_api
import settings_api
from db_url import normalize_db_url
from errors import api_error
from models import LEGACY_CATEGORIES, THEMES, Consult, db


def _migrate_categories():
    """예전 7개 종류로 저장된 상담 기록을 새 테마 이름으로 바꾼다 (이미 바뀌었으면 아무것도 안 함)"""
    changed = 0
    for old_name, new_name in LEGACY_CATEGORIES.items():
        changed += Consult.query.filter_by(category=old_name).update({"category": new_name})
    if changed:
        db.session.commit()
        print(f"[DB] 예전 종류 이름 {changed}건을 새 테마로 바꿨어요.", flush=True)


def _create_tables(app, attempts=3, wait_seconds=3):
    """테이블 만들기. DB가 잠깐 늦게 깨도 몇 번 다시 시도하고, 끝내 실패해도 서버는 켠다."""
    for n in range(1, attempts + 1):
        try:
            with app.app_context():
                db.create_all()
                _migrate_categories()
            return True
        except OperationalError as e:
            first_line = str(getattr(e, "orig", e)).splitlines()[0]
            print(f"[경고] DB 연결 실패 ({n}/{attempts}): {first_line}")
            if n < attempts:
                time.sleep(wait_seconds)
    print("[경고] DB에 연결하지 못했어요. 서버는 켜지지만 DB가 필요한 화면은 오류 안내가 나옵니다.")
    return False


def create_app(test_config=None):
    load_dotenv()
    app = Flask(__name__)

    secret = os.environ.get("SECRET_KEY")
    if not secret:
        # 없으면 임시 키 사용 (서버 재시작 시 로그인 풀림) → .env와 Render에 꼭 등록
        print("[경고] SECRET_KEY가 없어 임시 키를 씁니다.")
        secret = secrets.token_hex(32)

    app.config.update(
        SECRET_KEY=secret,
        SQLALCHEMY_DATABASE_URI=(
            normalize_db_url(os.environ.get("DATABASE_URL")) or "sqlite:///tiwon.db"
        ),
        SQLALCHEMY_ENGINE_OPTIONS={"pool_pre_ping": True},
        PERMANENT_SESSION_LIFETIME=timedelta(days=14),
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=bool(os.environ.get("RENDER")),  # Render(https)에서만
        MAX_CONTENT_LENGTH=6 * 1024 * 1024,  # 요청 전체 6MB 제한 (사진 5MB + 여유)
    )
    if test_config:
        app.config.update(test_config)
    if app.config["SQLALCHEMY_DATABASE_URI"].startswith("postgresql"):
        # 접속이 막힌 네트워크에서 한없이 기다리지 않게 10초 제한
        app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
            "pool_pre_ping": True, "connect_args": {"connect_timeout": 10}}

    db.init_app(app)
    app.register_blueprint(auth.bp)
    app.register_blueprint(settings_api.bp)
    app.register_blueprint(consults_api.bp)
    app.before_request(auth.load_current_user)

    _create_tables(app)  # 없는 테이블만 만든다 (DB 연결이 잠깐 안 돼도 서버는 켜짐)

    # DB 연결이 끊긴 상태에서 들어온 요청은 서버 오류 대신 안내로 응답
    @app.errorhandler(OperationalError)
    def db_unavailable(e):
        try:
            db.session.rollback()
        except Exception:
            pass
        if request.path.startswith("/api/"):
            return api_error(503, "DB_UNAVAILABLE", "데이터베이스에 연결하지 못했어요. 잠시 후 다시 시도해 주세요.")
        return "데이터베이스에 연결하지 못했어요. 잠시 후 새로고침해 주세요.", 503

    # API 주소에서 난 오류는 화면 대신 명세서 형식(JSON)으로 돌려준다
    @app.errorhandler(413)
    def too_large(e):
        if request.path.startswith("/api/"):
            return api_error(413, "IMAGE_TOO_LARGE", "사진은 5MB 이하만 올릴 수 있어요.")
        return e

    @app.errorhandler(404)
    def not_found(e):
        if request.path.startswith("/api/"):
            return api_error(404, "NOT_FOUND", "없는 주소예요.")
        return e

    @app.errorhandler(405)
    def wrong_method(e):
        if request.path.startswith("/api/"):
            return api_error(405, "METHOD_NOT_ALLOWED", "지원하지 않는 요청 방식이에요.")
        return e

    @app.errorhandler(500)
    def server_error(e):
        try:
            db.session.rollback()
        except Exception:
            pass
        if request.path.startswith("/api/"):
            return api_error(500, "INTERNAL_ERROR", "서버 오류가 생겼어요. 잠시 후 다시 시도해 주세요.")
        return e

    @app.route("/health")
    def health():
        # 잠들기 방지용: DB를 건드리지 않고 바로 응답
        return "ok"

    @app.route("/login")
    def login_page():
        if g.user is not None:
            return redirect(url_for("home"))
        return render_template("login.html")

    @app.route("/settings")
    @auth.page_login_required
    def settings_page():
        return render_template("settings.html", setting=g.user.setting,
                               focus=g.user.focus_map(), themes=THEMES)

    @app.route("/")
    @auth.page_login_required
    def home():
        if g.user.setting is None or not g.user.focus_themes:
            return redirect(url_for("settings_page"))
        return render_template("index.html", setting=g.user.setting, focus=g.user.focus_map())

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
