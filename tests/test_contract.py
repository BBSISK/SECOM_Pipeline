"""Tests for the stream record contract: the Python validator and the JSON Schema must agree."""

import json
from datetime import UTC, datetime
from pathlib import Path

import jsonschema
import pytest

from secom.contract import (
    SENSOR_COUNT,
    RejectReason,
    encode,
    make_record,
    missing_count,
    validate,
)

SCHEMA = json.loads(
    (Path(__file__).resolve().parent.parent / "schemas" / "run-record.schema.json").read_text()
)


def good_record(**overrides):
    record = make_record(
        replay_id="replay-2026-10-12T10-00-00Z",
        seq=0,
        run_id=0,
        original_ts=datetime(2008, 7, 19, 11, 55),
        label=-1,
        sensors=[float(i) for i in range(SENSOR_COUNT)],
        sent_at=datetime(2026, 10, 12, 10, 0, 0, tzinfo=UTC),
    )
    record.update(overrides)
    return record


def schema_accepts(record) -> bool:
    try:
        jsonschema.validate(record, SCHEMA)
        return True
    except jsonschema.ValidationError:
        return False


def test_good_record_passes_both():
    record = good_record()
    result = validate(encode(record))
    assert result.ok, result
    assert result.record == record
    assert schema_accepts(record)


def test_nan_becomes_null_and_is_counted_not_rejected():
    sensors = [1.0] * SENSOR_COUNT
    sensors[3] = float("nan")
    sensors[10] = None
    record = good_record(
        sensors=make_record(
            replay_id="r", seq=0, run_id=0, original_ts=datetime(2008, 7, 19), label=1, sensors=sensors
        )["sensors"]
    )
    assert record["sensors"][3] is None
    result = validate(encode(record))
    assert result.ok
    assert missing_count(result.record) == 2
    assert schema_accepts(record)


def test_sent_at_is_utc_with_z():
    record = make_record(
        replay_id="r",
        seq=0,
        run_id=0,
        original_ts=datetime(2008, 7, 19),
        label=-1,
        sensors=[None] * SENSOR_COUNT,
    )
    assert record["sent_at"].endswith("Z")
    assert validate(encode(record)).ok


# Each case: a broken record and the reason the validator must give. The JSON Schema must reject it too.
BAD_CASES = [
    ("missing field", {"__drop__": "label"}, RejectReason.MISSING_FIELD),
    ("extra field", {"colour": "blue"}, RejectReason.UNEXPECTED_FIELD),
    ("wrong version", {"schema_version": 2}, RejectReason.UNSUPPORTED_VERSION),
    ("empty replay_id", {"replay_id": ""}, RejectReason.BAD_IDENTITY),
    ("negative seq", {"seq": -1}, RejectReason.BAD_IDENTITY),
    ("seq as text", {"seq": "7"}, RejectReason.BAD_IDENTITY),
    ("run_id past the end", {"run_id": 1567}, RejectReason.BAD_IDENTITY),
    ("run_id as boolean", {"run_id": True}, RejectReason.BAD_IDENTITY),
    ("sent_at without Z", {"sent_at": "2026-10-12T10:00:00"}, RejectReason.BAD_TIMESTAMP),
    ("impossible date", {"original_ts": "2008-02-30T10:00:00"}, RejectReason.BAD_TIMESTAMP),
    ("original_ts in source format", {"original_ts": "19/07/2008 11:55:00"}, RejectReason.BAD_TIMESTAMP),
    ("label zero", {"label": 0}, RejectReason.BAD_LABEL),
    ("label as text", {"label": "fail"}, RejectReason.BAD_LABEL),
    ("too few sensors", {"sensors": [1.0] * 589}, RejectReason.WRONG_SENSOR_COUNT),
    ("too many sensors", {"sensors": [1.0] * 591}, RejectReason.WRONG_SENSOR_COUNT),
    ("sensors not a list", {"sensors": {"s000": 1.0}}, RejectReason.WRONG_SENSOR_COUNT),
    ("text reading", {"sensors": ["1.0"] + [1.0] * 589}, RejectReason.NON_NUMERIC_VALUE),
    ("boolean reading", {"sensors": [True] + [1.0] * 589}, RejectReason.NON_NUMERIC_VALUE),
]


@pytest.mark.parametrize(("name", "change", "reason"), BAD_CASES, ids=[c[0] for c in BAD_CASES])
def test_bad_records_rejected_with_reason(name, change, reason):
    record = good_record()
    if "__drop__" in change:
        del record[change["__drop__"]]
    else:
        record.update(change)
    result = validate(json.dumps(record))
    assert not result.ok
    assert result.reason == reason, result.detail
    # Impossible calendar dates pass a regex, so only the Python validator catches them.
    if name != "impossible date":
        assert not schema_accepts(record), f"JSON Schema accepted: {name}"


@pytest.mark.parametrize(
    "raw",
    [b"not json", b"[1, 2, 3]", b'{"sensors": NaN}', b"\xff\xfe", b""],
    ids=["text", "array", "NaN literal", "bad bytes", "empty"],
)
def test_malformed_payloads(raw):
    result = validate(raw)
    assert not result.ok
    assert result.reason == RejectReason.MALFORMED_JSON


def test_encode_refuses_nan():
    record = good_record()
    record["sensors"][0] = float("nan")
    with pytest.raises(ValueError):
        encode(record)


def test_reason_codes_documented():
    doc = (Path(__file__).resolve().parent.parent / "docs" / "record-contract.md").read_text()
    for reason in RejectReason:
        assert f"`{reason.value}`" in doc, f"{reason.value} missing from docs/record-contract.md"
