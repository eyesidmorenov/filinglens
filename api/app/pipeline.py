"""Pipeline de respuesta: búsqueda + generación.

Hoy usa datos de prueba con los formatos de los contratos del equipo:
- search() devuelve resultados del contrato 3 (lo hará José Luis)
- generate() devuelve la respuesta del contrato 4 (lo hará tenk-answer, de Juan Carlos)
"""


def search(question: str) -> list[dict]:
    # TODO: reemplazar por la búsqueda de José Luis
    return [
        {
            "chunk_id": "AAPL_2019_10K_p32_c1",
            "text": "Total net sales were $260,174 million for fiscal 2019.",
            "score": 0.86,
            "section": "Item 8",
            "page": 32,
            "company": "Apple Inc.",
            "fiscal_year": 2019,
        }
    ]


def generate(question: str, hits: list[dict]) -> dict:
    # TODO: reemplazar por tenk-answer:
    # gen.run(question=question, documents=[SearchResult.from_dict(h) for h in hits]).to_api_response()
    return {
        "answer": f"Test answer to: {question}",
        "sources": [
            {
                "company": h["company"],
                "fiscal_year": h["fiscal_year"],
                "section": h["section"],
                "page": h["page"],
                "excerpt": h["text"][:300],
            }
            for h in hits
        ],
        "latency_ms": 0,
    }


def answer_question(question: str) -> dict:
    hits = search(question)
    return generate(question, hits)