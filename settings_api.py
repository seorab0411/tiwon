"""예산·목표·줄이고 싶은 지출 설정 (기능 F-02)"""
from flask import Blueprint, g, jsonify, request

from auth import api_login_required
from errors import api_error
from models import THEMES, FocusTheme, Setting, db
from validators import validate_focus, validate_settings

bp = Blueprint("settings_api", __name__)


def setting_to_dict(s, focus):
    return {
        "monthly_budget": s.monthly_budget,
        "goal_name": s.goal_name,
        "goal_amount": s.goal_amount,
        "goal_deadline": s.goal_deadline.isoformat(),
        "tone": s.tone,
        # 고른 순서가 아니라 테마 목록 순서로 돌려준다
        "focus": {t: focus[t] for t in THEMES if t in focus},
    }


@bp.get("/api/settings")
@api_login_required
def get_settings():
    s = g.user.setting
    if s is None:
        return api_error(404, "NOT_FOUND", "아직 예산·목표를 설정하지 않았어요.")
    return jsonify(setting_to_dict(s, g.user.focus_map()))


@bp.put("/api/settings")
@api_login_required
def put_settings():
    data = request.get_json(silent=True) if request.is_json else None
    if not isinstance(data, dict):
        return api_error(400, "INVALID_INPUT", "JSON 형식으로 보내 주세요.")
    clean, errors = validate_settings(data)
    focus, focus_errors = validate_focus(data.get("focus"))
    errors += focus_errors
    if errors:
        return api_error(400, "INVALID_INPUT", errors[0])

    s = g.user.setting
    if s is None:
        s = Setting(user_id=g.user.id)
        db.session.add(s)
    for key, value in clean.items():
        setattr(s, key, value)

    # 줄이고 싶은 지출: 이번에 고른 것만 남기고 나머지는 지운다
    current = {f.category: f for f in g.user.focus_themes}
    for theme, row in current.items():
        if theme not in focus:
            db.session.delete(row)
    for theme, limit in focus.items():
        if theme in current:
            current[theme].limit_amount = limit
        else:
            db.session.add(FocusTheme(user_id=g.user.id, category=theme, limit_amount=limit))
    db.session.commit()
    db.session.refresh(g.user)
    return jsonify(setting_to_dict(s, g.user.focus_map()))
