"""Write a small fake SECOM dataset (same file formats, made-up numbers) for tests and CI smoke runs.

    python scripts/fake_secom.py --runs 5 --out /tmp/fake-secom

It is NOT the real data: values are synthetic, sensor 3 is always missing,
and every fifth run is a fail.
"""

from __future__ import annotations

import argparse
from pathlib import Path

SENSOR_COUNT = 590


def fake_texts(runs: int) -> tuple[str, str]:
    sensor_lines, label_lines = [], []
    for i in range(runs):
        values = ["NaN" if j == 3 else f"{i + j / 10:.4f}" for j in range(SENSOR_COUNT)]
        sensor_lines.append(" ".join(values))
        label = 1 if i % 5 == 0 else -1
        label_lines.append(f'{label} "19/07/2008 {i % 24:02d}:{i % 60:02d}:00"')
    return "\n".join(sensor_lines) + "\n", "\n".join(label_lines) + "\n"


def write(folder: Path, runs: int) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    sensors, labels = fake_texts(runs)
    (folder / "secom.data").write_text(sensors)
    (folder / "secom_labels.data").write_text(labels)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    write(args.out, args.runs)
    print(f"Wrote {args.runs} fake runs to {args.out}")
