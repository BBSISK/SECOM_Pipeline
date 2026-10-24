"""Statistical process control limits per sensor (SECOM-30).

Method (chosen 24 Oct 2026, see docs/analysis/control-limits.md):

1. Standardise each sensor (baseline median and SD), then transform it towards a normal shape with
   Yeo-Johnson (lambda fitted on the baseline, kept between 0 and 2 so both limits always map back to
   real sensor values). Standardising first matters: Yeo-Johnson is not
   scale-invariant, and on raw values in the thousands the fitted transform collapses numerically.
2. Remove gross outliers only: baseline points more than 6 SD from the mean after the transform.
3. Limits: mean +-3 SD of the cleaned, transformed baseline. Mapped back to sensor units they are
   usually asymmetric, which is the point: skewed sensors get a longer tail on the skewed side.

Why not textbook I-MR (centre +-2.66 x MR-bar)? On SECOM it alarms on 5% of in-control points instead of
0.27%: the sensors are heavy-tailed, and neighbouring runs are more alike than runs far apart, so the
moving range under-estimates the spread. MR-bar is still reported for each sensor.

The transform and the limit check are plain NumPy so the processor (SECOM-27) can apply the exported
limits without SciPy; SciPy is only needed here to fit lambda.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

SIGMA_LIMIT = 3.0  # control limits at +-3 SD
GROSS_LIMIT = 6.0  # Phase I clean-up removes points beyond 6 SD
D2 = 1.128  # bias constant for moving ranges of two points
MIN_DISTINCT = 20  # fewer distinct baseline values than this: flagged as discrete
SKEW_FLAG = 1.0  # |skew| still above this after the transform: flagged as non-normal
LAMBDA_RANGE = (0.0, 2.0)  # inside this range Yeo-Johnson maps the whole line onto the whole line
DRIFT_FLAG = 0.05  # fitted on the first half, alarms on more than 5% of the second half: flagged as drifting


def yeo_johnson(x, lam: float) -> np.ndarray:
    """Yeo-Johnson power transform of x with parameter lam (NaN stays NaN)."""
    x = np.asarray(x, dtype=float)
    out = np.full_like(x, np.nan)
    pos = x >= 0
    neg = x < 0  # NaN is in neither
    if abs(lam) < 1e-12:
        out[pos] = np.log1p(x[pos])
    else:
        out[pos] = ((x[pos] + 1) ** lam - 1) / lam
    if abs(lam - 2) < 1e-12:
        out[neg] = -np.log1p(-x[neg])
    else:
        out[neg] = -((-x[neg] + 1) ** (2 - lam) - 1) / (2 - lam)
    return out


def inverse_yeo_johnson(y, lam: float) -> np.ndarray:
    """Undo yeo_johnson: maps transformed values back to sensor units."""
    y = np.asarray(y, dtype=float)
    out = np.full_like(y, np.nan)
    pos = y >= 0
    neg = y < 0
    if abs(lam) < 1e-12:
        out[pos] = np.expm1(y[pos])
    else:
        out[pos] = (y[pos] * lam + 1) ** (1 / lam) - 1
    if abs(lam - 2) < 1e-12:
        out[neg] = -np.expm1(-y[neg])
    else:
        out[neg] = 1 - (1 - y[neg] * (2 - lam)) ** (1 / (2 - lam))
    return out


def fit_lambda(values) -> float:
    """Maximum-likelihood Yeo-Johnson lambda for the non-missing values (SciPy), kept within LAMBDA_RANGE.

    Outside 0..2 the transform squeezes one tail into a bounded interval, so a limit on that side can
    map to no finite sensor value and extreme values there could never signal. The likelihood is
    single-peaked in lambda, so clipping gives the best lambda within the range.
    """
    from scipy import stats  # only needed when fitting

    v = pd.Series(values, dtype=float).dropna().to_numpy()
    if len(v) < 3 or np.ptp(v) == 0:
        return 1.0
    lo, hi = LAMBDA_RANGE
    return float(np.clip(stats.yeojohnson_normmax(v), lo, hi))


def mr_bar(values) -> float:
    """Average moving range of consecutive non-missing values (time order kept)."""
    v = pd.Series(values, dtype=float).dropna()
    return float(v.diff().abs().mean())


def to_transformed(values, limits: dict) -> np.ndarray:
    """Sensor units -> the standardised, transformed scale the limits live on."""
    z = (np.asarray(values, dtype=float) - limits["loc"]) / limits["scale"]
    return yeo_johnson(z, limits["lambda"])


def to_sensor_units(t, limits: dict) -> np.ndarray:
    """Transformed scale -> sensor units (inverse of to_transformed)."""
    return inverse_yeo_johnson(t, limits["lambda"]) * limits["scale"] + limits["loc"]


def fit_sensor(values, lam: float | None = None) -> dict:
    """Limits for one sensor from its baseline values (in time order).

    Returns the standardising loc and scale, lambda, centre and SD on the transformed scale, the limits
    in sensor units, the number of gross outliers removed, MR-bar and the MR-based sigma as a share of
    the SD, and skew before and after.
    """
    raw = pd.Series(values, dtype=float)
    loc, scale = float(raw.median()), float(raw.std())
    z = (raw - loc) / scale
    lam = fit_lambda(z) if lam is None else lam
    t = pd.Series(yeo_johnson(z, lam), index=raw.index)
    centre, sd = t.mean(), t.std()
    gross = (t - centre).abs() > GROSS_LIMIT * sd
    if gross.any():
        t = t.mask(gross)
        centre, sd = t.mean(), t.std()
    lcl_t, ucl_t = centre - SIGMA_LIMIT * sd, centre + SIGMA_LIMIT * sd
    raw_sd = raw[~gross].std()
    mrb = mr_bar(raw[~gross])
    scaled = {"loc": loc, "scale": scale, "lambda": lam}
    return {
        "n": int(t.notna().sum()),
        "loc": loc,
        "scale": scale,
        "lambda": lam,
        "centre_t": centre,
        "sd_t": sd,
        "lcl_t": lcl_t,
        "ucl_t": ucl_t,
        "lcl": float(to_sensor_units([lcl_t], scaled)[0]),
        "centre": float(to_sensor_units([centre], scaled)[0]),
        "ucl": float(to_sensor_units([ucl_t], scaled)[0]),
        "gross_removed": int(gross.sum()),
        "mr_bar": mrb,
        "mr_sigma_share": (mrb / D2) / raw_sd if raw_sd > 0 else np.nan,
        "skew_raw": float(raw[~gross].skew()),
        "skew_t": float(t.skew()),
        "distinct": int(raw.nunique()),
    }


def signals(values, limits: dict) -> np.ndarray:
    """True where a value is outside its sensor's limits (NaN is never a signal)."""
    t = to_transformed(values, limits)
    with np.errstate(invalid="ignore"):
        return (t < limits["lcl_t"]) | (t > limits["ucl_t"])


def alarm_rate(values, limits: dict) -> float:
    """Share of non-missing values outside the limits."""
    v = np.asarray(values, dtype=float)
    present = ~np.isnan(v)
    if not present.any():
        return np.nan
    return float(signals(v, limits)[present].mean())


def fit_limits(baseline: pd.DataFrame) -> pd.DataFrame:
    """Limits table for every sensor that varies in the baseline (rows in time order).

    Sensors that are constant, or constant once gross outliers are removed, are left out.

    Adds flags: discrete (few distinct values), non_normal (still skewed after the transform) and
    drifting (limits from the first half alarm on more than 5% of the second half).
    """
    half = len(baseline) // 2
    rows = {}
    for name in baseline.columns:
        col = baseline[name]
        if col.dropna().nunique() < 2:
            continue
        row = fit_sensor(col)
        if not row["sd_t"] > 0:
            continue  # constant once gross outliers are removed: no limits possible
        first = fit_sensor(col.iloc[:half])
        row["half_split_alarm_rate"] = alarm_rate(col.iloc[half:], first)
        row["discrete"] = row["distinct"] < MIN_DISTINCT
        row["non_normal"] = abs(row["skew_t"]) > SKEW_FLAG
        row["drifting"] = bool(row["half_split_alarm_rate"] > DRIFT_FLAG)
        rows[name] = row
    table = pd.DataFrame.from_dict(rows, orient="index")
    table.index.name = "sensor"
    return table
