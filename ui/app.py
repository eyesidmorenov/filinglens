import os

import chainlit as cl
import httpx

API_URL = os.getenv("API_URL", "http://localhost:8000")

WELCOME_MESSAGE = (
    "Hi 👋 Ask me about the 10-K reports of NASDAQ companies.\n\n"
    "Hola 👋 Pregúntame sobre los reportes 10-K de empresas del NASDAQ."
)


def format_source(s: dict) -> str:
    section = s.get("section")
    if not section or section == "Unknown":
        section = "No section"
    name = s.get("ticker") or s["company"]
    return f"- {name} {s['fiscal_year']} · {section} · p. {s['page']}"


@cl.on_chat_start
async def start():
    await cl.Message(content=WELCOME_MESSAGE).send()


@cl.on_message
async def main(message: cl.Message):
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{API_URL}/ask", json={"question": message.content}
            )
            response.raise_for_status()
        data = response.json()
    except httpx.HTTPError:
        await cl.Message(
            content="I couldn't connect to the server. Please try again in a moment."
        ).send()
        return

    answer = data["answer"]
    sources = data.get("sources", [])
    if sources:
        lines = [format_source(s) for s in sources]
        answer += "\n\n**Sources:**\n" + "\n".join(lines)

    latency = data.get("latency_ms")
    if latency is not None:
        answer += f"\n\n_Response time: {latency} ms_"

    await cl.Message(content=answer).send()