"""Walk a repo and build a RepoMap: every fact we can get WITHOUT an LLM."""
from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

from autodocs.analyze_js import JS_EXTS, analyze_js
from autodocs.analyze_python import analyze_python, apply_include_prefixes, module_resolver
from autodocs.models import EnvVar, FileInfo, RepoMap

IGNORE_DIRS = {
    ".git", "node_modules", "venv", ".venv", "env", "__pycache__", "dist", "build", ".next",
    ".nuxt", "target", "vendor", ".idea", ".vscode", ".pytest_cache", ".mypy_cache", ".tox",
    "coverage", ".cache", "site-packages", ".ruff_cache", "out", ".turbo", ".gradle", "data",
    "chroma", "chroma_db", "uploads", ".terraform",
}
LANGS = {
    ".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript", ".go": "Go", ".rs": "Rust", ".java": "Java",
    ".kt": "Kotlin", ".rb": "Ruby", ".php": "PHP", ".cs": "C#", ".cpp": "C++", ".c": "C", ".h": "C",
    ".swift": "Swift", ".dart": "Dart", ".html": "HTML", ".css": "CSS", ".scss": "CSS", ".vue": "Vue",
    ".svelte": "Svelte", ".sql": "SQL", ".sh": "Shell", ".md": "Markdown", ".yml": "YAML",
    ".yaml": "YAML", ".toml": "TOML", ".json": "JSON", ".ipynb": "Jupyter Notebook",
}
NOT_CODE = {"Markdown", "YAML", "TOML", "JSON"}
KEY_FILE_NAMES = {
    "readme.md", "requirements.txt", "pyproject.toml", "setup.py", "setup.cfg", "package.json",
    "dockerfile", "docker-compose.yml", "docker-compose.yaml", "compose.yaml", ".env.example",
    ".env.sample", ".env.template", "makefile", "go.mod", "cargo.toml", "procfile", "manage.py",
    "contributing.md",
}
MAX_FILE_BYTES = 300_000
KEY_FILE_CHARS = 3_000


def _is_binary(p: Path) -> bool:
    try:
        return b"\0" in p.read_bytes()[:2048]
    except OSError:
        return True


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


def build_tree(paths: list[str], max_entries: int = 70, max_depth: int = 3) -> str:
    """A `tree`-style listing, folders first, trimmed so it stays readable."""
    root: dict = {}
    for p in sorted(paths):
        node = root
        parts = p.split("/")
        for i, part in enumerate(parts[:max_depth]):
            last = i == len(parts) - 1
            node = node.setdefault(part + ("" if last else "/"), {})
    lines: list[str] = []

    def walk(node: dict, prefix: str) -> None:
        items = sorted(node.items(), key=lambda kv: (not kv[0].endswith("/"), kv[0].lower()))
        for i, (name, child) in enumerate(items):
            if len(lines) >= max_entries:
                if not lines[-1].endswith("..."):
                    lines.append(prefix + "└── ...")
                return
            last = i == len(items) - 1
            lines.append(prefix + ("└── " if last else "├── ") + name)
            if child:
                walk(child, prefix + ("    " if last else "│   "))

    walk(root, "")
    return "\n".join(lines)


def parse_env_example(text: str, source: str) -> list[EnvVar]:
    out, comment = [], []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            comment = []
            continue
        if line.startswith("#"):
            body = line.lstrip("#").strip()
            m = re.match(r"^([A-Z][A-Z0-9_]+)\s*=\s*(.*)$", body)
            body = body.strip("-= ").strip()
            if not m and body:
                comment.append(body)
            continue
        m = re.match(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$", line)
        if m:
            value = m.group(2).split(" #")[0].strip().strip("'\"")
            out.append(EnvVar(m.group(1), value, " ".join(comment)[:200], source))
            comment = []
    return out


def _deps(rm: RepoMap, rel: str, text: str) -> None:
    name = rel.split("/")[-1].lower()
    try:
        if name.startswith("requirements") and name.endswith(".txt"):
            pkgs = [re.split(r"[<>=!~\[;\s#]", ln.strip())[0] for ln in text.splitlines()
                    if ln.strip() and not ln.strip().startswith(("#", "-"))]
            rm.dependencies.setdefault("Python", []).extend(p for p in pkgs if p)
        elif name == "pyproject.toml":
            data = tomllib.loads(text)
            proj = data.get("project", {})
            pkgs = [re.split(r"[<>=!~\[;\s]", d)[0] for d in proj.get("dependencies", [])]
            pkgs += list(data.get("tool", {}).get("poetry", {}).get("dependencies", {}).keys())
            rm.dependencies.setdefault("Python", []).extend(p for p in pkgs if p and p != "python")
            for script, target in proj.get("scripts", {}).items():
                rm.scripts[script] = f"{script}  (runs {target})"
        elif name == "package.json":
            data = json.loads(text)
            deps = list(data.get("dependencies", {})) + list(data.get("devDependencies", {}))
            rm.dependencies.setdefault("JavaScript", []).extend(deps)
            for s, cmd in data.get("scripts", {}).items():
                rm.scripts[f"npm run {s}"] = cmd
            if data.get("main"):
                rm.entry_points.append(f"{rel}: main = {data['main']}")
        elif name == "go.mod":
            rm.dependencies.setdefault("Go", []).extend(
                ln.split()[0] for ln in text.splitlines() if ln.startswith("\t") and ln.split())
        elif name == "cargo.toml":
            rm.dependencies.setdefault("Rust", []).extend(tomllib.loads(text).get("dependencies", {}).keys())
        elif name == "makefile":
            for t in re.findall(r"^([a-zA-Z][\w-]*):", text, re.M):
                rm.scripts[f"make {t}"] = "Makefile target"
    except (ValueError, tomllib.TOMLDecodeError):
        pass


def import_path(rel: str, files: set[str]) -> tuple[str, str]:
    """('backend', 'app.main') for backend/app/main.py when backend/ has no __init__.py but app/ does.

    That's the folder you have to run the app from, and the module name to give uvicorn."""
    parts = rel[:-3].split("/")
    i = len(parts) - 1  # index of the file itself
    while i > 0 and "/".join(parts[:i]) + "/__init__.py" in files:
        i -= 1
    root = "/".join(parts[:i])
    mod = ".".join(p for p in parts[i:] if p != "__init__")
    return root, mod


def scan_repo(root: Path, name: str, url: str | None = None) -> RepoMap:
    root = Path(root)
    rm = RepoMap(name=name, url=url, root=str(root))
    py_results = {}
    env_seen: dict[str, EnvVar] = {}

    for p in sorted(root.rglob("*")):
        rel_parts = p.relative_to(root).parts
        if any(part in IGNORE_DIRS or (part.startswith(".") and part not in (".github", ".env.example",
               ".env.sample", ".env.template")) for part in rel_parts[:-1]):
            continue
        if not p.is_file() or p.is_symlink():
            continue
        rel = "/".join(rel_parts)
        size = p.stat().st_size
        if size > MAX_FILE_BYTES or _is_binary(p):
            rm.files.append(FileInfo(rel, "Binary/large", 0, size))
            continue
        text = _read(p)
        lang = LANGS.get(p.suffix.lower(), "Dockerfile" if p.name.lower() == "dockerfile" else "Other")
        lines = text.count("\n") + 1
        rm.files.append(FileInfo(rel, lang, lines, size))
        if lang not in NOT_CODE and lang not in ("Other", "Binary/large"):
            rm.languages[lang] = rm.languages.get(lang, 0) + lines
        low = p.name.lower()

        if low in KEY_FILE_NAMES or (low.startswith("requirements") and low.endswith(".txt")):
            if len(rel_parts) <= 2:
                rm.key_files[rel] = text[:KEY_FILE_CHARS]
            _deps(rm, rel, text)
        if low.startswith(".env.") and low != ".env":
            for ev in parse_env_example(text, rel):
                env_seen[ev.name] = ev
        if low in ("license", "license.md", "license.txt") and not rm.license:
            first = text.strip().splitlines()[0] if text.strip() else ""
            rm.license = first.strip("# ").strip()
        if "test" in rel.lower() and lang in ("Python", "JavaScript", "TypeScript", "Go", "Rust", "Java"):
            rm.has_tests = True
        if low == "manage.py":
            rm.entry_points.append("manage.py (Django)")
            rm.run_commands.append("python manage.py runserver")

        if lang == "Python" and p.suffix == ".py":
            r = analyze_python(rel, text)
            if r:
                py_results[rel] = r
        elif p.suffix.lower() in JS_EXTS and ".min." not in low:
            mod, syms, routes, env = analyze_js(rel, text, lang)
            rm.modules.append(mod)
            rm.symbols.extend(syms)
            rm.routes.extend(routes)
            for ev in env:
                env_seen.setdefault(ev.name, ev)

    # Test files are documented as tests, not as part of the app (their fake servers aren't real routes)
    is_test = lambda rel: bool(re.search(r"(^|/)(tests?|__tests__|spec)/|(^|/)test_[^/]*$|_test\.py$|\.(test|spec)\.[jt]sx?$", rel))  # noqa: E731
    rm.routes = [r for r in rm.routes if not is_test(r.file)]
    for rel, r in list(py_results.items()):
        if is_test(rel):
            r.routes, r.app_vars, r.has_main_guard = [], [], False
        if rel.endswith("__main__.py"):
            root_dir, mod = import_path(rel, {f.path for f in rm.files})
            rm.run_commands.append(("cd " + root_dir + " && " if root_dir else "") + f"python -m {mod.removesuffix('.__main__')}")

    # Python: routes with router prefixes, entry points, env vars
    defaults = {e.name: e.default for e in env_seen.values()}
    for r in py_results.values():
        defaults.update({e.name: e.default for e in r.env_vars if e.default})
    rm.routes.extend(apply_include_prefixes(py_results, defaults))
    for rel, r in py_results.items():
        rm.modules.append(r.module)
        rm.symbols.extend(r.symbols)
        rm.schemas.update(r.schemas)
        for ev in r.env_vars:
            if ev.name in env_seen:
                if not env_seen[ev.name].default and ev.default:
                    env_seen[ev.name].default = ev.default
            else:
                env_seen[ev.name] = ev
        all_files = {f.path for f in rm.files}
        for var, fw in r.app_vars:
            rm.entry_points.append(f"{rel}: `{var} = {fw}(...)`")
            root_dir, mod = import_path(rel, all_files)
            cd = f"cd {root_dir} && " if root_dir else ""
            if fw in ("FastAPI", "Starlette"):
                rm.run_commands.append(f"{cd}uvicorn {mod}:{var} --reload")
            elif fw == "Flask":
                rm.run_commands.append(f"{cd}flask --app {mod} run")
        if r.has_main_guard:
            rm.entry_points.append(f"{rel}: has `if __name__ == \"__main__\"`")
            if "/" not in rel:
                rm.run_commands.append(f"python {rel}")

    # Keep only imports that point at modules inside this repo
    internal = {m.name for m in rm.modules}
    resolve_py = module_resolver({m.name for m in rm.modules if m.language == "Python"})
    for m in rm.modules:
        resolved = set()
        for imp in m.imports:
            if m.language == "Python":
                cand = resolve_py(imp)
            else:
                cand = imp if imp in internal else ""
            if not cand and m.language != "Python":
                for suffix in ("/index", ""):
                    if imp + suffix in internal:
                        cand = imp + suffix
            if cand and cand != m.name:
                resolved.add(cand)
        m.imports = sorted(resolved)

    for name, cmd in rm.scripts.items():
        if name.startswith("npm run ") and name.split()[-1] in ("dev", "start", "serve"):
            rm.run_commands.append(name)
    rm.env_vars = sorted(env_seen.values(), key=lambda e: not e.source.startswith(".env"))
    for k in rm.dependencies:
        rm.dependencies[k] = list(dict.fromkeys(rm.dependencies[k]))
    rm.run_commands = list(dict.fromkeys(rm.run_commands))
    rm.tree = build_tree([f.path for f in rm.files])
    rm.routes.sort(key=lambda r: (r.file, r.line))
    return rm


def repo_summary(rm: RepoMap, max_chars: int = 14_000) -> str:
    """Compact text version of the RepoMap for the LLM. Trimmed to fit free-tier limits."""
    parts = [f"# Repository: {rm.name}" + (f" ({rm.url})" if rm.url else "")]
    total = sum(rm.languages.values()) or 1
    langs = ", ".join(f"{k} {v * 100 // total}%" for k, v in sorted(rm.languages.items(), key=lambda kv: -kv[1]))
    parts.append(f"Languages: {langs or 'unknown'}. Files: {len(rm.files)}. Tests present: {rm.has_tests}. "
                 f"License: {rm.license or 'none found'}")
    parts.append("## File tree\n" + rm.tree)
    if rm.dependencies:
        parts.append("## Dependencies\n" + "\n".join(f"- {k}: {', '.join(v[:40])}" for k, v in rm.dependencies.items()))
    if rm.entry_points:
        parts.append("## Entry points\n" + "\n".join(f"- {e}" for e in rm.entry_points[:15]))
    if rm.run_commands:
        parts.append("## Run commands found in the code\n" + "\n".join(f"- `{c}`" for c in rm.run_commands))
    if rm.scripts:
        parts.append("## Scripts\n" + "\n".join(f"- `{k}`: {v}" for k, v in list(rm.scripts.items())[:20]))
    if rm.env_vars:
        parts.append("## Environment variables\n" + "\n".join(
            f"- {e.name}" + (f" (default: {e.default[:40]})" if e.default else "") + (f" - {e.comment[:100]}" if e.comment else "")
            for e in rm.env_vars[:40]))
    if rm.routes:
        parts.append("## HTTP routes\n" + "\n".join(
            f"- {r.method} {r.path} -> {r.handler} ({r.file}:{r.line}){' [auth]' if r.auth else ''}"
            for r in rm.routes[:60]))
    mods = [m for m in rm.modules if m.doc]
    if mods:
        parts.append("## Module docstrings\n" + "\n".join(f"- {m.path}: {m.doc[:160]}" for m in mods[:40]))
    syms = [s for s in rm.symbols if s.kind != "method"]
    if syms:
        parts.append("## Public functions and classes\n" + "\n".join(
            f"- {s.path}:{s.line} `{s.signature[:120]}`" + (f" - {s.doc[:100]}" if s.doc else "") for s in syms[:80]))
    for path, content in rm.key_files.items():
        if path.lower().endswith("readme.md"):
            parts.append(f"## Existing {path} (may be outdated)\n{content[:1500]}")
        else:
            parts.append(f"## {path}\n```\n{content[:1200]}\n```")
    text = "\n\n".join(parts)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n\n[... summary trimmed; use the tools to read more ...]"
    return text
