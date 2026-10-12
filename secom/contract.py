"""The stream record contract (SECOM-17).

One JSON record per production run travels from the replay producer, through
Kinesis, to the processor. This module is the single source of truth for what
a valid record is, in code; schemas/run-record.schema.json says the same thing
as a JSON Schema for anyone outside Python, and tests keep the two in step.

validate() never raises on bad input. It returns a Result whose `reason` is one
of the RejectReason codes, so the processor can count rejects by reason and
the README can report them.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

SCHEMA_VERSION = 1
SENSOR_COUNT = 590
MAX_RUN_ID = 1566  # SECOM has 1,567 runs, numbered from 0
LABELS = (-1, 1)  # -1 = pass, 1 = fail

FIELDS = ("schema_version", "replay_id", "seq", "run_id", "sent_at", "original_ts", "label", "sensors")
SENT_AT_FORMATS = ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ")
ORIGINAL_TS_FORMAT = "%Y-%m-%dT%H:%M:%S"


class RejectReason(StrEnum):
    """Why a record was rejected. Checked in this order; the first failure wins."""

    MALFORMED_JSON = "MALFORMED_JSON"  # not parseable JSON (includes NaN/Infinity literals) or not an object
    MISSING_FIELD = "MISSING_FIELD"  # a required field is absent
    UNEXPECTED_FIELD = "UNEXPECTED_FIELD"  # a field the contract doesn't define
    UNSUPPORTED_VERSION = "UNSUPPORTED_VERSION"  # schema_version is not one this code understands
    BAD_IDENTITY = "BAD_IDENTITY"  # replay_id, seq or run_id has the wrong type or range
    BAD_TIMESTAMP = "BAD_TIMESTAMP"  # sent_at or original_ts is not a valid date-time in the agreed format
    BAD_LABEL = "BAD_LABEL"  # label is not -1 or 1
    WRONG_SENSOR_COUNT = "WRONG_SENSOR_COUNT"  # sensors is not a list of exactly 590 items
    NON_NUMERIC_VALUE = "NON_NUMERIC_VALUE"  # a sensor reading is neither a number nor null
    DUPLICATE = (
        "DUPLICATE"  # run_id already accepted in this replay (set by the processor, which keeps state)
    )


@dataclass(frozen=True)
class Result:
    ok: bool
    record: dict[str, Any] | None = None
    reason: RejectReason | None = None
    detail: str = ""


def _reject(reason: RejectReason, detail: str) -> Result:
    return Result(ok=False, reason=reason, detail=detail)


def _is_int(value: Any) -> bool:
    # bool is a subclass of int in Python, but JSON true/false are not integers.
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    return (_is_int(value) or isinstance(value, float)) and math.isfinite(value)


def _parse_time(value: Any, formats: tuple[str, ...]) -> bool:
    if not isinstance(value, str):
        return False
    for fmt in formats:
        try:
            datetime.strptime(value, fmt)
            return True
        except ValueError:
            continue
    return False


def _reject_constant(name: str) -> None:
    raise ValueError(f"{name} is not valid JSON")


def validate(raw: str | bytes) -> Result:
    """Check one raw stream payload against the contract."""
    try:
        record = json.loads(raw, parse_constant=_reject_constant)
    except (ValueError, UnicodeDecodeError) as exc:
        return _reject(RejectReason.MALFORMED_JSON, str(exc)[:200])
    if not isinstance(record, dict):
        return _reject(RejectReason.MALFORMED_JSON, f"expected a JSON object, got {type(record).__name__}")

    missing = [f for f in FIELDS if f not in record]
    if missing:
        return _reject(RejectReason.MISSING_FIELD, ", ".join(missing))
    extra = sorted(set(record) - set(FIELDS))
    if extra:
        return _reject(RejectReason.UNEXPECTED_FIELD, ", ".join(extra))

    if record["schema_version"] != SCHEMA_VERSION or not _is_int(record["schema_version"]):
        return _reject(RejectReason.UNSUPPORTED_VERSION, repr(record["schema_version"]))

    replay_id = record["replay_id"]
    if not isinstance(replay_id, str) or not 1 <= len(replay_id) <= 64:
        return _reject(RejectReason.BAD_IDENTITY, "replay_id must be a string of 1-64 characters")
    if not _is_int(record["seq"]) or record["seq"] < 0:
        return _reject(RejectReason.BAD_IDENTITY, f"seq {record['seq']!r}")
    if not _is_int(record["run_id"]) or not 0 <= record["run_id"] <= MAX_RUN_ID:
        return _reject(RejectReason.BAD_IDENTITY, f"run_id {record['run_id']!r}")

    if not _parse_time(record["sent_at"], SENT_AT_FORMATS):
        return _reject(RejectReason.BAD_TIMESTAMP, f"sent_at {record['sent_at']!r}")
    if not _parse_time(record["original_ts"], (ORIGINAL_TS_FORMAT,)):
        return _reject(RejectReason.BAD_TIMESTAMP, f"original_ts {record['original_ts']!r}")

    if not _is_int(record["label"]) or record["label"] not in LABELS:
        return _reject(RejectReason.BAD_LABEL, repr(record["label"]))

    sensors = record["sensors"]
    if not isinstance(sensors, list) or len(sensors) != SENSOR_COUNT:
        size = len(sensors) if isinstance(sensors, list) else type(sensors).__name__
        return _reject(RejectReason.WRONG_SENSOR_COUNT, f"expected {SENSOR_COUNT}, got {size}")
    for index, value in enumerate(sensors):
        if value is not None and not _is_number(value):
            return _reject(RejectReason.NON_NUMERIC_VALUE, f"sensors[{index}] = {value!r}")

    return Result(ok=True, record=record)


def missing_count(record: dict[str, Any]) -> int:
    """How many sensor readings are missing (null). Recorded for every run; never a reason to reject."""
    return sum(1 for value in record["sensors"] if value is None)


def make_record(
    *,
    replay_id: str,
    seq: int,
    run_id: int,
    original_ts: datetime,
    label: int,
    sensors: list[float | None],
    sent_at: datetime | None = None,
) -> dict[str, Any]:
    """Build a contract-shaped record. NaN readings become null, as JSON has no NaN."""
    sent = (sent_at or datetime.now(UTC)).astimezone(UTC)
    return {
        "schema_version": SCHEMA_VERSION,
        "replay_id": replay_id,
        "seq": seq,
        "run_id": run_id,
        "sent_at": sent.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "original_ts": original_ts.strftime(ORIGINAL_TS_FORMAT),
        "label": label,
        "sensors": [None if v is None or (isinstance(v, float) and math.isnan(v)) else v for v in sensors],
    }


def encode(record: dict[str, Any]) -> bytes:
    """Serialise a record for the stream. Refuses NaN/Infinity rather than emitting invalid JSON."""
    return json.dumps(record, allow_nan=False, separators=(",", ":")).encode("utf-8")
