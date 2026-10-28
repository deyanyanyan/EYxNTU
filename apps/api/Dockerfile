FROM python:3.12-slim AS deps
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/srv/api:/srv/worker
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 libgl1 libglib2.0-0 libgomp1 && rm -rf /var/lib/apt/lists/*
WORKDIR /srv/api
COPY apps/api/requirements.txt apps/api/constraints.txt ./
# Use the CPU index exclusively; an extra index can select CUDA wheels instead.
RUN pip install --index-url https://download.pytorch.org/whl/cpu -c constraints.txt torch torchvision \
    && pip install -c constraints.txt -r requirements.txt

FROM deps AS base
COPY apps/api /srv/api
COPY packages/prompts /srv/packages/prompts
COPY scripts /srv/scripts

FROM deps AS worker
# Headless LibreOffice renders Word and PowerPoint uploads to PDF for the source viewer
# (app/core/rag/rendition.py); installed before the code so code changes do not reinstall it.
# Carlito, Caladea and Liberation are metric-compatible with Calibri, Cambria, Arial and
# Times New Roman, so rendered pages keep the original line and page breaks.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice-writer-nogui libreoffice-impress-nogui \
    fonts-crosextra-carlito fonts-crosextra-caladea fonts-liberation2 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
COPY apps/api /srv/api
COPY packages/prompts /srv/packages/prompts
COPY scripts /srv/scripts
WORKDIR /srv/worker
COPY services/worker /srv/worker
CMD ["python", "worker.py"]

FROM base AS api
EXPOSE 8000
# One bootstrap process for the local prototype. Workers wait for API health.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
