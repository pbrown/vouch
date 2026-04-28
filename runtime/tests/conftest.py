"""Test fixtures: real Postgres database, schema via Alembic, per-test rollback.

We use ``vouch_test`` as a dedicated database — separate from ``vouch`` — so a
test run never touches dev data. Schema is created once per session by running
``alembic upgrade head`` against the test URL. Each test runs inside a
transaction with a savepoint, so endpoint commits are visible within the test
but rolled back at teardown.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

TEST_DATABASE_URL = os.environ.get(
    "VOUCH_TEST_DATABASE_URL",
    "postgresql+psycopg2://vouch:vouch_dev@localhost:5432/vouch_test",
)
ADMIN_DATABASE_URL = "postgresql+psycopg2://vouch:vouch_dev@localhost:5432/postgres"
TEST_DB_NAME = TEST_DATABASE_URL.rsplit("/", 1)[-1]


def _ensure_test_database_exists() -> None:
    admin = create_engine(ADMIN_DATABASE_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :name"),
            {"name": TEST_DB_NAME},
        ).scalar()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{TEST_DB_NAME}"'))
    admin.dispose()


def _run_migrations() -> None:
    runtime_dir = Path(__file__).resolve().parent.parent
    cfg = Config(str(runtime_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(runtime_dir / "alembic"))
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session")
def test_engine() -> Iterator[Engine]:
    _ensure_test_database_exists()
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
    _run_migrations()
    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(test_engine: Engine) -> Iterator[Session]:
    """Per-test session bound to a transaction that rolls back on teardown.

    ``join_transaction_mode="create_savepoint"`` makes the session's commits
    into savepoint releases on the outer transaction, so endpoint code that
    calls ``db.commit()`` does not escape test isolation.
    """
    connection = test_engine.connect()
    transaction = connection.begin()
    SessionLocal = sessionmaker(
        bind=connection,
        autoflush=False,
        autocommit=False,
        join_transaction_mode="create_savepoint",
    )
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def client(db_session: Session) -> Iterator[TestClient]:
    from vouch_runtime.app import app
    from vouch_runtime.db import get_db

    def _override_get_db() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_db, None)
