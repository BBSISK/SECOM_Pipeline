# Stream record contract

Every production run travels from the replay producer, through Kinesis, to the processor as **one JSON record**. This page is the agreement between the two ends.

- **In code:** `secom/contract.py` (`validate()`, `make_record()`, `encode()`)
- **As a JSON Schema:** [`schemas/run-record.schema.json`](../schemas/run-record.schema.json), for tools and readers outside Python
- **Kept in step by tests:** `tests/test_contract.py` runs every bad example through both, and fails if either one accepts it

## Fields

| Field | Type | Meaning |
|---|---|---|
| `schema_version` | integer, always `1` | Contract version. Bumped on any breaking change |
| `replay_id` | string, 1-64 characters | Identifies one replay session. `seq` restarts at 0 for each new session |
| `seq` | integer ≥ 0 | Send order within the session. A jump in `seq` means a record was lost |
| `run_id` | integer 0-1566 | Row number of the run in `secom.data`. **The record's identity**: a duplicate has the same `run_id` |
| `sent_at` | UTC date-time ending in `Z`, e.g. `2026-10-12T10:00:00.000000Z` | When the producer sent it. **The event time** used downstream |
| `original_ts` | date-time, no time zone, e.g. `2008-07-19T11:55:00` | The run's timestamp in the original dataset (fab local time). Reference only |
| `label` | `-1` or `1` | In-line test result: `-1` pass, `1` fail |
| `sensors` | array of exactly 590 numbers or `null` | Readings in column order. `null` means missing |

Why `run_id` and not the timestamp: the data profile found 33 runs that share a timestamp with another run, so timestamps can't identify a record.

Why `null` and not `NaN`: JSON has no NaN. `make_record()` turns NaN into `null`, and `encode()` refuses to write NaN or Infinity rather than produce invalid JSON.

## Rejected: reason codes

A record is rejected only if it is **structurally broken**. Checks run in this order and the first failure is the reason recorded:

| Code | Rejected when |
|---|---|
| `MALFORMED_JSON` | The payload isn't valid JSON (including bare `NaN`/`Infinity`), isn't UTF-8, or isn't a JSON object |
| `MISSING_FIELD` | A required field is absent |
| `UNEXPECTED_FIELD` | A field the contract doesn't define is present |
| `UNSUPPORTED_VERSION` | `schema_version` isn't `1` |
| `BAD_IDENTITY` | `replay_id`, `seq` or `run_id` has the wrong type or is out of range |
| `BAD_TIMESTAMP` | `sent_at` or `original_ts` isn't a real date-time in the agreed format |
| `BAD_LABEL` | `label` isn't `-1` or `1` |
| `WRONG_SENSOR_COUNT` | `sensors` isn't a list of exactly 590 items |
| `NON_NUMERIC_VALUE` | A sensor reading is neither a number nor `null` |
| `DUPLICATE` | The `run_id` was already accepted in this replay. Set by the processor, which keeps state across records |

Every rejected record is still written to the raw S3 zone, so nothing is lost, and the reject log counts rejects by code.

## Recorded, not rejected

These are normal in a real feed. The record is accepted and the condition is flagged:

| Condition | How it's detected | Why it isn't a reject |
|---|---|---|
| Missing readings | `null` in `sensors`, counted by `missing_count()` | Every SECOM run has at least one missing reading ([data profile](data-profile.md)) |
| Gap | `seq` jumps by more than 1 within a `replay_id` | The missing record is lost upstream; the ones that arrived are still good |
| Late or out-of-order | `sent_at` older than the latest already seen | Late data is still real data; it is stored and flagged |

## Example (illustrative values, sensors shortened)

```json
{
  "schema_version": 1,
  "replay_id": "replay-2026-10-12T10-00-00Z",
  "seq": 0,
  "run_id": 0,
  "sent_at": "2026-10-12T10:00:00.000000Z",
  "original_ts": "2008-07-19T11:55:00",
  "label": -1,
  "sensors": [101.25, 2.5, null, 0.0047, "... 590 values in total ..."]
}
```
