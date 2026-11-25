"""Runs the whole job: fetch -> scan -> explore -> write -> fact-check -> fix -> save."""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from autodocs import writers
from autodocs.agent import ExplorerAgent
from autodocs.config import Settings
from autodocs.fetch import fetch_repo
from autodocs.llm import LLM, LLMError, build_llm
from autodocs.scanner import repo_summary, scan_repo
from autodocs.tools import RepoTools
from autodocs.verify import Report, Verifier, report_markdown

Event = Callable[[str, str], None]  # (stage, message)

FIX_PROMPT = """The README below contains claims that don't match the repository. Fix ONLY these problems:

{problems}

How to fix: correct the claim if the facts show the right value, otherwise remove it. Keep everything else
exactly as it is, including the tables and the project tree. Return ONLY the full corrected Markdown.

FACTS:
{facts}

README:
{readme}"""


@dataclass
class Result:
    repo: str
    out_dir: Path
    docs: dict[str, str]
    report: Report
    notes: dict
    meta: dict = field(default_factory=dict)


def _repo_text(root: Path, limit: int = 3_000_000) -> str:
    """All text in the repo, for 'is this setting mentioned anywhere?' checks."""
    from autodocs.scanner import IGNORE_DIRS

    chunks, size = [], 0
    for p in root.rglob("*"):
        if p.is_file() and not any(part in IGNORE_DIRS for part in p.relative_to(root).parts) and p.stat().st_size < 300_000:
            try:
                t = p.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            chunks.append(t)
            size += len(t)
            if size > limit:
                break
    return "\n".join(chunks)


def run(target: str, settings: Settings | None = None, out_dir: str | Path | None = None, offline: bool = False,
        llm: LLM | None = None, on_event: Event | None = None, fix: bool = True) -> Result:
    s = settings or Settings.from_env()
    emit = on_event or (lambda stage, msg: None)
    t0 = time.time()

    emit("fetch", f"Getting {target}")
    src = fetch_repo(target, token=s.github_token, max_mb=s.max_repo_mb)
    try:
        emit("scan", "Reading the code (no AI yet)")
        rm = scan_repo(src.path, src.name, src.url)
        emit("scan", f"Found {len(rm.files)} files, {len(rm.symbols)} functions/classes, {len(rm.routes)} HTTP routes, "
                     f"{len(rm.env_vars)} settings")
        summary = repo_summary(rm)

        if not offline and llm is None:
            llm = build_llm(s, on_switch=lambda m: emit("llm", m))
        steps: list[dict] = []
        files_read: list[str] = []
        warnings: list[str] = []
        env_desc: dict[str, str] = {}

        if offline:
            emit("explore", "Offline mode: skipping the AI agent")
            notes = writers.offline_notes(rm)
            readme = writers.offline_readme(rm, notes)
            api = writers.render_api_doc(rm, {}, {})
            arch, warnings = writers.write_architecture(None, rm, notes, summary)
        else:
            emit("explore", "Agent is exploring the repo")
            agent = ExplorerAgent(llm, RepoTools(src.path), max_steps=s.max_agent_steps,
                                  on_step=lambda m: emit("explore", m))
            ar = agent.run(summary)
            notes, steps, files_read = ar.notes, ar.steps, ar.files_read
            if not ar.finished_cleanly:
                warnings.append("The agent ran out of steps or replied badly; notes may be thin.")

            emit("write", "Describing settings")
            env_desc = writers.describe_env_vars(llm, rm, src.path)
            emit("write", "Writing README.md")
            readme = writers.write_readme(llm, rm, notes, summary, env_desc)
            emit("write", "Writing API.md")
            route_notes = writers.annotate_routes(llm, rm, src.path, on_event=lambda m: emit("write", m))
            symbol_notes = writers.annotate_symbols(llm, rm, src.path) if len(rm.routes) < 3 else {}
            api = writers.render_api_doc(rm, route_notes, symbol_notes)
            emit("write", "Writing ARCHITECTURE.md and drawing diagrams")
            arch, warnings2 = writers.write_architecture(llm, rm, notes, summary, log=lambda m: emit("write", m))
            warnings += warnings2

        docs = {"README.md": readme, "API.md": api, "ARCHITECTURE.md": arch}
        emit("verify", "Fact-checking every file, command, endpoint and setting")
        verifier = Verifier(rm, _repo_text(src.path))
        report = verifier.check_all(docs)
        emit("verify", f"Fact-check score: {report.score}% ({report.passed}/{report.total})")

        fails = report.failures("README.md")
        if fix and fails and llm is not None and not offline:
            emit("fix", f"Fixing {len(fails)} unverified claims in README.md")
            problems = "\n".join(f"- {c.kind}: `{c.claim}` (expected: {c.detail})" for c in fails)
            try:
                fixed = llm.chat([{"role": "user", "content": FIX_PROMPT.format(
                    problems=problems, facts=writers.facts_block(rm), readme=readme)}], temperature=0.1, max_tokens=6000)
                fixed = writers.fill_readme_placeholders(writers._strip_fences(fixed), rm, env_desc)
                new_report = verifier.check_all({**docs, "README.md": fixed})
                if new_report.score >= report.score and len(fixed) > len(readme) * 0.6:
                    docs["README.md"], report = fixed, new_report
                    emit("fix", f"Score after fixing: {report.score}%")
                else:
                    emit("fix", "Kept the original README (the fix didn't improve it)")
            except LLMError as e:
                emit("fix", f"Fix step skipped: {str(e)[:100]}")

        model_used = "none (offline mode)" if offline else getattr(llm, "last_used", getattr(llm, "name", "?"))
        meta = {
            "Repository": rm.url or rm.name,
            "Model": model_used,
            "AI calls": getattr(llm, "calls", "n/a") if not offline else 0,
            "Agent tool calls": len(steps),
            "Files the agent read": ", ".join(f"`{f}`" for f in files_read) or "none",
            "Time taken": f"{time.time() - t0:.0f}s",
        }
        for w in warnings:
            meta.setdefault("Warnings", "")
            meta["Warnings"] = (meta["Warnings"] + " " + w).strip()

        out = Path(out_dir or s.output_dir) / re.sub(r"[^\w.-]", "_", rm.name)
        out.mkdir(parents=True, exist_ok=True)
        for name, md in docs.items():
            (out / name).write_text(md, encoding="utf-8")
        (out / "QUALITY_REPORT.md").write_text(report_markdown(report, meta), encoding="utf-8")
        (out / "agent_trace.json").write_text(json.dumps(
            {"notes": notes, "steps": steps, "files_read": files_read, "report": report.to_dict(), "meta": meta},
            indent=2, default=str), encoding="utf-8")
        emit("done", f"Saved to {out}")
        return Result(rm.name, out, docs, report, notes, meta)
    finally:
        src.cleanup()
