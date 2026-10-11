"""Look up current on-demand AWS prices for this project's services in eu-west-1.

Uses the AWS Price List API through the AWS CLI (read-only, free to call).
Run from the repo root:

    aws login --profile barry
    python3 scripts/price_check.py --profile barry

It prints one line per price. The numbers feed the table in docs/costs.md.
"""

import argparse
import json
import subprocess

REGION = "eu-west-1"

# (label, service code, extra TERM_MATCH filters, usagetype without its region prefix)
QUERIES = [
    ("Kinesis shard-hour", "AmazonKinesis", {}, "Storage-ShardHour"),
    ("Kinesis PUT payload units", "AmazonKinesis", {}, "PutRequestPayloadUnits"),
    ("Fargate vCPU-hour (Linux/x86)", "AmazonECS", {}, "Fargate-vCPU-Hours:perCPU"),
    ("Fargate GB-hour (Linux/x86)", "AmazonECS", {}, "Fargate-GB-Hours"),
    (
        "RDS db.t4g.micro PostgreSQL Single-AZ",
        "AmazonRDS",
        {"instanceType": "db.t4g.micro", "databaseEngine": "PostgreSQL", "deploymentOption": "Single-AZ"},
        "InstanceUsage:db.t4g.micro",
    ),
    (
        "RDS gp3 storage GB-month (PostgreSQL, Single-AZ)",
        "AmazonRDS",
        {
            "volumeType": "General Purpose-GP3",
            "databaseEngine": "PostgreSQL",
            "deploymentOption": "Single-AZ",
        },
        "RDS:GP3-Storage",
    ),
    ("Public IPv4 address (in use)", "AmazonVPC", {}, "PublicIPv4:InUseAddress"),
    ("S3 Standard storage GB-month", "AmazonS3", {"storageClass": "General Purpose"}, "TimedStorage-ByteHrs"),
    ("ECR storage GB-month", "AmazonECR", {}, "TimedStorage-ByteHrs"),
    ("Lambda GB-second (x86)", "AWSLambda", {}, "Lambda-GB-Second"),
    ("Lambda requests", "AWSLambda", {}, "Request"),
    ("CloudWatch Logs ingestion GB", "AmazonCloudWatch", {}, "DataProcessing-Bytes"),
]


def get_products(profile, service, filters):
    args = [
        "aws",
        "pricing",
        "get-products",
        "--region",
        "us-east-1",
        "--service-code",
        service,
        "--output",
        "json",
        "--filters",
        f"Type=TERM_MATCH,Field=regionCode,Value={REGION}",
    ]
    for field, value in filters.items():
        args.append(f"Type=TERM_MATCH,Field={field},Value={value}")
    if profile:
        args += ["--profile", profile]
    out = subprocess.run(args, check=True, capture_output=True, text=True).stdout
    return [json.loads(item) for item in json.loads(out)["PriceList"]]


def on_demand_prices(product):
    for term in product.get("terms", {}).get("OnDemand", {}).values():
        for dim in term["priceDimensions"].values():
            usd = float(dim["pricePerUnit"].get("USD", "0"))
            if usd > 0:
                yield usd, dim["unit"], dim["description"]


def matches_usagetype(usagetype, usage_part):
    """True when usagetype, minus its region prefix (e.g. "EU-"), equals usage_part."""
    return usagetype.split("-", 1)[-1] == usage_part


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default=None)
    profile = parser.parse_args().profile

    for label, service, filters, usage_part in QUERIES:
        found = False
        for product in get_products(profile, service, filters):
            usagetype = product["product"]["attributes"].get("usagetype", "")
            if not matches_usagetype(usagetype, usage_part):
                continue
            for usd, unit, description in on_demand_prices(product):
                found = True
                print(f"{label} | {usagetype} | {usd:g} USD per {unit} | {description}")
        if not found:
            print(f"{label} | NOT FOUND")


if __name__ == "__main__":
    main()
