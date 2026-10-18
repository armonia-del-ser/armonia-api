from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Ensure test DB is used
TEST_DB = "test_armonia.db"
os.environ["DATABASE_URL"] = f"file:{TEST_DB}"

from app.core.config import settings

settings.database_url = f"file:{TEST_DB}"

import asyncio

from app.db.init_db import init_schema_and_seed
from app.main import app


@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    # Remove existing test DB if any
    if Path(TEST_DB).exists():
        Path(TEST_DB).unlink()

    asyncio.run(init_schema_and_seed())
    yield

    if Path(TEST_DB).exists():
        Path(TEST_DB).unlink()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c
