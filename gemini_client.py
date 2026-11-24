"""Gemini API 호출만 담당 (google-genai 라이브러리)."""
import os

TIMEOUT_MS = 40_000          # 한 번 호출 최대 40초 (gunicorn 제한 90초 안쪽)
DEFAULT_MODEL = "gemini-2.5-flash"

_client = None


class AIQuotaError(Exception):
    """무료 사용 한도 초과 (429)"""


class AIUnavailableError(Exception):
    """키 없음·네트워크 오류·서버 오류·빈 응답 등"""


def model_name():
    return os.environ.get("GEMINI_MODEL", "").strip() or DEFAULT_MODEL


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


def _is_quota_error(e):
    code = getattr(e, "code", None) or getattr(e, "status_code", None)
    return code == 429 or "RESOURCE_EXHAUSTED" in str(e) or "429" in str(code or "")


def ask(prompt, image_bytes=None, image_mime=None):
    """프롬프트(+사진)를 보내고 응답 글을 돌려준다."""
    client = _get_client()
    from google.genai import types

    contents = [prompt]
    if image_bytes:
        contents.append(types.Part.from_bytes(data=image_bytes, mime_type=image_mime))

    try:
        response = client.models.generate_content(
            model=model_name(),
            contents=contents,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.4,
            ),
        )
    except Exception as e:
        if _is_quota_error(e):
            raise AIQuotaError(str(e)) from e
        raise AIUnavailableError(str(e)) from e

    text = getattr(response, "text", None)
    if not text:
        raise AIUnavailableError("Gemini가 빈 응답을 보냈어요.")
    return text
