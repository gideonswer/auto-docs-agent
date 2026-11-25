"""The exploration agent.

It starts with the RepoMap summary (facts from static analysis), then decides for itself
which files to open and what to search for, until it understands the project well enough
to fill in a structured set of notes. Every writer later works from those notes, so the
docs describe what the code does, not what the repo name suggests.

Loop:  think -> pick a tool -> read the result -> repeat ... -> finish(notes)
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable

from autodocs.llm import LLM, LLMError, extract_json
from autodocs.tools import RepoTools

SYSTEM = """You are a senior technical writer investigating a code repository so you can document it accurately.
You are given facts from static analysis. Use the tools to read the code that matters, then write notes.

Reply with exactly ONE JSON object per turn, written as plain text in your message (do not use function calling):
{"thought": "<one sentence: what you want to learn and why>", "action": "<tool>", "args": {...}}

Tools:
- list_dir   args {"path": "folder"}                                   list a folder
- read_file  args {"path": "file", "start_line": 1, "end_line": 200}   read part of a file (line numbers shown)
- search     args {"pattern": "regex", "glob": "*.py"}                 grep the repo (glob optional)
- finish     args {"notes": {...}}                                     stop and hand over your notes

Strategy: read the entry point first, then the core logic, then config. Don't re-read files.
Prefer reading over guessing. Only state things the code supports.

The notes for finish must use this shape (use [] or "" when unknown, never invent):
{
 "purpose": "2-3 sentences: what problem it solves and for whom",
 "features": ["user-visible capability", ...],
 "how_it_works": ["step 1 of the main data flow", "step 2", ...],
 "components": [{"name": "short name", "paths": ["dir/file.py"], "responsibility": "one sentence"}],
 "external_services": ["APIs, databases, queues it talks to"],
 "setup_steps": ["install/config steps proven by files in the repo"],
 "run_commands": ["exact commands to run it, taken from the code or config"],
 "usage_examples": ["short example of using it: a CLI call, a curl request, a code snippet"],
 "gotchas": ["limits, requirements, surprising behaviour a new user should know"]
}"""

NOTE_KEYS = ("purpose", "features", "how_it_works", "components", "external_services",
             "setup_steps", "run_commands", "usage_examples", "gotchas")


@dataclass
class AgentResult:
    notes: dict
    steps: list[dict] = field(default_factory=list)   # {"thought","action","args"} for the report
    files_read: list[str] = field(default_factory=list)
    finished_cleanly: bool = True


def normalize_notes(raw) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    out: dict = {}
    for k in NOTE_KEYS:
        v = raw.get(k, "" if k == "purpose" else [])
        if k == "purpose":
            out[k] = v if isinstance(v, str) else " ".join(map(str, v)) if isinstance(v, list) else ""
        elif k == "components":
            comps = []
            for c in v if isinstance(v, list) else []:
                if isinstance(c, dict) and c.get("name"):
                    paths = c.get("paths") or ([c["path"]] if c.get("path") else [])
                    comps.append({"name": str(c["name"]), "paths": [str(p) for p in paths if p],
                                  "responsibility": str(c.get("responsibility", ""))})
            out[k] = comps
        else:
            out[k] = [str(x) if not isinstance(x, (dict, list)) else json.dumps(x) for x in v] \
                if isinstance(v, list) else ([str(v)] if v else [])
    return out


class ExplorerAgent:
    def __init__(self, llm: LLM, tools: RepoTools, max_steps: int = 8,
                 on_step: Callable[[str], None] | None = None, history_chars: int = 45_000):
        self.llm = llm
        self.tools = tools
        self.max_steps = max_steps
        self.on_step = on_step or (lambda _m: None)
        self.history_chars = history_chars

    def _trim(self, messages: list[dict]) -> list[dict]:
        """Keep the conversation under budget: shorten the OLDEST tool results first."""
        total = sum(len(m["content"]) for m in messages)
        for m in messages[2:]:
            if total <= self.history_chars:
                break
            if m["role"] == "user" and m["content"].startswith("Result") and len(m["content"]) > 400:
                total -= len(m["content"]) - 300
                m["content"] = m["content"][:300] + "\n[... older result shortened to save space ...]"
        return messages

    def run(self, repo_summary: str) -> AgentResult:
        messages = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"{repo_summary}\n\nYou have up to {self.max_steps} tool calls. Start."},
        ]
        result = AgentResult(notes={})
        bad_replies = 0
        asked_to_finish = False
        for _ in range(self.max_steps + 4):  # extra room for replies that weren't valid JSON
            last_turn = len(result.steps) >= self.max_steps
            if last_turn and not asked_to_finish:
                asked_to_finish = True
                messages.append({"role": "user", "content": "You are out of tool calls. Call finish now with your best notes."})
            reply = self.llm.chat(self._trim(messages), temperature=0.2, max_tokens=3000)
            try:
                action = extract_json(reply)
                name = str(action.get("action", "")).strip()
                args = action.get("args") or {}
            except (ValueError, AttributeError):
                bad_replies += 1
                if bad_replies >= 3:
                    break
                messages += [{"role": "assistant", "content": reply[:2000]},
                             {"role": "user", "content": "Reply with ONE JSON object only, as described."}]
                continue
            messages.append({"role": "assistant", "content": json.dumps(action)[:4000]})

            if name == "finish" or last_turn:
                notes = args.get("notes", args) if isinstance(args, dict) else {}
                result.notes = normalize_notes(notes)
                result.files_read = list(self.tools.files_read)
                result.finished_cleanly = name == "finish"
                self.on_step(f"Agent finished after {len(result.steps)} tool calls")
                return result

            thought = str(action.get("thought", ""))[:200]
            result.steps.append({"thought": thought, "action": name, "args": args})
            self.on_step(f"Step {len(result.steps)}: {name} {json.dumps(args)[:80]} - {thought}")
            observation = self.tools.run(name, args)
            messages.append({"role": "user", "content": f"Result of {name}:\n{observation}"})

        # The model never produced a usable finish: ask directly for notes as a last resort
        try:
            messages.append({"role": "user", "content": 'Reply now with only {"notes": {...}} using the notes shape.'})
            data = extract_json(self.llm.chat(self._trim(messages), max_tokens=3000))
            result.notes = normalize_notes(data.get("notes", data))
        except (ValueError, LLMError):
            result.notes = normalize_notes({})
        result.files_read = list(self.tools.files_read)
        result.finished_cleanly = False
        return result
