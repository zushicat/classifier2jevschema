"""SystemOneRequest -> source-engine /api/run-rlcd body translation
(plan §2.2–§2.3).

Every /v1/systemone call maps to exactly one run-rlcd call: ``state`` becomes
``context`` and each question becomes one schema field (noul -> boolean,
choice -> enum over option keys, score -> enum over level indices "0".."N-1").
"""

import json
import logging
from typing import Any

from classes.jev_errors import JevValidationError
from models.jev_models import (
    ChoiceQuestion,
    NoulQuestion,
    ScoreQuestion,
    SystemOneRequest,
)

logger = logging.getLogger(__name__)

#: Options longer than this — or containing whitespace — may classify poorly,
#: because the engine matches answers against single vocabulary tokens
#: (plan §2.3b). Passed through verbatim; warned about, never rewritten.
MAX_RECOMMENDED_OPTION_LENGTH = 24

_NO_ADDITIONAL_DESCRIPTION = "(no additional description)"


def serialize_text(value: Any) -> str:
    """``str`` verbatim; everything else JSON-encoded (plan §2.2/§2.9.3)."""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, indent=2)


def _contains_whitespace(text: str) -> bool:
    return any(char.isspace() for char in text)


def _noul_description(question: NoulQuestion) -> str:
    """{instructions}, plus — when ``criteria`` is present — the YES/NO rubric
    lines (each skipped if absent/null, plan §2.3a)."""
    description = serialize_text(question.instructions)
    if question.criteria is not None:
        lines = []
        if question.criteria.true is not None:
            lines.append(f"YES means: {serialize_text(question.criteria.true)}")
        if question.criteria.false is not None:
            lines.append(f"NO means: {serialize_text(question.criteria.false)}")
        if lines:
            description += "\n\n" + "\n".join(lines)
    return description


def _choice_description(question: ChoiceQuestion) -> str:
    """{instructions} + option lines ``- {option}: {rubric}`` (plan §2.3b)."""
    lines = []
    for option, rubric in question.criteria.items():
        if _contains_whitespace(option) or len(option) > MAX_RECOMMENDED_OPTION_LENGTH:
            logger.warning(
                "Choice option %r contains whitespace or is longer than %d chars; "
                "the engine matches answers against single vocabulary tokens, so it "
                "may classify poorly (passed through verbatim).",
                option,
                MAX_RECOMMENDED_OPTION_LENGTH,
            )
        rubric_text = rubric if rubric is not None else _NO_ADDITIONAL_DESCRIPTION
        lines.append(f"- {option}: {rubric_text}")
    return serialize_text(question.instructions) + "\n\nOptions:\n" + "\n".join(lines)


def _score_description(question: ScoreQuestion) -> str:
    """{instructions} + the ordinal level legend (plan §2.3c). The explicit
    "0 is the lowest" sentence anchors the ordinal direction."""
    level_count = len(question.criteria)
    header = f"Rating levels (0 is the lowest rating, {level_count - 1} the highest):"
    lines = [f"{i}: {serialize_text(level)}" for i, level in enumerate(question.criteria)]
    return serialize_text(question.instructions) + "\n\n" + header + "\n" + "\n".join(lines)


def build_engine_request(request: SystemOneRequest) -> dict:
    """Build the run-rlcd body: one source field per Jev question, in
    question order. Answer keys = question ids = schema field names."""
    schema: dict[str, dict[str, Any]] = {}
    for question_id, question in request.questions.items():
        if isinstance(question, NoulQuestion):
            schema[question_id] = {
                "type": "boolean",
                "description": _noul_description(question),
                # no "choices" — the engine rejects choices on booleans
            }
        elif isinstance(question, ChoiceQuestion):
            schema[question_id] = {
                "type": "enum",
                "description": _choice_description(question),
                "choices": list(question.criteria.keys()),
            }
        elif isinstance(question, ScoreQuestion):
            schema[question_id] = {
                "type": "enum",
                "description": _score_description(question),
                "choices": [str(i) for i in range(len(question.criteria))],
            }
        else:  # pragma: no cover — the discriminated union prevents this
            raise JevValidationError(f"Unsupported question type for {question_id!r}")
    return {"context": serialize_text(request.state), "schema": schema}
