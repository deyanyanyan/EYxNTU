FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/srv/api:/srv/worker
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 libgl1 libglib2.0-0 libgomp1 && rm -rf /var/lib/apt/lists/*
WORKDIR /srv/api
COPY apps/api/requirements.txt apps/api/constraints.txt ./
# Use the CPU index exclusively; an extra index can select CUDA wheels instead.
RUN pip install --index-url https://download.pytorch.org/whl/cpu -c constraints.txt torch torchvision \
    && pip install -c constraints.txt -r requirements.txt
COPY apps/api /srv/api
COPY packages/prompts /srv/packages/prompts
COPY scripts /srv/scripts

FROM base AS worker
WORKDIR /srv/worker
COPY services/worker /srv/worker
CMD ["python", "worker.py"]

FROM base AS api
EXPOSE 8000
# One bootstrap process for the local prototype. Workers wait for API health.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
