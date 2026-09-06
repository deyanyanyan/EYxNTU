# Same runtime as the API (shares app/ and packages/prompts), different entrypoint.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PYTHONPATH=/srv/api:/srv/worker

RUN apt-get update && apt-get install -y --no-install-recommends build-essential libpq5 ffmpeg libreoffice-impress fonts-dejavu && rm -rf /var/lib/apt/lists/*

WORKDIR /srv/worker
COPY apps/api/requirements.txt /srv/api/requirements.txt
RUN pip install --extra-index-url https://download.pytorch.org/whl/cpu torch && pip install -r /srv/api/requirements.txt

COPY apps/api /srv/api
COPY packages/prompts /srv/packages/prompts
COPY services/worker /srv/worker

CMD ["python", "worker.py"]
