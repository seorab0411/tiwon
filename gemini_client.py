"""Gemini API 호출만 담당 (google-genai 라이브러리).

한 모델이 붐비거나(503) 한도가 차면(429) 예비 모델로 자동으로 넘어간다.
"""
import os

TIMEOUT_MS = 20_000          # 모델 하나당 최대 20초 (모델 3개 × 20초 < gunicorn 150초)
DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_FALLBACKS = "gemini-2.5-flash,gemini-3.5-flash"
MAX_MODELS = 3

_client = None


class AIQuotaError(Exception):
    """모든 모델의 무료 사용 한도 초과 (429)"""


class AIUnavailableError(Exception):
    """키 없음·네트워크 오류·서버 혼잡·빈 응답 등"""


def model_name():
    return os.environ.get("GEMINI_MODEL", "").strip() or DEFAULT_MODEL


def model_candidates():
    """먼저 쓸 모델 + 예비 모델 (중복 없이 최대 3개)"""
    fallbacks = os.environ.get("GEMINI_FALLBACK_MODELS", DEFAULT_FALLBACKS)
    names = [model_name()] + [m.strip() for m in fallbacks.split(",")]
    result = []
    for name in names:
        if name and name not in result:
            result.append(name)
    return result[:MAX_MODELS]


def _get_client():
    global _client
    if _client is None:
        key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not key:
            raise AIUnavailableError("GEMINI_API_KEY가 설정되지 않았어요.")
        try:
            from google import genai
            from google.genai import types
        except Exception as e:  # 라이브러리 설치 문제
            raise AIUnavailableError(f"google-genai 불러오기 실패: {e}") from e
        try:
            _client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=TIMEOUT_MS))
        except Exception:
            _client = genai.Client(api_key=key)  # 시간 제한 옵션을 못 쓰는 버전 대비
    return _client


def _status_code(e):
    code = getattr(e, "code", None) or getattr(e, "status_code", None)
    if code is None:
        return None
    try:
        return int(code)
    except (TypeError, ValueError):
        return None


def _is_quota_error(e):
    return _status_code(e) == 429 or "RESOURCE_EXHAUSTED" in str(e)


def _should_try_next_model(e):
    """다른 모델로 바꾸면 될 수도 있는 오류: 혼잡(5xx), 한도(429), 없는 모델(404), 시간 초과"""
    code = _status_code(e)
    text = str(e)
    if code is not None and (code >= 500 or code in (404, 429)):
        return True
    return any(word in text for word in ("UNAVAILABLE", "RESOURCE_EXHAUSTED", "overloaded",
                                         "high demand", "timed out", "Timeout", "NOT_FOUND"))


def _log(message):
    print(f"[Gemini] {message}", flush=True)  # Render Logs에 남는다


def ask(prompt, image_bytes=None, image_mime=None):
    """프롬프트(+사진)를 보내고 응답 글을 돌려준다."""
    client = _get_client()
    from google.genai import types

    contents = [prompt]
    if image_bytes:
        contents.append(types.Part.from_bytes(data=image_bytes, mime_type=image_mime))
    config = types.GenerateContentConfig(response_mime_type="application/json", temperature=0.4)

    errors = []
    for name in model_candidates():
        try:
            response = client.models.generate_content(model=name, contents=contents, config=config)
        except Exception as e:
            first_line = str(e).splitlines()[0][:300]
            _log(f"{name} 실패: {first_line}")
            errors.append(e)
            if _should_try_next_model(e):
                continue
            raise AIUnavailableError(first_line) from e

        text = getattr(response, "text", None)
        if text:
            if name != model_candidates()[0]:
                _log(f"예비 모델 {name}로 응답 받음")
            return text
        _log(f"{name} 빈 응답")
        errors.append(AIUnavailableError("빈 응답"))

    if errors and all(_is_quota_error(e) for e in errors):
        raise AIQuotaError("모든 모델의 무료 한도를 다 썼어요.")
    raise AIUnavailableError("모든 모델이 응답하지 않았어요.")
