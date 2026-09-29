import os
import httpx
import chainlit as cl

API_URL = os.getenv("API_URL", "http://localhost:8000")


@cl.on_chat_start
async def start():
    await cl.Message(
        content="Hola 👋 Soy tu asesor financiero. Pregúntame sobre las empresas del NASDAQ."
    ).send()


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
            content="No pude conectarme con el servidor. Intenta de nuevo en un momento."
        ).send()
        return

    answer = data["answer"]
    sources = data.get("sources", [])
    if sources:
        lines = [f"- {s['ticker']} {s['fiscal_year']} · {s.get('section') or 'sin sección'} · pág. {s['page']}" for s in sources]
        answer += "\n\n**Fuentes:**\n" + "\n".join(lines)

    await cl.Message(content=answer).send()