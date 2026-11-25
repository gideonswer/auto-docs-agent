"""Runs the real OpenAI-compatible client against a local fake server, so the exact HTTP
requests Gemini/Groq would receive are exercised without needing an API key."""
import json
import socket
import threading
import time

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from autodocs import pipeline
from autodocs.config import Settings
from tests.conftest import ScriptedLLM

brain = ScriptedLLM()
seen: list[dict] = []
fake = FastAPI()
state = {"fail_next": 1, "tool_error_sent": False}


@fake.post("/v1/chat/completions")
async def completions(req: Request):
    body = await req.json()
    seen.append(body)
    if state["fail_next"]:
        state["fail_next"] -= 1
        return JSONResponse({"error": {"message": "overloaded"}}, status_code=503)
    text = brain.chat(body["messages"])
    if not state["tool_error_sent"] and '"action": "read_file"' in text:
        # behave like Groq's gpt-oss: the reply arrives as a rejected "function call"
        state["tool_error_sent"] = True
        action = json.loads(text[text.index("{"): text.rindex("}") + 1])
        gen = json.dumps({"name": action["action"], "arguments": action["args"]})
        return JSONResponse({"error": {"message": "Tool choice is none, but model called a tool",
                                       "type": "invalid_request_error", "code": "tool_use_failed",
                                       "failed_generation": gen}}, status_code=400)
    return {"id": "x", "object": "chat.completion", "created": 0, "model": body["model"],
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": text}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_pipeline_over_real_http(sample_repo, tmp_path, monkeypatch):
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(fake, host="127.0.0.1", port=port, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(50):
        if server.started:
            break
        time.sleep(0.1)
    monkeypatch.setattr("autodocs.llm.time.sleep", lambda s: None)  # don't actually wait on retries
    s = Settings(llm_provider="openai_compatible", llm_model="fake-model", llm_fallback_provider="",
                 openai_compatible_base_url=f"http://127.0.0.1:{port}/v1", openai_compatible_api_key="x")
    try:
        res = pipeline.run(str(sample_repo), s, out_dir=tmp_path)
    finally:
        server.should_exit = True
    assert res.report.score == 100.0
    assert len(seen) > 8 and all(b["model"] == "fake-model" for b in seen)
    assert res.meta["Agent tool calls"] == 3
    assert state["tool_error_sent"]  # the Groq-style error was recovered, not fatal
