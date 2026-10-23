# Running costs

Region: eu-west-1. Prices come from the AWS Price List API via `scripts/price_check.py` (read-only), cross-checked in the [AWS Pricing Calculator](https://calculator.aws/); update this table whenever a service is added or prices change.

## How each service is billed

| Service | Stack | How it bills | Demo-mode exposure |
|---|---|---|---|
| S3 (state bucket) | Bootstrap | Per GB stored and per request | Negligible: a few KB of state |
| IAM, GitHub OIDC provider | Bootstrap | Free | None |
| AWS Budgets | Bootstrap | Free for the first budgets in an account, then a small daily fee per budget | Check how many budgets the account already has |
| ECR | Bootstrap | Per GB-month of images stored | Small: a lifecycle policy keeps only recent images |
| VPC, 2 subnets, internet gateway, route table, security groups | Runtime | Free | None. Deliberately no NAT gateway |
| S3 gateway endpoint | Runtime | Free (gateway endpoints have no hourly or data charge) | None |
| Kinesis Data Streams (1 provisioned shard) | Runtime | Per shard-hour, plus PUT payload units | Only while the runtime stack exists |
| ECS Fargate (producer, 0.25 vCPU / 0.5 GB) | Runtime | Per vCPU-hour and GB-hour while the task runs | Only while running |
| Public IPv4 address (producer task) | Runtime | Per hour while the address is in use | Only while the producer runs. Cheaper than a NAT gateway |
| Lambda (processor) | Runtime | Per request and per GB-second | Negligible at a few records per second |
| RDS PostgreSQL (db.t4g.micro) | Runtime | Per instance-hour, plus GB-month of storage | Only while the runtime stack exists |
| CloudWatch Logs and alarms | Runtime | Per GB ingested and per alarm-month | Small; log retention is set short |

**Deliberately avoided:** NAT gateway (billed per hour even when idle), interface VPC endpoints for Kinesis, and KMS customer-managed keys.

## Unit prices (eu-west-1, on-demand, checked 11 Oct 2026)

From `python3 scripts/price_check.py` (AWS Price List API).

| Item | Price (USD) |
|---|---|
| Kinesis provisioned shard | 0.017 per shard-hour |
| Kinesis PUT payload units | 0.0165 per million (25 KB units) |
| Fargate vCPU | 0.04048 per vCPU-hour |
| Fargate memory | 0.004445 per GB-hour |
| RDS db.t4g.micro, PostgreSQL, Single-AZ | 0.017 per instance-hour |
| RDS gp3 storage, PostgreSQL | 0.127 per GB-month |
| Public IPv4 address in use | 0.005 per hour |
| S3 Standard storage | 0.023 per GB-month |
| ECR storage | 0.10 per GB-month |
| Lambda compute (x86) | 0.0000167 per GB-second (first tier) |
| Lambda requests | 0.20 per million |
| CloudWatch Logs ingestion | 0.57 per GB |

## Monthly estimates

Assumptions: 730 hours in a month; producer task 0.25 vCPU / 0.5 GB; RDS with 20 GB of gp3 storage; one SECOM run sent every 3 seconds (about 0.9 million records a month, each under 25 KB); Lambda at 512 MB for about 0.2 s per batch; about 1 GB of logs a month.

| Scenario | Monthly estimate (USD) | How it adds up |
|---|---|---|
| Bootstrap only (between demos) | **under $1** | State bucket a few KB (under $0.01), ECR images about 1 GB ($0.10). IAM and OIDC free. The budget itself may add a small daily fee if the account has more budgets than the free allowance. |
| Runtime stack running 24/7 for a whole month | **about $42** | RDS instance $12.41, Kinesis shard $12.41, Fargate $9.01, public IPv4 $3.65, RDS storage $2.54, Lambda up to $1.50, logs $0.57, Kinesis PUTs $0.01 |
| Typical demo month (bootstrap + about 20 hours of runtime) | **about $2** | Runtime costs about $0.05 an hour while it exists (Kinesis $0.017 + RDS $0.017 + Fargate $0.012 + IPv4 $0.005), so 20 hours is about $1.03, plus prorated storage and the bootstrap stack |

**What this shows:** left running all month, the runtime stack would cost about twice the $20 budget. Destroyed between demos, a month of regular demos costs about $2. That is why demo mode, the budget alerts and the documented teardown exist.
