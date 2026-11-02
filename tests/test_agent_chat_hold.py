import asyncio
from types import SimpleNamespace as Part

from geoview.src import agent_chat


def ai(text):
    return Part(event="messages", data=[{"type": "AIMessageChunk", "content": text}, {}])


def stage(key, detail):
    return Part(event="custom", data={"stage": key, "detail": detail})


def run(parts, monkeypatch):
    async def stream(*args, **kwargs):
        for p in parts:
            yield p

    monkeypatch.setattr(agent_chat, "AGENT_PROFILE", "pro")
    agent_chat.state.chat_messages = []
    client = Part(runs=Part(stream=stream))
    asyncio.run(agent_chat._consume(client))
    return [(m["role"], m["text"]) for m in agent_chat.state.chat_messages]


def test_a_failed_verdict_drops_the_answer_it_judged(monkeypatch):
    msgs = run([ai("wrong "), ai("answer"), stage("verify", "⚠️ Verifier: partial"), ai("fixed")], monkeypatch)
    assert msgs == [("system", "⚠️ Verifier: partial"), ("assistant", "fixed")]


def test_a_passed_verdict_shows_the_answer_first(monkeypatch):
    msgs = run([ai("right"), stage("verify", "✅ Verifier: pass")], monkeypatch)
    assert msgs == [("assistant", "right"), ("system", "✅ Verifier: pass")]
