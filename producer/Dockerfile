# Replay producer image (SECOM-15).
# Build from the repo root:  docker build -f producer/Dockerfile -t secom-producer .
# The official Docker Hub python image, pulled through Google's public Docker Hub mirror (mirror.gcr.io).
# Docker Hub and Amazon ECR Public both rate-limit anonymous pulls from shared GitHub runner IPs
# (ECR Public returned 429 "Data limit exceeded" on most runs in Oct 2026); the mirror needs no login or IAM.
FROM mirror.gcr.io/library/python:3.12-slim

# No .pyc files, unbuffered logs (so CloudWatch sees each line straight away).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data

WORKDIR /app

# Standard library only: nothing to pip install, so the image stays small and has no third-party packages.
COPY secom/__init__.py secom/contract.py secom/producer.py ./secom/

# Run as an unprivileged user, never root.
RUN useradd --create-home --uid 10001 producer
USER producer

# The SECOM files are mounted at /data (or baked in later); they are not part of this repo.
CMD ["python", "-m", "secom.producer"]
