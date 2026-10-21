import asyncio
import json
import os

import chainlit as cl
import httpx

API_URL = os.getenv("API_URL", "http://localhost:8000")

CONNECTION_ERROR = "I couldn't connect to the server. Please try again in a moment."
SEARCHING = "_Searching the 10-K reports…_"


def source_label(i: int, s: dict) -> str:
    section = s.get("section")
    if not section or section == "Unknown":
        section = "No section"
    name = s.get("ticker") or s["company"]
    # Page 0 = Yahoo Finance snapshot (years after the 10-Ks): there is no page, show the fetch date
    if s.get("page") == 0 and section.startswith("Yahoo Finance"):
        fetched = section.partition("fetched on ")[2].rstrip(")") or "unknown date"
        return f"{i}. {name} {s['fiscal_year']} · Yahoo Finance · fetched on {fetched}"
    return f"{i}. {name} {s['fiscal_year']} · {section} · p. {s['page']}"


def format_answer(data: dict) -> tuple[str, list]:
    """Final answer text with its citations, and the side panels each citation opens."""
    answer = data["answer"]
    sources = data.get("sources", [])
    elements = []
    if sources:
        labels = []
        for i, s in enumerate(sources, start=1):
            label = source_label(i, s)
            labels.append(label)
            elements.append(
                cl.Text(name=label, content=s.get("excerpt", ""), display="side")
            )
        answer += "\n\n**Citations:**\n" + "\n".join(f"- {lbl}" for lbl in labels)

    latency = data.get("latency_ms")
    if latency is not None:
        answer += f"\n\n_Response time: {latency} ms_"
    return answer, elements


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


@cl.on_chat_end
async def on_chat_end():
    # The user closed the page or started a new chat: stop the answer in progress, so the
    # connection to the API closes and Claude stops writing (backlog #7)
    task = cl.user_session.get("answer_task")
    if task and not task.done():
        task.cancel()


@cl.on_message
async def main(message: cl.Message):
    cl.user_session.set("answer_task", asyncio.current_task())
    # Shown while the API searches and Claude starts; replaced by the first words of the answer
    msg = cl.Message(content=SEARCHING)
    await msg.send()
    started = False
    final = None
    error = CONNECTION_ERROR

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120, connect=10)) as client:
            async with client.stream(
                "POST", f"{API_URL}/ask/stream", json={"question": message.content}
            ) as response:
                response.raise_for_status()
                # One JSON event per line: pieces of text while Claude writes, then the final answer
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    event = json.loads(line)
                    if event["type"] == "token":
                        if not started:
                            msg.content = ""  # remove "Searching…" before the first words
                            started = True
                        await msg.stream_token(event["text"])
                    elif event["type"] == "final":
                        final = event
                    elif event["type"] == "error":
                        error = event["message"]
    except httpx.HTTPError:
        pass

    if final is None:
        msg.content = error
        await msg.send()
        return

    # The streamed text was a preview: replace it with the final answer and its citations
    msg.content, msg.elements = format_answer(final)
    await msg.send()
