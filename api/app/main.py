from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from app.pipeline import ANSWER_ERROR, answer_question, answer_question_stream, warm_up
from app.suggestions import suggest
import json
import logging
import threading
import time

logger = logging.getLogger("uvicorn.error")  # shows in `docker compose logs api`

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load the BGE model in the background: /health answers right away,
    # and the first question no longer waits for the model (backlog #3).
    threading.Thread(target=warm_up, daemon=True).start()
    yield

app = FastAPI(title="Financial Advisor Chatbot API", lifespan=lifespan)

class Question(BaseModel):
    question: str
    # Optional: lets us test the real search before the company/year piece exists.
    ticker: str | None = None
    fiscal_year: int | None = None

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

class Suggestions(BaseModel):
    suggestions: list[str]

@app.get("/suggestions", response_model=Suggestions)
def suggestions(question: str, asked: list[str] = Query(default=[])):
    """2-3 follow-up questions about the same company, from templates (no Claude). Not part of Contract 4.

    `asked` (repeatable) = questions already asked in the conversation, so they aren't suggested again.
    """
    try:
        return Suggestions(suggestions=suggest(question, asked))
    except Exception:
        # Suggestions are an extra: if something fails, the chat just shows none
        logger.exception("/suggestions failed")
        return Suggestions(suggestions=[])

@app.post("/ask", response_model=Answer, response_model_exclude_none=True)
def ask(payload: Question):
    start = time.perf_counter()
    try:
        result = answer_question(payload.question, payload.ticker, payload.fiscal_year)
    except Exception:
        # Elasticsearch or Claude failed: a clear message instead of a bare HTTP 500 (backlog #6)
        logger.exception("/ask failed")
        raise HTTPException(status_code=503, detail=ANSWER_ERROR)
    # Latencia total (búsqueda + generación). Pendiente confirmar con el equipo.
    latency_ms = int((time.perf_counter() - start) * 1000)
    return Answer(
        answer=result["answer"],
        sources=result["sources"],
        latency_ms=latency_ms,
    )

@app.post("/ask/stream")
async def ask_stream(payload: Question):
    """Same as /ask, but the answer arrives while Claude writes it: one JSON event per line.

    {"type": "token", "text": "..."}                         a new piece of the answer (preview)
    {"type": "final", "answer", "sources", "latency_ms"}     the answer to keep, same fields as /ask
    {"type": "error", "message": "..."}                      something failed

    If the client leaves (page closed, stop pressed), Claude stops writing (backlog #7).
    """
    cancelled = threading.Event()
    stream = answer_question_stream(payload.question, payload.ticker, payload.fiscal_year, cancelled)

    async def events():
        start = time.perf_counter()
        try:
            # Search and Claude are slow and blocking: each next event is read in a worker thread
            while (event := await run_in_threadpool(next, stream, None)) is not None:
                if event["type"] == "final":
                    # Same shape as /ask: validated sources and total latency (search + generation)
                    event["sources"] = [Source(**s).model_dump(exclude_none=True) for s in event["sources"]]
                    event["latency_ms"] = int((time.perf_counter() - start) * 1000)
                yield json.dumps(event) + "\n"
        finally:
            # Runs when the answer ends, and also when the client disconnects mid-answer
            cancelled.set()

    return StreamingResponse(events(), media_type="application/x-ndjson")
