# FilingLens ETL: extraction and chunking (deliverable 2)
# A run-once container: it processes data/raw/ and exits.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ src/
COPY tests/ tests/

# data/ is mounted from the host by docker compose, never baked into the image
ENV DATA_DIR=/app/data \
    PYTHONUNBUFFERED=1

CMD ["python", "-m", "src.run_pipeline"]
