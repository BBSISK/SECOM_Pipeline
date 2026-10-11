# SECOM Semiconductor Pipeline

A streaming data pipeline on AWS that watches a semiconductor fab's sensor data for a process drifting toward failure, using statistical process control (SPC).

It replays the real **SECOM** dataset (590 sensor measurements across 1,567 production runs from a wafer fab, each labelled pass or fail) as a simulated live stream. The pipeline validates and cleans each run, stores raw and cleaned data, computes SPC control limits, drift flags and a fail-risk indicator per run, and feeds a dashboard.

**The live stream is simulated.** SECOM is a fixed historical dataset. A replay producer publishes its runs in order, at a configurable rate, as if they were arriving off the line. Everything downstream treats it as a real feed.

> This README is updated every sprint. The status table below says plainly what is built and what is still planned.

## Why

I spent 30 years at Intel in high-volume semiconductor manufacturing (SPC, FMEA, engineering team leadership). This project rebuilds that way of thinking about yield and process control as a modern cloud data product.

## Status

| Component | Status |
|---|---|
| Repo, branch and pull-request workflow | In progress (Sprint 1) |
| Terraform with remote state in S3 (native locking) | In progress (Sprint 1) |
| Keyless CI authentication (GitHub OIDC → IAM) | Planned (Sprint 1) |
| AWS Budget and alerts, documented teardown | Planned (Sprint 1) |
| CI checks required before merge | Planned (Sprint 1) |
| Replay producer | Planned (Sprint 1) |
| Stream ingest, validation, storage, health signals, dashboard | Planned |

Nothing is running in production yet.

## Planned architecture

Replay producer (ECS Fargate) → Kinesis Data Streams → processor (Lambda, container image) → S3 raw zone and RDS PostgreSQL cleaned layer → SPC health signals → dashboard. All infrastructure in Terraform, region eu-west-1. A full diagram and service table arrive with README v1.

## Infrastructure

- **Terraform** for all infrastructure, with state in a versioned, encrypted, private S3 bucket and S3 native locking from the first apply. See [docs/bootstrap.md](docs/bootstrap.md).
- Two stacks: a long-lived **bootstrap** stack, and a **runtime** stack that is created for demos and destroyed afterwards to keep costs low.

## Way of working

Jira Scrum (two-week sprints), one branch and pull request per story, protected `main`. See [docs/workflow.md](docs/workflow.md).

## Data

SECOM dataset (McCann & Johnston, 2008), UCI Machine Learning Repository. Full citation and licence are added after the data-profiling spike (SECOM-14).

## Authorship

Designed, built and operated by Barry Sisk with AI assistance (Claude).

## Licence

MIT. See [LICENSE](LICENSE).
