FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends build-essential libpq5 && rm -rf /var/lib/apt/lists/*

WORKDIR /srv/api
COPY apps/api/requirements.txt .
# CPU torch keeps the image small; the gpu compose profile overrides EMBEDDING_DEVICE
# and can build with the cuda index instead.
RUN pip install --extra-index-url https://download.pytorch.org/whl/cpu torch && pip install -r requirements.txt

COPY apps/api /srv/api
COPY packages/prompts /srv/packages/prompts

EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2"]
