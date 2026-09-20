"""Unit tests for the source engine client (plan §6): respx-mocked engine —
200 pass-through / 400 / 5xx / timeout / connect error / unparseable JSON.
"""

import httpx
import pytest

from classes import source_engine_client
from classes.jev_errors import JevValidationError, SourceEngineError, SourceUnavailableError
from classes.source_engine_client import run_rlcd
from settings import config

ENGINE_PAYLOAD = {
    "mode": "parallel_constrained_calibrated",
    "schema_match": True,
    "parsed_json": {"q": {"value": True, "prob": 0.5}},
    "field_telemetry": {
        "q": {"top_choices": [{"choice": "false", "probability": 0.5}]}
    },
}


def route(mock_engine):
    return mock_engine.post("/api/run-rlcd")


# --------------------------------------------------------------------------
# Happy path
# --------------------------------------------------------------------------


async def test_200_payload_passes_through(mock_engine):
    route(mock_engine).mock(return_value=httpx.Response(200, json=ENGINE_PAYLOAD))

    result = await run_rlcd({"context": "hi", "schema": {}})

    assert result == ENGINE_PAYLOAD
    assert route(mock_engine).called
    request = route(mock_engine).calls.last.request
    assert request.read() == b'{"context":"hi","schema":{}}'


# --------------------------------------------------------------------------
# Error mapping (plan §2.8)
# --------------------------------------------------------------------------


async def test_engine_400_maps_to_jev_validation_error(mock_engine):
    route(mock_engine).mock(
        return_value=httpx.Response(400, json={"detail": "choices on boolean field"})
    )
    with pytest.raises(JevValidationError, match="choices on boolean field"):
        await run_rlcd({"context": "hi", "schema": {}})


async def test_engine_400_non_json_body_maps_to_jev_validation_error(mock_engine):
    route(mock_engine).mock(return_value=httpx.Response(400, text="plain rejection"))
    with pytest.raises(JevValidationError, match="plain rejection"):
        await run_rlcd({"context": "hi", "schema": {}})


async def test_engine_5xx_maps_to_source_engine_error(mock_engine):
    route(mock_engine).mock(
        return_value=httpx.Response(502, json={"detail": "bad gateway"})
    )
    with pytest.raises(SourceEngineError, match="HTTP 502"):
        await run_rlcd({"context": "hi", "schema": {}})


async def test_engine_404_maps_to_source_engine_error(mock_engine):
    route(mock_engine).mock(return_value=httpx.Response(404, json={"detail": "Not Found"}))
    with pytest.raises(SourceEngineError, match="HTTP 404"):
        await run_rlcd({"context": "hi", "schema": {}})


async def test_timeout_maps_to_source_unavailable(mock_engine):
    route(mock_engine).side_effect = httpx.TimeoutException("timed out")
    with pytest.raises(SourceUnavailableError, match="timed out"):
        await run_rlcd({"context": "hi", "schema": {}})


async def test_connect_error_maps_to_source_unavailable(mock_engine):
    route(mock_engine).side_effect = httpx.ConnectError("connection refused")
    with pytest.raises(SourceUnavailableError, match="unreachable"):
        await run_rlcd({"context": "hi", "schema": {}})


async def test_unparseable_json_200_maps_to_source_engine_error(mock_engine):
    route(mock_engine).mock(return_value=httpx.Response(200, text="<html>not json</html>"))
    with pytest.raises(SourceEngineError, match="unparseable JSON"):
        await run_rlcd({"context": "hi", "schema": {}})


# --------------------------------------------------------------------------
# Client lifecycle
# --------------------------------------------------------------------------


async def test_settings_change_creates_fresh_client(monkeypatch, mock_engine):
    route(mock_engine).mock(return_value=httpx.Response(200, json=ENGINE_PAYLOAD))
    await run_rlcd({"context": "hi", "schema": {}})
    first_client = source_engine_client.get_client()

    monkeypatch.setattr(config, "SOURCE_API_TIMEOUT_SECONDS", 5.0)
    await run_rlcd({"context": "hi", "schema": {}})
    second_client = source_engine_client.get_client()

    assert first_client is not second_client


async def test_aclose_client_drops_singleton(mock_engine):
    route(mock_engine).mock(return_value=httpx.Response(200, json=ENGINE_PAYLOAD))
    await run_rlcd({"context": "hi", "schema": {}})
    client = source_engine_client.get_client()
    await source_engine_client.aclose_client()

    assert client.is_closed
    assert source_engine_client._client is None
