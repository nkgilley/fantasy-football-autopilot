from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase, Session
from typing import Generator

from app.config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(
    settings.sqlite_url,
    connect_args={"check_same_thread": False},
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def init_db() -> None:
    from app import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    migrations = [
        "ALTER TABLE roster_players ADD COLUMN ros_ecr INTEGER DEFAULT 999",
        "ALTER TABLE roster_players ADD COLUMN ros_pos_rank VARCHAR(32) DEFAULT ''",
        "ALTER TABLE free_agent_candidates ADD COLUMN ros_ecr INTEGER DEFAULT 999",
        "ALTER TABLE free_agent_candidates ADD COLUMN ros_pos_rank VARCHAR(32) DEFAULT ''",
        "ALTER TABLE free_agent_candidates ADD COLUMN recommended_drop_player_ros_rank VARCHAR(32) DEFAULT ''",
    ]
    with engine.begin() as conn:
        for stmt in migrations:
            try:
                conn.execute(text(stmt))
            except Exception:
                pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
