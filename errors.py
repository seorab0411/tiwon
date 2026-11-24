"""API 오류 응답 형식 통일: {"error": {"code": ..., "message": ...}}"""
from flask import jsonify


def api_error(status, code, message):
    return jsonify({"error": {"code": code, "message": message}}), status
