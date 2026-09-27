from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="Financial Advisor Chatbot API")

class Question(BaseModel):
    question: str

class Source(BaseModel):
    company: str
    year: int
    section: str

class Answer(BaseModel):
    answer: str
    sources: list[Source] = []

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/ask", response_model=Answer)
def ask(payload: Question):
    # MOCK: luego se reemplaza por el pipeline de Haystack
    return Answer(
        answer=f"Respuesta de prueba a: {payload.question}",
        sources=[Source(company="Apple", year=2022, section="Item 7")],
    )