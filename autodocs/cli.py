"""Command line:  python -m autodocs https://github.com/owner/repo"""
from __future__ import annotations

import argparse
import logging
import sys

from autodocs import __version__
from autodocs.config import Settings
from autodocs.fetch import FetchError
from autodocs.llm import LLMError

ICONS = {"fetch": "⬇", "scan": "🔎", "explore": "🤖", "write": "✍", "verify": "✔", "fix": "🔧", "llm": "↪", "done": "✅"}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="autodocs",
        description="Point it at a GitHub repo (or a local folder) and get a README, API docs and "
                    "architecture diagrams, fact-checked against the code.")
    p.add_argument("repo", help="GitHub URL, owner/repo, or a local folder path")
    p.add_argument("-o", "--out", default=None, help="output folder (default: output/)")
    p.add_argument("--offline", action="store_true", help="no AI: docs from static analysis only (no API key needed)")
    p.add_argument("--steps", type=int, default=None, help="max agent tool calls (default 8)")
    p.add_argument("--no-fix", action="store_true", help="don't let the AI correct unverified claims")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--version", action="version", version=f"autodocs {__version__}")
    a = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO if a.verbose else logging.WARNING, format="  %(message)s")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # emojis on Windows terminals

    s = Settings.from_env()
    if a.steps:
        s.max_agent_steps = a.steps

    from autodocs.pipeline import run

    def show(stage: str, msg: str) -> None:
        print(f"{ICONS.get(stage, '•')} {msg}", flush=True)

    try:
        res = run(a.repo, s, out_dir=a.out, offline=a.offline, on_event=show, fix=not a.no_fix)
    except (FetchError, LLMError) as e:
        print(f"\n❌ {e}", file=sys.stderr)
        if isinstance(e, LLMError):
            print("   Tip: check the API keys in .env, or try --offline to test without AI.", file=sys.stderr)
        return 1
    print(f"\nDone. Open {res.out_dir} to see README.md, API.md, ARCHITECTURE.md and QUALITY_REPORT.md")
    if res.report.failures():
        print(f"⚠ {len(res.report.failures())} claims couldn't be verified; they're listed in QUALITY_REPORT.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
