import io
import time
import zipfile

import pytest
from fastapi.testclient import TestClient

from autodocs import pipeline
from autodocs.config import Settings
from autodocs.fetch import FetchError, RepoSource, _safe_extract, fetch_repo, parse_github
from tests.conftest import ScriptedLLM


def test_full_ai_run_fixes_its_own_mistakes(sample_repo, tmp_path):
    llm = ScriptedLLM()
    events = []
    res = pipeline.run(str(sample_repo), Settings(), out_dir=tmp_path, llm=llm,
                       on_event=lambda s, m: events.append((s, m)))
    readme = res.docs["README.md"]
    # placeholders were replaced with exact tables from the code
    assert "{{" not in readme and "| `SECRET_KEY` | `change-me` | Secret used to sign login tokens |" in readme
    assert "Where the shop database lives" in readme
    assert "shop-api/\n├── shop/" in readme
    # the made-up claims were caught and removed by the fix pass
    assert "python run.py" not in readme and "/api/orders" not in readme and "REDIS_URL" not in readme
    assert any(s == "fix" for s, _ in events)
    assert res.report.failures("README.md") == []
    # API docs: exact paths + AI summaries + schema fields + curl
    api = res.docs["API.md"]
    assert "### POST /api/items" in api and "Handle POST /api/items" in api
    assert "| `name` | `str` | Yes | `min_length=1`, `max_length=80` |" in api
    assert '-d \'{"name": "name", "price": 0.5, "tags": []}\'' in api
    # architecture: broken AI diagrams were repaired, and the import graph is always there
    arch = res.docs["ARCHITECTURE.md"]
    assert 'C["Client (browser)"]' in arch
    assert "## Listing items" in arch and "API-->>U: items" in arch
    assert "## Module dependencies" in arch
    for name in ("README.md", "API.md", "ARCHITECTURE.md", "QUALITY_REPORT.md", "agent_trace.json"):
        assert (res.out_dir / name).exists()
    assert "Fact-check score: 100.0%" in (res.out_dir / "QUALITY_REPORT.md").read_text(encoding="utf-8")


def test_offline_mode_needs_no_llm(sample_repo, tmp_path):
    res = pipeline.run(str(sample_repo), Settings(), out_dir=tmp_path, offline=True)
    assert res.report.score == 100.0
    assert "uvicorn shop.main:app --reload" in res.docs["README.md"]
    assert "offline mode" in res.docs["README.md"]


def test_missing_api_key_gives_a_clear_error(sample_repo, tmp_path):
    from autodocs.llm import LLMError
    s = Settings(gemini_api_key="", groq_api_key="")
    with pytest.raises(LLMError, match="--offline"):
        pipeline.run(str(sample_repo), s, out_dir=tmp_path)


@pytest.mark.parametrize("target,expected", [
    ("https://github.com/gideonswer/chat-with-docs", ("gideonswer", "chat-with-docs", None)),
    ("github.com/a/b.git", ("a", "b", None)),
    ("https://github.com/a/b/tree/dev", ("a", "b", "dev")),
    ("a/b", ("a", "b", None)),
    ("https://gitlab.com/a/b", None),
])
def test_parse_github(target, expected):
    assert parse_github(target) == expected


def test_local_folder_and_bad_target(sample_repo):
    assert fetch_repo(str(sample_repo)).name == "shop-api"
    with pytest.raises(FetchError):
        fetch_repo("not a repo at all")


def test_zip_slip_is_blocked(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../evil.txt", "x")
    with zipfile.ZipFile(buf) as zf, pytest.raises(FetchError):
        _safe_extract(zf, tmp_path / "out")


def test_web_job_end_to_end(sample_repo, monkeypatch):
    from autodocs.web.app import app
    monkeypatch.setattr(pipeline, "fetch_repo", lambda *a, **k: RepoSource(path=sample_repo, name="shop-api",
                                                                          url="https://github.com/me/shop-api"))
    c = TestClient(app)
    assert c.post("/api/jobs", json={"repo": "/etc/passwd"}).status_code == 422  # no server paths
    job = c.post("/api/jobs", json={"repo": "https://github.com/me/shop-api", "offline": True}).json()
    for _ in range(50):
        j = c.get(f"/api/jobs/{job['id']}").json()
        if j["status"] in ("done", "error"):
            break
        time.sleep(0.1)
    assert j["status"] == "done", j["error"]
    assert set(j["docs"]) == {"README.md", "API.md", "ARCHITECTURE.md", "QUALITY_REPORT.md"}
    z = zipfile.ZipFile(io.BytesIO(c.get(f"/api/jobs/{job['id']}/download").content))
    assert "README.md" in z.namelist()
    assert c.get("/api/jobs/nope").status_code == 404
    assert "Auto-Docs Agent" in c.get("/").text
