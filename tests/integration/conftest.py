from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import Base, SessionLocal, engine
from app.main import app


@pytest.fixture(scope="session", autouse=True)
def schema():
    if "test" not in settings.database_url:
        pytest.exit("Refusing to wipe a database whose URL does not contain 'test'.")
    if not settings.demo_mode:
        pytest.exit("Integration tests need DEMO_MODE=true.")
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture(autouse=True)
def empty_tables():
    yield
    with engine.begin() as connection:
        for table in reversed(Base.metadata.sorted_tables):
            connection.execute(table.delete())


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session


@pytest.fixture(autouse=True)
def outbox(monkeypatch):
    sent = []

    def record_message(channel, destination, message, subject="Ngao"):
        sent.append(SimpleNamespace(channel=channel, to=destination, message=message, subject=subject))

    monkeypatch.setattr("app.notify.deliver", record_message)
    return sent
