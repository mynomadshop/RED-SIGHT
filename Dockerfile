# RedSight - High-Performance Local AI Intelligence Platform
# Production Dockerfile

FROM python:3.12-slim AS base

# Prevent Python from writing .pyc files and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    RED_SIGHT_MODE=local_preferred \
    RED_SIGHT_DATA_ROOT=/data \
    LM_STUDIO_BASE_URL=http://host.docker.internal:1234/v1 \
    QDRANT_URL=http://qdrant:6333 \
    LOG_LEVEL=INFO

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the complete installable package before building it. Installing from a
# metadata-only layer can silently create an empty wheel.
COPY pyproject.toml README.md ./
COPY app/ app/
COPY redsight/ redsight/
COPY redsight_actions/ redsight_actions/
COPY ui/ ui/
COPY scripts/ scripts/
RUN pip install --no-cache-dir .

# Create data directory
RUN mkdir -p /data

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

CMD ["uvicorn", "app.server:app", "--host", "0.0.0.0", "--port", "8000"]
