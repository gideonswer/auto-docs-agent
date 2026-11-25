"""Lightweight JavaScript/TypeScript reading with regular expressions.

Not a full parser, but enough to find Express-style routes, exported functions and
relative imports for the dependency diagram.
"""
from __future__ import annotations

import posixpath
import re

from autodocs.models import EnvVar, Module, Route, Symbol

ROUTE_RE = re.compile(
    r"\b(?P<obj>app|router|server|api|[a-zA-Z_]\w*Router)\s*\.\s*(?P<m>get|post|put|delete|patch|all)\s*\(\s*"
    r"(?P<q>['\"`])(?P<path>[^'\"`]+)(?P=q)"
)
EXPORT_FN_RE = re.compile(
    r"^export\s+(?:default\s+)?(?:async\s+)?function\s*\*?\s*(?P<name>\w+)\s*(?P<sig>\([^)]*\))", re.M)
EXPORT_CLASS_RE = re.compile(r"^export\s+(?:default\s+)?class\s+(?P<name>\w+)", re.M)
EXPORT_CONST_RE = re.compile(
    r"^export\s+const\s+(?P<name>\w+)\s*(?::[^=]+)?=\s*(?:async\s+)?(?P<sig>\([^)]*\)|\w+)\s*=>", re.M)
IMPORT_RE = re.compile(
    r"""(?:import\s+(?:[^'"]+?\s+from\s+)?|require\s*\(\s*|import\s*\(\s*)['"](?P<p>\.{1,2}/[^'"]+)['"]""")
ENV_RE = re.compile(r"process\.env\.([A-Z][A-Z0-9_]+)|import\.meta\.env\.([A-Z][A-Z0-9_]+)")
JSDOC_RE = re.compile(r"/\*\*(?P<body>(?:(?!\*/).)*?)\*/\s*$", re.S)
JS_EXTS = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")


def _line_of(src: str, pos: int) -> int:
    return src.count("\n", 0, pos) + 1


def _jsdoc_before(src: str, pos: int) -> str:
    m = JSDOC_RE.search(src[max(0, pos - 800):pos])
    if not m:
        return ""
    lines = [ln.strip().lstrip("*").strip() for ln in m["body"].splitlines()]
    text = " ".join(ln for ln in lines if ln and not ln.startswith("@"))
    return text[:300]


def strip_ext(p: str) -> str:
    for ext in JS_EXTS:
        if p.endswith(ext):
            return p[: -len(ext)]
    return p


def analyze_js(rel_path: str, source: str, language: str):
    mod = Module(name=strip_ext(rel_path), path=rel_path, language=language)
    symbols: list[Symbol] = []
    routes: list[Route] = []
    env: list[EnvVar] = []
    base_dir = posixpath.dirname(rel_path)

    for m in IMPORT_RE.finditer(source):
        target = posixpath.normpath(posixpath.join(base_dir, m["p"]))
        mod.imports.append(strip_ext(target))

    for m in ROUTE_RE.finditer(source):
        method = "ANY" if m["m"] == "all" else m["m"].upper()
        handler_snip = source[m.end(): m.end() + 120].split("\n")[0]
        hm = re.search(r",\s*(?:async\s+)?(\w+)\s*[,)]", handler_snip)
        handler = hm.group(1) if hm and hm.group(1) not in ("function", "req") else "(inline handler)"
        auth = bool(re.search(r"auth|protect|requireUser|verifyToken", handler_snip, re.I))
        routes.append(Route(method, m["path"], handler, rel_path, _line_of(source, m.start()),
                            [], _jsdoc_before(source, m.start()), "Express", auth))

    for rx, kind in ((EXPORT_FN_RE, "function"), (EXPORT_CONST_RE, "function"), (EXPORT_CLASS_RE, "class")):
        for m in rx.finditer(source):
            sig = m.groupdict().get("sig") or ""
            if sig and not sig.startswith("("):
                sig = f"({sig})"
            signature = f"class {m['name']}" if kind == "class" else f"function {m['name']}{sig}"
            symbols.append(Symbol(kind, m["name"], signature, _jsdoc_before(source, m.start()),
                                  rel_path, _line_of(source, m.start()), mod.name))

    for m in ENV_RE.finditer(source):
        env.append(EnvVar(m.group(1) or m.group(2), "", "", rel_path))
    return mod, symbols, routes, env
