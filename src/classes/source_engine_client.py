"""Async httpx client for the source engine's /api/run-rlcd endpoint, with
error mapping (plan §2.8, Phase 3 item 4).

- engine 400                       -> JevValidationError      (route: 422)
- connect error / timeout          -> SourceUnavailableError  (route: 502)
- engine 5xx / other non-200,
  unparseable JSON                 -> SourceEngineError       (route: 502)

The client is a module-level singleton created lazily from the current
``settings.config`` values; if the settings change (tests monkeypatch them),
the next call transparently creates a fresh client.
"""

import logging

import httpx

from classes.jev_errors import JevValidationError, SourceEngineError, SourceUnavailableError
from settings import config

logger = logging.getLogger(__name__)

_RUN_RLCD_PATH = "/api/run-rlcd"

_client: httpx.AsyncClient | None = None


def get_client() -> httpx.AsyncClient:
    """Return the shared AsyncClient, (re)creating it when settings changed."""
    global _client
    base_url = str(config.SOURCE_API_BASE_URL)
    timeout = httpx.Timeout(config.SOURCE_API_TIMEOUT_SECONDS)
    if (
        _client is None
        or _client.is_closed
        or str(_client.base_url) != base_url
        or _client.timeout != timeout
    ):
        _client = httpx.AsyncClient(base_url=base_url, timeout=timeout)
    return _client


async def aclose_client() -> None:
    """Close and drop the shared client (teardown / between test groups)."""
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


def reset_client() -> None:
    """Drop the shared client without awaiting a close (sync test isolation)."""
    global _client
    _client = None


def _error_detail(response: httpx.Response) -> str:
    """Extract a human-readable message from an engine error response."""
    try:
        body = response.json()
    except ValueError:
        text = response.text.strip()
        return text[:500] if text else f"HTTP {response.status_code}"
    if isinstance(body, dict) and "detail" in body:
        return str(body["detail"])
    return str(body)[:500]


async def run_rlcd(payload: dict) -> dict:
    """Exactly one POST /api/run-rlcd call per /v1/systemone call (plan §1)."""
    client = get_client()
    try:
        response = await client.post(_RUN_RLCD_PATH, json=payload)
    except httpx.TimeoutException as exc:
        raise SourceUnavailableError(
            f"Source engine timed out after {config.SOURCE_API_TIMEOUT_SECONDS}s "
            f"(it serializes requests behind a GPU lock): {exc}"
        ) from exc
    except httpx.HTTPError as exc:
        raise SourceUnavailableError(f"Source engine unreachable: {exc}") from exc

    if response.status_code == 400:
        # Schema rule violation: client-side translation bug or unsupported
        # input — Jev would call this unprocessable (plan §2.8).
        raise JevValidationError(_error_detail(response))
    if response.status_code != 200:
        raise SourceEngineError(
            f"Source engine returned HTTP {response.status_code}: "
            f"{_error_detail(response)}"
        )
    try:
        return response.json()
    except ValueError as exc:
        raise SourceEngineError(
            f"Source engine returned unparseable JSON: {response.text[:200]!r}"
        ) from exc
