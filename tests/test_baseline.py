"""Tests for secom/baseline.py (SECOM-29), on small hand-made tables."""

import numpy as np
import pandas as pd

from secom.baseline import (
    BASELINE,
    PHASE2,
    RAMP_UP,
    assign_period,
    extreme_runs,
    half_split_shift,
    pass_only_spread_ratio,
    period_summaries,
    robust_z,
    weekly_stability,
)


def labels_at(times, results):
    return pd.DataFrame({"label": results, "timestamp": pd.to_datetime(times)})


def test_assign_period_boundaries():
    ts = pd.Series(pd.to_datetime(["2008-08-24 23:59", "2008-08-25 00:00", "2008-09-28 23:59", "2008-09-29 00:00"]))
    assert list(assign_period(ts)) == [RAMP_UP, BASELINE, BASELINE, PHASE2]


def test_period_summaries_counts_runs_and_fails():
    labels = labels_at(["2008-08-01", "2008-08-26", "2008-08-27", "2008-10-01"], [1, -1, 1, -1])
    out = {s.period: s for s in period_summaries(labels, assign_period(labels["timestamp"]))}
    assert (out[RAMP_UP].runs, out[RAMP_UP].fails) == (1, 1)
    assert (out[BASELINE].runs, out[BASELINE].fails) == (2, 1)
    assert out[BASELINE].fail_rate == 0.5
    assert (out[PHASE2].runs, out[PHASE2].fails) == (1, 0)


def test_weekly_stability_flags_a_shifted_week_and_skips_flat_sensors():
    # Two weeks, 4 runs each. s1 sits at 0 in week one and 10 in week two; s2 never changes.
    times = ["2008-09-01", "2008-09-02", "2008-09-03", "2008-09-04", "2008-09-08", "2008-09-09", "2008-09-10", "2008-09-11"]
    labels = labels_at(times, [-1, -1, -1, 1, -1, -1, -1, -1])
    sensors = pd.DataFrame({"s1": [0, 0, 0, 0, 10, 10, 10, 10], "s2": [5.0] * 8})
    sensors.loc[1, "s1"] = np.nan  # one missing value in week one
    out = weekly_stability(sensors, labels)
    assert list(out["runs"]) == [4, 4]
    assert list(out["fails"]) == [1, 0]
    assert list(out["share_shifted"]) == [1.0, 1.0]  # only s1 counts; it is far from its overall mean both weeks
    assert out["missing_pct"].iloc[0] == 1 / 8 * 100  # 1 of 8 cells (2 sensors x 4 runs)


def test_half_split_shift_is_zero_for_a_steady_sensor_and_large_for_a_step():
    sensors = pd.DataFrame({"steady": [1, 2, 1, 2, 1, 2, 1, 2], "step": [0, 0, 0, 0, 5, 5, 5, 5], "flat": [3] * 8})
    out = half_split_shift(sensors)
    assert out["steady"] == 0
    assert out["step"] > 1.5
    assert "flat" not in out


def test_pass_only_spread_ratio_finds_a_sensor_driven_by_one_failing_run():
    labels = labels_at(["2008-09-01"] * 6, [-1, -1, -1, -1, -1, 1])
    sensors = pd.DataFrame({"spiky": [1, 2, 1, 2, 1, 50], "calm": [1, 2, 1, 2, 1, 2]})
    out = pass_only_spread_ratio(sensors, labels)
    assert list(out.index) == ["spiky"]
    assert out["spiky"] < 0.1


def test_robust_z_ignores_the_outlier_it_measures():
    sensors = pd.DataFrame({"a": [10, 11, 9, 10, 11, 9, 100]})
    z = robust_z(sensors)["a"]
    assert z.iloc[-1] > 50
    assert z.iloc[:-1].max() <= 1.0


def test_extreme_runs_needs_enough_sensors_at_once():
    base = np.tile([10.0, 11.0, 9.0, 10.0, 11.0, 9.0, 10.0], (6, 1)).T  # 7 runs x 6 sensors, MAD > 0
    sensors = pd.DataFrame(base, columns=[f"s{i}" for i in range(6)])
    sensors.iloc[3, :5] = 500  # run 3: five sensors extreme
    sensors.iloc[5, :2] = 500  # run 5: only two
    out = extreme_runs(sensors, threshold=10, min_sensors=5)
    assert list(out.index) == [3]
    assert out[3] == 5
