"""Check a replay's output: every line must pass the stream contract.

docker run ... secom-producer > out.jsonl
python scripts/check_replay_output.py out.jsonl --expect 5
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from secom.contract import validate  # noqa: E402

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("--expect", type=int, help="exact number of records expected")
    args = parser.parse_args()
    lines = [line for line in args.path.read_bytes().splitlines() if line.strip()]
    bad = [(n, r.reason, r.detail) for n, line in enumerate(lines, 1) if not (r := validate(line)).ok]
    for n, reason, detail in bad:
        print(f"line {n}: {reason} {detail}")
    if args.expect is not None and len(lines) != args.expect:
        sys.exit(f"expected {args.expect} records, got {len(lines)}")
    if bad:
        sys.exit(f"{len(bad)} of {len(lines)} records broke the contract")
    print(f"OK: {len(lines)} records, all valid")
