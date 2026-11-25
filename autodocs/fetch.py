"""Get a repository onto disk: a GitHub URL, `owner/repo` shorthand, or a local folder."""
from __future__ import annotations

import io
import re
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

import httpx

GITHUB_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?github\.com/(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+?)(?:\.git)?"
    r"(?:/tree/(?P<ref>[^/?#]+))?/?(?:[?#].*)?$"
)
SHORT_RE = re.compile(r"^(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+)$")


class FetchError(RuntimeError):
    pass


@dataclass
class RepoSource:
    path: Path              # folder containing the repo files
    name: str               # e.g. "chat-with-docs"
    url: str | None = None  # GitHub URL, if it came from GitHub
    owner: str | None = None
    temp_dir: Path | None = None  # delete this when finished

    def cleanup(self) -> None:
        if self.temp_dir and self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)


def parse_github(target: str) -> tuple[str, str, str | None] | None:
    """Return (owner, repo, ref) for a GitHub URL or owner/repo, else None."""
    target = target.strip()
    m = GITHUB_RE.match(target)
    if m:
        return m["owner"], m["repo"], m["ref"]
    if not Path(target).exists():
        m = SHORT_RE.match(target)
        if m:
            return m["owner"], m["repo"], None
    return None


def _safe_extract(zf: zipfile.ZipFile, dest: Path) -> None:
    """Extract, refusing any entry that would land outside `dest` (zip-slip)."""
    dest = dest.resolve()
    for member in zf.infolist():
        target = (dest / member.filename).resolve()
        if target != dest and not target.is_relative_to(dest):
            raise FetchError(f"Unsafe path in archive: {member.filename}")
    zf.extractall(dest)


def _download_zip(owner: str, repo: str, ref: str | None, dest: Path, token: str, max_mb: int) -> Path:
    url = f"https://codeload.github.com/{owner}/{repo}/zip/{ref or 'HEAD'}"
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    limit = max_mb * 1024 * 1024
    buf = io.BytesIO()
    with httpx.stream("GET", url, headers=headers, follow_redirects=True, timeout=60) as r:
        if r.status_code == 404:
            raise FetchError(f"Repo not found: {owner}/{repo} (is it private? set GITHUB_TOKEN)")
        r.raise_for_status()
        for chunk in r.iter_bytes():
            buf.write(chunk)
            if buf.tell() > limit:
                raise FetchError(f"Repo is larger than {max_mb} MB (change MAX_REPO_MB to allow it)")
    with zipfile.ZipFile(buf) as zf:
        _safe_extract(zf, dest)
    # GitHub zips contain one top-level folder like "repo-main/"
    children = [p for p in dest.iterdir() if p.is_dir()]
    return children[0] if len(children) == 1 else dest


def _git_clone(owner: str, repo: str, ref: str | None, dest: Path, token: str) -> Path:
    if not shutil.which("git"):
        raise FetchError("git is not installed")
    auth = f"x-access-token:{token}@" if token else ""
    cmd = ["git", "clone", "--depth", "1", "--quiet"]
    if ref:
        cmd += ["--branch", ref]
    out = dest / repo
    cmd += [f"https://{auth}github.com/{owner}/{repo}.git", str(out)]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if res.returncode != 0:
        msg = res.stderr.replace(token, "***") if token else res.stderr
        raise FetchError(f"git clone failed: {msg.strip()[:300]}")
    shutil.rmtree(out / ".git", ignore_errors=True)
    return out


def fetch_repo(target: str, token: str = "", max_mb: int = 50) -> RepoSource:
    """Turn whatever the user typed into a folder on disk."""
    gh = parse_github(target)
    if gh is None:
        p = Path(target).expanduser()
        if not p.is_dir():
            raise FetchError(f"'{target}' is not a GitHub URL or a folder on this computer")
        return RepoSource(path=p.resolve(), name=p.resolve().name)

    owner, repo, ref = gh
    tmp = Path(tempfile.mkdtemp(prefix="autodocs-"))
    url = f"https://github.com/{owner}/{repo}"
    errors = []
    for method in (_download_zip, _git_clone):
        try:
            args = (owner, repo, ref, tmp, token, max_mb) if method is _download_zip else (owner, repo, ref, tmp, token)
            path = method(*args)
            return RepoSource(path=path, name=repo, url=url, owner=owner, temp_dir=tmp)
        except FetchError as e:
            if "not found" in str(e) or "larger than" in str(e):
                shutil.rmtree(tmp, ignore_errors=True)
                raise
            errors.append(str(e))
        except Exception as e:  # network errors etc. -> try the next method
            errors.append(f"{method.__name__}: {e}")
        for child in tmp.iterdir():
            shutil.rmtree(child, ignore_errors=True) if child.is_dir() else child.unlink()
    shutil.rmtree(tmp, ignore_errors=True)
    raise FetchError("Could not download the repo. " + " | ".join(errors))
