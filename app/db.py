import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base


def normalize_db_url(url: str) -> str:
    url = url.strip().strip('"').strip("'")

    # Railway a veces entrega postgres://
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)

    # Si ya viene explicitado con psycopg2/psycopg3, lo corregimos
    if url.startswith("postgresql+psycopg2://"):
        url = url.replace("postgresql+psycopg2://", "postgresql+psycopg://", 1)

    if url.startswith("postgresql+psycopg3://"):
        url = url.replace("postgresql+psycopg3://", "postgresql+psycopg://", 1)

    # Si viene genérico, forzamos psycopg (psycopg3)
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)

    return url


raw = os.getenv("DATABASE_URL")
if not raw:
    raise RuntimeError("Missing DATABASE_URL")

DATABASE_URL = normalize_db_url(raw)

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    connect_args={"sslmode": "require"},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()