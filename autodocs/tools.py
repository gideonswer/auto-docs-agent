"""The tools the agent can use to look around the repo. All are read-only and stay inside it."""
from __future__ import annotations

import fnmatch
import re
from pathlib import Path

from autodocs.scanner import IGNORE_DIRS, MAX_FILE_BYTES

MAX_READ_LINES = 220
MAX_READ_CHARS = 9_000
MAX_SEARCH_HITS = 30


class ToolError(Exception):
    pass


class RepoTools:
    def __init__(self, root: Path | str):
        self.root = Path(root).resolve()
        self.files_read: list[str] = []

    def _resolve(self, path: str) -> Path:
        path = (path or ".").strip().lstrip("/").replace("\\", "/")
        p = (self.root / path).resolve()
        if p != self.root and not p.is_relative_to(self.root):
            raise ToolError("path is outside the repository")
        if not p.exists():
            raise ToolError(f"'{path}' does not exist. Use list_dir to see what's there.")
        return p

    def _skip(self, p: Path) -> bool:
        return any(part in IGNORE_DIRS for part in p.relative_to(self.root).parts)

    def list_dir(self, path: str = ".") -> str:
        p = self._resolve(path)
        if not p.is_dir():
            raise ToolError(f"'{path}' is a file, not a folder. Use read_file.")
        entries = []
        for c in sorted(p.iterdir(), key=lambda c: (c.is_file(), c.name.lower())):
            if c.name in IGNORE_DIRS or c.name == ".git":
                continue
            entries.append(f"{c.name}/" if c.is_dir() else f"{c.name}  ({c.stat().st_size} bytes)")
        return "\n".join(entries[:200]) or "(empty folder)"

    def read_file(self, path: str, start_line: int = 1, end_line: int | None = None) -> str:
        p = self._resolve(path)
        if p.is_dir():
            raise ToolError(f"'{path}' is a folder. Use list_dir.")
        if p.stat().st_size > MAX_FILE_BYTES * 3:
            raise ToolError("file is too large to read")
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        start = max(1, int(start_line or 1))
        end = min(len(lines), int(end_line) if end_line else start + MAX_READ_LINES - 1,
                  start + MAX_READ_LINES - 1)
        body = "\n".join(f"{i:>4} | {lines[i - 1]}" for i in range(start, end + 1))
        if len(body) > MAX_READ_CHARS:
            body = body[:MAX_READ_CHARS] + "\n[... cut: ask for a smaller line range ...]"
        rel = p.relative_to(self.root).as_posix()
        if rel not in self.files_read:
            self.files_read.append(rel)
        more = f"\n[file has {len(lines)} lines; showing {start}-{end}]" if end < len(lines) or start > 1 else ""
        return (body or "(empty file)") + more

    def search(self, pattern: str, glob: str | None = None) -> str:
        try:
            rx = re.compile(pattern, re.I)
        except re.error:
            rx = re.compile(re.escape(pattern), re.I)
        hits = []
        for p in sorted(self.root.rglob("*")):
            if not p.is_file() or self._skip(p) or p.stat().st_size > MAX_FILE_BYTES:
                continue
            rel = p.relative_to(self.root).as_posix()
            if glob and not fnmatch.fnmatch(rel, glob) and not fnmatch.fnmatch(p.name, glob):
                continue
            try:
                text = p.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if rx.search(line):
                    hits.append(f"{rel}:{i}: {line.strip()[:160]}")
                    if len(hits) >= MAX_SEARCH_HITS:
                        return "\n".join(hits) + "\n[... more matches; narrow the pattern or add a glob ...]"
        return "\n".join(hits) or "no matches"

    def run(self, action: str, args: dict) -> str:
        args = args if isinstance(args, dict) else {}
        try:
            if action == "list_dir":
                return self.list_dir(args.get("path", "."))
            if action == "read_file":
                return self.read_file(args.get("path", ""), args.get("start_line", 1), args.get("end_line"))
            if action == "search":
                return self.search(str(args.get("pattern", "")), args.get("glob"))
        except ToolError as e:
            return f"ERROR: {e}"
        except (TypeError, ValueError) as e:
            return f"ERROR: bad arguments ({e})"
        return f"ERROR: unknown action '{action}'. Use list_dir, read_file, search or finish."
