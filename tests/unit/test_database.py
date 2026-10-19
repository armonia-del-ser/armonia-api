from sqlmodel import Session, select, text

from app.db.database import get_engine, get_engine_url, get_session
from app.models.service import Service


def test_get_engine_url_formats():
    assert get_engine_url("file:local.db") == "sqlite:///local.db"
    assert get_engine_url("sqlite:///local.db") == "sqlite:///local.db"
    assert (
        get_engine_url("libsql://my-db.turso.io", "sec-token")
        == "sqlite+libsql://my-db.turso.io?auth_token=sec-token"
    )
    assert (
        get_engine_url("sqlite+libsql://my-db.turso.io", "sec-token")
        == "sqlite+libsql://my-db.turso.io?auth_token=sec-token"
    )


def test_engine_pragma_and_session():
    engine = get_engine()
    with Session(engine) as session:
        # Check foreign keys pragma is active on SQLite
        fk_status = session.execute(text("PRAGMA foreign_keys;")).one()
        assert fk_status == (1,)

        # Query services table via SQLModel
        services = session.exec(select(Service)).all()
        assert len(services) > 0


def test_get_session_dependency():
    gen = get_session()
    session = next(gen)
    assert isinstance(session, Session)
    try:
        res = session.execute(text("SELECT 1;")).one()
        assert res == (1,)
    finally:
        try:
            next(gen)
        except StopIteration:
            pass
