FROM python:3.12-slim

WORKDIR /app

# 1. Librerías de la API y del buscador
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 2. tenk-answer (Juan Carlos), instalado como paquete
COPY --from=tenk . /tmp/tenk-answer
RUN pip install --no-cache-dir /tmp/tenk-answer && rm -rf /tmp/tenk-answer

# 3. Código del buscador (José Luis) y de la API
COPY --from=search src ./search/src
COPY app ./app
ENV SEARCH_DIR=/app/search

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]