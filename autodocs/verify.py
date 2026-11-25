"""Fact-check the generated docs against the repository.

AI-written docs fail in a predictable way: they mention a file that doesn't exist, a command
nobody defined, an endpoint with the wrong path, or a setting the code never reads. Each of
those is easy to check mechanically, so we check every one and report a score.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from autodocs import mermaid
from autodocs.models import RepoMap
from autodocs.scanner import IGNORE_DIRS

GENERATED = {".env", "output", "docs-output", ".DS_Store", "env"}

PATH_RE = re.compile(r"^\.{0,2}/?[\w.@-]+(?:/[\w.@-]+)*/?$")
FILE_EXT_RE = re.compile(r"\.(py|js|ts|tsx|jsx|json|toml|txt|md|yml|yaml|cfg|ini|html|css|sh|env|example|lock|mjs|cjs|sql)$")
ENDPOINT_RE = re.compile(r"\b(GET|POST|PUT|DELETE|PATCH)\s+`?(/(?:<[^>\s]*>|[\w{}/:.-])*)")
ENV_RE = re.compile(r"^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+$")
MARKETING = ("seamless", "powerful", "robust", "cutting-edge", "revolutionary", "effortless", "blazing",
             "leverage", "state-of-the-art", "world-class", "game-changing")
NOT_PATHS = {"main", "master", "HEAD", "true", "false", "null", "None", "localhost"}


@dataclass
class Check:
    doc: str
    kind: str      # path | command | endpoint | env | diagram
    claim: str
    ok: bool
    detail: str = ""


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)
    style_warnings: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.checks)

    @property
    def passed(self) -> int:
        return sum(c.ok for c in self.checks)

    @property
    def score(self) -> float:
        return 100.0 if not self.checks else round(100 * self.passed / self.total, 1)

    def failures(self, doc: str | None = None) -> list[Check]:
        return [c for c in self.checks if not c.ok and (doc is None or c.doc == doc)]

    def to_dict(self) -> dict:
        return {"score": self.score, "passed": self.passed, "total": self.total,
                "checks": [asdict(c) for c in self.checks], "style_warnings": self.style_warnings}


def _norm_route(path: str) -> str:
    path = re.sub(r"\{[^}]+\}|<[^>]+>|:\w+", "{}", path.rstrip("/.") or "/")
    return path


def _split_markdown(md: str) -> tuple[str, list[tuple[str, str]]]:
    """Return (prose without code blocks, [(language, code)])."""
    blocks = [(m.group(1).lower(), m.group(2)) for m in re.finditer(r"```(\w*)[^\n]*\n(.*?)```", md, re.S)]
    prose = re.sub(r"```.*?```", "", md, flags=re.S)
    return prose, blocks


class Verifier:
    def __init__(self, rm: RepoMap, repo_text: str = ""):
        self.rm = rm
        self.files = rm.file_paths()
        self.dirs = {"/".join(f.split("/")[:i]) for f in self.files for i in range(1, f.count("/") + 1)}
        self.routes = {(r.method, _norm_route(r.path)) for r in rm.routes}
        self.route_paths = {_norm_route(r.path) for r in rm.routes}
        self.env = {e.name for e in rm.env_vars}
        self.repo_text = repo_text
        self.py_modules = {m.name for m in rm.modules}
        self.basenames = {f.rsplit("/", 1)[-1] for f in self.files}

    # -- single claims -------------------------------------------------------------------------
    def path_exists(self, p: str) -> bool:
        p = p.strip().strip("`").rstrip("/").removeprefix("./")
        if p.startswith(self.rm.name + "/"):
            p = p[len(self.rm.name) + 1:]
        return p in self.files or p in self.dirs or p in ("", ".")

    def module_exists(self, name: str) -> bool:
        """`app.main` exists if there's a module app.main, or backend.app.main (run from backend/)."""
        return name in self.py_modules or any(n.endswith("." + name) for n in self.py_modules)

    def endpoint_ok(self, method: str, path: str) -> bool:
        return (method, _norm_route(path)) in self.routes or ("ANY", _norm_route(path)) in self.routes

    def env_ok(self, name: str) -> bool:
        return name in self.env or (bool(self.repo_text) and name in self.repo_text)

    def command_check(self, cmd: str) -> tuple[bool, str] | None:
        """None = not something we know how to check."""
        c = cmd.strip()
        c = re.sub(r"^\$\s*", "", c).split(" #")[0].strip()
        if not c or c.startswith("#"):
            return None
        m = re.match(r"pip3? install (?:-r|--requirement) (\S+)", c)
        if m:
            return self.path_exists(m[1]), f"needs {m[1]}"
        m = re.match(r"pip3? install -e \.?", c)
        if m:
            ok = bool({"pyproject.toml", "setup.py"} & self.files)
            return ok, "needs pyproject.toml or setup.py"
        m = re.match(r"python3?\s+-m\s+([\w.]+)", c)
        if m:
            mod = m[1]
            if mod in ("venv", "pip", "pytest", "http.server", "unittest", "build"):
                return None
            ok = self.module_exists(mod) or any(f.endswith(f"{mod.replace('.', '/')}/__main__.py") for f in self.files)
            return ok, f"module {mod}"
        m = re.match(r"python3?\s+([\w./-]+\.py)", c)
        if m:
            return self.path_exists(m[1]), f"needs {m[1]}"
        m = re.match(r"uvicorn\s+([\w.]+):(\w+)", c)
        if m:
            return self.module_exists(m[1]), f"module {m[1]}"
        m = re.match(r"(?:npm|pnpm|yarn)(?: run)? (\w[\w:-]*)", c)
        if m and m[1] not in ("install", "i", "ci", "add", "init", "test", "start"):
            return f"npm run {m[1]}" in self.rm.scripts, f"script '{m[1]}' in package.json"
        if re.match(r"npm (?:install|ci|i)\b", c):
            return "package.json" in self.files, "needs package.json"
        m = re.match(r"(?:cp|copy|Copy-Item)\s+(\S+)\s+\S+", c)
        if m:
            return self.path_exists(m[1]), f"needs {m[1]}"
        m = re.match(r"cd\s+(\S+)$", c)
        if m:
            target = m[1].strip("/")
            return target == self.rm.name or self.path_exists(target), f"folder {target}"
        m = re.match(r"git clone\s+(\S+)", c)
        if m and self.rm.url:
            ok = m[1].rstrip("/").removesuffix(".git").lower() == self.rm.url.lower()
            return ok, f"should be {self.rm.url}"
        if re.match(r"docker(?:-| )compose\b", c):
            ok = bool({"docker-compose.yml", "docker-compose.yaml", "compose.yaml", "compose.yml"} & self.files)
            return ok, "needs a compose file"
        if re.match(r"docker build\b", c):
            return "Dockerfile" in self.files, "needs Dockerfile"
        m = re.match(r"make (\w[\w-]*)", c)
        if m:
            return f"make {m[1]}" in self.rm.scripts, f"Makefile target {m[1]}"
        if re.match(r"(?:python3? -m )?pytest\b", c):
            return self.rm.has_tests, "needs tests"
        return None

    # -- whole documents --------------------------------------------------------------------
    def check_doc(self, name: str, md: str) -> list[Check]:
        checks: list[Check] = []
        prose, blocks = _split_markdown(md)
        seen: set[tuple[str, str]] = set()

        def add(kind: str, claim: str, ok: bool, detail: str = "") -> None:
            if (kind, claim) not in seen:
                seen.add((kind, claim))
                checks.append(Check(name, kind, claim, ok, detail))

        # inline `code` that looks like a file path or a setting
        for span in re.findall(r"`([^`\n]+)`", prose):
            s = span.strip()
            if ENV_RE.match(s):
                add("env", s, self.env_ok(s), "setting read by the code or listed in .env.example")
                continue
            if s.startswith("/") and not FILE_EXT_RE.search(s):
                if self.route_paths:
                    n = _norm_route(s)
                    ok = n in self.route_paths or any(r.startswith(n.rstrip("/") + "/") for r in self.route_paths)
                    add("endpoint", s, ok, "a route (or route prefix) in the code")
                continue
            if " " in s or s in NOT_PATHS or "://" in s or s.startswith(("-", "$", "<", "@", "~")) or "*" in s:
                continue
            if not PATH_RE.match(s) or re.match(r"^\d", s) or s.count(".") > 3 or s.startswith("..."):
                continue
            first = s.removeprefix("./").split("/")[0]
            if first in IGNORE_DIRS or first in GENERATED:
                continue  # created by the reader (venv, .env, output folder), not part of the repo
            if "/" in s:
                ext = FILE_EXT_RE.search(s)
                if not ext and s.count("/") == 1 and not s.endswith("/") and not self.path_exists(first):
                    continue  # probably a model or package name like openai/gpt-oss-20b
                add("path", s, self.path_exists(s), "file or folder in the repo")
            elif s.startswith(".") and not (re.match(r"^\.[a-z0-9][a-z0-9_-]*(\.[a-z0-9]+)*$", s)
                                            and (FILE_EXT_RE.search(s) or "env" in s or self.path_exists(s))):
                continue  # `.method` style code references, not files
            elif FILE_EXT_RE.search(s) or s.startswith("."):
                ok = self.path_exists(s) or s in self.basenames
                add("path", s, ok, "file in the repo")

        # METHOD /path mentions anywhere (prose and tables)
        for m in ENDPOINT_RE.finditer(md):
            add("endpoint", f"{m[1]} {m[2]}", self.endpoint_ok(m[1], m[2]), "a route in the code")

        for lang, code in blocks:
            if lang in ("bash", "sh", "shell", "console", "powershell", "ps1", "cmd", "zsh", ""):
                for raw in code.replace("\\\n", " ").splitlines():
                    for part in re.split(r"\s*&&\s*", raw.strip()):
                        res = self.command_check(part)
                        if res is not None:
                            add("command", part.strip()[:120], res[0], res[1])
            elif lang == "mermaid":
                errs = mermaid.problems(code.strip())
                add("diagram", code.strip().splitlines()[0][:60] if code.strip() else "(empty)", not errs,
                    "; ".join(errs) or "renders")
        return checks

    def check_all(self, docs: dict[str, str]) -> Report:
        rep = Report()
        for name, md in docs.items():
            rep.checks.extend(self.check_doc(name, md))
            low = md.lower()
            for w in MARKETING:
                if re.search(rf"\b{re.escape(w)}\b", low):
                    rep.style_warnings.append(f"{name}: uses the marketing word '{w}'")
        return rep


def report_markdown(rep: Report, meta: dict) -> str:
    lines = ["# Documentation quality report", "",
             f"**Fact-check score: {rep.score}%** ({rep.passed} of {rep.total} checkable claims verified against the code)",
             ""]
    for k, v in meta.items():
        lines.append(f"- **{k}:** {v}")
    lines.append("")
    fails = rep.failures()
    if fails:
        lines += ["## Claims that could not be verified", "", "Review these by hand before publishing.", "",
                  "| Document | Type | Claim | Expected |", "|---|---|---|---|"]
        lines += [f"| {c.doc} | {c.kind} | `{c.claim.replace('|', '/')}` | {c.detail} |" for c in fails]
        lines.append("")
    else:
        lines += ["Every checkable claim matched the code.", ""]
    by_kind: dict[str, list[int]] = {}
    for c in rep.checks:
        t = by_kind.setdefault(c.kind, [0, 0])
        t[0] += c.ok
        t[1] += 1
    if by_kind:
        lines += ["## What was checked", "", "| Type | Verified | What it means |", "|---|---|---|"]
        meaning = {"path": "file and folder names exist", "command": "commands use files and scripts that exist",
                   "endpoint": "HTTP routes match the code", "env": "settings are actually read by the code",
                   "diagram": "Mermaid diagrams pass the syntax check"}
        for k, (ok, tot) in by_kind.items():
            lines.append(f"| {k} | {ok}/{tot} | {meaning.get(k, '')} |")
        lines.append("")
    if rep.style_warnings:
        lines += ["## Style warnings", "", *[f"- {w}" for w in rep.style_warnings], ""]
    return "\n".join(lines)
