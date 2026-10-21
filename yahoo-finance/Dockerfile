# FilingLens Yahoo Finance coverage check (research spike)
# A run-once container: it asks Yahoo Finance about the 25 companies and exits.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY overrides.csv .
COPY src/ src/
COPY tests/ tests/

# data/ is mounted from the host by docker compose, never baked into the image
ENV DATA_DIR=/app/data \
    PYTHONUNBUFFERED=1

CMD ["python", "-m", "src.coverage"]
