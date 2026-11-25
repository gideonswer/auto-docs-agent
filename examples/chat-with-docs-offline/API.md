# chat-with-docs API reference

Base URL when running locally: `http://localhost:8000`

## Authentication

Endpoints marked **Login needed** expect a token in the `Authorization` header:

```http
Authorization: Bearer <your token>
```

Get a token from `POST /api/auth/login`.

## Endpoints

| Method | Path | Summary | Login needed |
|---|---|---|---|
| `GET` | [`/api/health`](#get-apihealth) | Health | No |
| `GET` | [`/`](#get-) | Index | No |
| `POST` | [`/api/auth/register`](#post-apiauthregister) | Register | No |
| `POST` | [`/api/auth/login`](#post-apiauthlogin) | Login | No |
| `GET` | [`/api/auth/me`](#get-apiauthme) | Me | Yes |
| `POST` | [`/api/workspaces/{workspace_id}/chat`](#post-apiworkspacesworkspaceidchat) | Chat | Yes |
| `GET` | [`/api/workspaces/{workspace_id}/documents`](#get-apiworkspacesworkspaceiddocuments) | List documents | Yes |
| `POST` | [`/api/workspaces/{workspace_id}/documents`](#post-apiworkspacesworkspaceiddocuments) | Upload document | Yes |
| `DELETE` | [`/api/workspaces/{workspace_id}/documents/{document_id}`](#delete-apiworkspacesworkspaceiddocumentsdocumentid) | Delete document | Yes |
| `POST` | [`/api/workspaces/{workspace_id}/evals`](#post-apiworkspacesworkspaceidevals) | Create eval run | Yes |
| `GET` | [`/api/workspaces/{workspace_id}/evals`](#get-apiworkspacesworkspaceidevals) | List eval runs | Yes |
| `GET` | [`/api/workspaces/{workspace_id}/evals/{run_id}`](#get-apiworkspacesworkspaceidevalsrunid) | Get eval run | Yes |
| `GET` | [`/api/workspaces`](#get-apiworkspaces) | List workspaces | Yes |
| `POST` | [`/api/workspaces`](#post-apiworkspaces) | Create workspace | Yes |
| `DELETE` | [`/api/workspaces/{workspace_id}`](#delete-apiworkspacesworkspaceid) | Delete workspace | Yes |

## Health

### GET /api/health

- **Login needed:** No
- **Source:** [`app/main.py` line 33](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/main.py#L33) (`health`)

**Example request**

```bash
curl "http://localhost:8000/api/health"
```

## General

### GET /

- **Login needed:** No
- **Source:** [`app/main.py` line 43](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/main.py#L43) (`index`)

**Example request**

```bash
curl "http://localhost:8000/"
```

## Auth

### POST /api/auth/register

- **Login needed:** No
- **Source:** [`app/routers/auth.py` line 15](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/routers/auth.py#L15) (`register`)

| Parameter | In | Type |
|---|---|---|
| `body` | JSON body | `RegisterIn` |

`RegisterIn` fields:

| Field | Type | Required | Rules |
|---|---|---|---|
| `email` | `EmailStr` | Yes |  |
| `password` | `str` | Yes | `min_length=8`, `max_length=72` |

**Example request**

```bash
curl -X POST "http://localhost:8000/api/auth/register" \
  -H "Content-Type: application/json" \
  -d '{"email": "you@example.com", "password": "a-strong-password"}'
```

### POST /api/auth/login

- **Login needed:** No
- **Source:** [`app/routers/auth.py` line 26](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/routers/auth.py#L26) (`login`)

| Parameter | In | Type |
|---|---|---|
| `username` | form field | `str` |
| `password` | form field | `str` |

**Example request**

```bash
curl -X POST "http://localhost:8000/api/auth/login" \
  -F "username=<username>" \
  -F "password=<password>"
```

### GET /api/auth/me

- **Login needed:** Yes
- **Source:** [`app/routers/auth.py` line 34](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/routers/auth.py#L34) (`me`)

**Example request**

```bash
curl "http://localhost:8000/api/auth/me" \
  -H "Authorization: Bearer $TOKEN"
```

## Workspaces

### POST /api/workspaces/{workspace_id}/chat

- **Login needed:** Yes
- **Source:** [`app/routers/chat.py` line 16](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/routers/chat.py#L16) (`chat`)

| Parameter | In | Type |
|---|---|---|
| `workspace_id` | path | `string` |
| `body` | JSON body | `ChatIn` |

`ChatIn` fields:

| Field | Type | Required | Rules |
|---|---|---|---|
| `question` | `str` | Yes | `min_length=1`, `max_length=2000` |
| `top_k` | `int \| None` | No (default `None`) | `ge=1`, `le=20` |

**Example request**

```bash
curl -X POST "http://localhost:8000/api/workspaces/1/chat" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"question": "question", "top_k": 1}'
```

### GET /api/workspaces/{workspace_id}/documents

- **Login needed:** Yes
- **Source:** [`app/routers/documents.py` line 26](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/routers/documents.py#L26) (`list_documents`)

| Parameter | In | Type |
|---|---|---|
| `workspace_id` | path | `string` |

**Example request**

```bash
curl "http://localhost:8000/api/workspaces/1/documents" \
  -H "Authorization: Bearer $TOKEN"
```

### POST /api/workspaces/{workspace_id}/documents

- **Login needed:** Yes
- **Source:** [`app/routers/documents.py` line 31](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/routers/documents.py#L31) (`upload_document`)

| Parameter | In | Type |
|---|---|---|
| `workspace_id` | path | `string` |
| `file` | file upload | `UploadFile` |

**Example request**

```bash
curl -X POST "http://localhost:8000/api/workspaces/1/documents" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@path/to/file"
```

### DELETE /api/workspaces/{workspace_id}/documents/{document_id}

- **Login needed:** Yes
- **Source:** [`app/routers/documents.py` line 75](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/routers/documents.py#L75) (`delete_document`)

| Parameter | In | Type |
|---|---|---|
| `document_id` | path | `int` |
| `workspace_id` | path | `string` |

**Example request**

```bash
curl -X DELETE "http://localhost:8000/api/workspaces/1/documents/1" \
  -H "Authorization: Bearer $TOKEN"
```

### POST /api/workspaces/{workspace_id}/evals

- **Login needed:** Yes
- **Source:** [`app/routers/evals.py` line 24](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/routers/evals.py#L24) (`create_eval_run`)

| Parameter | In | Type |
|---|---|---|
| `workspace_id` | path | `string` |
| `body` | JSON body | `EvalRunIn` |

`EvalRunIn` fields:

| Field | Type | Required | Rules |
|---|---|---|---|
| `cases` | `list[EvalCaseIn]` | Yes | `min_length=1`, `max_length=50` |
| `use_llm_judge` | `bool` | No (default `True`) |  |
| `notes` | `str` | No (default `''`) |  |

**Example request**

```bash
curl -X POST "http://localhost:8000/api/workspaces/1/evals" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"cases": [], "use_llm_judge": true, "notes": ""}'
```

### GET /api/workspaces/{workspace_id}/evals

- **Login needed:** Yes
- **Source:** [`app/routers/evals.py` line 46](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/routers/evals.py#L46) (`list_eval_runs`)

| Parameter | In | Type |
|---|---|---|
| `workspace_id` | path | `string` |

**Example request**

```bash
curl "http://localhost:8000/api/workspaces/1/evals" \
  -H "Authorization: Bearer $TOKEN"
```

### GET /api/workspaces/{workspace_id}/evals/{run_id}

- **Login needed:** Yes
- **Source:** [`app/routers/evals.py` line 52](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/routers/evals.py#L52) (`get_eval_run`)

| Parameter | In | Type |
|---|---|---|
| `run_id` | path | `int` |
| `workspace_id` | path | `string` |

**Example request**

```bash
curl "http://localhost:8000/api/workspaces/1/evals/1" \
  -H "Authorization: Bearer $TOKEN"
```

### GET /api/workspaces

- **Login needed:** Yes
- **Source:** [`app/routers/workspaces.py` line 22](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/routers/workspaces.py#L22) (`list_workspaces`)

**Example request**

```bash
curl "http://localhost:8000/api/workspaces" \
  -H "Authorization: Bearer $TOKEN"
```

### POST /api/workspaces

- **Login needed:** Yes
- **Source:** [`app/routers/workspaces.py` line 27](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/routers/workspaces.py#L27) (`create_workspace`)

| Parameter | In | Type |
|---|---|---|
| `body` | JSON body | `WorkspaceIn` |

`WorkspaceIn` fields:

| Field | Type | Required | Rules |
|---|---|---|---|
| `name` | `str` | Yes | `min_length=1`, `max_length=120` |

**Example request**

```bash
curl -X POST "http://localhost:8000/api/workspaces" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "name"}'
```

### DELETE /api/workspaces/{workspace_id}

- **Login needed:** Yes
- **Source:** [`app/routers/workspaces.py` line 36](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/routers/workspaces.py#L36) (`delete_workspace`)

| Parameter | In | Type |
|---|---|---|
| `workspace_id` | path | `string` |

**Example request**

```bash
curl -X DELETE "http://localhost:8000/api/workspaces/1" \
  -H "Authorization: Bearer $TOKEN"
```

## Code reference

Public functions and classes, grouped by file.

### `app/auth.py`

**`def hash_password(password: str) -> str`** ([line 16](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/auth.py#L16))

**`def verify_password(password: str, hashed: str) -> bool`** ([line 20](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/auth.py#L20))

**`def create_access_token(user_id: int) -> str`** ([line 24](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/auth.py#L24))

**`def get_current_user(token: str=Depends(oauth2_scheme), db: Session=Depends(get_db)) -> User`** ([line 33](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/auth.py#L33))

**`def get_owned_workspace(workspace_id: int, user: User=Depends(get_current_user), db: Session=Depends(get_db)) -> Workspace`** ([line 51](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/auth.py#L51))

Every workspace route goes through this, so users can never see each other's data.

### `app/config.py`

All settings live here. Change providers/models in .env — no code changes needed.

**`class Settings(BaseSettings)`** ([line 7](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/config.py#L7))

**`def get_settings() -> Settings`** ([line 48](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/config.py#L48))

### `app/db.py`

**`class Base(DeclarativeBase)`** ([line 20](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/db.py#L20))

**`def get_db()`** ([line 24](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/db.py#L24))

### `app/embeddings.py`

Free, local embeddings with sentence-transformers (no API key, no cost).

**`class Embedder(Protocol)`** ([line 12](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/embeddings.py#L12))

Methods: `embed()`

**`class SentenceTransformerEmbedder`** ([line 16](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/embeddings.py#L16))

Methods: `embed()`

**`def get_embedder() -> Embedder`** ([line 30](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/embeddings.py#L30))

### `app/evals.py`

Evaluation: how good are the answers, really?

**`def normalize(text: str) -> list[str]`** ([line 30](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/evals.py#L30))

**`def token_f1(prediction: str, reference: str) -> float`** ([line 37](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/evals.py#L37))

**`def parse_judge(raw: str) -> tuple[int | None, str]`** ([line 49](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/evals.py#L49))

**`def judge(llm: LLM, question: str, reference: str, candidate: str) -> tuple[int | None, str]`** ([line 63](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/evals.py#L63))

**`def run_case(case: EvalCaseIn, workspace_id: int, *, llm, embedder, store, top_k: int, use_judge: bool) -> dict`** ([line 75](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/evals.py#L75))

**`def summarize(rows: list[dict]) -> dict`** ([line 108](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/evals.py#L108))

**`def run_eval(cases: list[EvalCaseIn], workspace_id: int, *, llm: LLM, embedder: Embedder, store: ChromaStore, top_k: int, use_judge: bool) -> tuple[dict, list[dict]]`** ([line 127](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/evals.py#L127))

### `app/ingest.py`

PDF -> pages -> overlapping chunks that remember their page number (for citations).

**`class IngestError(ValueError)`** ([line 13](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/ingest.py#L13))

**`def extract_pages(pdf_bytes: bytes) -> list[str]`** ([line 17](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/ingest.py#L17))

**`def clean(text: str) -> str`** ([line 28](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/ingest.py#L28))

**`def split_text(text: str, size: int, overlap: int) -> list[str]`** ([line 36](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/ingest.py#L36))

Split on word boundaries into ~`size`-character windows overlapping by ~`overlap`.

**`def chunk_pages(pages: list[str], document_id: int, filename: str, size: int, overlap: int) -> list[Chunk]`** ([line 60](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/ingest.py#L60))

### `app/llm.py`

Provider-agnostic LLM layer.

**`class LLMError(RuntimeError)`** ([line 22](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/llm.py#L22))

**`class LLM(Protocol)`** ([line 26](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/llm.py#L26))

Methods: `complete()`

**`class OpenAICompatibleLLM`** ([line 32](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/llm.py#L32))

Works for Gemini, Groq, Ollama and anything else that speaks the OpenAI API.

Methods: `complete()`

**`class ClaudeLLM`** ([line 56](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/llm.py#L56))

Methods: `complete()`

**`class FallbackLLM`** ([line 80](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/llm.py#L80))

Try the primary model; if it errors (e.g. free-tier daily limit), use the backup.

Methods: `complete_traced()`, `complete()`

**`def call_llm(llm: LLM, system: str, user: str, temperature: float=0.0) -> tuple[str, str]`** ([line 105](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/llm.py#L105))

Call any LLM and also report which model actually produced the answer.

**`def build_provider(provider: str, model: str, s: Settings) -> LLM`** ([line 112](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/llm.py#L112))

**`def get_llm() -> LLM`** ([line 130](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/llm.py#L130))

FastAPI dependency. Built once, reused for every request.

### `app/main.py`

**`async def lifespan(_: FastAPI)`** ([line 19](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/main.py#L19))

### `app/models.py`

**`def now() -> datetime`** ([line 9](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/models.py#L9))

**`class User(Base)`** ([line 13](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/models.py#L13))

**`class Workspace(Base)`** ([line 23](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/models.py#L23))

**`class Document(Base)`** ([line 35](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/models.py#L35))

**`class EvalRun(Base)`** ([line 47](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/models.py#L47))

### `app/rag.py`

Retrieve -> prompt -> answer with [n] citations.

**`class RagResult`** ([line 22](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/rag.py#L22))

**`def build_prompt(question: str, hits: list[Hit]) -> str`** ([line 30](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/rag.py#L30))

**`def parse_citations(answer: str, n_sources: int) -> list[int]`** ([line 37](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/rag.py#L37))

**`def answer_question(question: str, workspace_id: int, *, llm: LLM, embedder: Embedder, store: ChromaStore, top_k: int) -> RagResult`** ([line 42](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/rag.py#L42))

### `app/routers/documents.py`

**`def to_out(d: Document) -> DocumentOut`** ([line 20](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/routers/documents.py#L20))

### `app/routers/evals.py`

**`def to_out(r: EvalRun) -> EvalRunOut`** ([line 18](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/routers/evals.py#L18))

### `app/routers/workspaces.py`

**`def to_out(ws: Workspace) -> WorkspaceOut`** ([line 17](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/routers/workspaces.py#L17))

### `app/schemas.py`

**`class RegisterIn(BaseModel)`** ([line 7](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/schemas.py#L7))

**`class TokenOut(BaseModel)`** ([line 12](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/schemas.py#L12))

**`class UserOut(BaseModel)`** ([line 17](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/schemas.py#L17))

**`class WorkspaceIn(BaseModel)`** ([line 23](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/schemas.py#L23))

**`class WorkspaceOut(BaseModel)`** ([line 27](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/schemas.py#L27))

**`class DocumentOut(BaseModel)`** ([line 34](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/schemas.py#L34))

**`class ChatIn(BaseModel)`** ([line 43](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/schemas.py#L43))

**`class Source(BaseModel)`** ([line 48](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/schemas.py#L48))

**`class ChatOut(BaseModel)`** ([line 57](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/schemas.py#L57))

**`class EvalCaseIn(BaseModel)`** ([line 66](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/schemas.py#L66))

**`class EvalRunIn(BaseModel)`** ([line 73](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/schemas.py#L73))

**`class EvalRunOut(BaseModel)`** ([line 79](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/schemas.py#L79))

### `app/vectorstore.py`

ChromaDB vector store. One collection; every chunk is tagged with its workspace_id, and every query is filtered by it, so workspaces stay isolated.

**`class Chunk`** ([line 11](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/vectorstore.py#L11))

**`class Hit`** ([line 20](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/vectorstore.py#L20))

**`class ChromaStore`** ([line 25](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/vectorstore.py#L25))

Methods: `add()`, `search()`, `delete_document()`, `delete_workspace()`

**`def get_store() -> ChromaStore`** ([line 80](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/vectorstore.py#L80))

---
*Generated by [Auto-Docs Agent](https://github.com/gideonswer/auto-docs-agent). Endpoint paths, parameters and source links are read from the code; descriptions are AI-written and should be reviewed.*
