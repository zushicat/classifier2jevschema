"""Unit tests for the request translator (plan §4 Phase 3, §6).

Translator tests assert exact description strings and choices arrays.
"""

import json
import logging

import pytest

from classes.jev_translator import build_engine_request, serialize_text
from models.jev_models import SystemOneRequest

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


# --------------------------------------------------------------------------
# serialize_text
# --------------------------------------------------------------------------


def test_serialize_text_string_verbatim():
    assert serialize_text("hello") == "hello"


def test_serialize_text_dict_exact():
    assert serialize_text({"a": 1, "b": ["x", "y"]}) == json.dumps(
        {"a": 1, "b": ["x", "y"]}, ensure_ascii=False, indent=2
    )


def test_serialize_text_preserves_non_ascii():
    assert "mähh" in serialize_text({"sound": "mähh"})
    assert "\\u" not in serialize_text({"sound": "mähh"})


# --------------------------------------------------------------------------
# §2.7 golden translation
# --------------------------------------------------------------------------


def test_section_27_translates_to_expected_engine_body():
    body = build_engine_request(make_request())

    assert list(body) == ["context", "schema"]
    assert body["context"] == SECTION_27_REQUEST["state"]
    assert list(body["schema"]) == ["is_request", "department", "frustration"]

    # noul -> plain boolean, no "choices" (the engine rejects choices on booleans)
    assert body["schema"]["is_request"] == {
        "type": "boolean",
        "description": "Is this a request?",
    }

    # choice -> enum over option keys, insertion order, null-rubric lines
    assert body["schema"]["department"] == {
        "type": "enum",
        "description": (
            "What kind of pet does the customer have?\n"
            "\n"
            "Options:\n"
            "- CAT: (no additional description)\n"
            "- BIRD: (no additional description)\n"
            "- DOG: (no additional description)"
        ),
        "choices": ["CAT", "BIRD", "DOG"],
    }

    # score -> enum over level indices with the ordinal-anchor wording
    assert body["schema"]["frustration"] == {
        "type": "enum",
        "description": (
            "How frustrated is the customer?\n"
            "\n"
            "Rating levels (0 is the lowest rating, 2 the highest):\n"
            "0: Calm\n"
            "1: Frustrated\n"
            "2: Very angry"
        ),
        "choices": ["0", "1", "2"],
    }


# --------------------------------------------------------------------------
# noul descriptions (§2.3a)
# --------------------------------------------------------------------------


def test_noul_with_both_criteria_parts():
    payload = {
        **SECTION_27_REQUEST,
        "questions": {
            "q": {
                "type": "noul",
                "instructions": "Is this urgent?",
                "criteria": {"true": "It is urgent", "false": "It can wait"},
            }
        },
    }
    body = build_engine_request(make_request(payload))
    assert body["schema"]["q"]["description"] == (
        "Is this urgent?\n\nYES means: It is urgent\nNO means: It can wait"
    )


def test_noul_with_only_true_part_skips_false_line():
    payload = {
        **SECTION_27_REQUEST,
        "questions": {
            "q": {
                "type": "noul",
                "instructions": "Is this urgent?",
                "criteria": {"true": "It is urgent"},
            }
        },
    }
    body = build_engine_request(make_request(payload))
    assert body["schema"]["q"]["description"] == "Is this urgent?\n\nYES means: It is urgent"


def test_noul_criteria_present_but_empty_adds_nothing():
    payload = {
        **SECTION_27_REQUEST,
        "questions": {
            "q": {"type": "noul", "instructions": "Is this urgent?", "criteria": {}}
        },
    }
    body = build_engine_request(make_request(payload))
    assert body["schema"]["q"]["description"] == "Is this urgent?"


def test_noul_criteria_parts_can_be_structured():
    payload = {
        **SECTION_27_REQUEST,
        "questions": {
            "q": {
                "type": "noul",
                "instructions": "Is this urgent?",
                "criteria": {"true": {"urgency": "high"}},
            }
        },
    }
    body = build_engine_request(make_request(payload))
    assert body["schema"]["q"]["description"] == (
        "Is this urgent?\n\nYES means: "
        + json.dumps({"urgency": "high"}, ensure_ascii=False, indent=2)
    )


# --------------------------------------------------------------------------
# choice descriptions (§2.3b)
# --------------------------------------------------------------------------


def test_choice_with_rubrics():
    payload = {
        **SECTION_27_REQUEST,
        "questions": {
            "q": {
                "type": "choice",
                "instructions": "Pick a size",
                "criteria": {"S": "small", "L": None},
            }
        },
    }
    body = build_engine_request(make_request(payload))
    assert body["schema"]["q"]["description"] == (
        "Pick a size\n\nOptions:\n- S: small\n- L: (no additional description)"
    )
    assert body["schema"]["q"]["choices"] == ["S", "L"]


def test_choice_option_insertion_order_preserved():
    payload = {
        **SECTION_27_REQUEST,
        "questions": {
            "q": {
                "type": "choice",
                "instructions": "Pick",
                "criteria": {"ZEBRA": None, "AARDVARK": None, "MIDGE": None},
            }
        },
    }
    body = build_engine_request(make_request(payload))
    assert body["schema"]["q"]["choices"] == ["ZEBRA", "AARDVARK", "MIDGE"]


def test_choice_option_with_whitespace_and_long_option_warns(caplog):
    payload = {
        **SECTION_27_REQUEST,
        "questions": {
            "q": {
                "type": "choice",
                "instructions": "Pick",
                "criteria": {"CAT": None, "red tabby cat": None, "x" * 30: None},
            }
        },
    }
    with caplog.at_level(logging.WARNING, logger="classes.jev_translator"):
        body = build_engine_request(make_request(payload))

    # passed through verbatim
    assert body["schema"]["q"]["choices"] == ["CAT", "red tabby cat", "x" * 30]
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 2  # whitespace option + long option


def test_choice_short_clean_options_do_not_warn(caplog):
    payload = {
        **SECTION_27_REQUEST,
        "questions": {
            "q": {"type": "choice", "instructions": "Pick", "criteria": {"CAT": None}}
        },
    }
    with caplog.at_level(logging.WARNING, logger="classes.jev_translator"):
        build_engine_request(make_request(payload))
    assert caplog.records == []


# --------------------------------------------------------------------------
# score descriptions (§2.3c)
# --------------------------------------------------------------------------


def test_score_levels_can_be_structured():
    payload = {
        **SECTION_27_REQUEST,
        "questions": {
            "q": {
                "type": "score",
                "instructions": "Rate it",
                "criteria": ["low", {"detail": "mid level"}],
            }
        },
    }
    body = build_engine_request(make_request(payload))
    assert body["schema"]["q"]["description"] == (
        "Rate it\n\nRating levels (0 is the lowest rating, 1 the highest):\n"
        "0: low\n1: " + json.dumps({"detail": "mid level"}, ensure_ascii=False, indent=2)
    )
    assert body["schema"]["q"]["choices"] == ["0", "1"]


def test_score_single_digit_choices_are_single_tokens():
    payload = {
        **SECTION_27_REQUEST,
        "questions": {
            "q": {
                "type": "score",
                "instructions": "Rate it",
                "criteria": [str(i) for i in range(10)],
            }
        },
    }
    body = build_engine_request(make_request(payload))
    assert body["schema"]["q"]["choices"] == ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9"]


# --------------------------------------------------------------------------
# state serialization (§2.2)
# --------------------------------------------------------------------------


def test_state_dict_is_json_serialized_into_context():
    payload = {**SECTION_27_REQUEST, "state": {"customer": "frustrated", "lang": "en"}}
    body = build_engine_request(make_request(payload))
    assert body["context"] == json.dumps(
        {"customer": "frustrated", "lang": "en"}, ensure_ascii=False, indent=2
    )


def test_state_list_is_json_serialized_into_context():
    payload = {**SECTION_27_REQUEST, "state": ["line one", "line two"]}
    body = build_engine_request(make_request(payload))
    assert body["context"] == json.dumps(["line one", "line two"], ensure_ascii=False, indent=2)


def test_no_temperature_key_ever_sent():
    body = build_engine_request(make_request())
    assert "temperature" not in body
