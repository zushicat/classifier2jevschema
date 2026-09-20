"""End-to-end route tests through the app with a mocked engine (plan §6).

Covers: full happy-path shape, 422 validation bodies, auth (401/403), 502
paths, GET /v1/models, and legacy /simple/* 404.
"""

import httpx
import pytest

from settings import config

SECTION_27_REQUEST = {
    "state": "My cat has food allergies. Does your pet food contain any allergens? "
    "The customer is quite frustrated about repeated failed deliveries.",
    "model": "jev-latest",
    "questions": {
        "is_request": {"type": "noul", "instructions": "Is this a request?"},
        "department": {
            "type": "choice",
            "instructions": "What kind of pet does the customer have?",
            "criteria": {"CAT": None, "BIRD": None, "DOG": None},
        },
        "frustration": {
            "type": "score",
            "instructions": "How frustrated is the customer?",
            "criteria": ["Calm", "Frustrated", "Very angry"],
        },
    },
}

ENGINE_PAYLOAD = {
    "mode": "parallel_constrained_calibrated",
    "elapsed_ms": 181.14,
    "total_tokens_generated": 0,
    "is_valid_json": True,
    "schema_match": True,
    "parsed_json": {
        "is_request": {"value": False, "prob": 0.9709},
        "department": {"value": "CAT", "prob": 0.9993},
        "frustration": {"value": "0", "prob": 0.7506},
    },
    "field_telemetry": {
        "is_request": {
            "value": False,
            "type": "boolean",
            "confidence": 0.9709,
            "cardinality": 2,
            "top_choices": [
                {"choice": "false", "probability": 0.9709},
                {"choice": "true", "probability": 0.0291},
            ],
        },
        "department": {
            "value": "CAT",
            "type": "enum",
            "confidence": 0.9993,
            "cardinality": 3,
            "top_choices": [
                {"choice": "CAT", "probability": 0.9993},
                {"choice": "BIRD", "probability": 0.0006},
                {"choice": "DOG", "probability": 0.0001},
            ],
        },
        "frustration": {
            "value": "0",
            "type": "enum",
            "confidence": 0.7506,
            "cardinality": 3,
            "top_choices": [
                {"choice": "0", "probability": 0.7506},
                {"choice": "2", "probability": 0.1525},
                {"choice": "1", "probability": 0.0969},
            ],
        },
    },
    "has_calibrated_probabilities": True,
    "num_fields": 3,
}


@pytest.fixture
def ok_engine(engine_route):
    engine_route.mock(return_value=httpx.Response(200, json=ENGINE_PAYLOAD))
    return engine_route


# --------------------------------------------------------------------------
# Happy path
# --------------------------------------------------------------------------


async def test_full_three_type_request_returns_jev_response_shape(client, ok_engine):
    response = await client.post("/v1/systemone", json=SECTION_27_REQUEST)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()

    assert set(body) == {"model", "answers", "usage"}
    assert body["model"] == "jev-latest"

    answers = body["answers"]
    assert set(answers) == {"is_request", "department", "frustration"}

    assert answers["is_request"] == {"type": "noul", "noul": 0.0291}

    department = answers["department"]
    assert department["type"] == "choice"
    assert department["choice"] == "CAT"
    assert department["probabilities"] == {"CAT": 0.9993, "BIRD": 0.0006, "DOG": 0.0001}
    assert department["confidence"] == 0.999

    frustration = answers["frustration"]
    assert frustration["type"] == "score"
    assert frustration["score"] == 0.4019
    assert frustration["legend"] == {"0": "Calm", "1": "Frustrated", "2": "Very angry"}
    assert frustration["probabilities"] == {"0": 0.7506, "1": 0.0969, "2": 0.1525}
    assert frustration["confidence"] == 0.6259

    assert body["usage"] == {"input_tokens": 108, "output_tokens": 0}


async def test_extra_request_fields_are_ignored(client, ok_engine):
    payload = {**SECTION_27_REQUEST, "metadata": {"request_id": "sdk-abc"}}
    response = await client.post("/v1/systemone", json=payload)
    assert response.status_code == 200


async def test_reported_model_id_env_is_respected(client, ok_engine, monkeypatch):
    monkeypatch.setattr(config, "REPORTED_MODEL_ID", "jev-local-rlcd-1.0.0")
    response = await client.post("/v1/systemone", json=SECTION_27_REQUEST)
    assert response.json()["model"] == "jev-local-rlcd-1.0.0"


async def test_exactly_one_engine_call_per_systemone_call(client, ok_engine):
    await client.post("/v1/systemone", json=SECTION_27_REQUEST)
    assert ok_engine.call_count == 1


async def test_engine_receives_translated_context_and_schema(client, ok_engine):
    await client.post("/v1/systemone", json=SECTION_27_REQUEST)
    import json as jsonlib

    engine_body = jsonlib.loads(ok_engine.calls.last.request.read())
    assert engine_body["context"] == SECTION_27_REQUEST["state"]
    assert set(engine_body["schema"]) == {"is_request", "department", "frustration"}
    assert engine_body["schema"]["is_request"]["type"] == "boolean"
    assert engine_body["schema"]["department"]["choices"] == ["CAT", "BIRD", "DOG"]
    assert engine_body["schema"]["frustration"]["choices"] == ["0", "1", "2"]
    assert "temperature" not in engine_body


# --------------------------------------------------------------------------
# 422 — request validation (default FastAPI body) and engine 400
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        {**SECTION_27_REQUEST, "state": 7},  # scalar state
        {k: v for k, v in SECTION_27_REQUEST.items() if k != "state"},  # missing state
        {**SECTION_27_REQUEST, "model": ""},  # empty model
        {**SECTION_27_REQUEST, "questions": {}},  # empty questions map
        {
            **SECTION_27_REQUEST,
            "questions": {"q": {"type": "score", "instructions": "rate", "criteria": ["only"]}},
        },  # score with 1 level
        {
            **SECTION_27_REQUEST,
            "questions": {"q": {"type": "unknown", "instructions": "?"}},
        },  # unknown type
    ],
)
async def test_validation_failures_return_default_422_body(client, payload):
    response = await client.post("/v1/systemone", json=payload)
    assert response.status_code == 422
    body = response.json()
    assert "detail" in body
    assert isinstance(body["detail"], list)  # FastAPI's default validation body


async def test_engine_400_maps_to_422_with_engine_detail(client, engine_route):
    engine_route.mock(
        return_value=httpx.Response(400, json={"detail": "boolean field must not have choices"})
    )
    response = await client.post("/v1/systemone", json=SECTION_27_REQUEST)
    assert response.status_code == 422
    assert response.json() == {"detail": "boolean field must not have choices"}


async def test_not_allowed_model_returns_422(client, engine_route, monkeypatch):
    monkeypatch.setattr(config, "ALLOWED_MODELS", "jev-latest, jev-preview")
    payload = {**SECTION_27_REQUEST, "model": "gpt-4o"}
    response = await client.post("/v1/systemone", json=payload)
    assert response.status_code == 422
    assert "not allowed" in response.json()["detail"]


async def test_allowed_model_accepted_when_allowlist_set(client, ok_engine, monkeypatch):
    monkeypatch.setattr(config, "ALLOWED_MODELS", "jev-latest, jev-preview")
    response = await client.post("/v1/systemone", json=SECTION_27_REQUEST)
    assert response.status_code == 200


async def test_any_model_accepted_without_allowlist(client, ok_engine):
    payload = {**SECTION_27_REQUEST, "model": "anything-goes"}
    response = await client.post("/v1/systemone", json=payload)
    assert response.status_code == 200
    assert response.json()["model"] == "anything-goes"


# --------------------------------------------------------------------------
# 502 — engine unreachable / bad engine response
# --------------------------------------------------------------------------


async def test_engine_unreachable_returns_502(client, engine_route):
    engine_route.side_effect = httpx.ConnectError("connection refused")
    response = await client.post("/v1/systemone", json=SECTION_27_REQUEST)
    assert response.status_code == 502
    assert "unreachable" in response.json()["detail"]


async def test_engine_timeout_returns_502(client, engine_route):
    engine_route.side_effect = httpx.TimeoutException("timed out")
    response = await client.post("/v1/systemone", json=SECTION_27_REQUEST)
    assert response.status_code == 502
    assert "detail" in response.json()


async def test_engine_5xx_returns_502(client, engine_route):
    engine_route.mock(return_value=httpx.Response(500, json={"detail": "boom"}))
    response = await client.post("/v1/systemone", json=SECTION_27_REQUEST)
    assert response.status_code == 502
    assert "boom" in response.json()["detail"]


async def test_engine_schema_match_false_returns_502(client, engine_route):
    payload = {**ENGINE_PAYLOAD, "schema_match": False}
    engine_route.mock(return_value=httpx.Response(200, json=payload))
    response = await client.post("/v1/systemone", json=SECTION_27_REQUEST)
    assert response.status_code == 502
    assert "schema_match" in response.json()["detail"]


# --------------------------------------------------------------------------
# Auth (§2.8): 401 missing / 401 bad scheme / 403 wrong token
# --------------------------------------------------------------------------


@pytest.fixture
def auth_enabled(monkeypatch):
    monkeypatch.setattr(config, "USE_API_KEY", True)
    monkeypatch.setattr(config, "API_KEY", "sk-1234")


async def test_missing_authorization_header_returns_401(client, ok_engine, auth_enabled):
    response = await client.post("/v1/systemone", json=SECTION_27_REQUEST)
    assert response.status_code == 401
    assert response.json() == {"detail": "Missing Authorization header"}


async def test_invalid_scheme_returns_401(client, ok_engine, auth_enabled):
    response = await client.post(
        "/v1/systemone",
        json=SECTION_27_REQUEST,
        headers={"Authorization": "Basic sk-1234"},
    )
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid authorization scheme"}


async def test_wrong_token_returns_403(client, ok_engine, auth_enabled):
    response = await client.post(
        "/v1/systemone",
        json=SECTION_27_REQUEST,
        headers={"Authorization": "Bearer sk-wrong"},
    )
    assert response.status_code == 403
    assert response.json() == {"detail": "Invalid token"}


async def test_correct_token_returns_200(client, ok_engine, auth_enabled):
    response = await client.post(
        "/v1/systemone",
        json=SECTION_27_REQUEST,
        headers={"Authorization": "Bearer sk-1234"},
    )
    assert response.status_code == 200


async def test_health_endpoint_stays_unauthenticated(client, auth_enabled):
    response = await client.get("/")
    assert response.status_code == 200


# --------------------------------------------------------------------------
# GET /v1/models and unknown paths
# --------------------------------------------------------------------------


async def test_get_models_returns_static_catalog(client):
    response = await client.get("/v1/models")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"models"}
    names = [model["name"] for model in body["models"]]
    assert names == ["jev-latest", "jev-preview"]
    for model in body["models"]:
        assert set(model) == {"name", "description", "release_date"}


async def test_legacy_simple_paths_return_default_404(client):
    response = await client.get("/simple/get-request")
    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


async def test_unknown_path_returns_default_404(client):
    response = await client.post("/nonexistent", json={})
    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}
