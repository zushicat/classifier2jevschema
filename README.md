# classifier2jevschema — a Jev-compatible proxy for the local Parallel Constrained Decision Engine
This is a drop-in Jev proxy for a local classifier: FastAPI adapter that exposes TypeSafe's POST /v1/systemone API (noul/choice/score questions) on top of a locally hosted Parallel Constrained Decision Engine, so any typesafe.ai-compatible client works offline by just changing the base URL.


This app translates between the i/o schema used by the local classifier engine
([harshatheg/Qwen-2.5-1B-RLCD](https://huggingface.co/harshatheg/Qwen-2.5-1B-RLCD)) and
TypeSafe AI's [Jev](https://docs.typesafe.ai/api) i/o schema. A client built against the
Jev API (curl, the TypeSafe SDKs, any HTTP client) only has to change the base URL to
`http://localhost:11100` and gets the same request/response shape, the same answer types
(`noul` / `choice` / `score`), and the same error semantics.

```
[ source api :9321 ] <-- context+schema -- [ classifier2jevschema :11100 ] <-- state+model+questions -- [ client ]
[ source api :9321 ] -- parsed_json+telemetry -> [ classifier2jevschema :11100 ] -- model+answers+usage -> [ client ]
```

## What is Qwen-2.5-1B-RLCD anyway?
From the 🤗 page:
"A high-throughput inference engine for structured information extraction, decision routing, and categorical classification on Apple Silicon using MLX."

So, this is basically an inference engine that turns the default LLM `mlx-community/Qwen2.5-1.5B-Instruct-4bit` into a fast-running classifier which can be
easily served on your local machine.


## So what's the problem?
No actual problem, but it would be nice to be able to use the same schema as
[Jev](https://docs.typesafe.ai/api). That way, when using Qwen-2.5-1B-RLCD, your
application layer doesn't need any adaptations for any API endpoints except setting the
URL.

## Installation

### 1 — install the source engine (harshatheg/Qwen-2.5-1B-RLCD)
```
git clone https://huggingface.co/harshatheg/Qwen-2.5-1B-RLCD.git
cd parallel-constrained-decoding

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

1. They left `git clone https://github.com/your-org/parallel-constrained-decoding.git`
   in the installation instructions on the 🤗 page.
2. When starting the API server (with `bash run.sh` or, better, so you control the port):
   ```
   python -m uvicorn server.app:app --host 0.0.0.0 --port 9321
   ```
   The model is downloaded on first start.

### 2 — run this proxy
```
cp .env.example .env        # then edit as needed
docker compose build
docker compose up -d
```
The proxy listens on `http://localhost:11100`; inside the container the engine is
expected at `http://host.docker.internal:9321` (default).

## Quicktest

Jev-style request from the **host**:
```bash
curl -s -X POST http://localhost:11100/v1/systemone \
  -H 'Content-Type: application/json' \
  -d '{
    "state": "I see a dangerous dwarf on the road to the east.",
    "model": "jev-latest",
    "questions": {
      "danger_close": { "type": "noul", "instructions": "Is any dangerous creature close to me?", "criteria": {
        "true": "i can see a dangerous creature",
        "false": "i see no dangerous creature"
      } },
      "avoid_direction":   { "type": "choice", "instructions": "In which direction do I see a dangerous creature?",
        "criteria": { "NORTH": null, "WEST": null, "EAST": null, "SOUTH": null } }
    }
  }' | python3 -m json.tool
```

The same request from **inside the container** (the app itself is `localhost:80` there):
```bash
docker compose exec classifier2jevschema curl -s -X POST http://localhost:80/v1/systemone \
  -H 'Content-Type: application/json' -d '{ ...same body... }'
```

A TypeSafe-SDK-style client needs only the base URL change (+ any dummy API key while
`USE_API_KEY=false`):
```python
from typesafe import Client   # pseudocode — any Jev client works the same way
client = Client(base_url="http://localhost:11100")
```

## Endpoints

| Method | Path              | Purpose                                                                 |
|--------|-------------------|-------------------------------------------------------------------------|
| `POST` | `/v1/systemone`   | Jev-style classification (translated to one `POST /api/run-rlcd` call)  |
| `GET`  | `/v1/models`      | Static local catalog (`jev-latest`, `jev-preview`) for the TypeSafe SDK |
| `GET` / `POST` | `/`        | Health check (unauthenticated)                                          |

## Mapping (Jev ⇄ source engine)

### Endpoint map

| Jev (target)          | classifier2jevschema | Source engine call                |
|-----------------------|----------------------|-----------------------------------|
| `POST /v1/systemone`  | `POST /v1/systemone` | `POST /api/run-rlcd` (exactly 1)  |
| `GET /v1/models`      | `GET /v1/models`     | — (static local catalog)          |

`/api/run-naive`, `/api/compare` and `/api/stream-naive` are never used: Jev answers
*require* per-option probabilities, which only the RLCD endpoint returns. `temperature`
is not part of the Jev schema and is never sent.

### Request mapping

| Jev field      | Source field | Transformation                                                                 |
|----------------|--------------|--------------------------------------------------------------------------------|
| `state`        | `context`    | `str` → verbatim; `dict`/`list` → JSON (indent 2); scalars → **422**           |
| `model`        | —            | Validated as non-empty string, otherwise ignored (see `ALLOWED_MODELS`)        |
| `questions`    | `schema`     | One source field per Jev question; answer keys = question ids                  |
| *extra fields* | —            | Ignored, so SDKs that add metadata don't break                                 |

### Question mapping

| Jev question | Source field | Description composition                                                        |
|--------------|--------------|--------------------------------------------------------------------------------|
| `noul`       | `boolean`    | `{instructions}`, plus `\n\nYES means: …` / `NO means: …` when `criteria` parts are present |
| `choice`     | `enum` (keys in insertion order as `choices`) | `{instructions}` + `\n\nOptions:\n` + `- {option}: {rubric}` (`null` → `(no additional description)`) |
| `score`      | `enum` over level indices `"0".."N-1"` | `{instructions}` + `\n\nRating levels (0 is the lowest rating, {N-1} the highest):\n` + `{i}: {criteria[i]}` |

Limits (→ 422): choice 1–255 options, score 2–10 levels, `instructions` non-empty.

### Response mapping

The engine's `field_telemetry.<id>.top_choices` (keyed by option name — it is sorted by
probability, never by declaration order), `.value` and `parsed_json.<id>.value` build:

| Jev answer | Built from |
|------------|------------|
| `noul`     | probability of the `"true"` entry in `top_choices` (round 4; fallback: parsed value `True` → `1.0` else `0.0`); no `confidence` |
| `choice`   | `choice` = telemetry value; `probabilities` = declared option → probability (missing → `0.0`), rounded to 4 decimals and renormalized to sum 1 (residual to the argmax option); `confidence` = TypeSafe's published formula `clamp((n·p_max − 1)/(n − 1), 0, 1)` |
| `score`    | `probabilities` over `"0".."N-1"` (same rounding/renormalization); `legend` = request criteria verbatim; `score` = `Σ i·pᵢ` (may land between levels); `confidence` = same formula |

`usage.input_tokens = ceil(serialized_prompt_chars / USAGE_TOKEN_DIVISOR)` (an estimate —
the engine reports no token counts), `usage.output_tokens = 0`.
Response `model` = `REPORTED_MODEL_ID` if set, otherwise the model string the client sent.

## Error semantics

| Situation | Response |
|-----------|----------|
| Body fails validation (missing `state`/`model`/`questions`, wrong `type`, scalar `state`, out-of-bounds criteria, empty `instructions`, …) | **422** with FastAPI's default validation body (`{"detail": [...]}`) |
| `USE_API_KEY=true` and Authorization missing / bad scheme / wrong token | **401 / 401 / 403** `{"detail": ...}` |
| Source engine returns 400 (schema rule violation) | **422** `{"detail": "<engine message>"}` |
| Source engine unreachable / connection error / timeout (default 120 s — the engine queues behind its GPU lock) | **502** `{"detail": ...}` (documented deviation) |
| Source engine 5xx, or unparseable/incomplete result (`schema_match=false`, missing telemetry) | **502** `{"detail": ...}` — the proxy never invents answers |
| Unknown path | **404** default `{"detail": "Not Found"}` |
| Unknown model string | Accepted (see `ALLOWED_MODELS`) |

## Configuration (`.env`)

| Variable | Default | Meaning |
|----------|---------|---------|
| `USE_API_KEY` | `false` | Require `Authorization: Bearer <API_KEY>` on `/v1/*` |
| `API_KEY` | — | Bearer token checked when `USE_API_KEY=true` |
| `SOURCE_API_BASE_URL` | `http://host.docker.internal:9321` | Source engine base URL |
| `SOURCE_API_TIMEOUT_SECONDS` | `120.0` | Request timeout (the engine serializes behind a GPU lock) |
| `REPORTED_MODEL_ID` | *(empty → echo)* | Model id reported in responses, e.g. `jev-local-rlcd-1.0.0` |
| `ALLOWED_MODELS` | *(empty → accept any)* | Comma-separated allowlist of model ids |
| `USAGE_TOKEN_DIVISOR` | `4.0` | chars→tokens divisor for the `usage` estimate |

`.env` changes require `docker compose up -d --force-recreate`; `.py` changes are picked
up live (volume mount + `uvicorn --reload`).

## Limitations

| Limitation | Note |
|---|---|
| The engine matches enum answers against single vocabulary tokens | Multi-word/long choice options classify poorly; they are passed through verbatim with a warning log — keep option keys short |
| `noul` is a probability, not a boolean | Clients that treat `noul ≥ 0.5` as yes get engine-calibrated but locally-produced numbers |
| Score is the expectation over the level distribution | Same math Jev publishes (probability-weighted across levels); the formula is pinned by tests |
| `usage.input_tokens` is a chars/4 estimate | Env-tunable divisor; documented as an estimate |
| Rounded `probabilities` are renormalized to sum to 1 | Residual added to the argmax option |
| TypeSafe's structure-in-instructions semantics are approximated | `criteria`/`instructions` structure is JSON-stringified into the field description |
| The engine queues concurrent requests behind a GPU lock | Generous default timeout; concurrent clients serialize |
| No streaming, no retry layer | Jev's `/v1/systemone` surface is plain JSON; the engine rarely rejects requests |

## Testing

All code and tests run inside the container (volume mount + reload make host edits live):

```bash
docker compose exec classifier2jevschema pytest -q                 # unit suite
docker compose exec classifier2jevschema pytest -q -m integration  # live engine round trips
docker compose exec classifier2jevschema pytest -q -m integration --no-header -o addopts=""
```

The integration tests skip cleanly when the source engine is unreachable.
`test_request.http` contains ready-made REST Client calls (health, models, the Jev
quicktest, a validation failure and a wrong-token variant) against
`http://localhost:11100`.
