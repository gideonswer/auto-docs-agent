# chat-with-docs architecture

The repository implements a FastAPI web service that lets users upload PDFs, ask questions, and get answers with page‑level citations. It stores user data in SQLite, chunks PDFs into overlapping pieces, embeds them with sentence‑transformers, and keeps the vectors in a local ChromaDB collection.

When a user asks a question, the service embeds the query, retrieves the top‑k relevant chunks from the workspace‑filtered vector store, builds a prompt that includes citation markers, calls the configured LLM, and returns the answer with citations. Evaluation runs compare the LLM answer to a reference answer and report metrics.

## Components

```mermaid
flowchart TD
  A["FastAPI app (app.main)"]
  B["Auth router (app.routers.auth)"]
  C["Workspace router (app.routers.workspaces)"]
  D["Document router (app.routers.documents)"]
  E["Chat router (app.routers.chat)"]
  F["Eval router (app.routers.evals)"]
  G["SQLAlchemy DB (app.db)"]
  H["ChromaDB store (app.vectorstore)"]
  I["Embedding model (app.embeddings)"]
  J["LLM provider (app.llm)"]
  K["RAG logic (app.rag)"]
  L["PDF ingest (app.ingest)"]
  M["Evaluation logic (app.evals)"]
  A --> B
  A --> C
  A --> D
  A --> E
  A --> F
  B --> G
  C --> G
  D --> G
  D --> L
  E --> J
  E --> K
  F --> M
  F --> J
  K --> I
  K --> J
  L --> I
  L --> H
  M --> I
  M --> J
  M --> K
  H --> G
```

| Component | Where | Responsibility |
|---|---|---|
| app.main | `app/main.py` | FastAPI app setup, router inclusion, health endpoint, static file serving |
| app.config | `app/config.py` | Central settings holder using pydantic‑settings |
| app.db | `app/db.py` | SQLAlchemy engine and session factory |
| app.models | `app/models.py` | ORM models for users, workspaces, documents, eval runs, and chunks |
| app.embeddings | `app/embeddings.py` | Sentence‑transformer based embedder |
| app.vectorstore | `app/vectorstore.py` | ChromaDB wrapper for storing and querying chunks |
| app.rag | `app/rag.py` | Prompt construction, citation parsing, and answer generation |
| app.llm | `app/llm.py` | Provider‑agnostic LLM interface and fallback logic |
| app.ingest | `app/ingest.py` | PDF parsing, page extraction, cleaning, chunking |
| app.evals | `app/evals.py` | Evaluation logic: scoring, judging, summarizing results |

## Chat request flow

```mermaid
sequenceDiagram
  participant U as User
  participant API as FastAPI
  participant Auth as Auth
  participant RAG as RAG
  participant Embed as Embedder
  participant Store as ChromaDB
  participant LLM as LLM
  U->>API: POST /api/workspaces/{id}/chat
  API->>Auth: verify JWT
  Auth->>API: return user
  API->>RAG: build prompt
  RAG->>Embed: embed query
  Embed->>RAG: vector
  RAG->>Store: retrieve top‑k
  Store->>RAG: chunks
  RAG->>LLM: call LLM with prompt
  LLM->>RAG: answer with citations
  RAG->>API: return answer
  API->>U: JSON response
```

## Module dependencies

Drawn from the import statements in the code, so it is always accurate. An arrow means "imports".

```mermaid
flowchart LR
    subgraph grp_app["app/"]
        app_auth["auth"]
        app_embeddings["embeddings"]
        app_evals["evals"]
        app_ingest["ingest"]
        app_llm["llm"]
        app_main["main"]
        app_rag["rag"]
    end
    subgraph grp_app_routers["app/routers/"]
        app_routers_auth["auth"]
        app_routers_chat["chat"]
        app_routers_documents["documents"]
        app_routers_evals["evals"]
        app_routers_workspaces["workspaces"]
    end
    app_evals --> app_embeddings
    app_evals --> app_llm
    app_evals --> app_rag
    app_rag --> app_embeddings
    app_rag --> app_llm
    app_routers_chat --> app_llm
    app_routers_chat --> app_rag
    app_routers_documents --> app_ingest
    app_routers_evals --> app_evals
    app_routers_evals --> app_llm
    app_main --> grp_app_routers
    grp_app_routers --> app_auth
    grp_app_routers --> app_embeddings
```

Left out to keep the picture readable, because most modules use them: `app.config`, `app.db`, `app.models`, `app.schemas`, `app.vectorstore`.

## HTTP API map

🔒 = login needed. Details are in [API.md](API.md).

```mermaid
flowchart LR
    API["chat-with-docs API"]
    API --> g_health["/health"]
    g_health --> r_health_0["GET /api/health"]
    API --> g_root["/"]
    g_root --> r_root_0["GET /"]
    API --> g_auth["/auth"]
    g_auth --> r_auth_0["POST /api/auth/register"]
    g_auth --> r_auth_1["POST /api/auth/login"]
    g_auth --> r_auth_2["GET /api/auth/me 🔒"]
    API --> g_workspaces["/workspaces"]
    g_workspaces --> r_workspaces_0["POST /api/workspaces/{workspace_id}/chat 🔒"]
    g_workspaces --> r_workspaces_1["GET /api/workspaces/{workspace_id}/documents 🔒"]
    g_workspaces --> r_workspaces_2["POST /api/workspaces/{workspace_id}/documents 🔒"]
    g_workspaces --> r_workspaces_3["DELETE /api/workspaces/{workspace_id}/documents/{document_id} 🔒"]
    g_workspaces --> r_workspaces_4["POST /api/workspaces/{workspace_id}/evals 🔒"]
    g_workspaces --> r_workspaces_5["GET /api/workspaces/{workspace_id}/evals 🔒"]
    g_workspaces --> r_workspaces_6["GET /api/workspaces/{workspace_id}/evals/{run_id} 🔒"]
    g_workspaces --> r_workspaces_7["GET /api/workspaces 🔒"]
    g_workspaces --> r_workspaces_8["POST /api/workspaces 🔒"]
    g_workspaces --> r_workspaces_9["DELETE /api/workspaces/{workspace_id} 🔒"]
```

## Dependencies

- **Python:** `fastapi`, `uvicorn`, `sqlalchemy`, `pydantic-settings`, `email-validator`, `python-multipart`, `pyjwt`, `bcrypt`, `pypdf`, `chromadb`, `sentence-transformers`, `openai`, `anthropic`, `pytest`, `httpx`, `reportlab`

## Design decisions

- Using a single ChromaDB collection with a workspace_id tag keeps workspaces isolated without needing separate databases.
- Embedding with sentence‑transformers avoids external API calls and keeps the system free to run offline.
- The LLM layer is provider‑agnostic; it falls back to a secondary provider automatically, improving reliability.
- JWT authentication is handled in a dedicated router, ensuring all workspace routes enforce ownership checks.
- PDF ingestion splits pages into overlapping chunks; this improves retrieval quality by preserving context across chunk boundaries.

---
*Generated by [Auto-Docs Agent](https://github.com/gideonswer/auto-docs-agent). The dependency diagram and API map come straight from the code; the other diagrams are AI-drawn and checked to render.*
