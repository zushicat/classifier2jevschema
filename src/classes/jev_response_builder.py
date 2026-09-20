"""Source-engine /api/run-rlcd response -> SystemOneResponse (plan §2.4–§2.6).

Source data used per field ``<id>``: ``field_telemetry.<id>`` (``.top_choices``
as ``[{choice, probability}, ...]``, ``.value``, ``.confidence``) and
``parsed_json.<id>.value``.

Verified live (plan §2.4): boolean ``top_choices`` uses the string keys
``"false"``/``"true"``; enum ``top_choices`` is the full candidate set **sorted
by probability, not by declaration order** — everything is therefore keyed by
option name, never by position.
"""

import logging
import math
from typing import Any

from classes.jev_errors import SourceEngineError
from classes.jev_translator import build_engine_request, serialize_text
from models.jev_models import (
    ChoiceAnswer,
    ChoiceQuestion,
    NoulAnswer,
    NoulQuestion,
    ScoreAnswer,
    ScoreQuestion,
    SystemOneRequest,
    SystemOneResponse,
    Usage,
)
from settings import config

logger = logging.getLogger(__name__)

_NOUL_TRUE_KEY = "true"


# --------------------------------------------------------------------------
# Telemetry access helpers
# --------------------------------------------------------------------------


def _telemetry_for(engine_payload: dict, question_id: str) -> dict:
    telemetry = engine_payload.get("field_telemetry")
    if not isinstance(telemetry, dict) or question_id not in telemetry:
        raise SourceEngineError(
            f"Source response has no field_telemetry entry for question {question_id!r}"
        )
    entry = telemetry[question_id]
    if not isinstance(entry, dict):
        raise SourceEngineError(
            f"Source field_telemetry entry for {question_id!r} is malformed"
        )
    return entry


def _telemetry_probabilities(telemetry: dict, question_id: str) -> dict[str, float]:
    """top_choices keyed by option name (order-independent, plan §2.4)."""
    top_choices = telemetry.get("top_choices")
    if not isinstance(top_choices, list) or not top_choices:
        raise SourceEngineError(
            f"Source field_telemetry for {question_id!r} has no usable top_choices"
        )
    probabilities: dict[str, float] = {}
    for entry in top_choices:
        if not isinstance(entry, dict) or "choice" not in entry:
            raise SourceEngineError(
                f"Source field_telemetry for {question_id!r} has a malformed top_choices entry"
            )
        probabilities[entry["choice"]] = float(entry.get("probability", 0.0))
    return probabilities


# --------------------------------------------------------------------------
# Probability math (plan §2.4)
# --------------------------------------------------------------------------


def _round4(value: float) -> float:
    return round(value, 4)


def _renormalize(probabilities: dict[str, float], question_id: str) -> dict[str, float]:
    """Round to 4 decimals, then renormalize so the map sums to exactly 1 by
    adding the residual to the argmax option (Jev documents "floats that sum
    to 1"; plan §2.4). Ties on the argmax resolve to the first declared key.
    """
    rounded = {key: _round4(value) for key, value in probabilities.items()}
    total = sum(rounded.values())
    if total <= 0.0:
        raise SourceEngineError(
            f"Source probabilities for {question_id!r} carry no usable mass"
        )
    residual = _round4(1.0 - total)
    if residual != 0.0:
        argmax = max(rounded, key=rounded.get)
        rounded[argmax] = _round4(rounded[argmax] + residual)
    return rounded


def _confidence(probabilities: dict[str, float]) -> float:
    """TypeSafe's published confidence definition (docs.typesafe.ai/confidence,
    plan §2.4): for n options with peak probability p_max,

        confidence = clamp((n x p_max - 1) / (n - 1), 0, 1)        # n >= 2

    All mass on one option -> 1.0; uniform spread -> 0.0. This is computed
    from the (renormalized) distribution, not from the engine's per-field
    confidence (= probability of the chosen answer).
    """
    n = len(probabilities)
    if n < 2:
        return 1.0
    p_max = max(probabilities.values())
    value = (n * p_max - 1) / (n - 1)
    return _round4(min(1.0, max(0.0, value)))


# --------------------------------------------------------------------------
# Per-question answer builders
# --------------------------------------------------------------------------


def _noul_answer(question_id: str, engine_payload: dict) -> NoulAnswer:
    """p = probability of the "true" entry in top_choices (round 4). Fallback
    if the entry is missing: parsed value True -> 1.0 else 0.0. No confidence
    (Jev noul answers carry none)."""
    telemetry = _telemetry_for(engine_payload, question_id)
    probabilities = _telemetry_probabilities(telemetry, question_id)
    p = probabilities.get(_NOUL_TRUE_KEY)
    if p is None:
        parsed = engine_payload.get("parsed_json") or {}
        parsed_value = (parsed.get(question_id) or {}).get("value")
        p = 1.0 if parsed_value is True else 0.0
        logger.warning(
            "Noul question %r has no 'true' entry in top_choices; fell back to "
            "parsed_json value %r -> %s",
            question_id,
            parsed_value,
            p,
        )
    return NoulAnswer(type="noul", noul=_round4(p))


def _choice_answer(question_id: str, question: ChoiceQuestion, engine_payload: dict) -> ChoiceAnswer:
    telemetry = _telemetry_for(engine_payload, question_id)
    probabilities = _telemetry_probabilities(telemetry, question_id)

    value = telemetry.get("value")
    if not isinstance(value, str):
        raise SourceEngineError(
            f"Source field_telemetry for {question_id!r} has no string value"
        )

    # Declared order; options absent from top_choices -> 0.0; rounded +
    # renormalized so the map sums to 1 (plan §2.4).
    distribution = _renormalize(
        {option: probabilities.get(option, 0.0) for option in question.criteria},
        question_id,
    )
    return ChoiceAnswer(
        type="choice",
        choice=value,
        probabilities=distribution,
        confidence=_confidence(distribution),
    )


def _score_answer(question_id: str, question: ScoreQuestion, engine_payload: dict) -> ScoreAnswer:
    telemetry = _telemetry_for(engine_payload, question_id)
    probabilities = _telemetry_probabilities(telemetry, question_id)

    level_count = len(question.criteria)
    distribution = _renormalize(
        {str(i): probabilities.get(str(i), 0.0) for i in range(level_count)},
        question_id,
    )
    # Expectation over the level distribution — may land between levels
    # (Jev semantics, plan §2.4). Computed from the final visible distribution.
    score = _round4(sum(i * distribution[str(i)] for i in range(level_count)))

    # legend verbatim from the request; non-string levels are JSON-stringified
    # so the response stays a string map (Jev legend values are strings).
    legend = {str(i): serialize_text(level) for i, level in enumerate(question.criteria)}

    return ScoreAnswer(
        type="score",
        score=score,
        legend=legend,
        probabilities=distribution,
        confidence=_confidence(distribution),
    )


# --------------------------------------------------------------------------
# Top-level builder
# --------------------------------------------------------------------------


def build_systemone_response(
    request: SystemOneRequest, engine_payload: dict
) -> SystemOneResponse:
    """Assemble the Jev response from one run-rlcd payload.

    Raises SourceEngineError (-> 502) if ``schema_match`` is false,
    ``parsed_json`` is null, or a question id is missing from the telemetry —
    the local stack must never invent answers (plan §2.4).
    """
    if engine_payload.get("schema_match") is not True:
        raise SourceEngineError("Source engine reports schema_match=false")
    parsed_json = engine_payload.get("parsed_json")
    if not isinstance(parsed_json, dict):
        raise SourceEngineError("Source engine response has no parsed_json")

    answers = {}
    for question_id, question in request.questions.items():
        if isinstance(question, NoulQuestion):
            answers[question_id] = _noul_answer(question_id, engine_payload)
        elif isinstance(question, ChoiceQuestion):
            answers[question_id] = _choice_answer(question_id, question, engine_payload)
        elif isinstance(question, ScoreQuestion):
            answers[question_id] = _score_answer(question_id, question, engine_payload)
        else:  # pragma: no cover — the discriminated union prevents this
            raise SourceEngineError(f"Unsupported question type for {question_id!r}")

    # usage.input_tokens: chars/4 estimate over the final context plus all
    # field descriptions actually sent to the engine (plan §2.6). The engine
    # reports no token counts (total_tokens_generated = 0 in RLCD mode), and
    # Jev bills only input tokens.
    engine_request = build_engine_request(request)
    prompt_chars = len(engine_request["context"]) + sum(
        len(field["description"]) for field in engine_request["schema"].values()
    )
    usage = Usage(
        input_tokens=math.ceil(prompt_chars / config.USAGE_TOKEN_DIVISOR),
        output_tokens=0,
    )

    # model echo: REPORTED_MODEL_ID if set, else the model the client sent
    # (plan §2.5).
    model = config.REPORTED_MODEL_ID or request.model
    return SystemOneResponse(model=model, answers=answers, usage=usage)
