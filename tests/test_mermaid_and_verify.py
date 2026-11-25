import shutil

import pytest

from autodocs import mermaid
from autodocs.scanner import scan_repo
from autodocs.verify import Verifier


def test_clean_quotes_labels_and_strips_fences():
    code = "```mermaid\nflowchart TD\n  A[User (browser)] -->|POST /chat (json)| B[API]\n```"
    out = mermaid.clean(code)
    assert out.startswith("flowchart TD")
    assert 'A["User (browser)"]' in out and '|"POST /chat (json)"|' in out


@pytest.mark.parametrize("code,expected", [
    ("flowchart TD\n  A[x --> B", "unbalanced"),
    ("hello\nA-->B", "diagram type"),
    ("flowchart TD\n  subgraph S\n  A-->B", "'subgraph'"),
    ("flowchart TD\n  end[Stop] --> A", "'end'"),
    ("sequenceDiagram\n  A->>B: hi\n  this is prose", "unrecognised"),
])
def test_problems_catches_common_breakage(code, expected):
    assert any(expected in p for p in mermaid.problems(code))


def test_good_diagrams_pass():
    assert mermaid.problems('flowchart LR\n  A["a"] --> B[("db")]') == []
    assert mermaid.problems("sequenceDiagram\n  participant U\n  U->>S: hi\n  S-->>U: ok") == []


def test_module_graph_and_routes_diagram(sample_repo):
    rm = scan_repo(sample_repo, "shop-api")
    graph, shared = mermaid.module_graph(rm)
    assert "shop_main --> shop_routers_items" in graph
    assert mermaid.problems(graph) == []
    assert "tests" not in graph
    rd = mermaid.routes_diagram(rm)
    assert "🔒" in rd and mermaid.problems(rd) == []


@pytest.mark.skipif(not shutil.which("mmdc"), reason="Mermaid CLI not installed")
def test_generated_diagrams_really_render(sample_repo):
    rm = scan_repo(sample_repo, "shop-api")
    assert mermaid.mmdc_check(mermaid.module_graph(rm)[0]) is None
    assert mermaid.mmdc_check(mermaid.routes_diagram(rm)) is None


def test_verifier_flags_only_false_claims(sample_repo):
    rm = scan_repo(sample_repo, "shop-api", "https://github.com/me/shop-api")
    v = Verifier(rm, "SECRET_KEY PORT")
    md = """Edit `shop/config.py` (not `shop/settings.py`). Model: `openai/gpt-oss-20b`. Create `.env`.
Call `GET /api/items/{id}` and `DELETE /api/items`. Set `SECRET_KEY`, not `REDIS_URL`.

```bash
git clone https://github.com/me/shop-api.git
cd shop-api
pip install -r requirements.txt && cp .env.example .env
python run.py
uvicorn shop.main:app --reload
npm run dev
npm run build
```
"""
    results = {c.claim: c.ok for c in v.check_doc("README.md", md)}
    assert results["shop/config.py"] and not results["shop/settings.py"]
    assert "openai/gpt-oss-20b" not in results and ".env" not in results
    assert results["GET /api/items/{id}"] and not results["DELETE /api/items"]
    assert results["SECRET_KEY"] and not results["REDIS_URL"]
    assert results["git clone https://github.com/me/shop-api.git"] and results["cd shop-api"]
    assert results["pip install -r requirements.txt"] and results["cp .env.example .env"]
    assert not results["python run.py"] and results["uvicorn shop.main:app --reload"]
    assert results["npm run dev"] and not results["npm run build"]


def test_marketing_words_are_flagged(sample_repo):
    rm = scan_repo(sample_repo, "shop-api")
    rep = Verifier(rm).check_all({"README.md": "A powerful and seamless shop."})
    assert len(rep.style_warnings) == 2
