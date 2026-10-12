# Replay producer

**The live stream in this project is simulated.** SECOM is a fixed, historical dataset from a real fab (1,567 runs, July to October 2008). The replay producer sends its runs one at a time, in their original order, at a set rate, as if they were coming off the line now. Everything downstream treats the stream as a real feed.

Code: `secom/producer.py` (standard library only). Container: `producer/Dockerfile`.

## What each record contains

One record per run, in the [stream record contract](record-contract.md):

- `run_id`: the run's row in the dataset
- `seq`: send order in this replay session; a gap means a record was lost
- `sent_at`: stamped when the record is produced, in UTC. This is the event time
- `original_ts`: the run's real 2008 timestamp, kept for reference
- `label` and the 590 sensor readings, with `null` for missing values

## Settings

All settings are environment variables, so the same image runs on a laptop and on ECS Fargate.

| Variable | Default | Meaning |
|---|---|---|
| `DATA_DIR` | `data/raw` (`/data` in the container) | Folder holding `secom.data` and `secom_labels.data` |
| `RATE_SECONDS` | `3` | Pause between sends. `0` sends as fast as possible |
| `START_RUN` | `0` | First run to send |
| `LOOP` | `false` | Start again from run 0 after the last run (`seq` keeps counting) |
| `MAX_RECORDS` | none | Stop after this many records |
| `SINK` | `stdout` | `stdout`, `file` (JSON Lines) or `kinesis` (arrives with the stream in Sprint 2) |
| `OUTPUT_FILE` | none | Path for `SINK=file` |
| `REPLAY_ID` | `replay-<UTC time>` | Name of this replay session |
| `CHAOS_DROP` | `0` | Probability a record is never sent |
| `CHAOS_DUPLICATE` | `0` | Probability a record is sent twice |
| `CHAOS_DELAY` | `0` | Probability a record is held back and sent late |
| `CHAOS_DELAY_BY` | `3` | How many later records overtake a delayed one |
| `CHAOS_CORRUPT` | `0` | Probability a record is broken in one of six ways |
| `CHAOS_SEED` | none | Fixes the random choices, so a chaos run can be repeated exactly |

## Chaos mode: a messy feed on purpose

A real feed loses, repeats, delays and garbles records. Chaos mode does all four, so the pipeline can be shown to cope:

| Chaos | What arrives downstream | What the pipeline must do |
|---|---|---|
| Drop | A gap in `seq` | Flag the gap; keep processing |
| Duplicate | The same record twice (same `run_id` and `seq`) | Keep one, count the other as `DUPLICATE` |
| Delay | A record after later ones, with an older `sent_at` | Accept it, flag it as late |
| Corrupt | A broken record | Reject it with the right reason code |

Each corruption maps to one contract reason code, and the tests check every one:

| Corruption | Reason code |
|---|---|
| Truncated JSON | `MALFORMED_JSON` |
| Field removed | `MISSING_FIELD` |
| Label set to 0 | `BAD_LABEL` |
| One sensor reading short | `WRONG_SENSOR_COUNT` |
| A reading replaced by text | `NON_NUMERIC_VALUE` |
| `sent_at` replaced by text | `BAD_TIMESTAMP` |

## Ground truth for reconciliation

When it finishes, the producer prints one line to stderr saying exactly what it did:

```
REPLAY_SUMMARY {"corrupted": {"bad_label": [73, 125, 150], ...}, "delayed": [37, 43, ...], "dropped": [3, 23, ...], "duplicated": [5, 32, ...], "intended": 200, "replay_id": "...", "sent": 202}
```

Once the processor is built, its counts (rejects by reason, gaps, duplicates, late records) are checked against this line. If the two disagree, the pipeline has a bug.

## Run it locally

You need the dataset in `data/raw/` first (`python scripts/profile_secom.py` downloads it).

```bash
# Ten clean records, no pause, printed to the screen
RATE_SECONDS=0 MAX_RECORDS=10 python -m secom.producer

# A whole replay with chaos, written to a file, then checked against the contract
RATE_SECONDS=0 SINK=file OUTPUT_FILE=out/replay.jsonl \
  CHAOS_SEED=1 CHAOS_DROP=0.02 CHAOS_DUPLICATE=0.02 CHAOS_DELAY=0.02 CHAOS_CORRUPT=0.02 \
  python -m secom.producer
python scripts/check_replay_output.py out/replay.jsonl
```

With chaos on, the check reports the corrupted lines; that is expected.

## Run it in a container

```bash
docker build -f producer/Dockerfile -t secom-producer .
docker run --rm -v "$PWD/data/raw:/data:ro" -e RATE_SECONDS=1 -e MAX_RECORDS=5 secom-producer
```

The image runs as an unprivileged user and contains only the producer code, no third-party packages and no data. CI builds it on every pull request and runs it against a small fake dataset (`scripts/fake_secom.py`), checking every record against the contract.
