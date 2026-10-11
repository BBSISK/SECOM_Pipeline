"""Unit tests for secom/profile.py, on tiny hand-made data (no network, no real dataset)."""

import pandas as pd
import pytest

from secom.profile import (
    class_balance,
    constant_sensors,
    missing_summary,
    monitorable_sensors,
    near_constant_sensors,
    read_labels,
    read_sensors,
    time_summary,
    weekly_fail_rate,
)

SENSORS_TEXT = """\
1.0 5.0 NaN 7.0
2.0 5.0 NaN 7.0
3.0 5.0 9.0 7.0
NaN 5.0 NaN 7.5
"""

LABELS_TEXT = """\
-1 "19/07/2008 11:55:00"
-1 "19/07/2008 12:32:00"
1 "19/07/2008 12:20:00"
-1 "21/07/2008 08:00:00"
"""


@pytest.fixture
def sensors():
    return read_sensors(SENSORS_TEXT)


@pytest.fixture
def labels():
    return read_labels(LABELS_TEXT)


def test_read_sensors_shape_and_nan(sensors):
    assert sensors.shape == (4, 4)
    assert list(sensors.columns) == ["s000", "s001", "s002", "s003"]
    assert sensors.isna().sum().sum() == 4


def test_read_labels_parses_label_and_day_first_timestamp(labels):
    assert list(labels["label"]) == [-1, -1, 1, -1]
    assert labels["timestamp"].iloc[0] == pd.Timestamp("2008-07-19 11:55:00")
    assert labels["timestamp"].iloc[3] == pd.Timestamp("2008-07-21 08:00:00")


def test_missing_summary_counts(sensors):
    ms = missing_summary(sensors)
    assert ms.cells_total == 16
    assert ms.cells_missing == 4
    assert ms.missing_share == pytest.approx(0.25)
    assert ms.runs_with_any_missing == 3
    # s001 and s003 complete; s000 missing 25% (20-50 band); s002 missing 75% (over 50%)
    assert ms.sensors_by_band == {"none": 2, "under 5%": 0, "5-20%": 0, "20-50%": 1, "over 50%": 1}
    assert ms.worst_sensors[0] == ("s002", 0.75)


def test_constant_sensors_ignore_missing(sensors):
    # s001 is always 5.0; s002 has a single reading (9.0) among missing values, so it carries no signal either
    assert constant_sensors(sensors) == ["s001", "s002"]


def test_all_missing_sensor_counts_as_constant():
    frame = read_sensors("NaN 1.0\nNaN 2.0\n")
    assert constant_sensors(frame) == ["s000"]


def test_near_constant_threshold():
    frame = read_sensors("\n".join(["7.0 1.0"] * 19 + ["8.0 2.0"]) + "\n")
    # s000: one value is 95% of readings -> near-constant; s001 same; neither is fully constant
    assert near_constant_sensors(frame, min_share=0.95) == ["s000", "s001"]
    assert near_constant_sensors(frame, min_share=0.99) == []


def test_class_balance(labels):
    balance = class_balance(labels)
    assert (balance.passes, balance.fails) == (3, 1)
    assert balance.fail_rate == pytest.approx(0.25)
    assert balance.ratio == pytest.approx(3.0)


def test_class_balance_rejects_unknown_labels():
    bad = read_labels('0 "19/07/2008 11:55:00"\n')
    with pytest.raises(ValueError, match="Unexpected label"):
        class_balance(bad)


def test_time_summary_finds_out_of_order_and_gaps(labels):
    times = time_summary(labels)
    assert times.out_of_order == 1  # 12:20 comes after 12:32 in file order
    assert times.duplicate_timestamps == 0
    assert times.first == pd.Timestamp("2008-07-19 11:55:00")
    assert times.last == pd.Timestamp("2008-07-21 08:00:00")
    assert times.days_with_runs == 2
    assert times.longest_gap_after_run == 2  # the jump to 21 July follows run 2


def test_weekly_fail_rate(labels):
    weekly = weekly_fail_rate(labels)
    assert weekly["runs"].sum() == 4
    assert weekly["fails"].sum() == 1
    assert (weekly["fail_rate"] <= 1).all()


def test_monitorable_excludes_constant_and_mostly_missing(sensors):
    assert monitorable_sensors(sensors, max_missing=0.5) == ["s000", "s003"]
    assert monitorable_sensors(sensors, max_missing=0.2) == ["s003"]
