"""Set SPC control limits for every monitorable sensor (SECOM-30).

Run from the repo root, after scripts/spc_baseline.py:

    python3 scripts/spc_limits.py

Reads the baseline window from docs/analysis/baseline.json and writes:
    docs/analysis/control-limits.csv      one row per charted sensor (used by SECOM-31 and the processor)
    docs/analysis/control-limits.md       method, comparison and results
    docs/analysis/control-limits/*.png    three charts
Phase II runs are not read for anything here.
"""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from secom.baseline import BASELINE, assign_period  # noqa: E402
from secom.profile import monitorable_sensors, read_labels, read_sensors  # noqa: E402
from secom.spc import D2, fit_limits, fit_sensor, signals  # noqa: E402

BLUE, ORANGE = "#2a78d6", "#eb6834"
SURFACE, INK, MUTED, GRID = "#fcfcfb", "#2b2b29", "#6b6a63", "#e6e5e0"
TARGET = 0.0027  # share of in-control points outside +-3 sigma limits for a normal process


def style(ax) -> None:
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=9)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def pooled_rate(test: pd.DataFrame, lo: pd.Series, hi: pd.Series) -> float:
    present = test.notna()
    out = ((test < lo) | (test > hi)) & present
    return out.to_numpy().sum() / present.to_numpy().sum()


def method_comparison(baseline: pd.DataFrame, limits_first_half: pd.DataFrame) -> dict[str, float]:
    """Pooled alarm rate on the second half of the baseline, with limits set on the first half."""
    half = len(baseline) // 2
    first, second = baseline.iloc[:half], baseline.iloc[half:]
    out = {}
    centre = first.mean()
    sigma = first.diff().abs().mean() / D2
    out["Classic I-MR (mean +-3 MR-sigma)"] = pooled_rate(second, centre - 3 * sigma, centre + 3 * sigma)
    cleaned = first.copy()
    for _ in range(10):
        c, s = cleaned.mean(), cleaned.diff().abs().mean() / D2
        outside = (cleaned < c - 3 * s) | (cleaned > c + 3 * s)
        if not outside.to_numpy().any():
            break
        cleaned = cleaned.mask(outside)
    c, s = cleaned.mean(), cleaned.diff().abs().mean() / D2
    out["I-MR with iterative clean-up"] = pooled_rate(second, c - 3 * s, c + 3 * s)
    med = first.median()
    mad = (first - med).abs().median() * 1.4826
    out["Median +-3 robust SD (MAD)"] = pooled_rate(second, med - 3 * mad, med + 3 * mad)
    alarms = present = 0
    for name, row in limits_first_half.iterrows():
        col = second[name].to_numpy(dtype=float)
        ok = ~np.isnan(col)
        alarms += int(signals(col, row)[ok].sum())
        present += int(ok.sum())
    out["Chosen: Yeo-Johnson, mean +-3 SD, gross clean-up"] = alarms / present
    return out


def chart_methods(rates: dict[str, float], out: Path) -> None:
    names = list(rates)[::-1]
    values = [rates[n] * 100 for n in names]
    colours = [ORANGE if n.startswith("Chosen") else BLUE for n in names]
    fig, ax = plt.subplots(figsize=(9, 3.2), facecolor=SURFACE)
    style(ax)
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.barh(names, values, color=colours, height=0.55)
    ax.axvline(TARGET * 100, color=INK, linewidth=1, linestyle="--")
    ax.text(TARGET * 100, -0.45, "  target 0.27%", color=INK, fontsize=9, va="center")
    for y, v in enumerate(values):
        ax.text(v + 0.1, y, f"{v:.2f}%", va="center", color=INK, fontsize=9)
    ax.set_xlabel("Points outside the limits on the second half of the baseline (%)", color=MUTED, fontsize=9)
    ax.set_xlim(0, max(values) * 1.18)
    ax.set_ylim(-0.8, len(names) - 0.5)
    fig.suptitle("False alarms on in-control data, by method", x=0.02, ha="left", color=INK, fontsize=11)
    fig.tight_layout()
    fig.savefig(out, dpi=150, facecolor=SURFACE)
    plt.close(fig)


def chart_sensor_rates(table: pd.DataFrame, drift_cut: float, out: Path) -> None:
    rates = (table["half_split_alarm_rate"] * 100).clip(upper=25)
    fig, ax = plt.subplots(figsize=(9, 3.2), facecolor=SURFACE)
    style(ax)
    ax.hist(rates, bins=np.arange(0, 25.5, 0.5), color=BLUE, edgecolor=SURFACE, linewidth=1)
    ax.axvline(TARGET * 100, color=INK, linewidth=1, linestyle="--")
    ax.axvline(drift_cut * 100, color=ORANGE, linewidth=1.5)
    top = ax.get_ylim()[1]
    ax.text(TARGET * 100, top * 0.95, "  target 0.27%", color=INK, fontsize=9, va="top")
    ax.text(drift_cut * 100, top * 0.95, "  drifting beyond 5%", color=INK, fontsize=9, va="top")
    ax.set_xlabel("Second-half alarm rate per sensor (%, capped at 25)", color=MUTED, fontsize=9)
    ax.set_ylabel("Sensors", color=MUTED, fontsize=9)
    ax.set_title(
        "Most sensors alarm near the target rate; a minority drift", loc="left", color=INK, fontsize=11
    )
    fig.tight_layout()
    fig.savefig(out, dpi=150, facecolor=SURFACE)
    plt.close(fig)


def chart_examples(baseline, times, table, picks: list[tuple[str, str]], out: Path) -> None:
    fig, axes = plt.subplots(len(picks), 1, figsize=(9, 2.3 * len(picks)), sharex=True, facecolor=SURFACE)
    for ax, (name, why) in zip(axes, picks, strict=True):
        style(ax)
        row = table.loc[name]
        values = baseline[name].to_numpy(dtype=float)
        flagged = signals(values, row)
        ax.plot(times, values, color=BLUE, linewidth=1)
        ax.scatter(times[flagged], values[flagged], color=ORANGE, s=18, zorder=3, label="outside limits")
        for level, style_ in ((row["ucl"], "--"), (row["centre"], "-"), (row["lcl"], "--")):
            ax.axhline(level, color=MUTED, linewidth=1, linestyle=style_)
        lo = np.nanmin([np.nanmin(values), row["lcl"]])
        hi = np.nanmax([np.nanmax(values), row["ucl"]])
        pad = (hi - lo) * 0.08
        ax.set_ylim(lo - pad, hi + pad)
        rate = np.nanmean(np.where(np.isnan(values), np.nan, flagged)) * 100
        ax.set_title(
            f"{name}: {why} ({rate:.1f}% of baseline points outside)", loc="left", color=INK, fontsize=10
        )
    axes[0].legend(loc="upper right", frameon=False, fontsize=9)
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    fig.suptitle(
        "Baseline runs with their limits (dashed) and centre line, in sensor units",
        x=0.06,
        ha="left",
        color=INK,
        fontsize=11,
    )
    fig.tight_layout()
    fig.savefig(out, dpi=150, facecolor=SURFACE)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--data-dir", type=Path, default=REPO / "data" / "raw")
    parser.add_argument("--out-dir", type=Path, default=REPO / "docs" / "analysis")
    args = parser.parse_args()
    warnings.filterwarnings("ignore", category=RuntimeWarning)

    window = json.loads((args.out_dir / "baseline.json").read_text())
    sensors_all = read_sensors((args.data_dir / "secom.data").read_text())
    labels = read_labels((args.data_dir / "secom_labels.data").read_text())
    monitored = monitorable_sensors(sensors_all)
    in_base = assign_period(labels["timestamp"]) == BASELINE
    if int(in_base.sum()) != window["baseline_runs"]:
        raise SystemExit("Baseline window changed: re-run scripts/spc_baseline.py first.")
    baseline = sensors_all.loc[in_base, monitored]
    times = labels.loc[in_base, "timestamp"].to_numpy()

    table = fit_limits(baseline)
    not_charted = sorted(set(monitored) - set(table.index))
    half = len(baseline) // 2
    first_half = pd.DataFrame.from_dict(
        {name: fit_sensor(baseline[name].iloc[:half]) for name in table.index}, orient="index"
    )
    rates = method_comparison(baseline[table.index], first_half)

    chart_dir = args.out_dir / "control-limits"
    chart_dir.mkdir(parents=True, exist_ok=True)
    chart_methods(rates, chart_dir / "method-comparison.png")
    chart_sensor_rates(table, 0.05, chart_dir / "alarm-rate-by-sensor.png")

    ordinary = table[~table["discrete"] & ~table["drifting"] & ~table["non_normal"]]
    typical = (ordinary["half_split_alarm_rate"] - TARGET).abs().idxmin()
    skewed = ordinary["skew_raw"].abs().idxmax()
    drifting = table[table["drifting"] & ~table["discrete"]]["half_split_alarm_rate"].idxmax()
    picks = [
        (typical, "a typical sensor"),
        (skewed, f"strongly skewed (skew {table.loc[skewed, 'skew_raw']:.1f}), so the limits are asymmetric"),
        (drifting, "the sensor that drifts most inside the baseline"),
        ("s337", "with the extreme whole-run events from SECOM-29"),
    ]
    chart_examples(baseline, times, table, picks, chart_dir / "example-charts.png")

    export = table[
        [
            "n",
            "loc",
            "scale",
            "lambda",
            "centre_t",
            "sd_t",
            "lcl_t",
            "ucl_t",
            "lcl",
            "centre",
            "ucl",
            "mr_bar",
            "gross_removed",
        ]
        + ["half_split_alarm_rate", "discrete", "non_normal", "drifting"]
    ]
    export.to_csv(args.out_dir / "control-limits.csv", float_format="%.6g")

    n = len(table)
    drift = table[table["drifting"]].sort_values("half_split_alarm_rate", ascending=False)
    drift_rows = "\n".join(
        f"| `{s}` | {r.half_split_alarm_rate * 100:.1f}% | {r.skew_raw:.1f} |"
        for s, r in drift.head(15).iterrows()
    )
    method_rows = "\n".join(
        f"| {name} | {rate * 100:.2f}% | {rate / TARGET:.0f}x |" for name, rate in rates.items()
    )
    chosen = rates["Chosen: Yeo-Johnson, mean +-3 SD, gross clean-up"]
    per_run = chosen * n
    sigma_share = table["mr_sigma_share"]
    n_lam0, n_lam2 = int((table["lambda"] == 0).sum()), int((table["lambda"] == 2).sum())
    med_rate = table["half_split_alarm_rate"].median()
    n_drift = int(table["drifting"].sum())
    gross_total = int(table["gross_removed"].sum())
    values_total = int(table["n"].sum()) + gross_total
    md = f"""# SPC Phase I: control limits (SECOM-30)

Generated by `scripts/spc_limits.py` from the baseline window chosen in SECOM-29
(25 Aug to 28 Sep 2008, {window["baseline_runs"]} runs). Phase II runs are not read here.

## Decision

Each sensor gets limits set like this:

1. **Standardise and transform**: subtract the baseline median, divide by the baseline SD, then apply a
   Yeo-Johnson power transform with the sensor's own lambda (maximum likelihood). Standardising first
   matters: the transform is not scale-invariant, and on raw values in the thousands it collapses
   numerically (an early version produced 29 sensors with zero-width limits). Lambda is kept between
   0 and 2: outside that range the transform squeezes one tail into a bounded interval, a limit on that
   side can match no real sensor value, and extreme values there could never signal (an early version
   left 37 sensors without an upper limit, including ones with the whole-run outliers from SECOM-29).
2. **Clean up gross outliers only**: points more than 6 SD from the mean after the transform are removed,
   once. That took out {gross_total:,} of {values_total:,} values.
3. **Limits at mean +-3 SD** of the cleaned, transformed values. Mapped back to sensor units they are
   usually asymmetric: a skewed sensor gets a longer allowance on its long-tail side.

A new value is a signal when its transformed value falls outside the limits. The transform is plain
NumPy in `secom/spc.py`, so the processor (SECOM-27) can apply these limits without SciPy.

**{n} sensors are charted.** The other {len(not_charted)} monitorable sensors are constant inside the
baseline,
or constant once their gross outliers are removed ({", ".join(f"`{s}`" for s in not_charted)}), so they
can't have limits. Lambda sits at the bottom of its range (0, a log transform) for
{n_lam0} sensors and at the top (2) for {n_lam2}: those are
skewed beyond what the transform can fully correct.

The full table is `docs/analysis/control-limits.csv`: sensor, n, the standardising median and
SD (`loc`, `scale`), lambda, centre and SD on the transformed scale, limits on both scales,
MR-bar, gross outliers removed, and the flags below.

## Why not textbook I-MR?

The usual individuals chart sets limits at centre +-2.66 x MR-bar (3 sigma, with sigma estimated from
the average moving range). To compare methods without looking at Phase II, each one was fitted on the
first half of the baseline and checked on the second half, which is still in control. A method that fits
should put about **0.27%** of those points outside its limits.

![False alarms by method](control-limits/method-comparison.png)

| Method | Second-half alarm rate | Times the target |
|---|---|---|
{method_rows}

Three things push the textbook method off:

- **Heavy tails.** Before the transform the median sensor has skew {table["skew_raw"].median():.1f}, and
  {int((table["skew_raw"].abs() > 1).sum())} of {n} sensors have |skew| above 1. After it, the median skew
  is {table["skew_t"].median():.2f} and {int(table["non_normal"].sum())} sensors stay above 1.
- **The moving range under-estimates the spread.** Neighbouring runs are more alike than runs far
  apart, so sigma from MR-bar is a median {sigma_share.median():.2f} of the plain SD (10th percentile
  {sigma_share.quantile(0.1):.2f}). Limits built on it are too narrow. MR-bar is still in the table.
- **Iterative clean-up makes it worse.** Removing every point outside the limits and recomputing
  narrows the limits each round, so more points fall outside next time. Only gross outliers are removed.

## How well the chosen limits fit

![Alarm rate by sensor](control-limits/alarm-rate-by-sensor.png)

Per sensor, with limits from the first half: the median sensor alarms on
{med_rate * 100:.2f}% of second-half points, about {med_rate / TARGET:.0f} times the 0.27% target.
(Without the 0-2 bound on lambda it was 0.28%, but 37 sensors could then never alarm on their high side;
that trade is deliberate.) The pooled
rate is higher ({chosen * 100:.2f}%) because a minority drift: **{n_drift} sensors alarm on more than 5%**
and are flagged `drifting`.

| Most drifting sensors | Second-half alarm rate | Skew before transform |
|---|---|---|
{drift_rows}

Other flags: {int(table["non_normal"].sum())} sensors `non_normal` (|skew| still above 1 after the transform)
and {int(table["discrete"].sum())} sensors `discrete` (fewer than 20 distinct baseline values, where a
continuous transform is a rough fit). Their limits are kept but should be read with that in mind.

![Example charts](control-limits/example-charts.png)

The drifting example, `{drifting}`, shows why that flag matters: it steps down to a new level around
19 Sep, inside the baseline, so for this sensor the "in-control" period is not in control and its limits
are stretched to cover both levels. Drifting sensors need their own treatment in Phase II rather than
these limits alone.

## What this means for Phase II (SECOM-31)

Even limits that fit perfectly would flag 0.27% x {n} sensors = **{TARGET * n:.1f} points per run** by
chance; at the measured {chosen * 100:.2f}% it is about **{per_run:.0f} per run**. So a single
out-of-limit point on one sensor means little. SECOM-31 should work per run: count signals, compare the
count with what the baseline produces, and treat the drifting sensors separately (EWMA is built for slow
drift).
"""
    (args.out_dir / "control-limits.md").write_text(md)
    print(
        f"{n} sensors charted, {len(not_charted)} not charted; "
        f"pooled half-split alarm rate {chosen * 100:.2f}%"
    )
    print(f"Wrote control-limits.md, control-limits.csv and 3 charts in {chart_dir}")


if __name__ == "__main__":
    main()
