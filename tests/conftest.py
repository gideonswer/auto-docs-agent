"""Shared test fixtures. Tests run fully offline: a scripted fake LLM replaces the real one."""
from __future__ import annotations

import json
import re
import textwrap
from pathlib import Path

import pytest

FILES = {
    "README.md": "# Shop API\n\nA tiny shop backend used to test Auto-Docs Agent.\n",
    "requirements.txt": "fastapi>=0.110\nuvicorn\npydantic-settings\n",
    ".env.example": "# Secret used to sign login tokens\nSECRET_KEY=change-me\n\n# Max items per page\nPAGE_SIZE=20\n",
    "LICENSE": "MIT License\n\nCopyright (c) 2026 test\n",
    "shop/__init__.py": "",
    "shop/config.py": '''
        """Settings for the shop."""
        from pydantic_settings import BaseSettings


        class Settings(BaseSettings):
            secret_key: str = "change-me"
            page_size: int = 20
            database_url: str = "sqlite:///shop.db"
        ''',
    "shop/auth.py": '''
        """Login helpers."""
        from fastapi import Depends, HTTPException
        from shop.config import Settings


        def get_current_user(token: str = ""):
            """Return the user for a bearer token."""
            if not token:
                raise HTTPException(401, "Not logged in")
            return {"id": 1}


        def require_admin(user=Depends(get_current_user)):
            return user
        ''',
    "shop/schemas.py": '''
        from pydantic import BaseModel, Field


        class ItemIn(BaseModel):
            name: str = Field(min_length=1, max_length=80)
            price: float
            tags: list[str] = []
        ''',
    "shop/routers/__init__.py": "",
    "shop/routers/items.py": '''
        """Item endpoints."""
        from fastapi import APIRouter, Depends, HTTPException
        from shop.auth import get_current_user, require_admin
        from shop.schemas import ItemIn

        router = APIRouter(prefix="/items")


        @router.get("")
        def list_items(page: int = 1):
            """List items, newest first."""
            return []


        @router.post("", status_code=201)
        def create_item(body: ItemIn, user=Depends(require_admin)):
            """Create an item. Admins only."""
            return body


        @router.get("/{item_id}")
        def get_item(item_id: int, user=Depends(get_current_user)):
            if item_id < 0:
                raise HTTPException(404, "Item not found")
            return {"id": item_id}
        ''',
    "shop/main.py": '''
        """App entry point."""
        from fastapi import FastAPI
        from shop.routers import items

        app = FastAPI(title="Shop")
        app.include_router(items.router, prefix="/api")


        @app.get("/health")
        def health():
            return {"ok": True}
        ''',
    "web/package.json": json.dumps({"name": "web", "scripts": {"dev": "node server.js"},
                                    "dependencies": {"express": "^4"}}),
    "web/server.js": textwrap.dedent('''
        const express = require('express');
        const { greet } = require('./lib/greet');
        const app = express();
        /** Say hello */
        app.get('/hello/:name', (req, res) => res.send(greet(req.params.name)));
        app.listen(process.env.PORT || 3000);
        '''),
    "web/lib/greet.js": "/** Build a greeting. */\nexport function greet(name) { return `Hi ${name}`; }\n",
    "tests/test_items.py": "def test_ok():\n    assert True\n",
}


@pytest.fixture
def sample_repo(tmp_path: Path) -> Path:
    root = tmp_path / "shop-api"
    for rel, content in FILES.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(content).lstrip("\n"), encoding="utf-8")
    (root / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00binary")
    return root


NOTES = {
    "purpose": "A small shop backend with an item catalogue and admin-only item creation.",
    "features": ["List and view items", "Create items (admins only)", "Health check"],
    "how_it_works": ["A request hits FastAPI", "The items router checks the login", "The handler returns JSON"],
    "components": [{"name": "API app", "paths": ["shop/main.py"], "responsibility": "Creates the FastAPI app"},
                   {"name": "Items router", "paths": ["shop/routers/items.py"], "responsibility": "Item endpoints"}],
    "external_services": [],
    "setup_steps": ["pip install -r requirements.txt"],
    "run_commands": ["uvicorn shop.main:app --reload"],
    "usage_examples": ["curl http://localhost:8000/api/items"],
    "gotchas": ["Creating items needs an admin token"],
}

README_WITH_MISTAKES = """# Shop API

A small shop backend.

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env
python run.py
uvicorn shop.main:app --reload
```

## Configuration

{{CONFIGURATION}}

## API

Call `GET /api/items` to list items or `POST /api/orders` to place an order.

{{API_SUMMARY}}

## Project structure

{{PROJECT_STRUCTURE}}

Settings live in `shop/config.py` and `shop/settings.py`. Set `SECRET_KEY` and `REDIS_URL`.
"""


class ScriptedLLM:
    """Plays the part of Gemini. Answers each kind of prompt the pipeline sends."""

    name = "fake:scripted"

    def __init__(self, agent_actions: list | None = None, bad_component_diagram: bool = True):
        self.agent_actions = list(agent_actions) if agent_actions is not None else [
            {"thought": "See the layout", "action": "list_dir", "args": {"path": "shop"}},
            {"thought": "Read the entry point", "action": "read_file", "args": {"path": "shop/main.py"}},
            {"thought": "Find routes", "action": "search", "args": {"pattern": "@router\\.", "glob": "*.py"}},
            {"thought": "Done", "action": "finish", "args": {"notes": NOTES}},
        ]
        self.bad_component_diagram = bad_component_diagram
        self.prompts: list[str] = []
        self.calls = 0
        self.last_used = self.name

    def chat(self, messages, temperature=0.2, max_tokens=4096) -> str:
        self.calls += 1
        last = messages[-1]["content"]
        self.prompts.append(last)
        system = messages[0]["content"] if messages[0]["role"] == "system" else ""
        if "investigating a code repository" in system:
            action = self.agent_actions.pop(0) if self.agent_actions else {"action": "finish", "args": {"notes": NOTES}}
            return action if isinstance(action, str) else "Sure! Here's my next step:\n```json\n" + json.dumps(action) + "\n```"
        if last.startswith("For each setting"):
            return json.dumps({"DATABASE_URL": "Where the shop database lives"})
        if last.startswith("Write README.md"):
            return "```markdown\n" + README_WITH_MISTAKES + "\n```"
        if last.startswith("The README below contains claims"):
            fixed = README_WITH_MISTAKES.replace("python run.py\n", "").replace(" or `POST /api/orders` to place an order", "")
            return fixed.replace(" and `shop/settings.py`", "").replace(" and `REDIS_URL`", "")
        if last.startswith("You are documenting HTTP endpoints"):
            ids = re.findall(r"^### ((?:GET|POST|PUT|DELETE|PATCH) \S+)", last, re.M)
            return json.dumps({i: {"summary": f"Handle {i}", "description": "Does the thing.", "example_body": "",
                                   "response": "JSON.", "errors": ["404: not found"]} for i in ids})
        if last.startswith("You are writing a Python/JS API reference"):
            ids = re.findall(r"^### (\S+)", last, re.M)
            return json.dumps({i: {"summary": f"Does {i}."} for i in ids})
        if last.startswith("Describe the architecture"):
            comp = ('flowchart TD\n  C[Client (browser)] --> A[FastAPI app]\n  A --> R[Items router]\n  R --> DB[("SQLite")]'
                    if self.bad_component_diagram else 'flowchart TD\n  A["App"] --> B["Router"]')
            return json.dumps({
                "overview": "The shop is a FastAPI app.\n\nRequests go through the items router.",
                "component_diagram": comp,
                "sequence_title": "listing items",
                "sequence_diagram": "sequenceDiagram\n  participant U as User\n  U->>API: GET /api/items\n  API-->>U: [items",
                "design_decisions": ["Routers keep each resource in its own file."],
            })
        if "This Mermaid sequenceDiagram has problems" in last:
            return json.dumps({"diagram": "sequenceDiagram\n  participant U as User\n  U->>API: GET /api/items\n  API-->>U: items"})
        if "This Mermaid" in last:
            return json.dumps({"diagram": "flowchart TD\n  A[\"App\"] --> B[\"Router\"]"})
        return "{}"
