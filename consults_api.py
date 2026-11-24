"""구매 상담·결과 기록·상담 기록·절약 현황 (기능 F-03 ~ F-08)"""
from datetime import datetime, timezone

from flask import Blueprint, g, jsonify, request
from sqlalchemy import func

import gemini_client
from auth import api_login_required
from consult_logic import (MAX_IMAGE_BYTES, AIResponseError, apply_guards, build_prompt,
                           calc_delay_days, daily_saving_target, detect_image_mime,
                           goal_progress, month_range_utc, parse_ai_response, to_kst,
                           validate_consult_input)
from errors import api_error
from models import DECISIONS, Consult, db
from validators import to_int, today_kst

bp = Blueprint("consults_api", __name__)

AI_ATTEMPTS = 2  # 응답 형식이 깨지면 1번 더 요청


# ---------- 조회 도우미 ----------

def _amount():
    """실제 결제 금액이 있으면 그것, 없으면 상담 때 가격"""
    return func.coalesce(Consult.actual_price, Consult.price)


def _in_month(query, start, end):
    return query.filter(Consult.created_at >= start, Consult.created_at < end)


def _spent(user_id, start, end):
    q = db.session.query(func.coalesce(func.sum(_amount()), 0)).filter(
        Consult.user_id == user_id, Consult.decision == "BOUGHT")
    return int(_in_month(q, start, end).scalar() or 0)


def _saved_total(user_id):
    q = db.session.query(func.coalesce(func.sum(_amount()), 0)).filter(
        Consult.user_id == user_id, Consult.decision == "SKIPPED")
    return int(q.scalar() or 0)


def _by_category(user_id, start, end):
    q = db.session.query(Consult.category, func.count(Consult.id), func.sum(_amount())).filter(
        Consult.user_id == user_id, Consult.decision == "BOUGHT")
    rows = _in_month(q, start, end).group_by(Consult.category).all()
    stats = [{"category": c, "count": int(n), "amount": int(a or 0)} for c, n, a in rows]
    return sorted(stats, key=lambda s: s["amount"], reverse=True)


def _recent_bought(user_id, start, end, limit=5):
    q = Consult.query.filter(Consult.user_id == user_id, Consult.decision == "BOUGHT")
    rows = _in_month(q, start, end).order_by(Consult.created_at.desc()).limit(limit).all()
    return [{"date": to_kst(c.created_at).date().isoformat(), "item_name": c.item_name,
             "price": c.actual_price if c.actual_price is not None else c.price,
             "category": c.category} for c in rows]


def consult_to_dict(c):
    created = to_kst(c.created_at)
    decided = to_kst(c.decided_at)
    return {
        "consult_id": c.id,
        "input_type": c.input_type,
        "item_name": c.item_name,
        "price": c.price,
        "category": c.category,
        "verdict": c.verdict,
        "reason": c.reason,
        "alternatives": list(c.alternatives or []),
        "delay_days": c.delay_days,
        "decision": c.decision,
        "actual_price": c.actual_price,
        "created_at": created.isoformat() if created else None,
        "decided_at": decided.isoformat() if decided else None,
    }


# ---------- F-03~05 구매 상담 ----------

@bp.post("/api/consults")
@api_login_required
def create_consult():
    # 다른 사이트의 폼이 몰래 보내는 요청 차단 (fetch로만 붙일 수 있는 머리글)
    if request.headers.get("X-Requested-With") != "fetch":
        return api_error(400, "INVALID_INPUT", "잘못된 요청이에요.")

    setting = g.user.setting
    if setting is None:
        return api_error(409, "SETTINGS_REQUIRED", "먼저 예산·목표를 설정해 주세요.")

    text, price, errors = validate_consult_input(request.form.get("text"),
                                                 request.form.get("price"))
    if errors:
        return api_error(400, "INVALID_INPUT", errors[0])

    image_bytes = image_mime = None
    upload = request.files.get("image")
    if upload is not None and upload.filename:
        image_bytes = upload.read(MAX_IMAGE_BYTES + 1)
        if len(image_bytes) > MAX_IMAGE_BYTES:
            return api_error(413, "IMAGE_TOO_LARGE", "사진은 5MB 이하만 올릴 수 있어요.")
        image_mime = detect_image_mime(image_bytes)
        if image_mime is None:
            return api_error(400, "INVALID_INPUT", "사진은 jpg, png, webp 파일만 올릴 수 있어요.")

    if not text and image_bytes is None:
        return api_error(400, "INVALID_INPUT", "상담 내용이나 사진 중 하나는 꼭 넣어 주세요.")

    # 숫자 계산은 코드가 먼저 한다
    _, start, end = month_range_utc()
    today = today_kst()
    remaining = setting.monthly_budget - _spent(g.user.id, start, end)
    daily = daily_saving_target(setting.goal_amount, setting.goal_deadline, today)

    prompt = build_prompt(
        tone=setting.tone, setting=setting, remaining_budget=remaining, daily_target=daily,
        category_stats=_by_category(g.user.id, start, end),
        recent_items=_recent_bought(g.user.id, start, end),
        text=text, price=price, has_image=image_bytes is not None, today=today,
    )

    result = None
    for _attempt in range(AI_ATTEMPTS):
        try:
            raw = gemini_client.ask(prompt, image_bytes, image_mime)
        except gemini_client.AIQuotaError:
            return api_error(429, "AI_QUOTA_EXCEEDED",
                             "오늘 AI 상담 한도를 다 썼어요. 내일 다시 시도해 주세요.")
        except gemini_client.AIUnavailableError:
            return api_error(503, "AI_UNAVAILABLE", "AI가 잠시 응답하지 않아요. 잠시 후 다시 시도해 주세요.")
        try:
            result = parse_ai_response(raw)
            break
        except AIResponseError:
            continue
    if result is None:
        return api_error(503, "AI_UNAVAILABLE", "AI 답변을 이해하지 못했어요. 다시 시도해 주세요.")

    if not result["recognized"]:
        return api_error(422, "ITEM_NOT_RECOGNIZED",
                         "무엇을 사려는지 알아보지 못했어요. 상품명과 가격을 글로 적어 주세요.")

    final_price = price if price is not None else result["price"]
    if final_price is None:
        return api_error(422, "PRICE_REQUIRED", "가격을 알아보지 못했어요. 가격을 직접 입력해 주세요.")

    apply_guards(result, final_price, remaining)

    consult = Consult(
        user_id=g.user.id,
        input_type="IMAGE" if image_bytes is not None else "TEXT",
        item_name=result["item_name"],
        price=final_price,
        category=result["category"],
        verdict=result["verdict"],
        reason=result["reason"],
        alternatives=result["alternatives"],
        delay_days=calc_delay_days(final_price, daily),
    )
    db.session.add(consult)
    db.session.commit()

    body = consult_to_dict(consult)
    body["remaining_budget"] = remaining
    body["message"] = result["message"]
    return jsonify(body), 201


# ---------- F-06 결과 기록 ----------

@bp.patch("/api/consults/<int:consult_id>/decision")
@api_login_required
def record_decision(consult_id):
    consult = db.session.get(Consult, consult_id)
    if consult is None or consult.user_id != g.user.id:  # 남의 기록은 없는 것처럼
        return api_error(404, "NOT_FOUND", "상담 기록을 찾을 수 없어요.")

    data = request.get_json(silent=True) if request.is_json else None
    if not isinstance(data, dict) or data.get("decision") not in DECISIONS:
        return api_error(400, "INVALID_INPUT", "decision은 BOUGHT 또는 SKIPPED여야 해요.")

    actual_price = None
    if data.get("actual_price") not in (None, ""):
        actual_price = to_int(data.get("actual_price"))
        if actual_price is None or actual_price < 0:
            return api_error(400, "INVALID_INPUT", "실제 가격은 0원 이상 숫자로 입력해 주세요.")

    consult.decision = data["decision"]
    consult.actual_price = actual_price
    consult.decided_at = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify(consult_to_dict(consult))


# ---------- F-08 상담 기록 / F-07 절약 현황 ----------

def _month_from_args():
    try:
        return month_range_utc(request.args.get("month"))
    except ValueError:
        return None


@bp.get("/api/consults")
@api_login_required
def list_consults():
    month = _month_from_args()
    if month is None:
        return api_error(400, "INVALID_INPUT", "month는 YYYY-MM 형식이어야 해요.")
    label, start, end = month
    q = _in_month(Consult.query.filter(Consult.user_id == g.user.id), start, end)
    rows = q.order_by(Consult.created_at.desc(), Consult.id.desc()).all()
    return jsonify({"month": label, "consults": [consult_to_dict(c) for c in rows]})


@bp.get("/api/summary")
@api_login_required
def summary():
    setting = g.user.setting
    if setting is None:
        return api_error(409, "SETTINGS_REQUIRED", "먼저 예산·목표를 설정해 주세요.")
    month = _month_from_args()
    if month is None:
        return api_error(400, "INVALID_INPUT", "month는 YYYY-MM 형식이어야 해요.")
    label, start, end = month
    spent = _spent(g.user.id, start, end)
    saved = _saved_total(g.user.id)
    return jsonify({
        "month": label,
        "monthly_budget": setting.monthly_budget,
        "spent": spent,
        "remaining_budget": setting.monthly_budget - spent,
        "saved_total": saved,
        "goal_name": setting.goal_name,
        "goal_amount": setting.goal_amount,
        "goal_progress": goal_progress(saved, setting.goal_amount),
        "by_category": _by_category(g.user.id, start, end),
    })
