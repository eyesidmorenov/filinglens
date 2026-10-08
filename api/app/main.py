from fastapi import FastAPI
from pydantic import BaseModel
from app.pipeline import answer_question
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

@app.post("/ask", response_model=Answer, response_model_exclude_none=True)
def ask(payload: Question):
    start = time.perf_counter()
    result = answer_question(payload.question)
    # Latencia total (búsqueda + generación). Pendiente confirmar con el equipo.
    latency_ms = int((time.perf_counter() - start) * 1000)
    return Answer(
        answer=result["answer"],
        sources=result["sources"],
        latency_ms=latency_ms,
    )