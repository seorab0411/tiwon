"""회원가입·로그인 (기능 F-01)"""
from functools import wraps

from flask import Blueprint, g, jsonify, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from errors import api_error
from models import User, db
from validators import validate_signup

bp = Blueprint("auth", __name__)


def load_current_user():
    """요청마다 세션의 사용자 번호로 로그인한 사용자를 g.user에 넣는다."""
    user_id = session.get("user_id")
    g.user = db.session.get(User, user_id) if user_id else None
    if user_id and g.user is None:  # 삭제된 사용자면 세션 정리
        session.clear()


def api_login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if g.get("user") is None:
            return api_error(401, "UNAUTHORIZED", "로그인이 필요해요.")
        return view(*args, **kwargs)
    return wrapper


def page_login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if g.get("user") is None:
            return redirect(url_for("login_page"))
        return view(*args, **kwargs)
    return wrapper


def _json_body():
    """JSON 요청만 받는다 (다른 사이트에서 폼으로 몰래 보내는 요청 차단)."""
    if not request.is_json:
        return None
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else None


def _login(user):
    session.clear()  # 로그인 전 세션을 버려서 세션 고정 공격 방지
    session["user_id"] = user.id
    session.permanent = True


@bp.post("/api/auth/signup")
def signup():
    data = _json_body()
    if data is None:
        return api_error(400, "INVALID_INPUT", "JSON 형식으로 보내 주세요.")
    clean, errors = validate_signup(data)
    if errors:
        return api_error(400, "INVALID_INPUT", errors[0])

    if User.query.filter_by(username=clean["username"]).first():
        return api_error(409, "USERNAME_TAKEN", "이미 쓰고 있는 아이디예요.")

    user = User(username=clean["username"],
                password_hash=generate_password_hash(clean["password"]))
    db.session.add(user)
    db.session.commit()
    _login(user)
    return jsonify({"user_id": user.id, "username": user.username}), 201


@bp.post("/api/auth/login")
def login():
    data = _json_body()
    if data is None:
        return api_error(400, "INVALID_INPUT", "JSON 형식으로 보내 주세요.")
    username = data.get("username")
    password = data.get("password")
    if not isinstance(username, str) or not isinstance(password, str):
        return api_error(400, "INVALID_INPUT", "아이디와 비밀번호를 입력해 주세요.")

    user = User.query.filter_by(username=username.strip().lower()).first()
    if user is None or not check_password_hash(user.password_hash, password):
        # 아이디가 없는지 비밀번호가 틀렸는지 알려주지 않는다
        return api_error(401, "INVALID_CREDENTIALS", "아이디 또는 비밀번호가 맞지 않아요.")

    _login(user)
    return jsonify({"user_id": user.id, "username": user.username})


@bp.post("/api/auth/logout")
def logout():
    session.clear()
    return jsonify({"ok": True})
