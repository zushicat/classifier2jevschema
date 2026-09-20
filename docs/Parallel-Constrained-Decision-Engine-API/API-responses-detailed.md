# API Response Reference

Detailed description of the **responses** for every endpoint of the Parallel Constrained Decision Engine API. All example payloads below were captured live from a running server (`http://localhost:9321`) using the following request:

```json
{
  "context": "My cat has food allergies. Does your pet food contain any allergens?",
  "schema": {
    "is_request": { "type": "boolean", "description": "Is this a request?" },
    "pet_type":   { "type": "enum", "description": "What kind of pet does the customer have?",
                    "choices": ["CAT", "BIRD", "DOG"] }
  }
}
```

Request documentation is in `API.md`.

---

## `GET /api/presets`

**Content type:** `application/json` — array of preset objects.

One entry per `*.json` file in the `presets/` directory, sorted by filename. Each preset is a complete example of a valid request body:

| Field         | Type     | Description |
|---------------|----------|-------------|
| `id`          | `string` | Preset identifier (e.g. `"code_security"`). |
| `title`       | `string` | Human-readable title describing the scenario. |
| `description` | `string` | Short scenario description. |
| `context`     | `string` | Sample text to classify — usable verbatim as the request `context`. |
| `schema`      | `object` | Sample schema — usable verbatim as the request `schema`. |

Example (truncated, first preset):

```json
[
  {
    "id": "code_security",
    "title": "Autonomous Code Security & PR Vulnerability Triage (28 Fields)",
    "description": "Automated SAST/DAST static analysis triage ...",
    "context": "CI/CD PIPELINE AUDIT #PR-10822\nRepository: payment-gateway-core\n...",
    "schema": {
      "is_vulnerability": {
        "type": "boolean",
        "description": "Whether pull request introduces severe security vulnerabilities"
      },
      "primary_cwe": {
        "type": "enum",
        "description": "Primary vulnerability classification",
        "choices": ["CWE_89_SQL_INJECTION", "CWE_798_HARDCODED_CREDENTIALS", "..."]
      }
      // ... 26 more fields
    }
  }
  // ... other presets
]
```

Errors: none documented — always returns the array (possibly empty if `presets/` is missing).

---

## `POST /api/run-rlcd` / `POST /api/run-parallel`

**Content type:** `application/json`. Both paths return identical bodies.

Actual captured response:

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
      "value": false,
      "type": "boolean",
      "confidence": 0.5039,
      "cardinality": 2,
      "top_choices": [
        { "choice": "false", "probability": 0.5039 },
        { "choice": "true", "probability": 0.4961 }
      ]
    },
    "pet_type": {
      "value": "CAT",
      "type": "enum",
      "confidence": 0.999,
      "cardinality": 3,
      "top_choices": [
        { "choice": "CAT", "probability": 0.999 },
        { "choice": "BIRD", "probability": 0.001 },
        { "choice": "DOG", "probability": 0.0 }
      ]
    }
  },
  "has_calibrated_probabilities": true,
  "num_fields": 2
}
```

### Field descriptions

| Field                          | Type      | Description |
|--------------------------------|-----------|-------------|
| `mode`                         | `string`  | Always `"parallel_constrained_calibrated"`. |
| `elapsed_ms`                   | `number`  | Total wall-clock inference time in milliseconds. |
| `prefill_ms`                   | `number`  | Time spent on the prompt prefill pass. |
| `suffix_eval_ms`               | `number`  | Time spent on the parallel suffix evaluation pass (all fields at once). |
| `total_tokens_generated`       | `number`  | Always `0` — no autoregressive decoding happens. |
| `sequential_forward_passes`    | `number`  | Always `1` regardless of how many fields the schema has. |
| `is_valid_json`                | `boolean` | Always `true` — output is constructed, not generated. |
| `schema_match`                 | `boolean` | Always `true` — every field is guaranteed present and valid. |
| `parsed_json`                  | `object`  | **The classification.** ⚠️ One key per schema field, but the value is *not* a plain answer — see below. |
| `field_telemetry`              | `object`  | Per-field calibrated probability details — see below. |
| `has_calibrated_probabilities` | `boolean` | Always `true`. |
| `num_fields`                   | `number`  | Number of schema fields evaluated. |

### ⚠️ `parsed_json` shape in RLCD mode

Unlike the naive endpoint, each field's value is an **object** with two properties:

```json
{
  "is_request": { "value": false, "prob": 0.5039 },
  "pet_type":   { "value": "CAT",  "prob": 0.999 }
}
```

- `value` — the chosen answer: `boolean` for boolean fields (real JSON `true`/`false`, not a string), `string` for enum fields.
- `prob` — confidence of that answer, 0–1, rounded to 4 decimals. Note the example: `is_request` is nearly a coin flip (0.5039) — always check `prob` before acting on low-confidence answers.

To extract plain values in a script:

```bash
curl -s -X POST http://localhost:9321/api/run-rlcd -H 'Content-Type: application/json' -d '{...}' \
  | python3 -c 'import json,sys; r=json.load(sys.stdin); print({k: v["value"] for k, v in r["parsed_json"].items()})'
```

### `field_telemetry` structure

One key per schema field:

| Property      | Type      | Description |
|---------------|-----------|-------------|
| `value`       | `bool` / `string` | The chosen answer (same as `parsed_json.<field>.value`). |
| `type`        | `string`  | `"boolean"` or `"enum"`. |
| `confidence`  | `number`  | Probability of the chosen answer (0–1, 4 decimals). Identical to `prob` in `parsed_json`. |
| `cardinality` | `number`  | Number of possible answers (2 for boolean, `len(choices)` for enum). |
| `top_choices` | `array`   | **All** candidate answers ranked by probability, descending. Each item: `{ "choice": string, "probability": number }`. |

Note: `top_choices` lists the full candidate set here (small schemas), not just the top 5 — rely on `cardinality` / array length rather than assuming a cap.

---

## `POST /api/run-naive`

**Content type:** `application/json`.

Actual captured response:

```json
{
  "mode": "naive_autoregressive",
  "elapsed_ms": 196.83,
  "total_tokens": 15,
  "tokens_per_second": 76.2,
  "sequential_forward_passes": 15,
  "is_valid_json": true,
  "schema_match": true,
  "raw_text": "{\n   \"is_request\": true,\n   \"pet_type\": \"CAT\"\n}",
  "parsed_json": { "is_request": true, "pet_type": "CAT" },
  "parse_error": null,
  "missing_keys": [],
  "invalid_enums": [],
  "has_calibrated_probabilities": false
}
```

### Field descriptions

| Field                          | Type            | Description |
|--------------------------------|-----------------|-------------|
| `mode`                         | `string`        | Always `"naive_autoregressive"`. |
| `elapsed_ms`                   | `number`        | Total generation time in milliseconds. |
| `total_tokens`                 | `number`        | Number of generated tokens (hard cap 700). |
| `tokens_per_second`            | `number`        | Decode throughput. |
| `sequential_forward_passes`    | `number`        | Equal to `total_tokens` — one model pass per token (this is why naive is slower). |
| `is_valid_json`                | `boolean`       | Whether `raw_text` parsed as JSON. |
| `schema_match`                 | `boolean`       | `true` only if `is_valid_json` **and** `missing_keys` and `invalid_enums` are both empty. |
| `raw_text`                     | `string`        | The raw generated JSON string, as decoded token by token. |
| `parsed_json`                  | `object` / `null` | **The classification — plain values** (`true`, `"CAT"`), unlike RLCD mode. `null` if parsing failed. |
| `parse_error`                  | `string` / `null` | Python exception message if JSON parsing failed, else `null`. |
| `missing_keys`                 | `array of string` | Schema fields absent from the generated JSON. |
| `invalid_enums`                | `array of string` | Enum fields whose generated value is not in `choices`, formatted `"field_name=value"`. |
| `has_calibrated_probabilities` | `boolean`       | Always `false` — no probabilities from this path. |

Unlike RLCD, the naive output is *generated text*: `parsed_json` can be `null`, `schema_match` can be `false`, and generation stops when the JSON object closes (balanced braces) or at a stop token / 700 tokens. Generation is deterministic (greedy argmax) regardless of `temperature`.

---

## `POST /api/stream-naive`

**Content type:** `text/event-stream` (Server-Sent Events). The HTTP response is a sequence of SSE frames:

```
data: <json event>\n
\n
```

Use `curl -N` (no buffering) to watch it live:

```
data: {"type": "token", "token": "{\n   \"", "accumulated": "{\n   \"", "token_count": 1, "elapsed_ms": 81.5}

data: {"type": "token", "token": "is", "accumulated": "{\n   \"is", "token_count": 2, "elapsed_ms": 87.9}

data: {"type": "token", "token": "_request", "accumulated": "{\n   \"is_request", "token_count": 3, "elapsed_ms": 94.0}
...
data: {"type": "done", "result": { ... }}
```

### Event types

**1. Token events** — one per generated token, in order:

| Field         | Type     | Description |
|---------------|----------|-------------|
| `type`        | `string` | Always `"token"`. |
| `token`       | `string` | The decoded text delta for this step. |
| `accumulated` | `string` | The full JSON generated so far (all prior deltas concatenated). |
| `token_count` | `number` | 1-based index of this token. |
| `elapsed_ms`  | `number` | Wall-clock time since generation started, 1 decimal. |

**2. Final event** — exactly one, last in the stream:

| Field  | Type     | Description |
|--------|----------|-------------|
| `type` | `string` | Always `"done"`. |
| `result` | `object` | Identical structure to the `/api/run-naive` response body (see that section). |

**3. Error event** — emitted in place of a token if generation throws:

```json
{ "type": "error", "error": "<message>" }
```

Parsing tip: split the stream on `\n\n`; each `data:` line is standalone JSON. Only the `type` field is stable across event kinds.

---

## `POST /api/compare`

**Content type:** `application/json`. Runs the naive path **and** the RLCD path sequentially, then returns both full results plus derived performance statistics.

Actual captured response (abridged — `naive` and `rlcd` carry the complete bodies documented in their respective sections above):

```json
{
  "speedup_multiplier": 3.3,
  "steps_reduction": 15.0,
  "naive": {
    "mode": "naive_autoregressive",
    "elapsed_ms": 167.28,
    "total_tokens": 15,
    "tokens_per_second": 89.7,
    "sequential_forward_passes": 15,
    "is_valid_json": true,
    "schema_match": true,
    "raw_text": "{\n   \"is_request\": true,\n   \"pet_type\": \"CAT\"\n}",
    "parsed_json": { "is_request": true, "pet_type": "CAT" },
    "parse_error": null,
    "missing_keys": [],
    "invalid_enums": [],
    "has_calibrated_probabilities": false
  },
  "parallel": {
    "mode": "parallel_constrained_calibrated",
    "elapsed_ms": 50.55,
    "prefill_ms": 29.53,
    "suffix_eval_ms": 18.71,
    "total_tokens_generated": 0,
    "sequential_forward_passes": 1,
    "is_valid_json": true,
    "schema_match": true,
    "parsed_json": {
      "is_request": { "value": false, "prob": 0.5039 },
      "pet_type": { "value": "CAT", "prob": 0.999 }
    },
    "field_telemetry": { "is_request": { "...": "..." }, "pet_type": { "...": "..." } },
    "has_calibrated_probabilities": true,
    "num_fields": 2
  },
  "rlcd": { "...": "identical object, same reference as parallel" }
}
```

### Field descriptions

| Field                | Type     | Description |
|----------------------|----------|-------------|
| `speedup_multiplier` | `number` | `naive.elapsed_ms / rlcd.elapsed_ms`, rounded to 1 decimal — how many times faster the parallel path was. |
| `steps_reduction`    | `number` | `naive.sequential_forward_passes / rlcd.sequential_forward_passes`, rounded to 1 decimal — for a 2-field schema, `15 / 1 = 15.0`. |
| `naive`              | `object` | Complete `/api/run-naive`-style result (no probabilities). |
| `parallel`           | `object` | Complete `/api/run-rlcd`-style result, including `field_telemetry`. |
| `rlcd`               | `object` | Same content as `parallel` (included for readability; both keys reference the same result). |

This endpoint runs two full inference passes back to back — expect roughly double the latency of a single call, and remember the GPU lock serializes any concurrent requests behind it.

---

## Errors (all POST endpoints)

Schema violations, malformed bodies, or inference failures return HTTP 400:

```
HTTP/1.1 400 Bad Request
{ "detail": "Field 'pet_type' of type enum must have choices defined." }
```

| HTTP code | Trigger |
|-----------|---------|
| `400`     | Invalid JSON body; missing `context`/`schema`; unsupported field `type`; `enum` without `choices`; more than 255 choices; internal inference error. |
| `404`     | Unknown path (e.g. `/api/run-rldc` typo). |
| `405`     | Wrong HTTP method (e.g. `GET /api/run-rlcd`). |

Streaming endpoint note: schema errors surface as HTTP 400 before the stream starts, but exceptions raised *during* generation are reported inline as a `{"type": "error", ...}` SSE event with HTTP 200.
