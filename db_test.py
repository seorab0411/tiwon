"""티원 - DB(Neon) 연결 테스트 (확인용, 서비스 코드 아님)"""
import os
import sys

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

url = os.environ.get("DATABASE_URL", "").strip().strip('"').strip("'")
if not url:
    print("[실패] .env에 DATABASE_URL이 없어요.")
    sys.exit(1)

# Neon 주소(postgresql://...)를 psycopg 3 드라이버용 주소로 바꿈
if url.startswith("postgres://"):
    url = "postgresql://" + url[len("postgres://"):]
if url.startswith("postgresql://"):
    url = "postgresql+psycopg://" + url[len("postgresql://"):]

try:
    engine = create_engine(url, pool_pre_ping=True)
    with engine.connect() as conn:
        version = conn.execute(text("SELECT version()")).scalar()
    print("[성공] DB 연결됨:", version.split(",")[0])
except Exception as e:
    print("[실패] DB 연결 오류:", e)
    sys.exit(1)