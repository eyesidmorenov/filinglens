import os

import chainlit as cl
import httpx

API_URL = os.getenv("API_URL", "http://localhost:8000")


def format_source(s: dict) -> str:
    section = s.get("section")
    if not section or section == "Unknown":
        section = "No section"
    name = s.get("ticker") or s["company"]
    return f"- {name} {s['fiscal_year']} · {section} · p. {s['page']}"

@cl.set_starters
async def set_starters():
    return [
        cl.Starter(
            label="Apple · 2019 · Risk factors",
            message="What were Apple's main risk factors in fiscal 2019?",
        ),
        cl.Starter(
            label="NVIDIA · 2020 · Business overview",
            message="How did NVIDIA describe its main business segments in fiscal 2020?",
        ),
        cl.Starter(
            label="Meta · 2021 · Business overview",
            message="How did Meta Platforms describe its business in fiscal 2021?",
        ),
    ]
    
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