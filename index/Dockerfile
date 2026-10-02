# FilingLens index loader (deliverable 3): chunks + BGE embeddings -> Elasticsearch.
# A run-once container: it loads data/chunks/ and exits.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ src/
COPY tests/ tests/

# data/ and the model cache are mounted by docker compose, never baked into the image
ENV DATA_DIR=/app/data \
    PYTHONUNBUFFERED=1

CMD ["python", "-m", "src.load"]
