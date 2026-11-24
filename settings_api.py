"""예산·목표 설정 (기능 F-02)"""
from flask import Blueprint, g, jsonify, request

from auth import api_login_required
from errors import api_error
from models import Setting, db
from validators import validate_settings

bp = Blueprint("settings_api", __name__)


def setting_to_dict(s):
    return {
        "monthly_budget": s.monthly_budget,
        "goal_name": s.goal_name,
        "goal_amount": s.goal_amount,
        "goal_deadline": s.goal_deadline.isoformat(),
        "tone": s.tone,
    }


@bp.get("/api/settings")
@api_login_required
def get_settings():
    s = g.user.setting
    if s is None:
        return api_error(404, "NOT_FOUND", "아직 예산·목표를 설정하지 않았어요.")
    return jsonify(setting_to_dict(s))


@bp.put("/api/settings")
@api_login_required
def put_settings():
    data = request.get_json(silent=True) if request.is_json else None
    if not isinstance(data, dict):
        return api_error(400, "INVALID_INPUT", "JSON 형식으로 보내 주세요.")
    clean, errors = validate_settings(data)
    if errors:
        return api_error(400, "INVALID_INPUT", errors[0])

    s = g.user.setting
    if s is None:
        s = Setting(user_id=g.user.id)
        db.session.add(s)
    for key, value in clean.items():
        setattr(s, key, value)
    db.session.commit()
    return jsonify(setting_to_dict(s))
