"""DB 주소 정리: Neon 주소를 SQLAlchemy + psycopg 3 드라이버용으로 바꾼다."""


def normalize_db_url(url):
    """빈 값이면 None, 아니면 드라이버에 맞는 주소를 돌려준다."""
    if not url:
        return None
    url = url.strip().strip('"').strip("'")
    if not url:
        return None
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url
