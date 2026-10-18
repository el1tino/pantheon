from collections.abc import Iterator

from sqlmodel import Session, SQLModel, create_engine

from app.config import get_settings

_engine = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(
            get_settings().database_url, connect_args={"check_same_thread": False}
        )
    return _engine


def init_db() -> None:
    from app.db import models  # noqa: F401  (registers tables)

    SQLModel.metadata.create_all(get_engine())
    _add_missing_columns()


# Columns added after a table first existed. create_all never alters tables, so databases
# from earlier milestones get them here.
_LATER_COLUMNS = {
    "runs": {"owner_id": "VARCHAR", "public": "BOOLEAN NOT NULL DEFAULT 0", "site_key": "VARCHAR"},
}


def _add_missing_columns() -> None:
    import secrets

    from sqlalchemy import text

    with get_engine().begin() as conn:
        for table, columns in _LATER_COLUMNS.items():
            have = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}
            for name, ddl in columns.items():
                if name not in have:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
        for (run_id,) in conn.execute(text("SELECT id FROM runs WHERE site_key IS NULL")).fetchall():
            conn.execute(text("UPDATE runs SET site_key = :k WHERE id = :id"),
                         {"k": secrets.token_urlsafe(18), "id": run_id})


def get_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session
