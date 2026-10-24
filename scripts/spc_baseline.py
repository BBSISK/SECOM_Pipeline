"""Choose and document the SPC Phase I baseline window (SECOM-29).

Run from the repo root, after scripts/profile_secom.py has downloaded the data:

    python3 scripts/spc_baseline.py

Writes:
    docs/analysis/baseline.md         the reasoning and the numbers
    docs/analysis/baseline/*.png      four charts
    docs/analysis/baseline.json       the window, for SECOM-30 to read
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from secom.baseline import (  # noqa: E402
    BASELINE,
    BASELINE_START,
    PHASE2,
    PHASE2_START,
    assign_period,
    extreme_runs,
    half_split_shift,
    pass_only_spread_ratio,
    period_summaries,
    robust_z,
    weekly_stability,
)
from secom.profile import monitorable_sensors, read_labels, read_sensors  # noqa: E402

# Validated reference palette (dataviz skill): categorical slots 1-4, light surface, text inks.
BLUE, ORANGE, AQUA, YELLOW = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
SURFACE, INK, MUTED, GRID = "#fcfcfb", "#2b2b29", "#6b6a63", "#e6e5e0"
BAND_BASE, BAND_P2 = "#e3eefb", "#fbe9e1"  # light tints of blue / orange for the period bands


def style(ax) -> None:
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=9)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def bands(ax, end) -> None:
    ax.axvspan(BASELINE_START, PHASE2_START, color=BAND_BASE, zorder=0, linewidth=0)
    ax.axvspan(PHASE2_START, end, color=BAND_P2, zorder=0, linewidth=0)


def label_bands(ax, end, y) -> None:
    mid_base = BASELINE_START + (PHASE2_START - BASELINE_START) / 2
    mid_p2 = PHASE2_START + (end - PHASE2_START) / 2
    ax.text(mid_base, y, "baseline", ha="center", va="top", color=INK, fontsize=9)
    ax.text(mid_p2, y, "phase II", ha="center", va="top", color=INK, fontsize=9)


def new_fig(rows=1, height=3.2):
    fig, axes = plt.subplots(rows, 1, figsize=(9, height * rows), sharex=True, facecolor=SURFACE)
    return fig, np.atleast_1d(axes)


def chart_runs_and_fails(weekly, end, out: Path) -> None:
    fig, (a1, a2) = new_fig(2, 2.4)
    x = weekly.index + np.timedelta64(3, "D")  # centre each bar on its week
    for ax in (a1, a2):
        style(ax)
        bands(ax, end)
    a1.bar(x, weekly["runs"], width=5.5, color=BLUE)
    a1.set_ylabel("Runs per week", color=MUTED, fontsize=9)
    label_bands(a1, end, weekly["runs"].max() * 1.12)
    a1.set_ylim(0, weekly["runs"].max() * 1.15)
    a2.plot(x, weekly["fail_rate"] * 100, color=ORANGE, linewidth=2, marker="o", markersize=5)
    a2.set_ylabel("Fail rate (%)", color=MUTED, fontsize=9)
    a2.set_ylim(0, max(25, weekly["fail_rate"].max() * 110))
    a2.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    fig.suptitle("Runs and fail rate by week", x=0.06, ha="left", color=INK, fontsize=11)
    fig.tight_layout()
    fig.savefig(out, dpi=150, facecolor=SURFACE)
    plt.close(fig)


def chart_sensor_shift(weekly, end, out: Path) -> None:
    fig, (ax,) = new_fig(1, 3.2)
    style(ax)
    bands(ax, end)
    x = weekly.index + np.timedelta64(3, "D")
    ax.plot(x, weekly["share_shifted"] * 100, color=BLUE, linewidth=2, marker="o", markersize=5)
    ax.set_ylabel("Sensors shifted > 0.5 SD (%)", color=MUTED, fontsize=9)
    ax.set_ylim(0, max(35, weekly["share_shifted"].max() * 110))
    label_bands(ax, end, ax.get_ylim()[1] * 0.97)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    ax.set_title("How many sensors sit away from their usual level, by week", loc="left", color=INK, fontsize=11)
    fig.tight_layout()
    fig.savefig(out, dpi=150, facecolor=SURFACE)
    plt.close(fig)


def chart_missing(weekly, end, out: Path) -> None:
    fig, (ax,) = new_fig(1, 3.0)
    style(ax)
    bands(ax, end)
    x = weekly.index + np.timedelta64(3, "D")
    ax.plot(x, weekly["missing_pct"], color=BLUE, linewidth=2, marker="o", markersize=5)
    ax.set_ylabel("Values missing (%)", color=MUTED, fontsize=9)
    ax.set_ylim(0, max(5, weekly["missing_pct"].max() * 1.15))
    label_bands(ax, end, ax.get_ylim()[1] * 0.97)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    ax.set_title("Missing values in the 446 monitorable sensors, by week", loc="left", color=INK, fontsize=11)
    fig.tight_layout()
    fig.savefig(out, dpi=150, facecolor=SURFACE)
    plt.close(fig)


def chart_sample_sensors(sensors, timestamps, names, end, out: Path, window: int = 50) -> None:
    """Rolling mean and rolling SD (in whole-period SD units) for a few sensors."""
    colours = [BLUE, ORANGE, AQUA, YELLOW]
    fig, (a1, a2) = new_fig(2, 2.6)
    for ax in (a1, a2):
        style(ax)
        bands(ax, end)
    for name, colour in zip(names, colours):
        col = sensors[name]
        z = (col - col.mean()) / col.std()
        roll_mean = z.rolling(window, min_periods=window // 2).mean()
        roll_sd = z.rolling(window, min_periods=window // 2).std()
        a1.plot(timestamps, roll_mean, color=colour, linewidth=2, label=name)
        a2.plot(timestamps, roll_sd, color=colour, linewidth=2, label=name)
    a1.axhline(0, color=MUTED, linewidth=0.8)
    a2.axhline(1, color=MUTED, linewidth=0.8)
    a1.set_ylabel(f"Rolling mean\n({window} runs, SD units)", color=MUTED, fontsize=9)
    a2.set_ylabel(f"Rolling SD\n({window} runs, SD units)", color=MUTED, fontsize=9)
    a1.legend(loc="upper right", frameon=False, fontsize=9, ncol=len(names))
    a2.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    fig.suptitle("Sample sensors over time", x=0.06, ha="left", color=INK, fontsize=11)
    fig.tight_layout()
    fig.savefig(out, dpi=150, facecolor=SURFACE)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", type=Path, default=REPO / "data" / "raw")
    parser.add_argument("--out-dir", type=Path, default=REPO / "docs" / "analysis")
    args = parser.parse_args()

    sensors_all = read_sensors((args.data_dir / "secom.data").read_text())
    labels = read_labels((args.data_dir / "secom_labels.data").read_text())
    monitored = monitorable_sensors(sensors_all)
    sensors = sensors_all[monitored]
    period = assign_period(labels["timestamp"])
    summaries = {s.period: s for s in period_summaries(labels, period)}
    weekly = weekly_stability(sensors, labels)
    end = labels["timestamp"].max()

    in_base = period == BASELINE
    base_sensors, base_labels = sensors[in_base], labels[in_base]
    halves = half_split_shift(base_sensors)
    n_half = int(in_base.sum()) // 2
    chance = 0.6745 * np.sqrt(2 / n_half)
    lag1 = base_sensors.apply(lambda c: c.dropna().autocorr(1) if c.dropna().std() > 0 else np.nan)
    flat_in_base = sorted(base_sensors.columns[base_sensors.std() == 0])
    sensitive = pass_only_spread_ratio(base_sensors, base_labels)
    top_run = {name: base_sensors[name].sub(base_sensors[name].mean()).abs().idxmax() for name in sensitive.index}
    top_is_fail = {name: int(labels.loc[run, "label"] == 1) for name, run in top_run.items()}
    extremes = extreme_runs(base_sensors)
    rz = robust_z(base_sensors)
    heavy = (rz > 6).sum(axis=1)
    is_fail = base_labels["label"] == 1
    heavy_runs = int((heavy >= 5).sum())
    share_fail_heavy = (heavy[is_fail] >= 5).mean()
    share_pass_heavy = (heavy[~is_fail] >= 5).mean()

    chart_dir = args.out_dir / "baseline"
    chart_dir.mkdir(parents=True, exist_ok=True)
    chart_runs_and_fails(weekly, end, chart_dir / "runs-and-fail-rate.png")
    chart_sensor_shift(weekly, end, chart_dir / "sensor-shift.png")
    chart_missing(weekly, end, chart_dir / "missing.png")
    rng = np.random.default_rng(29)
    typical = list(rng.choice([s for s in monitored if s not in sensitive.index and s not in flat_in_base], 2, replace=False))
    sample = list(sensitive.index[:2]) + sorted(typical)
    chart_sample_sensors(sensors, labels["timestamp"], sample, end, chart_dir / "sample-sensors.png")

    b, p2 = summaries[BASELINE], summaries[PHASE2]
    ramp = summaries.get("ramp-up")
    window = {
        "story": "SECOM-29",
        "baseline_start": str(BASELINE_START.date()),
        "baseline_end_exclusive": str(PHASE2_START.date()),
        "phase2_start": str(PHASE2_START.date()),
        "runs_used": "all runs in the window (passes and fails)",
        "baseline_runs": b.runs,
        "baseline_fails": b.fails,
        "phase2_runs": p2.runs,
        "phase2_fails": p2.fails,
        "monitorable_sensors": len(monitored),
        "flat_within_baseline": flat_in_base,
        "outlier_dominated_sensors": list(sensitive.index),
        "extreme_runs": [
            {"run": int(r), "timestamp": str(labels.loc[r, "timestamp"]), "fail": bool(labels.loc[r, "label"] == 1), "sensors_beyond_10_robust_sd": int(c)}
            for r, c in extremes.head(10).items()
        ],
    }
    (args.out_dir / "baseline.json").write_text(json.dumps(window, indent=2) + "\n")

    weekly_rows = "\n".join(
        f"| {w:%d %b} | {r.runs} | {r.fails} | {r.fail_rate * 100:.1f}% | {r.share_shifted * 100:.0f}% | {r.missing_pct:.1f}% |"
        for w, r in weekly.iterrows()
    )
    sens_rows = "\n".join(
        f"| `{s}` | {v:.2f} | {top_run[s]} | {'fail' if top_is_fail[s] else 'pass'} |" for s, v in sensitive.items()
    )
    extreme_rows = "\n".join(
        f"| {r} | {labels.loc[r, 'timestamp']:%d %b %H:%M} | {'fail' if labels.loc[r, 'label'] == 1 else 'pass'} | {c} |"
        for r, c in extremes.head(10).items()
    )
    md = f"""# SPC Phase I: the baseline window (SECOM-29)

Generated by `scripts/spc_baseline.py`. Control limits (SECOM-30) are set from a **baseline** period
when the process was running normally; every run after it is **Phase II**, judged against those limits
and never used to set them.

## Decision

| | From | To | Runs | Fails | Fail rate |
|---|---|---|---|---|---|
| Ramp-up (not used) | {ramp.first:%d %b %Y} | {ramp.last:%d %b %Y} | {ramp.runs} | {ramp.fails} | {ramp.fail_rate * 100:.1f}% |
| **Baseline (Phase I)** | **{b.first:%d %b %Y}** | **{b.last:%d %b %Y}** | **{b.runs}** | **{b.fails}** | **{b.fail_rate * 100:.1f}%** |
| Phase II (monitoring) | {p2.first:%d %b %Y} | {p2.last:%d %b %Y} | {p2.runs} | {p2.fails} | {p2.fail_rate * 100:.1f}% |

- **Window: 25 Aug to 28 Sep 2008.** Before it, the line was ramping up; it ends just before an
  early-October excursion, so Phase II contains a real problem for the charts to catch.
- **All runs in the window, passes and fails** (label-blind, as in classic SPC). The alternative,
  passing runs only, is discussed below.
- Sensors: the {len(monitored)} monitorable sensors from the data profile (vary, and at most 50% missing).
  {len(flat_in_base)} of them never change inside the baseline ({", ".join(f"`{s}`" for s in flat_in_base)}),
  so they can't have control limits; SECOM-30 lists them as not charted.

The window is also written to `docs/analysis/baseline.json` for SECOM-30 to read.

## Why this window

![Runs and fail rate by week](baseline/runs-and-fail-rate.png)

**Fail rate.** July to mid-August fails at 9.5-23% a week, mostly on low volume. From the week of 25 Aug it
drops to 1.5-4% and stays there for five weeks. In the week of 29 Sep it jumps to 8.9%, with 17 fails
between 2 and 6 Oct.

![How many sensors sit away from their usual level](baseline/sensor-shift.png)

**Sensor behaviour.** For each sensor and week, the shift is how far that week's mean sits from the
sensor's whole-period mean, in standard deviations. In the first weeks, 15-29% of sensors sit more than 0.5 SD away:
the process is still settling. From 18 Aug it is 4-8% and flat through the baseline. So the sensors settle about a week before
the fail rate does; starting at 25 Aug waits for both.

![Missing values by week](baseline/missing.png)

**Missing values** stay at 0.9-2.1% a week through the baseline. They jump to 4.1% in the last
(partial) week of October, a data-collection change worth knowing about in Phase II.

![Sample sensors over time](baseline/sample-sensors.png)

Two outlier-dominated sensors (`{sample[0]}`, `{sample[1]}`) and two typical ones (`{sample[2]}`, `{sample[3]}`,
picked at random with a fixed seed), as 50-run rolling mean and rolling SD in whole-period SD units. The
square steps in the rolling SD are single extreme runs entering and leaving the 50-run window; `{sample[0]}`
and `{sample[1]}` step together because the same runs are extreme in both. `{sample[2]}` drifts about
0.7 SD below its baseline level through Phase II: a slow drift for the EWMA chart to catch (SECOM-31).

### Weekly figures

| Week of | Runs | Fails | Fail rate | Sensors shifted > 0.5 SD | Missing |
|---|---|---|---|---|---|
{weekly_rows}

## How stable is the baseline itself?

- **Slow drift inside the window.** Comparing the first and second halves of the baseline, the median
  sensor moves {halves.median():.2f} SD, and {(halves > 0.5).mean() * 100:.0f}% of sensors move more than 0.5 SD.
  A perfectly steady process would give about {chance:.2f} SD by chance. So the "stable" period still
  drifts a little. I-MR limits come from run-to-run variation, so drifting sensors will signal more
  often; SECOM-30 and SECOM-31 have to allow for it.
- **Runs are close to independent.** The median lag-1 autocorrelation across sensors is
  {lag1.median():.2f}, and only {(lag1 > 0.3).mean() * 100:.0f}% of sensors are above 0.3, so individuals (I-MR)
  charts are a reasonable choice.

## All runs, or passing runs only?

Decided: **all runs** in the window. The trade-off:

- **All runs (chosen):** classic SPC. The baseline is whatever the process did, without looking at
  test results. Points that fall outside the first limits are reviewed and removed in SECOM-30's
  Phase I clean-up instead.
- **Passing runs only:** limits describe good production. In a real fab the test result arrives after
  the run, so this would be legitimate, but it mixes the labels into SPC.

For most sensors it makes no difference: dropping the {b.fails} fails changes the median sensor's
spread by a factor of {(base_sensors[base_labels["label"] != 1].std() / base_sensors.std()).median():.3f}. For
{len(sensitive)} sensors it cuts the spread by more than 10%. On a closer look that is **not** because those
sensors are noisy on failing runs in general: in each of them one run sits 11-22 SD from the mean, and in
{sum(top_is_fail.values())} of the {len(sensitive)} that single run is a fail. Remove it and the spread drops by the
same amount whatever its label.

| Sensor | Spread with passes only / all runs | Most extreme run | That run |
|---|---|---|---|
{sens_rows}

## Extreme runs and heavy tails

The outliers are **whole-run events**, not single sensors misbehaving. Measured on a robust scale
(median and MAD, which the outliers can't drag around), these baseline runs have the most sensors beyond
10 robust SDs at once:

| Run | When | Result | Sensors beyond 10 robust SD |
|---|---|---|---|
{extreme_rows}

And the tails are heavy everywhere: {heavy_runs} of the {b.runs} baseline runs have five or more sensors beyond
6 robust SDs. SECOM sensors are far from normal, so textbook three-sigma limits will flag far more than
0.27% of runs.

What this means for the next stories:

- **SECOM-30 (control limits)** must do a proper Phase I clean-up (remove gross outliers such as the runs
  above, recompute) and decide how to set limits for heavy-tailed sensors, for example from the moving
  range (which one outlier inflates less than the SD) or from empirical percentiles.
- **SECOM-32 (do signals warn before a fail?)** has an early hint to test properly: in the baseline,
  {share_fail_heavy * 100:.0f}% of failing runs have five or more extreme sensors, against {share_pass_heavy * 100:.0f}% of passing runs.
  Not a conclusion yet: the baseline has only {b.fails} fails.

## Phase II

The {p2.runs} runs from {p2.first:%d %b} onwards ({p2.fails} fails, {p2.fail_rate * 100:.1f}%) are held out. They are
used only to test the limits, in time order (SECOM-31), with no peeking while the limits are set.
"""
    (args.out_dir / "baseline.md").write_text(md)
    print(f"Wrote {args.out_dir / 'baseline.md'}, baseline.json and 4 charts in {chart_dir}")


if __name__ == "__main__":
    main()
