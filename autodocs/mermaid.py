"""Mermaid helpers: build diagrams from code facts, and clean up / check diagrams an LLM wrote.

LLMs often write Mermaid that looks right but fails to render (unquoted brackets in labels,
markdown fences, `end` used as a node id). We fix the common mistakes automatically and
reject anything that still looks broken, so a broken diagram never reaches the docs.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from collections import defaultdict
from pathlib import Path

from autodocs.models import RepoMap

DIAGRAM_TYPES = ("flowchart", "graph", "sequenceDiagram", "classDiagram", "erDiagram",
                 "stateDiagram", "stateDiagram-v2", "C4Context")
RESERVED_IDS = {"end", "graph", "subgraph", "style", "class", "click", "default", "flowchart"}


def safe_id(text: str) -> str:
    s = re.sub(r"\W+", "_", text).strip("_") or "node"
    if s[0].isdigit() or s.lower() in RESERVED_IDS:
        s = "n_" + s
    return s


def label(text: str) -> str:
    return '"' + text.replace('"', "'") + '"'


def graph_languages(rm: RepoMap) -> list[str]:
    """Languages that have internal imports worth drawing, biggest first ("Python", "JavaScript"...)."""
    counts: dict[str, int] = defaultdict(int)
    for m in rm.modules:
        counts["Python" if m.language == "Python" else "JavaScript/TypeScript"] += len(m.imports)
    return [k for k, v in sorted(counts.items(), key=lambda kv: -kv[1]) if v]


def module_graph(rm: RepoMap, max_nodes: int = 30, include_tests: bool = False,
                 language: str | None = None) -> tuple[str | None, list[str]]:
    """Dependency diagram drawn straight from import statements, grouped by folder.

    Modules that almost everything imports (config, models...) are left out of the picture
    and returned separately as `shared`, otherwise every arrow points at them."""
    language = language or (graph_languages(rm) or ["Python"])[0]
    mods = [m for m in rm.modules if (m.language == "Python") == (language == "Python")]
    mods = [m for m in mods if include_tests or not re.search(r"(^|[./])tests?([./]|$)|\.test$|\.spec$", m.name)]
    edges = {(m.name, i) for m in mods for i in m.imports}
    names = {m.name for m in mods}
    edges = {(a, b) for a, b in edges if a in names and b in names}
    if not edges:
        return None, []

    sep = "." if language == "Python" else "/"
    # Drop package __init__ nodes that only re-export (keeps the picture clean)
    pkg_only = {n for n in names if any(o.startswith(n + sep) for o in names)}
    edges = {(a, b) for a, b in edges if a not in pkg_only and b not in pkg_only}
    used = {n for e in edges for n in e}
    indeg: dict[str, int] = defaultdict(int)
    for _, b in edges:
        indeg[b] += 1
    hub_min = max(4, int(len(used) * 0.4))
    shared = sorted(n for n, d in indeg.items() if d >= hub_min)
    if shared and len(edges) > 25:
        edges = {(a, b) for a, b in edges if b not in shared and a not in shared}
        used = {n for e in edges for n in e}
    else:
        shared = []

    def group_of(name: str) -> str:
        return name.rsplit(sep, 1)[0] if sep in name else ""

    if len(used) > max_nodes or len(edges) > 45:  # too big: collapse to folder level
        collapse = lambda n: group_of(n) or n  # noqa: E731
        edges = {(collapse(a), collapse(b)) for a, b in edges if collapse(a) != collapse(b)}
        used = {n for e in edges for n in e}
        if not edges:
            return None, shared

    groups: dict[str, list[str]] = defaultdict(list)
    for n in sorted(used):
        groups[group_of(n)].append(n)
    lines = ["flowchart LR"]
    for g, members in groups.items():
        indent = "    "
        if g and len(groups) > 1:
            lines.append(f"    subgraph {safe_id('grp_' + g)}[{label(g.replace('.', '/') + '/')}]")
            indent = "        "
        for n in members:
            short = n.rsplit(sep, 1)[-1]
            lines.append(f"{indent}{safe_id(n)}[{label(short)}]")
        if g and len(groups) > 1:
            lines.append("    end")
    # Bundle arrows: if most files in a folder import the same module, draw ONE arrow from the folder
    # (and the same the other way round), otherwise a folder of routers turns into a hairball.
    bundled: set[tuple[str, str]] = set()  # mermaid ids
    if len(groups) > 1:
        for g, members in groups.items():
            if not g or len(members) < 3:
                continue
            gid = safe_id("grp_" + g)
            for t in sorted({b for a, b in edges if a in members and b not in members}):
                users = [a for a in members if (a, t) in edges]
                if len(users) * 2 >= len(members):
                    bundled.add((gid, safe_id(t)))
                    edges -= {(a, t) for a in users}
            for src in sorted({a for a, b in edges if b in members and a not in members}):
                if group_of(src).startswith(g + sep):
                    continue  # a file inside a subfolder of g: keep its arrows specific
                targets = [b for b in members if (src, b) in edges]
                if len(targets) >= 3 and len(targets) * 4 >= len(members) * 3:
                    bundled.add((safe_id(src), gid))
                    edges -= {(src, b) for b in targets}
    for a, b in sorted(edges):
        lines.append(f"    {safe_id(a)} --> {safe_id(b)}")
    for a, b in sorted(bundled):
        lines.append(f"    {a} --> {b}")
    return "\n".join(lines), shared


def routes_diagram(rm: RepoMap, max_routes: int = 25) -> str | None:
    """Mind-map style picture of the HTTP API, grouped by first path segment."""
    if not rm.routes:
        return None
    groups: dict[str, list] = defaultdict(list)
    for r in rm.routes[:max_routes]:
        segs = [s for s in r.path.split("/") if s and s != "api"]
        groups[segs[0] if segs else "root"].append(r)
    lines = ["flowchart LR", f"    API[{label(rm.name + ' API')}]"]
    for g, routes in groups.items():
        gid = safe_id("g_" + g)
        lines.append(f"    API --> {gid}[{label('/' + g if g != 'root' else '/')}]")
        for i, r in enumerate(routes):
            rid = safe_id(f"r_{g}_{i}")
            lines.append(f"    {gid} --> {rid}[{label(r.method + ' ' + r.path + (' 🔒' if r.auth else ''))}]")
    return "\n".join(lines)


_FENCE = re.compile(r"^```(?:mermaid)?\s*|\s*```$", re.M)
_SQUARE_LABEL = re.compile(r'(\b[A-Za-z_][\w-]*)\[(?!["(\[/\\])([^\]\n"]*?[(){}<>|#;:&,/][^\]\n"]*?)\]')
_ROUND_LABEL = re.compile(r'(\b[A-Za-z_][\w-]*)\((?![("\[])([^)\n"]*?[\[\]{}<>|#;:&,/][^)\n"]*?)\)')


def clean(code: str) -> str:
    """Fix the mistakes LLMs make most often."""
    code = _FENCE.sub("", code.strip()).strip()
    first = code.splitlines()[0].strip() if code else ""
    if first.startswith(("flowchart", "graph")):
        out = []
        for line in code.splitlines():
            line = _SQUARE_LABEL.sub(lambda m: f'{m[1]}["{m[2].strip()}"]', line)
            line = _ROUND_LABEL.sub(lambda m: f'{m[1]}("{m[2].strip()}")', line)
            # edge labels with special characters: A -->|text (x)| B
            line = re.sub(r"\|([^|\"\n]*[(){}\[\]][^|\"\n]*)\|", lambda m: f'|"{m[1]}"|', line)
            out.append(line)
        code = "\n".join(out)
    return code


def problems(code: str) -> list[str]:
    """Cheap structural checks. Returns a list of problems (empty = looks OK)."""
    errs = []
    lines = [ln for ln in code.splitlines() if ln.strip() and not ln.strip().startswith("%%")]
    if not lines:
        return ["diagram is empty"]
    head = lines[0].strip().split()[0]
    if head not in DIAGRAM_TYPES:
        errs.append(f"first line must start with a diagram type (e.g. 'flowchart TD'), got '{lines[0][:40]}'")
    body = "\n".join(lines[1:])
    for o, c in ("[]", "()", "{}"):
        stripped = re.sub(r'"[^"\n]*"', "", body)
        if stripped.count(o) != stripped.count(c):
            errs.append(f"unbalanced '{o}{c}' brackets")
    if body.count('"') % 2:
        errs.append("unbalanced double quotes")
    if head in ("flowchart", "graph"):
        opens = sum(1 for ln in lines if ln.strip().startswith("subgraph"))
        ends = sum(1 for ln in lines if ln.strip() == "end")
        if opens != ends:
            errs.append(f"{opens} 'subgraph' but {ends} 'end'")
        for ln in lines[1:]:
            if re.match(r"\s*end\s*[\[(-]", ln):
                errs.append("'end' cannot be used as a node id")
                break
    if head == "sequenceDiagram":
        for ln in lines[1:]:
            s = ln.strip()
            if s and not re.match(r"(participant|actor|autonumber|note|loop|alt|else|opt|par|and|end|rect|"
                                  r"critical|break|activate|deactivate|box|title|[\w\" ]+\s*-{1,2}[>x)]{1,2}[+-]?)",
                                  s, re.I):
                errs.append(f"unrecognised sequence line: '{s[:60]}'")
                break
    if len(lines) > 90:
        errs.append("diagram is too large to read (over 90 lines)")
    return errs


def mmdc_check(code: str, timeout: int = 60) -> str | None:
    """If the official Mermaid CLI (`mmdc`) is installed, use it for a real render test.

    Returns an error message, or None if it rendered (or mmdc isn't available)."""
    exe = shutil.which("mmdc")
    if not exe:
        return None
    with tempfile.TemporaryDirectory() as d:
        src, out = Path(d) / "d.mmd", Path(d) / "d.svg"
        src.write_text(code, encoding="utf-8")
        cfg = Path(d) / "p.json"
        cfg.write_text('{"args": ["--no-sandbox"]}')
        try:
            r = subprocess.run([exe, "-i", str(src), "-o", str(out), "-p", str(cfg), "-q"],
                               capture_output=True, text=True, timeout=timeout)
        except (subprocess.TimeoutExpired, OSError):
            return None
        if r.returncode != 0 or not out.exists():
            msg = (r.stderr or r.stdout).strip().splitlines()
            return next((m for m in msg if "Error" in m or "error" in m), msg[0] if msg else "render failed")[:300]
    return None


def validate(code: str, use_mmdc: bool = True) -> tuple[str, list[str]]:
    """Clean the diagram, then check it. Returns (cleaned_code, problems)."""
    code = clean(code)
    errs = problems(code)
    if not errs and use_mmdc:
        e = mmdc_check(code)
        if e:
            errs.append(e)
    return code, errs
