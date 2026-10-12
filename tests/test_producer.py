"""Tests for the replay producer. Small synthetic data, a fixed clock and no sleeping."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scripts.fake_secom import fake_texts
from secom.contract import SENSOR_COUNT, validate
from secom.producer import (
    CORRUPTIONS,
    EXPECTED_REASON,
    Config,
    FileSink,
    KinesisSink,
    Summary,
    corrupt,
    make_record,
    parse_runs,
    replay,
    run,
)


@pytest.fixture
def runs():
    return parse_runs(*fake_texts(40))


class FixedClock:
    """Returns a time that moves forward one second per call, so sent_at values are distinct and ordered."""

    def __init__(self):
        self.now = datetime(2026, 10, 12, 10, 0, 0, tzinfo=UTC)

    def __call__(self):
        self.now += timedelta(seconds=1)
        return self.now


def play(runs, **settings):
    config = Config(rate_seconds=0, replay_id="test-replay", **settings)
    summary = Summary()
    items = list(replay(runs, config, summary, clock=FixedClock()))
    return items, summary


def decoded(items):
    return [json.loads(i.payload) for i in items]


def test_parse_runs_reads_nan_as_none_and_dates_day_first(runs):
    assert len(runs) == 40
    assert runs[0].run_id == 0
    assert runs[0].sensors[3] is None
    assert len(runs[0].sensors) == SENSOR_COUNT
    assert runs[0].label == 1
    assert runs[0].original_ts == datetime(2008, 7, 19, 0, 0)


def test_parse_runs_refuses_mismatched_files():
    sensors, labels = fake_texts(3)
    with pytest.raises(ValueError, match="3 sensor rows but 2 label rows"):
        parse_runs(sensors, "\n".join(labels.splitlines()[:2]))


def test_clean_replay_sends_every_run_in_order_and_all_valid(runs):
    items, summary = play(runs)
    records = decoded(items)
    assert [r["run_id"] for r in records] == list(range(40))
    assert [r["seq"] for r in records] == list(range(40))
    assert all(validate(i.payload).ok for i in items)
    assert summary.intended == 40
    assert summary.dropped == summary.duplicated == summary.delayed == []
    sent_times = [r["sent_at"] for r in records]
    assert sent_times == sorted(sent_times)


def test_start_run_and_max_records(runs):
    items, summary = play(runs, start_run=10, max_records=5)
    assert [r["run_id"] for r in decoded(items)] == [10, 11, 12, 13, 14]
    assert summary.intended == 5


def test_loop_wraps_to_the_first_run(runs):
    items, _ = play(runs, start_run=38, loop=True, max_records=5)
    assert [r["run_id"] for r in decoded(items)] == [38, 39, 0, 1, 2]
    assert [r["seq"] for r in decoded(items)] == [0, 1, 2, 3, 4]  # seq keeps counting across the wrap


def test_drop_leaves_gaps_in_seq(runs):
    items, summary = play(runs, chaos_drop=0.3, chaos_seed=1)
    seqs = {r["seq"] for r in decoded(items)}
    assert summary.dropped, "seed should drop something"
    assert seqs.isdisjoint(summary.dropped)
    assert seqs | set(summary.dropped) == set(range(40))


def test_duplicates_repeat_the_same_payload(runs):
    items, summary = play(runs, chaos_duplicate=0.3, chaos_seed=2)
    assert summary.duplicated
    for seq in summary.duplicated:
        copies = [i for i in items if i.seq == seq]
        assert len(copies) == 2
        assert copies[0].payload == copies[1].payload
    assert len(items) == 40 + len(summary.duplicated)


def test_delayed_records_arrive_late_with_older_sent_at(runs):
    items, summary = play(runs, chaos_delay=0.2, chaos_delay_by=3, chaos_seed=3)
    assert summary.delayed
    order = [i.seq for i in items]
    assert sorted(order) == list(range(40))  # nothing lost
    records = decoded(items)
    delayed = set(summary.delayed)
    for seq in summary.delayed:
        if all(later in delayed for later in range(seq + 1, 40)):
            continue  # at the very end, with every later record also held, nothing can overtake it
        position = order.index(seq)
        assert any(s > seq for s in order[:position]), f"seq {seq} was not overtaken"
        # Its sent_at is older than the record sent just before it: genuinely late.
        assert records[position]["sent_at"] < records[position - 1]["sent_at"]


@pytest.mark.parametrize("kind", CORRUPTIONS)
def test_each_corruption_is_rejected_with_its_reason(kind, runs):
    record = make_record(
        replay_id="r",
        seq=0,
        run_id=0,
        original_ts=runs[0].original_ts,
        label=runs[0].label,
        sensors=runs[0].sensors,
    )
    result = validate(corrupt(record, kind))
    assert not result.ok
    assert result.reason.value == EXPECTED_REASON[kind]


def test_corrupt_mode_matches_summary(runs):
    items, summary = play(runs, chaos_corrupt=0.4, chaos_seed=4)
    corrupted_seqs = {s for seqs in summary.corrupted.values() for s in seqs}
    assert corrupted_seqs
    for item in items:
        assert validate(item.payload).ok == (item.seq not in corrupted_seqs)


def test_same_seed_gives_same_replay(runs):
    settings = {"chaos_drop": 0.1, "chaos_duplicate": 0.1, "chaos_delay": 0.1, "chaos_corrupt": 0.1}
    first, s1 = play(runs, chaos_seed=42, **settings)
    second, s2 = play(runs, chaos_seed=42, **settings)
    assert [i.payload for i in first] == [i.payload for i in second]
    assert s1 == s2


def test_config_from_env_reads_and_checks_settings():
    config = Config.from_env(
        {"RATE_SECONDS": "0.5", "START_RUN": "7", "LOOP": "true", "CHAOS_DROP": "0.05", "CHAOS_SEED": "9"}
    )
    assert (config.rate_seconds, config.start_run, config.loop, config.chaos_drop, config.chaos_seed) == (
        0.5,
        7,
        True,
        0.05,
        9,
    )
    with pytest.raises(ValueError, match="CHAOS_DROP"):
        Config.from_env({"CHAOS_DROP": "1.5"})
    with pytest.raises(ValueError, match="OUTPUT_FILE"):
        Config.from_env({"SINK": "file"})
    with pytest.raises(ValueError, match="SINK"):
        Config.from_env({"SINK": "carrier-pigeon"})


def test_kinesis_sink_is_a_clear_placeholder():
    with pytest.raises(NotImplementedError, match="Sprint 2"):
        KinesisSink()


def test_run_writes_json_lines_and_paces_sends(tmp_path: Path):
    sensors, labels = fake_texts(6)
    (tmp_path / "secom.data").write_text(sensors)
    (tmp_path / "secom_labels.data").write_text(labels)
    out = tmp_path / "out" / "replay.jsonl"
    config = Config(data_dir=tmp_path, rate_seconds=2.0, sink="file", output_file=out, replay_id="t")
    pauses = []
    summary = run(config, FileSink(out), sleep=pauses.append)
    lines = out.read_bytes().splitlines()
    assert len(lines) == 6 == summary.sent
    assert all(validate(line).ok for line in lines)
    assert pauses == [2.0] * 5  # a pause between sends, not before the first
