# ════════════════════════════════════════════════════════════════════════════
# EcomQA — Dockerfile (HF Spaces compatible, port 7860)
# Model weights baked in at build time → zero cold-start at runtime
# ════════════════════════════════════════════════════════════════════════════

FROM python:3.11-slim AS base

RUN apt-get update && apt-get install -y --no-install-recommends \
      gcc g++ libffi-dev curl git \
      libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
      libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
      libgbm1 libasound2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright Chromium (best-effort; may be skipped on Spaces)
RUN playwright install chromium --with-deps || true

# Pre-download all model weights so cold-start is near zero
COPY scripts/download_models.py scripts/
RUN python scripts/download_models.py --skip-playwright

COPY . .
RUN mkdir -p data

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV TRANSFORMERS_CACHE=/app/.hf_cache
ENV HF_HOME=/app/.hf_cache

EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=10s --start-period=120s \
  CMD curl -f http://localhost:7860/ || exit 1

# Single worker, generous timeout — HF free tier is slow
CMD ["gunicorn", "--bind", "0.0.0.0:7860", "--workers", "1", \
     "--worker-class", "gevent", "--timeout", "600", "src.app:app"]
