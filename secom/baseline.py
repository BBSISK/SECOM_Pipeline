"""SPC Phase I baseline window (SECOM-29).

Pure functions: split the runs into ramp-up, baseline (Phase I) and monitoring
(Phase II) periods by timestamp, and measure how settled the process is week by
week. scripts/spc_baseline.py draws the charts and writes docs/analysis/baseline.md.

Decision (23-24 Oct 2026): baseline = every run from 25 Aug to 28 Sep 2008
inclusive, passes and fails alike (label-blind, classic SPC). Runs from 29 Sep
onwards are Phase II and are never used to set limits.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

BASELINE_START = pd.Timestamp("2008-08-25")
PHASE2_START = pd.Timestamp("2008-09-29")  # baseline ends just before this

RAMP_UP, BASELINE, PHASE2 = "ramp-up", "baseline", "phase II"


def assign_period(timestamps: pd.Series) -> pd.Series:
    """Label each run ramp-up / baseline / phase II by its timestamp."""
    period = pd.Series(RAMP_UP, index=timestamps.index, dtype=object)
    period[(timestamps >= BASELINE_START) & (timestamps < PHASE2_START)] = BASELINE
    period[timestamps >= PHASE2_START] = PHASE2
    return period


@dataclass(frozen=True)
class PeriodSummary:
    period: str
    first: pd.Timestamp
    last: pd.Timestamp
    runs: int
    fails: int

    @property
    def fail_rate(self) -> float:
        return self.fails / self.runs if self.runs else 0.0


def period_summaries(labels: pd.DataFrame, period: pd.Series) -> list[PeriodSummary]:
    """Runs, fails and date range for each period, in time order."""
    out = []
    for name in (RAMP_UP, BASELINE, PHASE2):
        rows = labels[period == name]
        if rows.empty:
            continue
        out.append(
            PeriodSummary(
                period=name,
                first=rows["timestamp"].min(),
                last=rows["timestamp"].max(),
                runs=len(rows),
                fails=int((rows["label"] == 1).sum()),
            )
        )
    return out


def weekly_stability(sensors: pd.DataFrame, labels: pd.DataFrame, shift_threshold: float = 0.5) -> pd.DataFrame:
    """Per week (Monday start): runs, fail rate, how far sensors sit from their norm, and missingness.

    A sensor's shift in a week is |weekly mean - whole-period mean| / whole-period SD.
    Sensors with zero spread are skipped. Columns: runs, fails, fail_rate,
    median_abs_shift_sd, share_shifted (share of sensors beyond shift_threshold SD),
    missing_pct.
    """
    week = labels["timestamp"].dt.to_period("W-SUN").dt.start_time
    sd = sensors.std()
    usable = sd[sd > 0].index
    z = (sensors[usable] - sensors[usable].mean()) / sd[usable]
    shift = z.groupby(week).mean().abs()
    fail = (labels["label"] == 1).astype(int)
    out = pd.DataFrame(
        {
            "runs": fail.groupby(week).size(),
            "fails": fail.groupby(week).sum(),
        }
    )
    out["fail_rate"] = out["fails"] / out["runs"]
    out["median_abs_shift_sd"] = shift.median(axis=1)
    out["share_shifted"] = (shift > shift_threshold).mean(axis=1)
    out["missing_pct"] = sensors.isna().groupby(week).mean().mean(axis=1) * 100
    out.index.name = "week"
    return out


def half_split_shift(sensors: pd.DataFrame) -> pd.Series:
    """|mean of first half - mean of second half| / SD, per sensor, for runs in time order.

    A stationary process gives small values (median about 0.6745 * sqrt(2 / n_half)
    by chance); bigger values mean slow drift inside the window.
    """
    half = len(sensors) // 2
    sd = sensors.std()
    usable = sd[sd > 0].index
    first, second = sensors[usable].iloc[:half], sensors[usable].iloc[half:]
    return ((first.mean() - second.mean()).abs() / sd[usable]).dropna()


def pass_only_spread_ratio(sensors: pd.DataFrame, labels: pd.DataFrame, cut: float = 0.9) -> pd.Series:
    """SD with passes only / SD with all runs, for sensors where dropping fails cuts the spread below `cut`.

    In SECOM this mostly flags sensors whose spread is dominated by one extreme failing
    run, not sensors that are noisy on fails in general (see extreme_runs).
    """
    passes = labels["label"] != 1
    sd_all = sensors.std()
    sd_pass = sensors[passes].std()
    ratio = (sd_pass / sd_all)[sd_all > 0].dropna()
    return ratio[ratio < cut].sort_values()


def robust_z(sensors: pd.DataFrame) -> pd.DataFrame:
    """|value - median| / (1.4826 * MAD) per sensor; sensors with MAD 0 are dropped.

    Median and MAD are not dragged around by the extreme values they are meant to find,
    unlike the mean and SD.
    """
    med = sensors.median()
    mad = (sensors - med).abs().median() * 1.4826
    usable = mad[mad > 0].index
    return ((sensors[usable] - med[usable]) / mad[usable]).abs()


def extreme_runs(sensors: pd.DataFrame, threshold: float = 10.0, min_sensors: int = 5) -> pd.Series:
    """Runs where at least `min_sensors` sensors sit beyond `threshold` robust SDs, with the count, most first."""
    count = (robust_z(sensors) > threshold).sum(axis=1)
    return count[count >= min_sensors].sort_values(ascending=False)
