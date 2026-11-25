"""Provider-agnostic LLM layer with automatic fallback and retry.

Gemini, Groq and Ollama all speak the OpenAI chat API, so one client class covers them.
Claude has its own class. The agent only ever calls `llm.chat(messages)`, so switching
providers is a change in .env, not in code.

Why no native "function calling"? The agent asks for JSON actions in plain text instead.
That works the same on every provider, so if Gemini fails halfway through a run, Groq can
pick up the SAME conversation and carry on. Native tool-call formats differ per provider
and can't be handed over mid-run.
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Callable, Protocol

from autodocs.config import Settings

log = logging.getLogger(__name__)

OPENAI_COMPATIBLE_URLS = {
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "groq": "https://api.groq.com/openai/v1",
}
Message = dict[str, str]


class LLMError(RuntimeError):
    pass


class LLM(Protocol):
    name: str

    def chat(self, messages: list[Message], temperature: float = 0.2, max_tokens: int = 4096) -> str: ...


def _retry_wait(err: Exception, attempt: int) -> float | None:
    """Seconds to wait before retrying, or None if retrying won't help."""
    status = getattr(err, "status_code", None) or getattr(getattr(err, "response", None), "status_code", None)
    text = str(err)
    if status in (400, 401, 403, 404) and "RESOURCE_EXHAUSTED" not in text:
        return None  # bad key / bad model name: retrying won't fix it
    if status == 429 or "rate" in text.lower() or "429" in text:
        m = re.search(r"try again in ([\d.]+)s", text) or re.search(r"retry(?:_delay|Delay)?\D{0,20}([\d.]+)s", text)
        wait = float(m.group(1)) + 1 if m else 8 * (attempt + 1)
        return wait if wait <= 65 else None  # a daily limit: give up and use the backup
    return min(5 * 2 ** attempt, 30)  # 500/503 overloaded, timeouts: wait 5s, 10s, 20s...


AGENT_ACTIONS = {"list_dir", "read_file", "search", "finish"}


def recover_tool_call(err: Exception) -> str | None:
    """Groq's gpt-oss models sometimes send their answer as a native function call even though
    we didn't offer any functions. Groq then rejects it with 400 'tool_use_failed', but puts what
    the model said in `failed_generation`. We turn that back into the plain-JSON reply we wanted."""
    body = getattr(err, "body", None)
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        body = body["error"]
    if not isinstance(body, dict) or body.get("code") != "tool_use_failed":
        return None
    raw = body.get("failed_generation")
    if not raw:
        return None
    try:
        call = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError:
        return str(raw)  # plain text: that IS the answer
    if isinstance(call, list) and call:
        call = call[0]
    if not isinstance(call, dict) or "name" not in call:
        return json.dumps(call)
    name, args = call["name"], call.get("arguments") or call.get("parameters") or {}
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            args = {}
    if isinstance(args, dict) and "action" in args:  # model wrapped our whole JSON reply in a call
        return json.dumps(args)
    if name in AGENT_ACTIONS:
        return json.dumps({"thought": "", "action": name, "args": args})
    return json.dumps(args)  # e.g. a 'json' call carrying the object we asked for


class OpenAICompatibleLLM:
    """Works for Gemini, Groq, Ollama and anything else that speaks the OpenAI API."""

    def __init__(self, provider: str, model: str, base_url: str, api_key: str, retries: int = 3,
                 max_input_chars: int = 400_000, reasoning_effort: str = ""):
        from openai import OpenAI

        if not api_key:
            raise LLMError(f"No API key set for provider '{provider}'")
        self.name = f"{provider}:{model}"
        self.model = model
        self.retries = retries
        self.max_input_chars = max_input_chars
        self.reasoning_effort = reasoning_effort
        self.client = OpenAI(base_url=base_url, api_key=api_key, max_retries=0, timeout=180)

    def chat(self, messages: list[Message], temperature: float = 0.2, max_tokens: int = 4096) -> str:
        messages = fit_messages(messages, self.max_input_chars)
        extra = {"reasoning_effort": self.reasoning_effort} if self.reasoning_effort else {}
        if self.reasoning_effort:  # thinking tokens count towards the limit, so leave room
            max_tokens = max(max_tokens, 8192)
        for attempt in range(self.retries + 1):
            try:
                resp = self.client.chat.completions.create(
                    model=self.model, messages=messages, temperature=temperature, max_tokens=max_tokens, **extra)
                text = (resp.choices[0].message.content or "").strip()
                if not text:
                    raise LLMError(f"{self.name} returned an empty answer")
                return text
            except Exception as e:  # noqa: BLE001 - rate limits, network, bad key...
                recovered = recover_tool_call(e)
                if recovered:
                    return recovered
                wait = _retry_wait(e, attempt)
                if wait is None or attempt == self.retries:
                    raise LLMError(f"{self.name} failed: {str(e)[:300]}") from e
                log.info("%s: %s, retrying in %.0fs", self.name, str(e)[:80], wait)
                time.sleep(wait)
        raise LLMError(f"{self.name} failed")


def fit_messages(messages: list[Message], max_chars: int) -> list[Message]:
    """Shrink a conversation to fit a model's input limit (Groq's free tier is small).

    The system prompt and the latest message are kept whole; the longest messages in
    between are shortened first."""
    total = sum(len(m["content"]) for m in messages)
    if total <= max_chars:
        return messages
    msgs = [dict(m) for m in messages]
    middle = sorted(range(1, len(msgs) - 1), key=lambda i: -len(msgs[i]["content"]))
    for i in middle:
        if total <= max_chars:
            break
        c = msgs[i]["content"]
        keep = max(300, len(c) - (total - max_chars))
        if keep < len(c):
            msgs[i]["content"] = c[:keep] + "\n[... shortened to fit the model's limit ...]"
            total -= len(c) - len(msgs[i]["content"])
    if total > max_chars:  # still too big: the last message itself must give way
        last = msgs[-1]["content"]
        msgs[-1]["content"] = last[: max(2000, len(last) - (total - max_chars))]
    return msgs


class ClaudeLLM:
    def __init__(self, model: str, api_key: str):
        import anthropic

        if not api_key:
            raise LLMError("No API key set for provider 'claude'")
        self.name = f"claude:{model}"
        self.model = model
        self.client = anthropic.Anthropic(api_key=api_key, max_retries=3)

    def chat(self, messages: list[Message], temperature: float = 0.2, max_tokens: int = 4096) -> str:
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        rest = [m for m in messages if m["role"] != "system"]
        try:
            resp = self.client.messages.create(model=self.model, max_tokens=max_tokens, temperature=temperature,
                                               system=system, messages=rest)
        except Exception as e:  # noqa: BLE001
            raise LLMError(f"{self.name} failed: {str(e)[:300]}") from e
        return "".join(b.text for b in resp.content if b.type == "text").strip()


class FallbackLLM:
    """Try each model in order. Remembers which one answered last, for the report."""

    def __init__(self, models: list[LLM], on_switch: Callable[[str], None] | None = None):
        if not models:
            raise LLMError("No LLM configured. Add GEMINI_API_KEY or GROQ_API_KEY to .env, or use --offline.")
        self.models = models
        self.name = " -> ".join(m.name for m in models)
        self.last_used = models[0].name
        self.calls = 0
        self.on_switch = on_switch

    def chat(self, messages: list[Message], temperature: float = 0.2, max_tokens: int = 4096) -> str:
        errors = []
        for m in self.models:
            try:
                out = m.chat(messages, temperature, max_tokens)
                if m.name != self.last_used and self.on_switch:
                    self.on_switch(f"Switched to backup model {m.name}")
                self.last_used = m.name
                self.calls += 1
                return out
            except LLMError as e:
                log.warning("%s", e)
                errors.append(str(e))
        raise LLMError("All models failed: " + " || ".join(errors))


def build_provider(provider: str, model: str, s: Settings) -> LLM:
    provider = provider.lower().strip()
    if provider == "gemini":
        return OpenAICompatibleLLM(provider, model, OPENAI_COMPATIBLE_URLS[provider], s.gemini_api_key,
                                   reasoning_effort=s.reasoning_effort)
    if provider == "groq":
        # Groq's free tier allows only a few thousand tokens per minute, so keep requests small
        effort = s.reasoning_effort if "gpt-oss" in model else ""
        return OpenAICompatibleLLM(provider, model, OPENAI_COMPATIBLE_URLS[provider], s.groq_api_key,
                                   max_input_chars=s.groq_max_input_chars, reasoning_effort=effort)
    if provider == "claude":
        return ClaudeLLM(model, s.anthropic_api_key)
    if provider == "openai_compatible":
        return OpenAICompatibleLLM(provider, model, s.openai_compatible_base_url, s.openai_compatible_api_key)
    raise LLMError(f"Unknown LLM provider '{provider}'")


def build_llm(s: Settings, on_switch: Callable[[str], None] | None = None) -> FallbackLLM:
    models: list[LLM] = []
    errors = []
    for provider, model in ((s.llm_provider, s.llm_model), (s.llm_fallback_provider, s.llm_fallback_model)):
        if not provider:
            continue
        try:
            models.append(build_provider(provider, model, s))
        except LLMError as e:
            errors.append(str(e))
    if not models:
        raise LLMError("No LLM available (" + "; ".join(errors) + "). Add an API key to .env, or run with --offline.")
    return FallbackLLM(models, on_switch)


# ---------- JSON helpers (models wrap JSON in prose or code fences surprisingly often) ----------

def extract_json(text: str):
    """Pull the first JSON object out of a model reply. Raises ValueError if there isn't one."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    candidates = [fence.group(1)] if fence else []
    start = text.find("{")
    if start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidates.append(text[start:i + 1])
                    break
    for c in candidates:
        try:
            return json.loads(c)
        except json.JSONDecodeError:
            try:  # trailing commas are the most common mistake
                return json.loads(re.sub(r",\s*([}\]])", r"\1", c))
            except json.JSONDecodeError:
                continue
    raise ValueError("no valid JSON object found in the model's reply")


def chat_json(llm: LLM, messages: list[Message], max_tokens: int = 4096, attempts: int = 2):
    """Ask for JSON; if the reply isn't valid JSON, say so and ask once more."""
    msgs = list(messages)
    last = ""
    for _ in range(attempts):
        last = llm.chat(msgs, temperature=0.2, max_tokens=max_tokens)
        try:
            return extract_json(last)
        except ValueError as e:
            msgs = msgs + [{"role": "assistant", "content": last[:4000]},
                           {"role": "user", "content": f"That was not valid JSON ({e}). Reply with ONLY the JSON object."}]
    raise LLMError(f"Model did not return valid JSON. Last reply started: {last[:200]!r}")
