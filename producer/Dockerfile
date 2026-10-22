# Replay producer image (SECOM-15).
# Build from the repo root:  docker build -f producer/Dockerfile -t secom-producer .
# Pulled from Amazon ECR Public (a mirror of the official Docker image) to avoid Docker Hub rate limits in CI.
FROM public.ecr.aws/docker/library/python:3.15-slim

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
