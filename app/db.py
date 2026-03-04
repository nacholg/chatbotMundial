import os
from sqlalchemy import create_engine

def normalize_db_url(url: str) -> str:
    # Railway a veces entrega postgres://
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    # Forzamos psycopg3
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url

raw = os.getenv("SQLALCHEMY_DATABASE_URL") or os.getenv("DATABASE_URL")
if not raw:
    raise RuntimeError("Missing DATABASE_URL / SQLALCHEMY_DATABASE_URL")

DATABASE_URL = normalize_db_url(raw)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)