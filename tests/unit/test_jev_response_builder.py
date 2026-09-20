"""Unit tests for the response builder (plan §4 Phase 3, §6).

The golden test uses the exact §2.7 engine capture and must reproduce the
§2.7 response bit-for-bit (fixed expected floats).
"""

import pytest

from classes.jev_errors import SourceEngineError
from classes.jev_response_builder import build_systemone_response
from models.jev_models import SystemOneRequest, SystemOneResponse
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


def make_request(payload=None) -> SystemOneRequest:
    return SystemOneRequest.model_validate(payload or SECTION_27_REQUEST)


def make_engine_payload(**overrides) -> dict:
    """An engine capture consistent with the §2.7 worked example. Enum
    top_choices are sorted by probability, not by declaration order."""
    payload = {
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
    payload.update(overrides)
    return payload


def make_choice_request(criteria, question_id="q") -> SystemOneRequest:
    return make_request(
        {
            **SECTION_27_REQUEST,
            "questions": {
                question_id: {"type": "choice", "instructions": "Pick", "criteria": criteria}
            },
        }
    )


def make_choice_payload(top_choices, value=None, **overrides) -> dict:
    payload = {
        "schema_match": True,
        "parsed_json": {"q": {"value": value or top_choices[0][0]}},
        "field_telemetry": {
            "q": {
                "value": value or top_choices[0][0],
                "type": "enum",
                "confidence": 1.0,
                "cardinality": len(top_choices),
                "top_choices": [
                    {"choice": choice, "probability": prob} for choice, prob in top_choices
                ],
            }
        },
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Golden test: §2.7 engine capture -> §2.7 response, bit-for-bit
# --------------------------------------------------------------------------


def test_golden_section_27_capture_reproduces_response_bit_for_bit():
    response = build_systemone_response(make_request(), make_engine_payload())

    expected = {
        "model": "jev-latest",
        "answers": {
            "is_request": {"type": "noul", "noul": 0.0291},
            "department": {
                "type": "choice",
                "choice": "CAT",
                "probabilities": {"CAT": 0.9993, "BIRD": 0.0006, "DOG": 0.0001},
                "confidence": 0.999,
            },
            "frustration": {
                "type": "score",
                "score": 0.4019,
                "legend": {"0": "Calm", "1": "Frustrated", "2": "Very angry"},
                "probabilities": {"0": 0.7506, "1": 0.0969, "2": 0.1525},
                "confidence": 0.6259,
            },
        },
        "usage": {"input_tokens": 108, "output_tokens": 0},
    }
    assert response == SystemOneResponse.model_validate(expected)

    # probabilities keyed in declaration order (never telemetry order)
    dumped = response.model_dump()
    assert list(dumped["answers"]["department"]["probabilities"]) == ["CAT", "BIRD", "DOG"]
    assert list(dumped["answers"]["frustration"]["probabilities"]) == ["0", "1", "2"]

    # every probabilities map sums to exactly 1
    assert sum(dumped["answers"]["department"]["probabilities"].values()) == 1.0
    assert sum(dumped["answers"]["frustration"]["probabilities"].values()) == 1.0


# --------------------------------------------------------------------------
# noul (§2.4)
# --------------------------------------------------------------------------


def test_noul_rounds_to_four_decimals():
    request = make_request(
        {
            **SECTION_27_REQUEST,
            "questions": {"q": {"type": "noul", "instructions": "yes?"}},
        }
    )
    payload = {
        "schema_match": True,
        "parsed_json": {"q": {"value": False}},
        "field_telemetry": {
            "q": {
                "top_choices": [
                    {"choice": "false", "probability": 0.97091},
                    {"choice": "true", "probability": 0.02909},
                ]
            }
        },
    }
    answer = build_systemone_response(request, payload).answers["q"]
    assert answer.type == "noul"
    assert answer.noul == 0.0291


def test_noul_fallback_to_parsed_value_true():
    request = make_request(
        {**SECTION_27_REQUEST, "questions": {"q": {"type": "noul", "instructions": "yes?"}}}
    )
    payload = {
        "schema_match": True,
        "parsed_json": {"q": {"value": True}},
        "field_telemetry": {"q": {"top_choices": [{"choice": "false", "probability": 1.0}]}},
    }
    assert build_systemone_response(request, payload).answers["q"].noul == 1.0


def test_noul_fallback_to_parsed_value_false():
    request = make_request(
        {**SECTION_27_REQUEST, "questions": {"q": {"type": "noul", "instructions": "yes?"}}}
    )
    payload = {
        "schema_match": True,
        "parsed_json": {"q": {"value": "no"}},
        "field_telemetry": {"q": {"top_choices": [{"choice": "false", "probability": 1.0}]}},
    }
    assert build_systemone_response(request, payload).answers["q"].noul == 0.0


def test_noul_answer_carries_no_confidence():
    response = build_systemone_response(make_request(), make_engine_payload())
    assert "confidence" not in response.answers["is_request"].model_dump()


# --------------------------------------------------------------------------
# choice probabilities / confidence (§2.4)
# --------------------------------------------------------------------------


def test_missing_option_gets_zero_and_map_renormalizes_to_one():
    request = make_choice_request({"CAT": None, "BIRD": None, "DOG": None})
    payload = make_choice_payload([("CAT", 0.6), ("BIRD", 0.3)])  # DOG missing
    answer = build_systemone_response(request, payload).answers["q"]
    # residual 0.1 goes to the argmax option
    assert answer.probabilities == {"CAT": 0.7, "BIRD": 0.3, "DOG": 0.0}
    assert sum(answer.probabilities.values()) == 1.0


def test_rounding_residual_goes_to_argmax_option():
    request = make_choice_request({"A": None, "B": None, "C": None})
    payload = make_choice_payload([("A", 0.33333), ("B", 0.33333), ("C", 0.33333)])
    answer = build_systemone_response(request, payload).answers["q"]
    assert answer.probabilities == {"A": 0.3334, "B": 0.3333, "C": 0.3333}
    assert sum(answer.probabilities.values()) == 1.0


def test_confidence_all_mass_on_one_option_is_one():
    request = make_choice_request({"A": None, "B": None})
    payload = make_choice_payload([("A", 1.0), ("B", 0.0)])
    answer = build_systemone_response(request, payload).answers["q"]
    assert answer.confidence == 1.0


def test_confidence_uniform_spread_is_zero():
    request = make_choice_request({"A": None, "B": None})
    payload = make_choice_payload([("A", 0.5), ("B", 0.5)])
    answer = build_systemone_response(request, payload).answers["q"]
    assert answer.confidence == 0.0


def test_confidence_uses_published_formula_two_options():
    # 2-option score: 2p - 1
    request = make_choice_request({"A": None, "B": None})
    payload = make_choice_payload([("A", 0.75), ("B", 0.25)])
    answer = build_systemone_response(request, payload).answers["q"]
    assert answer.confidence == round(2 * 0.75 - 1, 4)


def test_single_option_choice_confidence_is_one():
    request = make_choice_request({"ONLY": None})
    payload = make_choice_payload([("ONLY", 0.42)])
    answer = build_systemone_response(request, payload).answers["q"]
    assert answer.confidence == 1.0
    assert answer.probabilities == {"ONLY": 1.0}


def test_choice_value_comes_from_telemetry_not_telemetry_order():
    request = make_choice_request({"CAT": None, "BIRD": None, "DOG": None})
    payload = make_choice_payload([("CAT", 0.9993), ("BIRD", 0.0006), ("DOG", 0.0001)])
    answer = build_systemone_response(request, payload).answers["q"]
    assert answer.choice == "CAT"


# --------------------------------------------------------------------------
# score (§2.4)
# --------------------------------------------------------------------------


def test_score_is_expectation_over_level_distribution():
    request = make_request(
        {
            **SECTION_27_REQUEST,
            "questions": {
                "q": {
                    "type": "score",
                    "instructions": "Rate",
                    "criteria": ["Calm", "Frustrated", "Very angry"],
                }
            },
        }
    )
    payload = {
        "schema_match": True,
        "parsed_json": {"q": {"value": "0"}},
        "field_telemetry": {
            "q": {
                "top_choices": [
                    {"choice": "0", "probability": 0.5},
                    {"choice": "2", "probability": 0.5},
                    {"choice": "1", "probability": 0.0},
                ]
            }
        },
    }
    answer = build_systemone_response(request, payload).answers["q"]
    assert answer.probabilities == {"0": 0.5, "1": 0.0, "2": 0.5}
    assert answer.score == 1.0  # 0*0.5 + 1*0.0 + 2*0.5
    assert answer.legend == {"0": "Calm", "1": "Frustrated", "2": "Very angry"}


def test_score_legend_with_ten_levels():
    criteria = [f"L{i}" for i in range(10)]
    request = make_request(
        {**SECTION_27_REQUEST, "questions": {"q": {"type": "score", "instructions": "Rate", "criteria": criteria}}}
    )
    payload = {
        "schema_match": True,
        "parsed_json": {"q": {"value": "9"}},
        "field_telemetry": {
            "q": {"top_choices": [{"choice": str(i), "probability": 0.1} for i in range(10)]}
        },
    }
    answer = build_systemone_response(request, payload).answers["q"]
    assert answer.legend == {str(i): f"L{i}" for i in range(10)}
    assert answer.score == 4.5


# --------------------------------------------------------------------------
# model echo (§2.5) and usage (§2.6)
# --------------------------------------------------------------------------


def test_model_echoes_requested_model_by_default():
    response = build_systemone_response(make_request(), make_engine_payload())
    assert response.model == "jev-latest"


def test_reported_model_id_overrides_echo(monkeypatch):
    monkeypatch.setattr(config, "REPORTED_MODEL_ID", "jev-local-rlcd-1.0.0")
    response = build_systemone_response(make_request(), make_engine_payload())
    assert response.model == "jev-local-rlcd-1.0.0"


def test_usage_estimate_uses_divisor(monkeypatch):
    monkeypatch.setattr(config, "USAGE_TOKEN_DIVISOR", 10.0)
    response = build_systemone_response(make_request(), make_engine_payload())
    # 432 serialized prompt chars -> ceil(432 / 10)
    assert response.usage.input_tokens == 44
    assert response.usage.output_tokens == 0


def test_usage_covers_context_and_all_field_descriptions():
    response = build_systemone_response(make_request(), make_engine_payload())
    # 432 chars (context 135 + 18 + 156 + 123) / 4.0 -> ceil(108) = 108
    assert response.usage.input_tokens == 108


# --------------------------------------------------------------------------
# Failure of the source response itself -> 502 path (§2.4)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "override",
    [
        {"schema_match": False},
        {"parsed_json": None},
        {"field_telemetry": {}},  # question id missing from telemetry
    ],
)
def test_incomplete_engine_payload_raises_source_engine_error(override):
    payload = make_engine_payload(**override)
    with pytest.raises(SourceEngineError):
        build_systemone_response(make_request(), payload)


def test_empty_top_choices_raises():
    request = make_choice_request({"A": None, "B": None})
    payload = make_choice_payload([("A", 1.0), ("B", 0.0)])
    payload["field_telemetry"]["q"]["top_choices"] = []
    with pytest.raises(SourceEngineError):
        build_systemone_response(request, payload)


def test_probabilities_without_mass_raise():
    request = make_choice_request({"A": None, "B": None})
    payload = make_choice_payload([("X", 1.0)])  # no overlap with declared options
    with pytest.raises(SourceEngineError):
        build_systemone_response(request, payload)
