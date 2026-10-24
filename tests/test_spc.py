"""Tests for secom/spc.py (SECOM-30): transform, limits and signals on hand-worked numbers."""

import math

import numpy as np
import pandas as pd
import pytest

from secom.spc import (
    LAMBDA_RANGE,
    alarm_rate,
    fit_lambda,
    fit_limits,
    fit_sensor,
    inverse_yeo_johnson,
    mr_bar,
    signals,
    to_sensor_units,
    to_transformed,
    yeo_johnson,
)


def test_yeo_johnson_known_values():
    assert yeo_johnson([2.5, -1.0], 1.0) == pytest.approx([2.5, -1.0])  # lambda 1 is the identity
    assert yeo_johnson([math.e - 1], 0.0)[0] == pytest.approx(1.0)  # lambda 0: log(1 + x)
    assert yeo_johnson([-(math.e - 1)], 2.0)[0] == pytest.approx(-1.0)  # lambda 2: -log(1 - x)
    assert yeo_johnson([3.0], 0.5)[0] == pytest.approx(2.0)  # ((3 + 1) ** 0.5 - 1) / 0.5
    assert np.isnan(yeo_johnson([np.nan], 0.5)[0])


@pytest.mark.parametrize("lam", [0.0, 0.3, 1.0, 1.7, 2.0])
def test_inverse_undoes_the_transform(lam):
    x = np.array([-4.0, -0.5, 0.0, 0.7, 9.0])
    assert inverse_yeo_johnson(yeo_johnson(x, lam), lam) == pytest.approx(x)


def test_fit_sensor_hand_worked_with_lambda_one():
    # values 1..5: median 3, SD sqrt(2.5) = 1.5811. With lambda 1 the transform is the identity, so on the
    # standardised scale the centre is 0 and the SD is 1; limits are -3 and 3, i.e. 3 -+ 3 * 1.5811.
    row = fit_sensor([1, 2, 3, 4, 5], lam=1.0)
    sd = math.sqrt(2.5)
    assert row["loc"] == 3 and row["scale"] == pytest.approx(sd)
    assert row["centre_t"] == pytest.approx(0.0, abs=1e-12) and row["sd_t"] == pytest.approx(1.0)
    assert (row["lcl_t"], row["ucl_t"]) == pytest.approx((-3.0, 3.0))
    assert (row["lcl"], row["centre"], row["ucl"]) == pytest.approx((3 - 3 * sd, 3.0, 3 + 3 * sd))
    assert row["mr_bar"] == 1.0
    assert row["gross_removed"] == 0


def test_gross_outlier_is_removed_once():
    values = [10.0, 11.0] * 50 + [1000.0]  # one value far beyond 6 SD (needs a long enough series)
    row = fit_sensor(values, lam=1.0)
    assert row["gross_removed"] == 1
    assert row["n"] == 100
    assert row["ucl"] < 20  # limits come from the cleaned values, not the outlier


def test_signals_and_alarm_rate():
    limits = fit_sensor([1, 2, 3, 4, 5], lam=1.0)  # sensor-unit limits about -1.74 and 7.74
    flagged = signals([3.0, 8.0, -2.0, np.nan], limits)
    assert list(flagged) == [False, True, True, False]
    assert alarm_rate([3.0, 8.0, np.nan, 4.0], limits) == pytest.approx(1 / 3)


def test_round_trip_between_scales():
    limits = fit_sensor([1.0, 2.0, 2.5, 3.0, 7.0, 4.0, 2.2], lam=0.4)
    x = np.array([0.5, 2.0, 6.0])
    assert to_sensor_units(to_transformed(x, limits), limits) == pytest.approx(x)


def test_fit_lambda_stays_in_range_for_very_skewed_data():
    rng = np.random.default_rng(0)
    skewed = np.exp(rng.normal(0, 2, 500))  # log-normal: would want lambda below 0
    lam = fit_lambda((skewed - np.median(skewed)) / skewed.std())
    assert LAMBDA_RANGE[0] <= lam <= LAMBDA_RANGE[1]
    row = fit_sensor(skewed)
    assert np.isfinite(row["lcl"]) and np.isfinite(row["ucl"])  # both limits map back to real values
    assert row["lcl"] < row["centre"] < row["ucl"]


def test_fit_limits_skips_flat_sensors_and_flags_a_step():
    rng = np.random.default_rng(1)
    n = 200
    baseline = pd.DataFrame(
        {
            "steady": rng.normal(50, 2, n),
            "step": np.r_[rng.normal(0, 1, n // 2), rng.normal(8, 1, n // 2)],  # level shift halfway
            "flat": np.full(n, 3.0),
            "flat_but_one": np.r_[np.zeros(n - 1), 500.0],  # constant once the outlier is removed
        }
    )
    table = fit_limits(baseline)
    assert set(table.index) == {"steady", "step"}
    assert not table.loc["steady", "drifting"]
    assert table.loc["step", "drifting"]  # first-half limits can't contain the second half
    assert table.loc["steady", "half_split_alarm_rate"] < 0.05


def test_mr_bar_skips_missing_values():
    assert mr_bar([1.0, np.nan, 3.0, 2.0]) == pytest.approx(1.5)  # ranges 2 and 1 after dropping NaN
