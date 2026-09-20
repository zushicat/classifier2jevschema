"""Pydantic v2 models for the Jev (/v1/systemone) contract.

Request side mirrors the Jev API request shape (state + model + questions with
noul / choice / score question types); response side is used as the route
``response_model`` so the generated OpenAPI mirrors the Jev docs.

Validation failures here surface as FastAPI's default 422 — which matches Jev
("422: The body details the offending field"), per plan §2.8.
"""

import json
from typing import Annotated, Any, Dict, List, Literal, Union

from pydantic import BaseModel, Field, field_validator, model_validator

#: Text-ish values accepted for ``state``, ``instructions`` and noul criteria
#: parts: ``str`` is used verbatim, ``dict``/``list`` are JSON-stringified
#: downstream (plan §2.2). Anything else (scalar number/bool/None) fails
#: validation -> 422.
SerializableText = Union[str, Dict[str, Any], List[Any]]

#: Jev limits, identical to the source engine's 255-choice limit (plan §2.3b).
CHOICE_MIN_OPTIONS = 1
CHOICE_MAX_OPTIONS = 255

#: Jev limits for Score levels (plan §2.3c).
SCORE_MIN_LEVELS = 2
SCORE_MAX_LEVELS = 10


def _stringify(value: Any) -> str:
    """Stringify a SerializableText value (validation-local mirror of the
    translator's ``serialize_text`` rules: str verbatim, else JSON)."""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, indent=2)


def _check_instructions_non_empty(value: Any) -> Any:
    if not _stringify(value).strip():
        raise ValueError("instructions must not be empty after stringification")
    return value


class _InstructionsMixin(BaseModel):
    """Shared ``instructions`` handling for all question types."""

    instructions: SerializableText

    @field_validator("instructions")
    @classmethod
    def _instructions_not_empty(cls, v):
        return _check_instructions_non_empty(v)


class NoulCriteria(BaseModel):
    """Optional yes/no rubric; each part is optional and may be absent/null."""

    true: SerializableText | None = None
    false: SerializableText | None = None


class NoulQuestion(_InstructionsMixin):
    type: Literal["noul"]
    criteria: NoulCriteria | None = None


class ChoiceQuestion(_InstructionsMixin):
    type: Literal["choice"]
    criteria: Dict[str, str | None]

    @field_validator("criteria")
    @classmethod
    def _criteria_size(cls, v):
        if not CHOICE_MIN_OPTIONS <= len(v) <= CHOICE_MAX_OPTIONS:
            raise ValueError(
                f"choice criteria must contain between {CHOICE_MIN_OPTIONS} and "
                f"{CHOICE_MAX_OPTIONS} options"
            )
        return v


class ScoreQuestion(_InstructionsMixin):
    type: Literal["score"]
    criteria: List[SerializableText]

    @field_validator("criteria")
    @classmethod
    def _criteria_size(cls, v):
        if not SCORE_MIN_LEVELS <= len(v) <= SCORE_MAX_LEVELS:
            raise ValueError(
                f"score criteria must contain between {SCORE_MIN_LEVELS} and "
                f"{SCORE_MAX_LEVELS} levels"
            )
        return v


Question = Annotated[
    Union[NoulQuestion, ChoiceQuestion, ScoreQuestion],
    Field(discriminator="type"),
]


class SystemOneRequest(BaseModel):
    """Jev request: state + model + questions (plan §2.2)."""

    state: SerializableText
    model: str = Field(min_length=1)
    questions: Dict[str, Question]

    @model_validator(mode="after")
    def _questions_non_empty(self):
        if not self.questions:
            raise ValueError("questions must contain at least one question")
        return self


# --------------------------------------------------------------------------
# Response models (plan §2.4)
# --------------------------------------------------------------------------


class NoulAnswer(BaseModel):
    type: Literal["noul"]
    noul: float = Field(ge=0.0, le=1.0)


class ChoiceAnswer(BaseModel):
    type: Literal["choice"]
    choice: str
    probabilities: Dict[str, float]
    confidence: float = Field(ge=0.0, le=1.0)


class ScoreAnswer(BaseModel):
    type: Literal["score"]
    score: float
    legend: Dict[str, str]
    probabilities: Dict[str, float]
    confidence: float = Field(ge=0.0, le=1.0)


Answer = Annotated[
    Union[NoulAnswer, ChoiceAnswer, ScoreAnswer],
    Field(discriminator="type"),
]


class Usage(BaseModel):
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)


class SystemOneResponse(BaseModel):
    """Jev response: model + answers + usage (plan §2.4)."""

    model: str
    answers: Dict[str, Answer]
    usage: Usage
