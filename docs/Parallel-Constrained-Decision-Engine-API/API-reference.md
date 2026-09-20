# API Documentation

API for the **Parallel Constrained Decision Engine** — a classifier backend (FastAPI) served at the base URL:

```
http://localhost:9321
```

The engine classifies a free-text `context` against a user-defined `schema` of boolean and enum questions, either via a single parallel forward pass (RLCD, with calibrated probabilities) or via autoregressive JSON generation (naive baseline). A static web UI is served at `/`; all programmatic access goes through the `/api/*` endpoints below.

---

## Endpoints overview

| Method   | Path                  | Purpose                                                        |
|----------|-----------------------|----------------------------------------------------------------|
| `GET`    | `/api/presets`        | List bundled example presets (sample contexts + schemas)       |
| `POST`   | `/api/run-rlcd`       | **Main classification endpoint** — parallel, 1 forward pass, calibrated probabilities |
| `POST`   | `/api/run-parallel`   | Exact alias of `/api/run-rlcd`                                 |
| `POST`   | `/api/run-naive`      | Baseline classification — autoregressive JSON token generation |
| `POST`   | `/api/stream-naive`   | Naive classification streamed as Server-Sent Events (SSE)      |
| `POST`   | `/api/compare`        | Run naive + RLCD, return both results and speedup statistics   |
| any      | `/` (static)          | Web UI (browser only — not part of the programmatic API)       |

---

## Common request schema

All `POST` endpoints accept the same JSON body (`application/json`):

| Field          | Type                | Required | Default        | Description |
|----------------|---------------------|----------|----------------|-------------|
| `context`      | `string`            | yes      | —              | The free text to classify. |
| `schema`       | `object`            | yes      | —              | Field definitions (see below). Sent as the JSON key `"schema"`. |
| `temperature`  | `number` (optional) | no       | see per-endpoint | Sampling temperature; only meaningful for the naive path. |

> Note: the body key is `schema` even though the internal Python field is named `schema_def` (alias `schema`).

### Schema definition

An object mapping **field name → field definition**. Field names become the keys of the returned classification.

Field definition:

| Property     | Type     | Required | Description |
|--------------|----------|----------|-------------|
| `type`       | `string` | yes      | `boolean` or `enum` (also accepts `choice` / `selection`). No other types are supported. |
| `description`| `string` | yes      | Natural-language description of the question — this is what the model reads. |
| `choices`    | `array of strings` | required for `enum` | Allowed answer values. **Max 255 choices.** Must be short, single-word values (answers are matched against single vocabulary tokens, so multi-word choices may fail to match). Booleans must not have `choices`. |

Example:

```json
{
  "context": "My cat has food allergies. Does your pet food contain any allergens?",
  "schema": {
    "is_request": {
      "type": "boolean",
      "description": "Is this a request?"
    },
    "pet_type": {
      "type": "enum",
      "description": "What kind of pet does the customer have?",
      "choices": ["CAT", "BIRD", "DOG"]
    }
  }
}
```

### Concurrency

Inference is serialized behind a GPU lock — a request that arrives while another is running will wait its turn. Do not issue concurrent requests expecting parallel execution.

### Errors

Invalid schemas, schema rule violations (bad type, missing `choices`, > 255 choices), or inference failures return:

```
HTTP 400
{ "detail": "<error message>" }
```

---

## `GET /api/presets`

Returns a JSON array of all bundled preset files. Each preset contains a ready-made example:

```json
[
  {
    "id": "code_security",
    "title": "Autonomous Code Security & PR Vulnerability Triage (28 Fields)",
    "description": "...",
    "context": "...",
    "schema": { "is_vulnerability": { "type": "boolean", "description": "..." }, ... }
  },
  ...
]
```

Example:

```bash
curl -s http://localhost:9321/api/presets | python3 -m json.tool
```

Useful for copying a working `context` + `schema` shape to adapt for your own requests.

---

## `POST /api/run-rlcd` (alias: `/api/run-parallel`)

**The recommended endpoint for programmatic classification.** Evaluates all schema fields in a single parallel forward pass (prefill + one suffix evaluation) and returns calibrated per-field answer probabilities. Always produces valid, schema-conformant JSON.

Defaults: `temperature = 1.0` (little practical effect; no token sampling occurs).

### Response (HTTP 200)

> ⚠️ In RLCD mode `parsed_json` values are **objects** `{"value": ..., "prob": ...}`, not plain answers. See `responses-API.md` for the full response reference with live examples.

| Field                        | Type      | Description |
|------------------------------|-----------|-------------|
| `mode`                       | `string`  | Always `"parallel_constrained_calibrated"`. |
| `elapsed_ms`                 | `number`  | Total wall-clock inference time. |
| `prefill_ms`                 | `number`  | Time spent on the prompt prefill pass. |
| `suffix_eval_ms`             | `number`  | Time spent on the parallel suffix evaluation pass. |
| `total_tokens_generated`     | `number`  | Always `0` (no autoregressive decoding). |
| `sequential_forward_passes`  | `number`  | Always `1`. |
| `is_valid_json`              | `boolean` | Always `true`. |
| `schema_match`               | `boolean` | Always `true`. |
| `parsed_json`                | `object`  | **The classification result** — one key per schema field with its chosen value. |
| `field_telemetry`            | `object`  | Per-field probabilities (see below). |
| `has_calibrated_probabilities` | `boolean` | Always `true`. |
| `num_fields`                 | `number`  | Number of schema fields evaluated. |

### `field_telemetry` structure

For each schema field `<name>`:

| Property      | Type     | Description |
|---------------|----------|-------------|
| `value`       | `string` | The chosen answer (e.g. `"true"` / `"CAT"`). |
| `type`        | `string` | `boolean` or `enum`. |
| `confidence`  | `number` | Probability of the chosen answer (0–1, rounded to 4 decimals). |
| `cardinality` | `number` | Number of possible choices for the field. |
| `top_choices` | `array`  | Up to 5 most likely answers, sorted by probability: `{ "choice": "CAT", "probability": 0.9 }`. |

### Example

```bash
curl -s -X POST http://localhost:9321/api/run-rlcd \
  -H 'Content-Type: application/json' \
  -d '{
    "context": "My cat has food allergies. Does your pet food contain any allergens?",
    "schema": {
      "is_request": { "type": "boolean", "description": "Is this a request?" },
      "pet_type":   { "type": "enum", "description": "What kind of pet does the customer have?",
                      "choices": ["CAT", "BIRD", "DOG"] }
    }
  }' | python3 -m json.tool
```

Sample response:

```json
{
  "mode": "parallel_constrained_calibrated",
  "elapsed_ms": 181.14,
  "prefill_ms": 141.88,
  "suffix_eval_ms": 30.62,
  "total_tokens_generated": 0,
  "sequential_forward_passes": 1,
  "is_valid_json": true,
  "schema_match": true,
  "parsed_json": {
    "is_request": { "value": false, "prob": 0.5039 },
    "pet_type": { "value": "CAT", "prob": 0.999 }
  },
  "field_telemetry": {
    "is_request": {
      "value": false, "type": "boolean", "confidence": 0.5039, "cardinality": 2,
      "top_choices": [ { "choice": "false", "probability": 0.5039 },
                       { "choice": "true", "probability": 0.4961 } ]
    },
    "pet_type": {
      "value": "CAT", "type": "enum", "confidence": 0.999, "cardinality": 3,
      "top_choices": [ { "choice": "CAT", "probability": 0.999 },
                       { "choice": "BIRD", "probability": 0.001 },
                       { "choice": "DOG", "probability": 0.0 } ]
    }
  },
  "has_calibrated_probabilities": true,
  "num_fields": 2
}
```

Note: `parsed_json.<field>.value` is the actual answer (real JSON boolean for boolean fields, string for enum fields); `prob` is its calibrated confidence. Full response reference with live examples: `responses-API.md`.

---

## `POST /api/run-naive`

Baseline: generates the JSON answer autoregressively, token by token (one forward pass per token), with a temperature-sampling decode. Returns the raw generated text and schema-conformance diagnostics. Slower than `/api/run-rlcd`; does not return probabilities.

Defaults: `temperature = 0.2`.

### Response (HTTP 200)

| Field                       | Type      | Description |
|-----------------------------|-----------|-------------|
| `mode`                      | `string`  | Always `"naive_autoregressive"`. |
| `elapsed_ms`                | `number`  | Total generation time. |
| `total_tokens`              | `number`  | Number of generated tokens (max 700). |
| `tokens_per_second`         | `number`  | Decode throughput. |
| `sequential_forward_passes` | `number`  | Equal to `total_tokens`. |
| `is_valid_json`             | `boolean` | Whether the raw output parsed as JSON. |
| `schema_match`              | `boolean` | Whether all schema fields are present and enum values valid. |
| `raw_text`                  | `string`  | The raw generated JSON string. |
| `parsed_json`               | `object`  | Parsed answer (may be `null` if parsing failed). |
| `parse_error`               | `string`  | Parse error message, or `null`. |
| `missing_keys`              | `array`   | Schema fields absent from the output. |
| `invalid_enums`             | `array`   | Enum fields whose value is not in `choices` (as `"name=value"` strings). |
| `has_calibrated_probabilities` | `boolean` | Always `false`. |

---

## `POST /api/stream-naive`

Same generation logic as `/api/run-naive`, but streamed as **Server-Sent Events** (`text/event-stream`). Each SSE `data:` line is a JSON event:

- Token event (repeated while decoding):
  ```json
  { "type": "token", "token": "CAT", "accumulated": "{\n  \"pet_type\": \"CAT\"", "token_count": 5, "elapsed_ms": 120.5 }
  ```
- Final event (last line of the stream) — identical structure to the `/api/run-naive` response:
  ```json
  { "type": "done", "result": { "mode": "naive_autoregressive", ... } }
  ```
- On failure: `{ "type": "error", "error": "<message>" }`.

Defaults: `temperature = 0.2`, max 700 tokens.

Example:

```bash
curl -N -X POST http://localhost:9321/api/stream-naive \
  -H 'Content-Type: application/json' \
  -d '{ "context": "...", "schema": { ... } }'
```

(`-N` disables curl buffering so tokens appear live.)

---

## `POST /api/compare`

Runs **both** engines sequentially on the same input and returns both results plus performance statistics. (Two full inference runs — slower than either single call.)

Defaults: naive `temperature = 0.2`, RLCD `temperature = 1.0`. A single `temperature` value overrides both.

### Response (HTTP 200)

| Field                | Type     | Description |
|----------------------|----------|-------------|
| `speedup_multiplier` | `number` | `naive.elapsed_ms / rlcd.elapsed_ms` (× faster, rounded to 0.1). |
| `steps_reduction`    | `number` | `naive.sequential_forward_passes / rlcd.sequential_forward_passes` (rounded to 0.1). |
| `naive`              | `object` | Full `/api/run-naive`-style result. |
| `parallel`           | `object` | Full `/api/run-rlcd`-style result. |
| `rlcd`               | `object` | Same object as `parallel`. |

```bash
curl -s -X POST http://localhost:9321/api/compare \
  -H 'Content-Type: application/json' \
  -d '{ "context": "...", "schema": { ... } }' | python3 -m json.tool
```

---

## Quick reference — which endpoint to use

- **Classify a message programmatically** → `POST /api/run-rlcd`
- **Need generation speed/behavior diagnostics or the baseline output** → `POST /api/run-naive`
- **Want the token stream live** → `POST /api/stream-naive` (SSE)
- **Benchmarking the two modes** → `POST /api/compare`
- **Discover example schemas** → `GET /api/presets`
