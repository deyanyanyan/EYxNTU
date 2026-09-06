FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends espeak-ng && rm -rf /var/lib/apt/lists/*
WORKDIR /srv/tts
COPY services/tts/requirements.txt .
RUN pip install -r requirements.txt
COPY services/tts /srv/tts
EXPOSE 8880
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8880"]
