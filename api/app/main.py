from fastapi import FastAPI
from pydantic import BaseModel
import time

app = FastAPI(title="Financial Advisor Chatbot API")

class Question(BaseModel):
    question: str

class Source(BaseModel):
    doc_id: str | None = None
    company: str
    ticker: str | None = None
    fiscal_year: int
    section: str | None = None
    page: int
    excerpt: str

class Answer(BaseModel):
    answer: str
    sources: list[Source] = []
    latency_ms: int

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/ask", response_model=Answer)
def ask(payload: Question):
    start = time.perf_counter()
    # MOCK: luego se reemplaza por el pipeline de Haystack
    sources = [
        Source(
            doc_id="AAPL_2019_10K",
            company="apple-inc",
            ticker="AAPL",
            fiscal_year=2019,
            section="Item 7",
            page=42,
            excerpt="Total net sales decreased 2% or $5.4 billion during 2019...",
        )
    ]
    latency_ms = int((time.perf_counter() - start) * 1000)
    return Answer(
        answer=f"Respuesta de prueba a: {payload.question}",
        sources=sources,
        latency_ms=latency_ms,
    )