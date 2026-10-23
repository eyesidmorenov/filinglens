FROM python:3.12-slim

WORKDIR /app

# 1. Libraries of the API and the search
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 2. tenk-answer (Juan Carlos), installed as a package
COPY --from=tenk . /tmp/tenk-answer
RUN pip install --no-cache-dir /tmp/tenk-answer && rm -rf /tmp/tenk-answer

# 3. Code of the search (José Luis) and the API
COPY --from=search src ./search/src
COPY app ./app
ENV SEARCH_DIR=/app/search

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]