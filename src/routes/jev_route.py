"""Jev-compatible routes (plan §2.1, §4 Phase 4).

- ``POST /v1/systemone``: one translated ``POST /api/run-rlcd`` call per
  request, returning the Jev response shape (§2.2–§2.6).
- ``GET /v1/models``: static local catalog — not required for basic drop-in
  use, but it makes the TypeSafe SDK (``client.models.list()``) work out of
  the box (§2.1).

Error semantics follow §2.8: pydantic validation failures surface as
FastAPI's default 422; engine 400 maps to 422 and engine unavailability /
bad engine responses to 502, always with FastAPI's ``{"detail": ...}`` body.
"""

import logging

from fastapi import APIRouter, HTTPException

from classes.jev_errors import JevValidationError, SourceEngineError, SourceUnavailableError
from classes.jev_response_builder import build_systemone_response
from classes.jev_translator import build_engine_request
from classes.source_engine_client import run_rlcd
from models.jev_models import SystemOneRequest, SystemOneResponse
from settings import config

logger = logging.getLogger(__name__)

router = APIRouter()

#: Date this local Jev imitation was implemented; reported as ``release_date``
#: in the model catalog.
IMPLEMENTATION_DATE = "2026-09-20"

_MODEL_CATALOG = [
    {
        "name": "jev-latest",
        "description": (
            "Jev-compatible proxy backed by the local Parallel Constrained "
            "Decision Engine (RLCD mode, calibrated probabilities)."
        ),
        "release_date": IMPLEMENTATION_DATE,
    },
    {
        "name": "jev-preview",
        "description": (
            "Pre-release alias served by the same local engine backend; "
            "identical behavior to jev-latest."
        ),
        "release_date": IMPLEMENTATION_DATE,
    },
]


@router.get("/v1/models")
async def list_models():
    return {"models": _MODEL_CATALOG}


def _validate_model(model: str) -> None:
    """Model is validated as a non-empty string by the request model and
    otherwise ignored. With ``ALLOWED_MODELS`` set (comma list), only listed
    ids are accepted (plan §2.2); empty means accept any model string."""
    allowed_raw = (config.ALLOWED_MODELS or "").strip()
    if not allowed_raw:
        return
    allowed = [entry.strip() for entry in allowed_raw.split(",") if entry.strip()]
    if model not in allowed:
        raise HTTPException(
            status_code=422,
            detail=f"model {model!r} is not allowed (ALLOWED_MODELS={allowed_raw!r})",
        )


@router.post("/v1/systemone", response_model=SystemOneResponse)
async def systemone(request: SystemOneRequest) -> SystemOneResponse:
    _validate_model(request.model)
    try:
        engine_request = build_engine_request(request)
        engine_payload = await run_rlcd(engine_request)
        return build_systemone_response(request, engine_payload)
    except JevValidationError as exc:
        # Source engine 400: client-side translation bug or unsupported
        # input — Jev would call this unprocessable (plan §2.8).
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (SourceUnavailableError, SourceEngineError) as exc:
        # Documented deviation: Jev has no equivalent for "backend down".
        raise HTTPException(status_code=502, detail=str(exc)) from exc
