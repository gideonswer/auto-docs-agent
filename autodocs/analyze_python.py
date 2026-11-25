"""Read Python files with the `ast` module: functions, classes, web routes, imports, settings.

Nothing here calls an LLM. These facts are exact, so the generated docs can be checked
against them later.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field

from autodocs.models import EnvVar, Module, Route, Symbol

HTTP_METHODS = {"get", "post", "put", "delete", "patch", "options", "head"}
ROUTE_ATTRS = HTTP_METHODS | {"route", "api_route", "websocket"}
AUTH_RE = __import__("re").compile(r"current_user|require_user|get_user|login_required|verify_token|authenticated", 2)


def module_name(rel_path: str) -> str:
    parts = rel_path[:-3].split("/") if rel_path.endswith(".py") else rel_path.split("/")
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) or rel_path


def _first_line(doc: str | None) -> str:
    if not doc:
        return ""
    doc = doc.strip()
    para = doc.split("\n\n")[0]
    return " ".join(para.split())[:300]


def _signature(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    prefix = "async def" if isinstance(fn, ast.AsyncFunctionDef) else "def"
    ret = f" -> {ast.unparse(fn.returns)}" if fn.returns else ""
    return f"{prefix} {fn.name}({ast.unparse(fn.args)}){ret}"


def _params(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    """Human-readable parameter list, e.g. ['item_id: int', 'q: str | None = None']."""
    args = fn.args
    positional = args.posonlyargs + args.args
    defaults = [None] * (len(positional) - len(args.defaults)) + list(args.defaults)
    out = []
    pairs = list(zip(positional, defaults)) + list(zip(args.kwonlyargs, args.kw_defaults))
    for a, d in pairs:
        if a.arg in ("self", "cls"):
            continue
        s = a.arg
        if a.annotation is not None:
            s += f": {ast.unparse(a.annotation)}"
        if d is not None:
            s += f" = {ast.unparse(d)}"
        out.append(s)
    return out


def _depends(fn) -> list[str]:
    """Names used inside Depends(...) / Security(...) in a function's parameters."""
    out = []
    for d in list(fn.args.defaults) + [k for k in fn.args.kw_defaults if k is not None]:
        for node in ast.walk(d):
            if isinstance(node, ast.Call) and ast.unparse(node.func).split(".")[-1] in ("Depends", "Security") \
                    and node.args:
                out.append(ast.unparse(node.args[0]).split(".")[-1])
    return out


def _const_str(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _kw(call: ast.Call, name: str) -> ast.AST | None:
    for k in call.keywords:
        if k.arg == name:
            return k.value
    return None


@dataclass
class PyFileResult:
    module: Module
    symbols: list[Symbol] = field(default_factory=list)
    routes: list[Route] = field(default_factory=list)  # paths WITHOUT include_router prefixes yet
    route_vars: dict[int, str] = field(default_factory=dict)  # id(route) -> router variable name
    includes: list[tuple[str, str, str, str]] = field(default_factory=list)  # (module alias, var, prefix, includer var)
    aliases: dict[str, str] = field(default_factory=dict)  # local name -> imported module
    env_vars: list[EnvVar] = field(default_factory=list)
    app_vars: list[tuple[str, str]] = field(default_factory=list)  # (var, framework) e.g. ("app","FastAPI")
    has_main_guard: bool = False
    fn_deps: dict[str, list[str]] = field(default_factory=dict)  # function -> Depends targets
    schemas: dict[str, list[list[str]]] = field(default_factory=dict)  # data classes / pydantic models


def _resolve_relative(mod: str, level: int, target: str | None, is_pkg: bool) -> str:
    base = mod.split(".")
    if not is_pkg:
        base = base[:-1]
    if level > 1:
        base = base[: len(base) - (level - 1)]
    parts = base + ([target] if target else [])
    return ".".join(p for p in parts if p)


def analyze_python(rel_path: str, source: str) -> PyFileResult | None:
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return None
    mod = module_name(rel_path)
    is_pkg = rel_path.endswith("__init__.py")
    res = PyFileResult(module=Module(name=mod, path=rel_path, language="Python",
                                     doc=_first_line(ast.get_docstring(tree))))
    prefixes: dict[str, str] = {}

    # --- imports (all of them; scanner filters to internal ones later) ---
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                res.module.imports.append(a.name)
                res.aliases[(a.asname or a.name).split(".")[0]] = a.name if a.asname else a.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom):
            base = _resolve_relative(mod, node.level, node.module, is_pkg) if node.level else (node.module or "")
            for a in node.names:
                full = f"{base}.{a.name}" if base else a.name
                res.module.imports.append(full)
                res.aliases[a.asname or a.name] = full
            if base:
                res.module.imports.append(base)

    # --- module-level assignments: app objects, routers with prefixes ---
    for node in tree.body:
        if isinstance(node, ast.If) and isinstance(node.test, ast.Compare):
            if "__name__" in ast.unparse(node.test) and "__main__" in ast.unparse(node.test):
                res.has_main_guard = True
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and node.targets:
            tgt = node.targets[0]
            if not isinstance(tgt, ast.Name):
                continue
            fname = ast.unparse(node.value.func).split(".")[-1]
            if fname in ("FastAPI", "Flask", "Starlette", "Quart", "Sanic"):
                res.app_vars.append((tgt.id, fname))
            if fname in ("APIRouter", "Blueprint"):
                p = _const_str(_kw(node.value, "prefix")) or _const_str(_kw(node.value, "url_prefix")) or ""
                prefixes[tgt.id] = p

    # --- include_router / register_blueprint calls (anywhere) ---
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr in ("include_router", "register_blueprint") and node.args:
            target = node.args[0]
            pnode = _kw(node, "prefix") or _kw(node, "url_prefix")
            prefix = _const_str(pnode)
            if prefix is None:  # e.g. prefix=settings.API_V1_STR -> resolved later from settings defaults
                prefix = "${" + ast.unparse(pnode).split(".")[-1] + "}" if pnode is not None else ""
            includer = ast.unparse(node.func.value)
            if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
                res.includes.append((target.value.id, target.attr, prefix, includer))
            elif isinstance(target, ast.Name):
                res.includes.append((target.id, "", prefix, includer))

    # --- settings classes (pydantic BaseSettings) -> env vars ---
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and any("Settings" in ast.unparse(b) for b in node.bases):
            for stmt in node.body:
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name) \
                        and not stmt.target.id.startswith("model_"):
                    default = ast.unparse(stmt.value) if stmt.value is not None else ""
                    res.env_vars.append(EnvVar(stmt.target.id.upper(), default.strip("'\""), "", rel_path))

    # --- os.getenv / os.environ ---
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = ast.unparse(node.func)
            if f in ("os.getenv", "os.environ.get", "getenv", "environ.get") and node.args:
                name = _const_str(node.args[0])
                if name:
                    d = ast.unparse(node.args[1]).strip("'\"") if len(node.args) > 1 else ""
                    res.env_vars.append(EnvVar(name, d, "", rel_path))
        elif isinstance(node, ast.Subscript) and ast.unparse(node.value) in ("os.environ", "environ"):
            name = _const_str(node.slice)
            if name:
                res.env_vars.append(EnvVar(name, "", "", rel_path))

    # --- functions, classes, routes ---
    def visit_fn(fn, parent: str = "") -> None:
        public = not fn.name.startswith("_")
        deps = _depends(fn)
        if not parent:
            res.fn_deps[fn.name] = deps
        if public:
            res.symbols.append(Symbol("method" if parent else "function", fn.name, _signature(fn),
                                      _first_line(ast.get_docstring(fn)), rel_path, fn.lineno, mod, parent))
        for dec in fn.decorator_list:
            if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)):
                continue
            attr = dec.func.attr
            if attr not in ROUTE_ATTRS:
                continue
            path = _const_str(dec.args[0]) if dec.args else _const_str(_kw(dec, "path")) or _const_str(_kw(dec, "rule"))
            if path is None:
                continue
            var = ast.unparse(dec.func.value)
            if attr in HTTP_METHODS:
                methods = [attr.upper()]
            elif attr == "websocket":
                methods = ["WS"]
            else:
                m = _kw(dec, "methods")
                methods = [e.value.upper() for e in getattr(m, "elts", []) if isinstance(e, ast.Constant)] or ["GET"]
            auth = any(AUTH_RE.search(ast.unparse(d)) for d in fn.decorator_list)
            for method in methods:
                r = Route(method, prefixes.get(var, "") + path, fn.name, rel_path, fn.lineno,
                          _params(fn), _first_line(ast.get_docstring(fn)),
                          "Flask" if attr == "route" else "FastAPI", auth, deps)
                res.routes.append(r)
                res.route_vars[id(r)] = var

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            visit_fn(node)
        elif isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            bases = ", ".join(ast.unparse(b) for b in node.bases)
            fields = [[st.target.id, ast.unparse(st.annotation), ast.unparse(st.value) if st.value else ""]
                      for st in node.body if isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name)
                      and not st.target.id.startswith("_") and "ClassVar" not in ast.unparse(st.annotation)]
            if fields and "Settings" not in bases:
                res.schemas[node.name] = fields
            res.symbols.append(Symbol("class", node.name, f"class {node.name}({bases})" if bases else f"class {node.name}",
                                      _first_line(ast.get_docstring(node)), rel_path, node.lineno, mod))
            for stmt in node.body:
                if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    visit_fn(stmt, parent=node.name)
    return res


def mark_auth(results: dict[str, PyFileResult], routes: list[Route]) -> None:
    """A route needs login if it depends (directly or through other dependencies) on a user check."""
    deps: dict[str, list[str]] = {}
    for r in results.values():
        deps.update(r.fn_deps)
    auth = {n for n in deps if AUTH_RE.search(n)} | {n for v in deps.values() for n in v if AUTH_RE.search(n)}
    changed = True
    while changed:
        changed = False
        for name, ds in deps.items():
            if name not in auth and any(d in auth for d in ds):
                auth.add(name)
                changed = True
    for route in routes:
        if route.framework == "FastAPI":
            route.auth = route.auth or any(d in auth for d in route.depends)


def module_resolver(names: set[str]):
    """Imports are written relative to a source root (`from app.db import x`) but our module names
    come from file paths (`backend.app.db`). Return a function mapping an import to a real module."""
    alias: dict[str, str | None] = {}
    for n in names:
        parts = n.split(".")
        for k in range(1, len(parts)):
            suf = ".".join(parts[k:])
            if suf not in names:
                alias[suf] = None if suf in alias and alias[suf] != n else n  # None = ambiguous

    def resolve(imp: str) -> str:
        cand = imp
        while cand:
            if cand in names:
                return cand
            if alias.get(cand):
                return alias[cand]
            cand = cand.rpartition(".")[0]
        return ""
    return resolve


def apply_include_prefixes(results: dict[str, PyFileResult], settings: dict[str, str] | None = None) -> list[Route]:
    """Add include_router(..., prefix=...) prefixes to routes, following nested routers.

    `settings` maps setting names (e.g. API_V1_STR) to their default values, so a prefix like
    `settings.API_V1_STR` can still be resolved."""
    settings = settings or {}
    resolve = module_resolver({r.module.name for r in results.values()})
    parent: dict[tuple[str, str], tuple[str, tuple[str, str]]] = {}  # (module, var) -> (prefix, includer)
    for r in results.values():
        for alias, var, prefix, includer in r.includes:
            target = r.aliases.get(alias, alias)
            if not var:  # `from app.routers.auth import router` -> alias maps to "app.routers.auth.router"
                target, _, var = target.rpartition(".")
            target = resolve(target) or target
            prefix = re.sub(r"\$\{(\w+)\}", lambda m: settings.get(m[1].upper(), ""), prefix)
            parent[(target, var)] = (prefix, (r.module.name, includer))

    def full_prefix(key: tuple[str, str], depth: int = 0) -> str:
        if key not in parent or depth > 10:
            return ""
        prefix, up = parent[key]
        return full_prefix(up, depth + 1) + prefix

    routes: list[Route] = []
    for r in results.values():
        for route in r.routes:
            p = full_prefix((r.module.name, r.route_vars.get(id(route), "")))
            if p:
                route.path = (p.rstrip("/") + route.path) or "/"
            routes.append(route)
    mark_auth(results, routes)
    return routes
