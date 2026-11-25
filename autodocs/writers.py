"""Turn the RepoMap (exact facts) and the agent's notes (understanding) into three documents.

Rule of thumb used everywhere: anything that can be copied from the code IS copied from
the code (file tree, env vars, endpoint paths, parameters, signatures, curl examples).
The LLM writes only the parts that need judgement: explanations, summaries and diagrams.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

from autodocs import mermaid
from autodocs.llm import LLM, LLMError, chat_json
from autodocs.models import RepoMap, Route

STYLE = """Style rules (follow strictly):
- Plain, direct English. Short sentences. Active voice. Address the reader as "you".
- Sentence-case headings ("Quick start", not "Quick Start").
- No marketing words: seamless, powerful, robust, cutting-edge, revolutionary, effortless, blazing, leverage.
- No emojis in headings. No invented badges, URLs, version numbers, screenshots or contact details.
- Only mention files, commands, endpoints and settings that appear in the facts you were given.
- If something is unknown, leave it out rather than guessing."""

PRIMITIVES = {"str", "int", "float", "bool", "bytes", "dict", "list", "None", "Any", "date", "datetime", "UUID"}


# --------------------------------------------------------------------------- helpers

def _code_snippet(root: Path, rel: str, line: int, max_lines: int = 45) -> str:
    try:
        lines = (root / rel).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    start = line - 1
    while start > 0 and lines[start - 1].lstrip().startswith("@"):
        start -= 1  # include decorators
    out = [lines[start]] if start < len(lines) else []
    for ln in lines[start + 1: start + max_lines]:
        if ln and not ln[0].isspace() and not ln.startswith((")", "]", "}")) and len(out) > 2:
            break  # next top-level definition
        out.append(ln)
    return "\n".join(out)


def src_link(rm: RepoMap, path: str, line: int | None = None) -> str:
    """Link to a file (and line). Absolute GitHub links work wherever the docs end up."""
    anchor = f"#L{line}" if line else ""
    return f"{rm.url}/blob/HEAD/{path}{anchor}" if rm.url else f"{path}{anchor}"


def _humanize(handler: str) -> str:
    words = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", handler).replace("_", " ").strip()
    return words[:1].upper() + words[1:] if words and not words.startswith("(") else ""


def classify_params(route: Route) -> dict[str, list[tuple[str, str]]]:
    """Split a FastAPI/Flask handler's parameters into path / query / body / file / form."""
    path_names = set(re.findall(r"[{<](?:\w+:)?(\w+)[}>]", route.path)) | set(re.findall(r":(\w+)", route.path))
    out: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for p in route.params:
        if "OAuth2PasswordRequestForm" in p:  # FastAPI's standard login form
            out["form"] += [("username", "str"), ("password", "str")]
            continue
        if "Depends(" in p or "Security(" in p:
            continue
        name, _, rest = p.partition(":")
        name = name.split("=")[0].strip()
        ann = rest.split("=")[0].strip() if rest else ""
        default = p.split("=", 1)[1].strip() if "=" in p else ""
        if name in ("request", "response", "background_tasks", "db", "session"):
            continue
        if name in path_names:
            out["path"].append((name, ann or "string"))
        elif "UploadFile" in ann or default.startswith("File("):
            out["file"].append((name, ann))
        elif default.startswith("Form("):
            out["form"].append((name, ann))
        elif ann and ann.split("[")[0].split("|")[0].strip() not in PRIMITIVES and ann[:1].isupper() \
                and not default.startswith(("Query(", "Header(", "Cookie(")):
            out["body"].append((name, ann))
        else:
            req = "required" if not default else f"default `{default}`"
            out["query"].append((name, f"{ann or 'string'}, {req}"))
    for n in path_names:  # Express routes: no signature, but path params are still known
        if all(n != x for x, _ in out["path"]):
            out["path"].append((n, "string"))
    return out


def base_url(rm: RepoMap) -> str:
    for c in rm.run_commands:
        if c.startswith("uvicorn"):
            return "http://localhost:8000"
        if c.startswith("flask"):
            return "http://localhost:5000"
    if any(r.framework == "Express" for r in rm.routes):
        return "http://localhost:3000"
    return "http://localhost:8000"


def _cell(text: str) -> str:
    """Make text safe inside a Markdown table cell."""
    return str(text).replace("|", "\\|").replace("\n", " ")


def _field_rules(default: str) -> tuple[str, str]:
    """('Yes'/'No (default x)', 'min_length=1, ...') from a model field's default value."""
    if not default:
        return "Yes", ""
    m = re.match(r"^Field\((.*)\)$", default, re.S)
    if not m:
        return f"No (default `{default}`)", ""
    args = [a.strip() for a in re.split(r",(?![^()\[\]]*[)\]])", m[1]) if a.strip()]
    dflt = next((a.split("=", 1)[1] for a in args if a.startswith("default=")), None)
    if dflt is None and args and "=" not in args[0] and args[0] != "...":
        dflt = args[0]
    rules = ", ".join(f"`{a}`" for a in args if "=" in a and not a.startswith(("default=", "description=")))
    return ("Yes" if dflt is None else f"No (default `{dflt}`)"), rules


def _example_value(name: str, typ: str, default: str):
    t = typ.replace(" ", "")
    if default.startswith("Field("):
        d = _field_rules(default)[0]
        default = d.split("`")[1] if "`" in d else ""
    if default and default not in ("None", "...") and not default.startswith("field("):
        try:
            return json.loads(default.replace("'", '"').replace("True", "true").replace("False", "false"))
        except json.JSONDecodeError:
            pass
    if "Email" in t or "email" in name:
        return "you@example.com"
    if "password" in name:
        return "a-strong-password"
    if t.startswith(("int", "Optional[int")) or t == "int|None":
        return 1
    if t.startswith(("float", "Optional[float")):
        return 0.5
    if t.startswith(("bool", "Optional[bool")):
        return True
    if t.startswith(("list", "List", "tuple", "set")):
        return []
    if t.startswith(("dict", "Dict")):
        return {}
    return name.replace("_", " ")


def example_body_from_schema(rm: RepoMap, model: str) -> str:
    fields = rm.schemas.get(model.split("|")[0].strip())
    if not fields:
        return ""
    return json.dumps({f: _example_value(f, t, d) for f, t, d in fields[:12]})


def curl_example(route: Route, rm: RepoMap, example_body: str = "") -> str:
    if route.method == "WS":
        return ""
    path = re.sub(r"[{<](?:\w+:)?(\w+)[}>]", lambda m: "1" if "id" in m[1] else f"<{m[1]}>", route.path)
    path = re.sub(r":(\w+)", lambda m: "1" if "id" in m[1] else f"<{m[1]}>", path)
    url = base_url(rm) + path
    parts = ["curl"]
    if route.method not in ("GET", "ANY"):
        parts.append(f"-X {route.method}")
    parts.append(f'"{url}"')
    if route.auth:
        parts.append('-H "Authorization: Bearer $TOKEN"')
    p = classify_params(route)
    for name, _ in p["file"]:
        parts.append(f'-F "{name}=@path/to/file"')
    for name, _ in p["form"]:
        parts.append(f'-F "{name}=<{name}>"')
    if p["body"] and not p["file"] and not p["form"]:
        schema_body = example_body_from_schema(rm, p["body"][0][1])
        body = schema_body or (example_body.strip() if example_body.strip().startswith("{") else "{ ... }")
        body = " ".join(body.split())
        parts.append('-H "Content-Type: application/json"')
        parts.append(f"-d '{body}'")
    head_n = 3 if route.method not in ("GET", "ANY") else 2
    head, rest = " ".join(parts[:head_n]), parts[head_n:]
    return " \\\n  ".join([head, *rest])


def env_table(rm: RepoMap, descriptions: dict[str, str] | None = None, limit: int = 40) -> str:
    if not rm.env_vars:
        return ""
    descriptions = descriptions or {}
    rows = ["| Variable | Default | What it does |", "|---|---|---|"]
    for e in rm.env_vars[:limit]:
        default = f"`{e.default}`" if e.default else "*(none)*"
        desc = descriptions.get(e.name) or e.comment or ""
        rows.append(f"| `{e.name}` | {_cell(default)} | {_cell(desc[:140])} |")
    src = sorted({e.source for e in rm.env_vars if e.source.startswith(".env")})
    note = f"\n\nCopy `{src[0]}` to `.env` and fill in your values." if src else ""
    return "\n".join(rows) + note


def routes_table(rm: RepoMap, link: str = "API.md") -> str:
    if not rm.routes:
        return ""
    rows = ["| Method | Path | Login needed |", "|---|---|---|"]
    for r in rm.routes:
        rows.append(f"| `{r.method}` | `{r.path}` | {'Yes' if r.auth else 'No'} |")
    return "\n".join(rows) + f"\n\nFull details and examples are in [{link}]({link})."


def _replace_placeholder(md: str, key: str, content: str, heading: str) -> str:
    token = "{{" + key + "}}"
    if token in md:
        return md.replace(token, content if content else "")
    if content:
        return md.rstrip() + f"\n\n## {heading}\n\n{content}\n"
    return md


def _strip_fences(md: str) -> str:
    md = md.strip()
    m = re.match(r"^```(?:markdown|md)?\s*\n(.*)\n```\s*$", md, re.S)
    return m.group(1) if m else md


def facts_block(rm: RepoMap) -> str:
    files = rm.file_paths()
    present = [f for f in ("requirements.txt", "pyproject.toml", "package.json", "Dockerfile", "docker-compose.yml",
                           ".env.example", "Makefile", "setup.py") if f in files]
    return json.dumps({
        "repo_name": rm.name, "repo_url": rm.url, "primary_language": rm.primary_language(),
        "files_present_at_root": present, "run_commands_found": rm.run_commands,
        "scripts": rm.scripts, "has_tests": rm.has_tests, "license": rm.license,
        "env_vars": [e.name for e in rm.env_vars][:40], "route_count": len(rm.routes),
    }, indent=1)


# --------------------------------------------------------------------------- README

README_PROMPT = """Write README.md for this repository.

{style}

Use this structure (skip a section if you have nothing true to say):
# <Project name>
One-sentence summary in bold-free plain text, then a short paragraph: what it does and who it's for.
## Features            (bullets, user-visible capabilities only)
## How it works        (3-6 numbered steps of the main flow; link to ARCHITECTURE.md for diagrams)
## Tech stack          (bullets, from the dependencies)
## Quick start         (numbered steps with ```bash code blocks; ONLY commands from the facts or notes)
## Configuration       (put the placeholder {{{{CONFIGURATION}}}} on its own line here)
## Usage               (how to use it once running; examples)
## API                 (only if there are HTTP routes: one sentence, then the placeholder {{{{API_SUMMARY}}}})
## Project structure   (one sentence, then the placeholder {{{{PROJECT_STRUCTURE}}}})
## Running tests       (only if tests exist)
## License             (only if a license was found)

Placeholders are filled in automatically with exact tables taken from the code: write each one exactly
once, on its own line, and don't write those tables yourself.
For "git clone", use the repo URL from the facts. If the repo has a .env.example, tell the reader to copy it.
Return ONLY the Markdown.

FACTS (exact, from static analysis):
{facts}

AGENT NOTES (from reading the code):
{notes}

REPOSITORY SUMMARY:
{summary}"""


def write_readme(llm: LLM, rm: RepoMap, notes: dict, summary: str, env_desc: dict[str, str]) -> str:
    prompt = README_PROMPT.format(style=STYLE, facts=facts_block(rm), notes=json.dumps(notes, indent=1)[:6000],
                                  summary=summary[:7000])
    md = _strip_fences(llm.chat([{"role": "user", "content": prompt}], temperature=0.3, max_tokens=5000))
    return fill_readme_placeholders(md, rm, env_desc)


def fill_readme_placeholders(md: str, rm: RepoMap, env_desc: dict[str, str]) -> str:
    md = _replace_placeholder(md, "CONFIGURATION", env_table(rm, env_desc), "Configuration")
    md = _replace_placeholder(md, "API_SUMMARY", routes_table(rm), "API")
    md = _replace_placeholder(md, "PROJECT_STRUCTURE", f"```text\n{rm.name}/\n{rm.tree}\n```", "Project structure")
    return md.strip() + "\n"


def describe_env_vars(llm: LLM, rm: RepoMap, root: Path) -> dict[str, str]:
    """One short description per setting that doesn't already have a comment."""
    todo = [e for e in rm.env_vars[:40] if not e.comment]
    if not todo:
        return {}
    usages = []
    for e in todo:
        snippet = ""
        try:
            text = (root / e.source).read_text(encoding="utf-8", errors="replace")
            i = text.find(e.name if not e.source.endswith(".py") else e.name.lower())
            snippet = text[max(0, i - 80): i + 160].replace("\n", " ") if i >= 0 else ""
        except OSError:
            pass
        usages.append(f"- {e.name} (default {e.default or 'none'}; found in {e.source}): {snippet}")
    prompt = ("For each setting, write a short description (max 12 words) of what it controls, based on the "
              "evidence. Return JSON {\"NAME\": \"description\"}. Use \"\" if the evidence isn't enough.\n\n"
              + "\n".join(usages))
    try:
        data = chat_json(llm, [{"role": "user", "content": prompt}], max_tokens=2000)
        return {k: str(v).strip().rstrip(".") for k, v in data.items() if isinstance(v, str) and v.strip()}
    except LLMError:
        return {}


# --------------------------------------------------------------------------- API docs

API_PROMPT = """You are documenting HTTP endpoints. For each endpoint below you get its handler source code.
Return JSON: {{"<METHOD path>": {{"summary": "max 10 words, starts with a verb",
 "description": "1-3 sentences: what it does, side effects, important rules",
 "example_body": "a small realistic JSON request body as a string, or \\"\\" if there is no JSON body",
 "response": "what a successful response contains (1-2 sentences)",
 "errors": ["<status code>: <when it happens>", ...]}}}}
Only describe behaviour visible in the code (including HTTPException / status codes raised).
{style}

{items}"""

SYMBOL_PROMPT = """You are writing a Python/JS API reference. For each item, using its source code, return JSON:
{{"<id>": {{"summary": "one sentence: what it does", "details": "optional 1-2 sentences on params, return value or errors"}}}}
{style}

{items}"""


def _batched(items: list[tuple[str, str]], budget: int = 12_000) -> list[list[tuple[str, str]]]:
    batches, cur, size = [], [], 0
    for key, text in items:
        if cur and size + len(text) > budget:
            batches.append(cur)
            cur, size = [], 0
        cur.append((key, text))
        size += len(text)
    if cur:
        batches.append(cur)
    return batches


def annotate_routes(llm: LLM, rm: RepoMap, root: Path, on_event=None) -> dict[str, dict]:
    items = [(r.id, f"### {r.id}\nHandler {r.handler} in {r.file}:{r.line}\n```\n{_code_snippet(root, r.file, r.line)}\n```")
             for r in rm.routes[:60]]
    out: dict[str, dict] = {}
    for batch in _batched(items):
        if on_event:
            on_event(f"Describing {len(batch)} endpoints")
        prompt = API_PROMPT.format(style=STYLE, items="\n\n".join(t for _, t in batch))
        try:
            data = chat_json(llm, [{"role": "user", "content": prompt}], max_tokens=6000)
            out.update({k: v for k, v in data.items() if isinstance(v, dict)})
        except LLMError as e:
            if on_event:
                on_event(f"Could not describe some endpoints: {str(e)[:100]}")
    return out


def annotate_symbols(llm: LLM, rm: RepoMap, root: Path, limit: int = 50) -> dict[str, dict]:
    syms = [s for s in rm.symbols if s.kind in ("function", "class") and "test" not in s.path.lower()][:limit]
    items = [(s.id, f"### {s.id}\n```\n{_code_snippet(root, s.path, s.line, 30)}\n```") for s in syms]
    out: dict[str, dict] = {}
    for batch in _batched(items):
        prompt = SYMBOL_PROMPT.format(style=STYLE, items="\n\n".join(t for _, t in batch))
        try:
            data = chat_json(llm, [{"role": "user", "content": prompt}], max_tokens=5000)
            out.update({k: v for k, v in data.items() if isinstance(v, dict)})
        except LLMError:
            pass
    return out


def render_api_doc(rm: RepoMap, route_notes: dict[str, dict], symbol_notes: dict[str, dict]) -> str:
    lines = [f"# {rm.name} API reference", ""]
    if rm.routes:
        lines += _render_routes(rm, route_notes)
    else:
        lines += ["This project has no HTTP endpoints, so this page documents its public functions and classes.", ""]
    lines += _render_symbols(rm, symbol_notes, heading_level=2 if not rm.routes else 2)
    lines.append("---\n*Generated by [Auto-Docs Agent](https://github.com/gideonswer/auto-docs-agent). "
                 "Endpoint paths, parameters and source links are read from the code; descriptions are AI-written "
                 "and should be reviewed.*")
    return "\n".join(lines).strip() + "\n"


def _render_routes(rm: RepoMap, notes: dict[str, dict]) -> list[str]:
    any_auth = any(r.auth for r in rm.routes)
    lines = [f"Base URL when running locally: `{base_url(rm)}`", ""]
    if any_auth:
        lines += ["## Authentication", "",
                  "Endpoints marked **Login needed** expect a token in the `Authorization` header:", "",
                  "```http\nAuthorization: Bearer <your token>\n```", ""]
        login = next((r for r in rm.routes if re.search(r"login|token|signin", r.path, re.I)), None)
        if login:
            lines += [f"Get a token from `{login.method} {login.path}`.", ""]
    groups: dict[str, list[Route]] = defaultdict(list)
    for r in rm.routes:
        segs = [s for s in r.path.split("/") if s and s != "api" and not s.startswith(("{", "<", ":"))]
        groups[segs[0] if segs else "General"].append(r)

    lines += ["## Endpoints", "", "| Method | Path | Summary | Login needed |", "|---|---|---|---|"]
    for r in rm.routes:
        s = notes.get(r.id, {}).get("summary") or r.doc or _humanize(r.handler)
        anchor = re.sub(r"[^a-z0-9 -]", "", f"{r.method} {r.path}".lower()).replace(" ", "-")
        lines.append(f"| `{r.method}` | [`{r.path}`](#{anchor}) | {_cell(s)} | {'Yes' if r.auth else 'No'} |")
    lines.append("")

    for g, routes in groups.items():
        lines += [f"## {g.replace('-', ' ').replace('_', ' ').capitalize()}", ""]
        for r in routes:
            n = notes.get(r.id, {})
            lines += [f"### {r.method} {r.path}", ""]
            if n.get("summary") or r.doc:
                lines += [str(n.get("summary") or r.doc), ""]
            if n.get("description"):
                lines += [str(n["description"]), ""]
            lines += [f"- **Login needed:** {'Yes' if r.auth else 'No'}",
                      f"- **Source:** [`{r.file}` line {r.line}]({src_link(rm, r.file, r.line)}) (`{r.handler}`)", ""]
            p = classify_params(r)
            table = []
            for kind, label in (("path", "path"), ("query", "query"), ("body", "JSON body"),
                                ("file", "file upload"), ("form", "form field")):
                for name, typ in p.get(kind, []):
                    table.append(f"| `{name}` | {label} | `{_cell(typ)}` |" if kind != "query" else
                                 f"| `{name}` | {label} | {_cell(typ)} |")
            if table:
                lines += ["| Parameter | In | Type |", "|---|---|---|", *table, ""]
            for _, model in p.get("body", []):
                fields = rm.schemas.get(model.split("|")[0].strip())
                if fields:
                    lines += [f"`{model}` fields:", "", "| Field | Type | Required | Rules |", "|---|---|---|---|"]
                    for f, t, d in fields:
                        req, rules = _field_rules(d)
                        lines.append(f"| `{f}` | `{_cell(t)}` | {req} | {_cell(rules)} |")
                    lines.append("")
            ex = curl_example(r, rm, str(n.get("example_body", "")))
            if ex:
                lines += ["**Example request**", "", "```bash", ex, "```", ""]
            if n.get("response"):
                lines += [f"**Response:** {n['response']}", ""]
            errs = [e for e in n.get("errors", []) if isinstance(e, str)]
            if errs:
                lines += ["**Errors**", "", *[f"- {e}" for e in errs], ""]
    return lines


def _render_symbols(rm: RepoMap, notes: dict[str, dict], heading_level: int = 2, limit: int = 60) -> list[str]:
    handlers = {(r.file, r.line) for r in rm.routes}
    syms = [s for s in rm.symbols if "test" not in s.path.lower() and (s.path, s.line) not in handlers]
    if not syms:
        return []
    h = "#" * heading_level
    lines = [f"{h} Code reference", "", "Public functions and classes, grouped by file.", ""]
    by_file: dict[str, list] = defaultdict(list)
    for s in syms[:limit * 2]:
        by_file[s.path].append(s)
    shown = 0
    for path, items in by_file.items():
        if shown >= limit:
            lines += [f"*{len(syms) - shown} more items not shown.*", ""]
            break
        mod_doc = next((m.doc for m in rm.modules if m.path == path and m.doc), "")
        lines += [f"{h}# `{path}`", ""] + ([mod_doc, ""] if mod_doc else [])
        for s in items:
            if s.kind == "method":
                continue
            n = notes.get(s.id, {})
            lines += [f"**`{s.signature}`** ([line {s.line}]({src_link(rm, path, s.line)}))", ""]
            text = n.get("summary") or s.doc
            if text:
                lines += [str(text) + (" " + str(n["details"]) if n.get("details") else ""), ""]
            methods = [m for m in items if m.kind == "method" and m.parent == s.name]
            if methods:
                lines += ["Methods: " + ", ".join(f"`{m.name}()`" for m in methods[:15]), ""]
            shown += 1
    return lines


# --------------------------------------------------------------------------- Architecture

ARCH_PROMPT = """Describe the architecture of this repository for a developer who is new to it.

{style}

Return JSON:
{{
 "overview": "2 short paragraphs of Markdown: the big picture and the main data flow",
 "component_diagram": "Mermaid 'flowchart TD' showing the main components, external services and data stores, max 15 nodes",
 "sequence_title": "name of the most important flow, e.g. 'Asking a question'",
 "sequence_diagram": "Mermaid 'sequenceDiagram' of that flow, max 12 messages",
 "design_decisions": ["a design choice visible in the code and why it helps", "..."]
}}

Mermaid rules: put every label in double quotes, e.g. A["Web UI (browser)"]; use simple ids (letters, digits, _);
never use 'end' as an id; database nodes look like DB[("SQLite")]; no styling or classDef lines.
Base everything on the notes and facts. Don't invent components.

AGENT NOTES:
{notes}

FACTS:
{facts}

DEPENDENCY DIAGRAM FROM IMPORTS (for reference):
{graph}

SUMMARY:
{summary}"""


def _fix_diagram(llm: LLM, code: str, errs: list[str], kind: str) -> tuple[str, list[str]]:
    prompt = (f"This Mermaid {kind} has problems: {'; '.join(errs)}\nFix it and return JSON "
              f'{{"diagram": "<fixed mermaid>"}}. Quote every label.\n\n{code}')
    try:
        fixed = chat_json(llm, [{"role": "user", "content": prompt}], max_tokens=2500).get("diagram", "")
    except LLMError:
        return code, errs
    return mermaid.validate(str(fixed))


def write_architecture(llm: LLM | None, rm: RepoMap, notes: dict, summary: str, log=None) -> tuple[str, list[str]]:
    """Returns (markdown, warnings)."""
    warnings: list[str] = []
    graph, shared = mermaid.module_graph(rm)
    data: dict = {}
    if llm is not None:
        prompt = ARCH_PROMPT.format(style=STYLE, notes=json.dumps(notes, indent=1)[:6000], facts=facts_block(rm),
                                    graph=(graph or "(none)")[:2500], summary=summary[:5000])
        try:
            data = chat_json(llm, [{"role": "user", "content": prompt}], max_tokens=5000)
        except LLMError as e:
            warnings.append(f"Architecture overview could not be written: {e}")
    diagrams = {}
    for key, kind in (("component_diagram", "flowchart"), ("sequence_diagram", "sequenceDiagram")):
        code = str(data.get(key, "")).strip()
        if not code:
            continue
        code, errs = mermaid.validate(code)
        if errs and llm is not None:
            if log:
                log(f"Repairing {kind}: {errs[0][:80]}")
            code, errs = _fix_diagram(llm, code, errs, kind)
        if errs:
            warnings.append(f"Dropped the AI-drawn {kind} because it would not render: {'; '.join(errs)[:200]}")
        else:
            diagrams[key] = code

    lines = [f"# {rm.name} architecture", ""]
    overview = str(data.get("overview", "")).strip()
    if overview:
        lines += [overview, ""]
    elif notes.get("purpose"):
        lines += [notes["purpose"], ""]
    if "component_diagram" in diagrams:
        lines += ["## Components", "", "```mermaid", diagrams["component_diagram"], "```", ""]
    comps = notes.get("components") or []
    if comps:
        lines += ["| Component | Where | Responsibility |", "|---|---|---|"]
        for c in comps:
            where = ", ".join(f"`{p}`" for p in c.get("paths", [])[:3])
            lines.append(f"| {c['name']} | {where} | {c.get('responsibility', '')} |")
        lines.append("")
    if "sequence_diagram" in diagrams:
        title = str(data.get("sequence_title") or "Main flow").strip()
        lines += [f"## {title[:1].upper() + title[1:]}", "", "```mermaid", diagrams["sequence_diagram"], "```", ""]
    steps = notes.get("how_it_works") or []
    if steps and "sequence_diagram" not in diagrams:
        lines += ["## How it works", "", *[f"{i}. {s}" for i, s in enumerate(steps, 1)], ""]
    langs = mermaid.graph_languages(rm)[:2]
    for i, lang in enumerate(langs):
        g, sh = (graph, shared) if i == 0 else mermaid.module_graph(rm, language=lang)
        if not g:
            continue
        title = "Module dependencies" + (f" ({lang})" if len(langs) > 1 else "")
        lines += [f"## {title}", "",
                  "Drawn from the import statements in the code, so it is always accurate. "
                  "An arrow means \"imports\".", "", "```mermaid", g, "```", ""]
        if sh:
            lines += ["Left out to keep the picture readable, because most modules use them: "
                      + ", ".join(f"`{x}`" for x in sh) + ".", ""]
    rd = mermaid.routes_diagram(rm)
    if rd:
        lines += ["## HTTP API map", "", "🔒 = login needed. Details are in [API.md](API.md).", "",
                  "```mermaid", rd, "```", ""]
    deps = rm.dependencies
    if deps:
        lines += ["## Dependencies", ""]
        for eco, pkgs in deps.items():
            lines.append(f"- **{eco}:** " + ", ".join(f"`{p}`" for p in pkgs[:30]))
        lines.append("")
    decisions = [d for d in data.get("design_decisions", []) if isinstance(d, str)]
    if decisions:
        lines += ["## Design decisions", "", *[f"- {d}" for d in decisions], ""]
    lines.append("---\n*Generated by [Auto-Docs Agent](https://github.com/gideonswer/auto-docs-agent). "
                 "The dependency diagram and API map come straight from the code; the other diagrams are AI-drawn "
                 "and checked to render.*")
    return "\n".join(lines).strip() + "\n", warnings


# --------------------------------------------------------------------------- offline mode (no LLM)

def offline_notes(rm: RepoMap) -> dict:
    readme = next((v for k, v in rm.key_files.items() if k.lower() == "readme.md"), "")
    paras = [p.strip() for p in re.split(r"\n\s*\n", readme) if p.strip() and not p.strip().startswith(("#", "[!", "!["))]
    purpose = paras[0] if paras else next((m.doc for m in rm.modules if m.doc), "")
    comps, seen = [], set()
    for m in rm.modules:
        if m.doc and "test" not in m.path.lower() and m.path not in seen:
            seen.add(m.path)
            comps.append({"name": m.name.rsplit(".", 1)[-1].rsplit("/", 1)[-1], "paths": [m.path], "responsibility": m.doc})
    return {"purpose": " ".join(purpose.split())[:600], "features": [], "how_it_works": [], "components": comps[:15],
            "external_services": [], "setup_steps": [], "run_commands": rm.run_commands, "usage_examples": [],
            "gotchas": []}


def offline_readme(rm: RepoMap, notes: dict) -> str:
    files = rm.file_paths()
    lines = [f"# {rm.name}", ""]
    if notes.get("purpose"):
        lines += [notes["purpose"], ""]
    if rm.dependencies:
        lines += ["## Tech stack", ""] + [f"- **{k}:** {', '.join(v[:12])}" for k, v in rm.dependencies.items()] + [""]
    steps: list[tuple[str, str]] = []
    if rm.url:
        steps.append(("Get the code", f"git clone {rm.url}.git\ncd {rm.name}"))
    if "requirements.txt" in files:
        steps.append(("Install the dependencies in a virtual environment",
                      "python -m venv .venv\n# Windows: .venv\\Scripts\\activate   macOS/Linux: source .venv/bin/activate\n"
                      "pip install -r requirements.txt"))
    elif "pyproject.toml" in files:
        steps.append(("Install the package", "pip install -e ."))
    if "package.json" in files:
        steps.append(("Install the dependencies", "npm install"))
    env_src = next((e.source for e in rm.env_vars if e.source.startswith(".env.")), None)
    if env_src:
        steps.append(("Create your settings file, then fill in your values", f"cp {env_src} .env"))
    if rm.run_commands:
        steps.append(("Start it", rm.run_commands[0]))
    if steps:
        lines += ["## Quick start", ""]
        for i, (title, cmd) in enumerate(steps, 1):
            lines += [f"{i}. {title}:", "", "   ```bash", *["   " + ln for ln in cmd.splitlines()], "   ```", ""]
    md = "\n".join(lines)
    md += "\n## Configuration\n\n{{CONFIGURATION}}\n" if rm.env_vars else ""
    md += "\n## API\n\n{{API_SUMMARY}}\n" if rm.routes else ""
    md += f"\n## Project structure\n\n{{{{PROJECT_STRUCTURE}}}}\n"
    md += "\n## Architecture\n\nSee [ARCHITECTURE.md](ARCHITECTURE.md) for diagrams.\n"
    if rm.has_tests:
        md += "\n## Running tests\n\n```bash\npytest\n```\n" if rm.primary_language() == "Python" else ""
    if rm.license:
        md += f"\n## License\n\n{rm.license}. See `LICENSE`.\n" if "LICENSE" in files else f"\n## License\n\n{rm.license}\n"
    md += ("\n---\n*Generated by [Auto-Docs Agent](https://github.com/gideonswer/auto-docs-agent) in offline mode "
           "(static analysis only, no AI).*\n")
    return fill_readme_placeholders(md, rm, {})
