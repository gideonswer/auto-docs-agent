"""Plain data classes shared by every stage. No logic lives here."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class FileInfo:
    path: str          # relative, forward slashes
    language: str
    lines: int
    size: int


@dataclass
class Symbol:
    kind: str          # "function" | "class" | "method"
    name: str
    signature: str
    doc: str
    path: str
    line: int
    module: str
    parent: str = ""   # class name for methods

    @property
    def id(self) -> str:
        return f"{self.module}.{self.parent + '.' if self.parent else ''}{self.name}"


@dataclass
class Route:
    method: str        # GET, POST, ...
    path: str          # /api/items/{id}
    handler: str
    file: str
    line: int
    params: list[str] = field(default_factory=list)
    doc: str = ""
    framework: str = ""
    auth: bool = False  # handler depends on a login/user dependency
    depends: list[str] = field(default_factory=list)  # FastAPI Depends(...) targets

    @property
    def id(self) -> str:
        return f"{self.method} {self.path}"


@dataclass
class Module:
    name: str          # dotted python module or relative JS path
    path: str
    language: str
    doc: str = ""
    imports: list[str] = field(default_factory=list)  # internal modules only


@dataclass
class EnvVar:
    name: str
    default: str = ""
    comment: str = ""
    source: str = ""   # file where we found it


@dataclass
class RepoMap:
    name: str
    url: str | None
    root: str
    files: list[FileInfo] = field(default_factory=list)
    languages: dict[str, int] = field(default_factory=dict)       # language -> lines
    key_files: dict[str, str] = field(default_factory=dict)       # path -> (truncated) content
    dependencies: dict[str, list[str]] = field(default_factory=dict)
    scripts: dict[str, str] = field(default_factory=dict)         # name -> command
    entry_points: list[str] = field(default_factory=list)         # human-readable
    run_commands: list[str] = field(default_factory=list)         # commands we can prove exist
    env_vars: list[EnvVar] = field(default_factory=list)
    symbols: list[Symbol] = field(default_factory=list)
    routes: list[Route] = field(default_factory=list)
    modules: list[Module] = field(default_factory=list)
    schemas: dict[str, list[list[str]]] = field(default_factory=dict)  # class -> [[field, type, default]]
    tree: str = ""
    license: str = ""
    has_tests: bool = False

    def file_paths(self) -> set[str]:
        return {f.path for f in self.files}

    def primary_language(self) -> str:
        return max(self.languages, key=self.languages.get) if self.languages else "Unknown"

    def to_dict(self) -> dict:
        return asdict(self)
