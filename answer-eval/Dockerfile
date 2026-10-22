# Steps 0 and 2 of the RAGAS evaluation (testset.py and score.py). Its own image: RAGAS needs other versions of the
# Anthropic and LangChain libraries than tenk-answer, so it never shares the API's environment.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ragas_eval ./ragas_eval
COPY tests ./tests
ENV DATA_DIR=/app/data

CMD ["python", "-m", "ragas_eval.score"]
