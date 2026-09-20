"""Integration tests against the live source engine through the app
(plan §4 Phase 5, §6).

Run explicitly:  pytest -q -m integration
They skip cleanly when ``SOURCE_API_BASE_URL`` is unreachable.
"""

import httpx
import pytest

from settings import config

pytestmark = pytest.mark.integration

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


@pytest.fixture
def live_engine():
    """Probe the engine once per test; skip cleanly when unreachable."""
    try:
        response = httpx.get(f"{config.SOURCE_API_BASE_URL}/api/presets", timeout=5.0)
        response.raise_for_status()
    except httpx.HTTPError:
        pytest.skip(f"source engine at {config.SOURCE_API_BASE_URL} is unreachable")
    return True


async def test_live_mixed_three_type_request(client, live_engine):
    """A schema_match=true engine result surfaces as a plain HTTP 200 — the
    builder maps any schema_match=false / missing data to 502 instead."""
    response = await client.post("/v1/systemone", json=SECTION_27_REQUEST)

    assert response.status_code == 200
    body = response.json()

    assert set(body) == {"model", "answers", "usage"}
    assert body["model"] == "jev-latest"

    answers = body["answers"]
    assert set(answers) == {"is_request", "department", "frustration"}

    noul = answers["is_request"]
    assert noul["type"] == "noul"
    assert 0.0 <= noul["noul"] <= 1.0
    assert "confidence" not in noul  # Jev noul answers carry none

    choice = answers["department"]
    assert choice["type"] == "choice"
    assert choice["choice"] in {"CAT", "BIRD", "DOG"}
    assert set(choice["probabilities"]) == {"CAT", "BIRD", "DOG"}
    assert sum(choice["probabilities"].values()) == pytest.approx(1.0, abs=1e-9)
    assert 0.0 <= choice["confidence"] <= 1.0

    score = answers["frustration"]
    assert score["type"] == "score"
    assert score["legend"] == {"0": "Calm", "1": "Frustrated", "2": "Very angry"}
    assert set(score["probabilities"]) == {"0", "1", "2"}
    assert sum(score["probabilities"].values()) == pytest.approx(1.0, abs=1e-9)
    assert 0.0 <= score["score"] <= 2.0
    assert 0.0 <= score["confidence"] <= 1.0

    usage = body["usage"]
    assert usage["input_tokens"] > 0
    assert usage["output_tokens"] == 0


async def test_live_255_option_choice_stress(client, live_engine):
    criteria = {f"opt{i}": None for i in range(255)}
    request = {
        "state": "Pick the option that best matches the message.",
        "model": "jev-latest",
        "questions": {
            "q": {"type": "choice", "instructions": "Which option matches?", "criteria": criteria}
        },
    }
    response = await client.post("/v1/systemone", json=request)

    assert response.status_code == 200
    answer = response.json()["answers"]["q"]
    assert answer["type"] == "choice"
    assert len(answer["probabilities"]) == 255
    assert set(answer["probabilities"]) == set(criteria)  # keys verbatim
    assert sum(answer["probabilities"].values()) == pytest.approx(1.0, abs=1e-9)
    assert answer["choice"] in criteria
    assert 0.0 <= answer["confidence"] <= 1.0


async def test_live_10_level_score_stress(client, live_engine):
    criteria = [f"Level {i}: magnitude {i} of 9" for i in range(10)]
    request = {
        "state": "Rate the intensity of the customer's frustration.",
        "model": "jev-latest",
        "questions": {
            "q": {"type": "score", "instructions": "How intense?", "criteria": criteria}
        },
    }
    response = await client.post("/v1/systemone", json=request)

    assert response.status_code == 200
    answer = response.json()["answers"]["q"]
    assert answer["type"] == "score"
    assert answer["legend"] == {str(i): f"Level {i}: magnitude {i} of 9" for i in range(10)}
    assert set(answer["probabilities"]) == {str(i) for i in range(10)}
    assert sum(answer["probabilities"].values()) == pytest.approx(1.0, abs=1e-9)
    assert 0.0 <= answer["score"] <= 9.0
    assert 0.0 <= answer["confidence"] <= 1.0
