"""Replay producer (SECOM-15).

SECOM is a fixed historical dataset. This producer replays its runs in order,
one record per run, at a set rate, as if they were coming off the line now.
Every record follows the stream contract (secom/contract.py).

A real feed is messy, so an optional, seeded "chaos mode" makes this one messy
on purpose, to prove the pipeline downstream copes:

    drop       a record is never sent       -> a gap in seq
    duplicate  a record is sent twice       -> same run_id and seq twice
    delay      a record is held back        -> arrives after later records, with an older sent_at
    corrupt    a record is broken           -> must be rejected with a specific reason code

At the end it prints a summary of exactly what it did, so the pipeline's
counts (rejects by reason, gaps, duplicates, late records) can be checked
against the truth.

Configuration is by environment variable (see Config.from_env) so the same
container image runs locally and on ECS Fargate.

Uses only the standard library, to keep the container image small.
"""

from __future__ import annotations

import json
import os
import random
import sys
import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from secom.contract import encode, make_record

CORRUPTIONS = (
    "malformed_json",
    "missing_field",
    "bad_label",
    "wrong_sensor_count",
    "text_reading",
    "bad_timestamp",
)

# The reason code the contract must give for each kind of corruption.
EXPECTED_REASON = {
    "malformed_json": "MALFORMED_JSON",
    "missing_field": "MISSING_FIELD",
    "bad_label": "BAD_LABEL",
    "wrong_sensor_count": "WRONG_SENSOR_COUNT",
    "text_reading": "NON_NUMERIC_VALUE",
    "bad_timestamp": "BAD_TIMESTAMP",
}


@dataclass(frozen=True)
class Run:
    run_id: int
    original_ts: datetime
    label: int
    sensors: list[float | None]


def parse_runs(sensor_text: str, label_text: str) -> list[Run]:
    """Read secom.data and secom_labels.data into runs, in file order."""
    sensor_lines = [line for line in sensor_text.splitlines() if line.strip()]
    label_lines = [line for line in label_text.splitlines() if line.strip()]
    if len(sensor_lines) != len(label_lines):
        raise ValueError(f"{len(sensor_lines)} sensor rows but {len(label_lines)} label rows")
    runs = []
    for run_id, (values, label_line) in enumerate(zip(sensor_lines, label_lines, strict=True)):
        sensors = [None if v == "NaN" else float(v) for v in values.split()]
        label, _, stamp = label_line.strip().partition(" ")
        runs.append(
            Run(
                run_id=run_id,
                original_ts=datetime.strptime(stamp.strip().strip('"'), "%d/%m/%Y %H:%M:%S"),
                label=int(label),
                sensors=sensors,
            )
        )
    return runs


def load_runs(data_dir: Path) -> list[Run]:
    return parse_runs((data_dir / "secom.data").read_text(), (data_dir / "secom_labels.data").read_text())


@dataclass
class Config:
    data_dir: Path = Path("data/raw")
    rate_seconds: float = 3.0
    start_run: int = 0
    loop: bool = False
    max_records: int | None = None
    sink: str = "stdout"
    output_file: Path | None = None
    replay_id: str | None = None
    chaos_drop: float = 0.0
    chaos_duplicate: float = 0.0
    chaos_delay: float = 0.0
    chaos_delay_by: int = 3
    chaos_corrupt: float = 0.0
    chaos_seed: int | None = None

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Config:
        env = dict(os.environ if env is None else env)

        def num(name: str, default: float) -> float:
            return float(env[name]) if env.get(name, "") != "" else default

        max_records = env.get("MAX_RECORDS", "")
        seed = env.get("CHAOS_SEED", "")
        output = env.get("OUTPUT_FILE", "")
        config = cls(
            data_dir=Path(env.get("DATA_DIR", "data/raw")),
            rate_seconds=num("RATE_SECONDS", 3.0),
            start_run=int(num("START_RUN", 0)),
            loop=env.get("LOOP", "false").lower() in ("1", "true", "yes"),
            max_records=int(max_records) if max_records else None,
            sink=env.get("SINK", "stdout"),
            output_file=Path(output) if output else None,
            replay_id=env.get("REPLAY_ID") or None,
            chaos_drop=num("CHAOS_DROP", 0.0),
            chaos_duplicate=num("CHAOS_DUPLICATE", 0.0),
            chaos_delay=num("CHAOS_DELAY", 0.0),
            chaos_delay_by=int(num("CHAOS_DELAY_BY", 3)),
            chaos_corrupt=num("CHAOS_CORRUPT", 0.0),
            chaos_seed=int(seed) if seed else None,
        )
        config.check()
        return config

    def check(self) -> None:
        for name in ("chaos_drop", "chaos_duplicate", "chaos_delay", "chaos_corrupt"):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name.upper()} must be between 0 and 1, got {value}")
        if self.rate_seconds < 0:
            raise ValueError("RATE_SECONDS must not be negative")
        if self.chaos_delay_by < 1:
            raise ValueError("CHAOS_DELAY_BY must be at least 1")
        if self.sink not in ("stdout", "file", "kinesis"):
            raise ValueError(f"SINK must be stdout, file or kinesis, got {self.sink!r}")
        if self.sink == "file" and self.output_file is None:
            raise ValueError("SINK=file needs OUTPUT_FILE")


@dataclass
class Summary:
    """Ground truth of what the producer did, to reconcile against the pipeline's own counts."""

    replay_id: str = ""
    intended: int = 0  # records the replay meant to send (one per seq number)
    sent: int = 0  # payloads actually sent, including duplicates and corrupted ones
    dropped: list[int] = field(default_factory=list)  # seq numbers never sent
    duplicated: list[int] = field(default_factory=list)  # seq numbers sent twice
    delayed: list[int] = field(default_factory=list)  # seq numbers sent late
    corrupted: dict[str, list[int]] = field(default_factory=dict)  # corruption kind -> seq numbers

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)


@dataclass(frozen=True)
class Outgoing:
    seq: int
    run_id: int
    payload: bytes


def corrupt(record: dict, kind: str) -> bytes:
    """Break a record in one specific way. Each kind maps to one contract reason code."""
    broken = json.loads(json.dumps(record))
    if kind == "malformed_json":
        return encode(record)[:-25]  # truncated mid-record
    if kind == "missing_field":
        del broken["label"]
    elif kind == "bad_label":
        broken["label"] = 0
    elif kind == "wrong_sensor_count":
        broken["sensors"] = broken["sensors"][:-1]
    elif kind == "text_reading":
        broken["sensors"][0] = "n/a"
    elif kind == "bad_timestamp":
        broken["sent_at"] = "yesterday"
    else:
        raise ValueError(f"unknown corruption {kind!r}")
    return json.dumps(broken).encode("utf-8")


def default_replay_id(now: datetime | None = None) -> str:
    stamp = (now or datetime.now(UTC)).strftime("%Y-%m-%dT%H-%M-%SZ")
    return f"replay-{stamp}"


def replay(
    runs: list[Run],
    config: Config,
    summary: Summary,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> Iterator[Outgoing]:
    """Yield payloads in the order they should be sent. Pure apart from the clock: no I/O, no sleeping."""
    # Chaos sampling must be repeatable from a seed; nothing here is a secret, so no crypto RNG needed.
    rng = random.Random(config.chaos_seed)  # noqa: S311
    summary.replay_id = config.replay_id or default_replay_id(clock())
    held: list[tuple[int, Outgoing]] = []  # (release after this many more sends, record)

    def order() -> Iterable[Run]:
        selected = runs[config.start_run :]
        while True:
            yield from selected
            if not config.loop:
                return
            selected = runs

    def release_due() -> Iterator[Outgoing]:
        nonlocal held
        still_held = []
        for wait, item in held:
            if wait <= 0:
                yield item
            else:
                still_held.append((wait - 1, item))
        held = still_held

    seq = -1
    for run in order():
        if config.max_records is not None and summary.intended >= config.max_records:
            break
        seq += 1
        summary.intended += 1

        if rng.random() < config.chaos_drop:
            summary.dropped.append(seq)
            continue

        record = make_record(
            replay_id=summary.replay_id,
            seq=seq,
            run_id=run.run_id,
            original_ts=run.original_ts,
            label=run.label,
            sensors=run.sensors,
            sent_at=clock(),
        )
        payload = encode(record)
        if rng.random() < config.chaos_corrupt:
            kind = rng.choice(CORRUPTIONS)
            payload = corrupt(record, kind)
            summary.corrupted.setdefault(kind, []).append(seq)
        item = Outgoing(seq=seq, run_id=run.run_id, payload=payload)

        if rng.random() < config.chaos_delay:
            # sent_at is already stamped, so when this arrives later it is genuinely late.
            held.append((config.chaos_delay_by, item))
            summary.delayed.append(seq)
        else:
            yield item
            if rng.random() < config.chaos_duplicate:
                summary.duplicated.append(seq)
                yield item
        yield from release_due()

    for _, item in held:  # anything still held goes out at the end
        yield item


class Sink(Protocol):
    def send(self, item: Outgoing) -> None: ...

    def close(self) -> None: ...


class StdoutSink:
    def send(self, item: Outgoing) -> None:
        sys.stdout.write(item.payload.decode("utf-8", errors="replace") + "\n")
        sys.stdout.flush()

    def close(self) -> None:
        pass


class FileSink:
    """JSON Lines: one payload per line, exactly as it would go onto the stream."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._file = path.open("wb")

    def send(self, item: Outgoing) -> None:
        self._file.write(item.payload + b"\n")

    def close(self) -> None:
        self._file.close()


class KinesisSink:
    """Placeholder until the Kinesis stream exists (Sprint 2). Same interface as the other sinks."""

    def __init__(self) -> None:
        raise NotImplementedError(
            "The Kinesis sink arrives with the stream in Sprint 2; use SINK=stdout or file."
        )

    def send(self, item: Outgoing) -> None:  # pragma: no cover
        raise NotImplementedError

    def close(self) -> None:  # pragma: no cover
        pass


def make_sink(config: Config) -> Sink:
    if config.sink == "file":
        return FileSink(config.output_file)
    if config.sink == "kinesis":
        return KinesisSink()
    return StdoutSink()


def run(config: Config, sink: Sink, sleep: Callable[[float], None] = time.sleep) -> Summary:
    runs = load_runs(config.data_dir)
    if not 0 <= config.start_run < len(runs):
        raise ValueError(f"START_RUN must be between 0 and {len(runs) - 1}")
    summary = Summary()
    try:
        for index, item in enumerate(replay(runs, config, summary)):
            if index and config.rate_seconds:
                sleep(config.rate_seconds)
            sink.send(item)
            summary.sent += 1
    finally:
        sink.close()
    return summary


def main() -> None:
    config = Config.from_env()
    summary = run(config, make_sink(config))
    print(f"REPLAY_SUMMARY {summary.to_json()}", file=sys.stderr)


if __name__ == "__main__":
    main()
