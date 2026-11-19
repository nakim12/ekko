# Phase 1 crawler for Fly.io: one machine running crawler.supervisor with the data volume at /data.
FROM python:3.13-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY crawler ./crawler
COPY analysis/src/ekko_analysis ./analysis/src/ekko_analysis
RUN pip install --no-cache-dir ".[crawler]"

ENV EKKO_DATA_DIR=/data \
    PYTHONUNBUFFERED=1

CMD ["python", "-m", "crawler.supervisor"]
