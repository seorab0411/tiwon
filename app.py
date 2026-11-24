import os
import secrets
from datetime import timedelta

from dotenv import load_dotenv
from flask import Flask, g, redirect, render_template, request, url_for

import auth
import consults_api
import settings_api
from db_url import normalize_db_url
from errors import api_error
from models import db


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

    db.init_app(app)
    app.register_blueprint(auth.bp)
    app.register_blueprint(settings_api.bp)
    app.register_blueprint(consults_api.bp)
    app.before_request(auth.load_current_user)

    with app.app_context():
        db.create_all()  # 없는 테이블만 만든다

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
        return render_template("settings.html", setting=g.user.setting)

    @app.route("/")
    @auth.page_login_required
    def home():
        if g.user.setting is None:
            return redirect(url_for("settings_page"))
        return render_template("index.html", setting=g.user.setting)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
