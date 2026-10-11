"""End-to-end test of scripts/profile_secom.py on a small fake dataset (no download)."""

import random
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def make_fake_secom(folder: Path, runs: int = 60, columns: int = 12) -> None:
    rng = random.Random(7)
    sensor_lines, label_lines = [], []
    for run in range(runs):
        values = []
        for col in range(columns):
            if col == 0:
                values.append("1.0")  # constant sensor
            elif col == 1 and run % 3:
                values.append("NaN")  # mostly-missing sensor
            else:
                values.append(f"{rng.gauss(10, 2):.4f}")
        sensor_lines.append(" ".join(values))
        label = 1 if run % 15 == 0 else -1
        day = 19 + run // 20
        label_lines.append(f'{label} "{day:02d}/07/2008 {run % 20:02d}:30:00"')
    (folder / "secom.data").write_text("\n".join(sensor_lines) + "\n")
    (folder / "secom_labels.data").write_text("\n".join(label_lines) + "\n")


def test_script_writes_report_and_charts(tmp_path):
    data = tmp_path / "raw"
    data.mkdir()
    make_fake_secom(data)
    out = tmp_path / "docs" / "data-profile.md"
    out.parent.mkdir()
    subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts" / "profile_secom.py"),
            "--data-dir",
            str(data),
            "--out",
            str(out),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    report = out.read_text()
    assert "| Production runs (rows) | 60 |" in report
    assert "| Sensor measurements per run (columns) | 12 |" in report
    assert "| Constant (one value, or no values, across all runs) | 1 |" in report
    assert "## What this means for the pipeline" in report
    for chart in ("missing-per-sensor.png", "missing-map.png", "weekly-fail-rate.png"):
        assert (out.parent / "data-profile" / chart).stat().st_size > 1000
