"""Settings, read from environment variables (or a .env file in the folder you run from)."""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


@dataclass
class Settings:
    llm_provider: str = "gemini"
    llm_model: str = "gemini-3.8-flash"
    llm_fallback_provider: str = "groq"
    llm_fallback_model: str = "openai/gpt-oss-20b"
    gemini_api_key: str = ""
    groq_api_key: str = ""
    anthropic_api_key: str = ""
    openai_compatible_base_url: str = "http://localhost:11434/v1"
    openai_compatible_api_key: str = "ollama"
    github_token: str = ""
    reasoning_effort: str = "low"      # how long thinking models think: none/low/medium/high, "" = model default
    groq_max_input_chars: int = 20_000  # ~5k tokens; Groq free tier has a small tokens-per-minute limit
    max_agent_steps: int = 8
    max_repo_mb: int = 50
    output_dir: str = "output"

    @classmethod
    def from_env(cls) -> "Settings":
        e = os.getenv
        return cls(
            llm_provider=e("LLM_PROVIDER", cls.llm_provider),
            llm_model=e("LLM_MODEL", cls.llm_model),
            llm_fallback_provider=e("LLM_FALLBACK_PROVIDER", cls.llm_fallback_provider),
            llm_fallback_model=e("LLM_FALLBACK_MODEL", cls.llm_fallback_model),
            gemini_api_key=e("GEMINI_API_KEY", ""),
            groq_api_key=e("GROQ_API_KEY", ""),
            anthropic_api_key=e("ANTHROPIC_API_KEY", ""),
            openai_compatible_base_url=e("OPENAI_COMPATIBLE_BASE_URL", cls.openai_compatible_base_url),
            openai_compatible_api_key=e("OPENAI_COMPATIBLE_API_KEY", cls.openai_compatible_api_key),
            github_token=e("GITHUB_TOKEN", ""),
            reasoning_effort=e("REASONING_EFFORT", cls.reasoning_effort),
            groq_max_input_chars=_int("GROQ_MAX_INPUT_CHARS", cls.groq_max_input_chars),
            max_agent_steps=_int("MAX_AGENT_STEPS", cls.max_agent_steps),
            max_repo_mb=_int("MAX_REPO_MB", cls.max_repo_mb),
            output_dir=e("OUTPUT_DIR", cls.output_dir),
        )
