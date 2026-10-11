"""Data-quality profile of the SECOM dataset (SECOM-14).

Pure functions here; scripts/profile_secom.py does the downloading, chart
drawing and file writing. Keeping the logic pure means it can be unit-tested
on tiny hand-made tables with no network and no real data.

SECOM layout (UCI Machine Learning Repository):
  secom.data         one production run per line, 590 space-separated sensor
                     values, missing values written as "NaN"
  secom_labels.data  one line per run: label (-1 = pass, 1 = fail) and a
                     quoted timestamp "dd/mm/yyyy hh:mm:ss"
"""

from __future__ import annotations

import io
from dataclasses import dataclass

import pandas as pd

PASS, FAIL = -1, 1

# Missing-value bands: (label, lower bound exclusive, upper bound inclusive).
MISSING_BANDS = [
    ("under 5%", 0.0, 0.05),
    ("5-20%", 0.05, 0.20),
    ("20-50%", 0.20, 0.50),
    ("over 50%", 0.50, 1.0),
]


def read_sensors(text: str) -> pd.DataFrame:
    """Parse secom.data: whitespace-separated floats, 'NaN' for missing."""
    frame = pd.read_csv(io.StringIO(text), sep=r"\s+", header=None, na_values=["NaN"], engine="python")
    frame.columns = [f"s{i:03d}" for i in range(frame.shape[1])]
    frame.index.name = "run"
    return frame


def read_labels(text: str) -> pd.DataFrame:
    """Parse secom_labels.data into columns: label (int), timestamp (datetime)."""
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        label, _, stamp = line.partition(" ")
        rows.append((int(label), stamp.strip().strip('"')))
    labels = pd.DataFrame(rows, columns=["label", "timestamp"])
    labels["timestamp"] = pd.to_datetime(labels["timestamp"], format="%d/%m/%Y %H:%M:%S")
    labels.index.name = "run"
    return labels


@dataclass
class MissingSummary:
    cells_total: int
    cells_missing: int
    runs_with_any_missing: int
    sensors_by_band: dict[str, int]
    worst_sensors: list[tuple[str, float]]

    @property
    def missing_share(self) -> float:
        return self.cells_missing / self.cells_total if self.cells_total else 0.0


def missing_summary(sensors: pd.DataFrame, worst_n: int = 10) -> MissingSummary:
    share = sensors.isna().mean()
    bands = {"none": int((share == 0).sum())}
    for name, low, high in MISSING_BANDS:
        bands[name] = int(((share > low) & (share <= high)).sum())
    worst = share.sort_values(ascending=False).head(worst_n)
    return MissingSummary(
        cells_total=int(sensors.size),
        cells_missing=int(sensors.isna().sum().sum()),
        runs_with_any_missing=int(sensors.isna().any(axis=1).sum()),
        sensors_by_band=bands,
        worst_sensors=[(str(k), float(v)) for k, v in worst.items() if v > 0],
    )


def constant_sensors(sensors: pd.DataFrame) -> list[str]:
    """Sensors that never change: at most one distinct value once missing values are ignored.

    A sensor that is entirely missing also counts: it carries no information.
    """
    return [col for col in sensors.columns if sensors[col].nunique(dropna=True) <= 1]


def near_constant_sensors(sensors: pd.DataFrame, min_share: float = 0.95) -> list[str]:
    """Non-constant sensors where one value covers at least min_share of the readings present."""
    result = []
    for col in sensors.columns:
        present = sensors[col].dropna()
        if present.nunique() <= 1 or present.empty:
            continue
        if present.value_counts(normalize=True).iloc[0] >= min_share:
            result.append(col)
    return result


@dataclass
class ClassBalance:
    passes: int
    fails: int

    @property
    def total(self) -> int:
        return self.passes + self.fails

    @property
    def fail_rate(self) -> float:
        return self.fails / self.total if self.total else 0.0

    @property
    def ratio(self) -> float:
        """Passes per fail, e.g. 14.1 means about 14 passes for every fail."""
        return self.passes / self.fails if self.fails else float("inf")


def class_balance(labels: pd.DataFrame) -> ClassBalance:
    counts = labels["label"].value_counts()
    unexpected = set(counts.index) - {PASS, FAIL}
    if unexpected:
        raise ValueError(f"Unexpected label values: {sorted(unexpected)}")
    return ClassBalance(passes=int(counts.get(PASS, 0)), fails=int(counts.get(FAIL, 0)))


@dataclass
class TimeSummary:
    first: pd.Timestamp
    last: pd.Timestamp
    out_of_order: int
    duplicate_timestamps: int
    median_gap: pd.Timedelta
    longest_gap: pd.Timedelta
    longest_gap_after_run: int
    days_with_runs: int


def time_summary(labels: pd.DataFrame) -> TimeSummary:
    """How the runs are spread in time, in file order (the order the replay will send them)."""
    ts = labels["timestamp"].reset_index(drop=True)
    steps = ts.diff().iloc[1:]
    positive = steps[steps > pd.Timedelta(0)]
    longest_at = int(steps.idxmax()) - 1 if not steps.empty else 0
    return TimeSummary(
        first=ts.min(),
        last=ts.max(),
        out_of_order=int((steps < pd.Timedelta(0)).sum()),
        duplicate_timestamps=int(ts.duplicated().sum()),
        median_gap=positive.median() if not positive.empty else pd.Timedelta(0),
        longest_gap=steps.max() if not steps.empty else pd.Timedelta(0),
        longest_gap_after_run=longest_at,
        days_with_runs=int(ts.dt.normalize().nunique()),
    )


def weekly_fail_rate(labels: pd.DataFrame) -> pd.DataFrame:
    """Runs and fail rate per calendar week, for the trend chart."""
    weekly = labels.set_index("timestamp").resample("W")["label"]
    out = pd.DataFrame({"runs": weekly.size(), "fails": weekly.apply(lambda s: int((s == FAIL).sum()))})
    out = out[out["runs"] > 0]
    out["fail_rate"] = out["fails"] / out["runs"]
    return out


def monitorable_sensors(sensors: pd.DataFrame, max_missing: float = 0.5) -> list[str]:
    """First cut of sensors worth an SPC chart: they vary, and at most max_missing of readings are missing.

    This is a proposal for the baseline rule; the final rule is decided in the health-signals epic.
    """
    share = sensors.isna().mean()
    excluded = set(constant_sensors(sensors)) | set(share[share > max_missing].index)
    return [c for c in sensors.columns if c not in excluded]
