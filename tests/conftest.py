"""Shared pytest fixtures (plan §6).

- ``client``: ASGI in-process client for the FastAPI app (no live server).
- ``mock_engine``: respx interception of the source engine with the settings
  base URL monkeypatched to a fake host.

The engine client is a module-level singleton; drop it around every test so
monkeypatched settings (base URL, timeout) always take effect.
"""

import pytest
import respx
from httpx import ASGITransport, AsyncClient

from app import app
from classes import source_engine_client
from settings import config

FAKE_ENGINE_BASE_URL = "http://engine.test"


@pytest.fixture(autouse=True)
def _reset_engine_client():
    source_engine_client.reset_client()
    yield
    source_engine_client.reset_client()


@pytest.fixture
async def client():
    # timeout=None: integration tests wait on the real engine, which
    # serializes requests behind a GPU lock and can be slow.
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", timeout=None) as async_client:
        yield async_client


@pytest.fixture
def mock_engine(monkeypatch):
    monkeypatch.setattr(config, "SOURCE_API_BASE_URL", FAKE_ENGINE_BASE_URL)
    # assert_all_called=False: several route tests intentionally reject a
    # request before the engine is ever called.
    with respx.mock(base_url=FAKE_ENGINE_BASE_URL, assert_all_called=False) as mock:
        yield mock


@pytest.fixture
def engine_route(mock_engine):
    return mock_engine.post("/api/run-rlcd")
