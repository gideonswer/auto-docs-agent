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
| `GET` | [`/api/health`](#get-apihealth) | Check service health | No |
| `GET` | [`/`](#get-) | Serve index page | No |
| `POST` | [`/api/auth/register`](#post-apiauthregister) | Register a new user | No |
| `POST` | [`/api/auth/login`](#post-apiauthlogin) | Authenticate a user | No |
| `GET` | [`/api/auth/me`](#get-apiauthme) | Get current user | Yes |
| `POST` | [`/api/workspaces/{workspace_id}/chat`](#post-apiworkspacesworkspaceidchat) | Ask a question in a workspace | Yes |
| `GET` | [`/api/workspaces/{workspace_id}/documents`](#get-apiworkspacesworkspaceiddocuments) | List workspace documents | Yes |
| `POST` | [`/api/workspaces/{workspace_id}/documents`](#post-apiworkspacesworkspaceiddocuments) | Upload a PDF document | Yes |
| `DELETE` | [`/api/workspaces/{workspace_id}/documents/{document_id}`](#delete-apiworkspacesworkspaceiddocumentsdocumentid) | Delete a document | Yes |
| `POST` | [`/api/workspaces/{workspace_id}/evals`](#post-apiworkspacesworkspaceidevals) | Create an evaluation run | Yes |
| `GET` | [`/api/workspaces/{workspace_id}/evals`](#get-apiworkspacesworkspaceidevals) | List evaluation runs | Yes |
| `GET` | [`/api/workspaces/{workspace_id}/evals/{run_id}`](#get-apiworkspacesworkspaceidevalsrunid) | Get a specific eval run | Yes |
| `GET` | [`/api/workspaces`](#get-apiworkspaces) | List user workspaces | Yes |
| `POST` | [`/api/workspaces`](#post-apiworkspaces) | Create a workspace | Yes |
| `DELETE` | [`/api/workspaces/{workspace_id}`](#delete-apiworkspacesworkspaceid) | Delete a workspace | Yes |

## Health

### GET /api/health

Check service health

Returns a JSON object with status ok and LLM provider/model information. If a fallback provider is configured, it is included; otherwise null.

- **Login needed:** No
- **Source:** [`app/main.py` line 33](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/main.py#L33) (`health`)

**Example request**

```bash
curl "http://localhost:8000/api/health"
```

**Response:** A JSON object containing status, llm, and optional fallback fields.

## General

### GET /

Serve index page

Returns the index.html file from the static directory. No JSON body is sent.

- **Login needed:** No
- **Source:** [`app/main.py` line 43](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/main.py#L43) (`index`)

**Example request**

```bash
curl "http://localhost:8000/"
```

**Response:** HTML content of index.html.

## Auth

### POST /api/auth/register

Register a new user

Creates a user with the provided email and password. If the email already exists, returns 409. On success, returns a JWT access token.

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

**Response:** JSON with an access_token field.

**Errors**

- 409: Email already registered

### POST /api/auth/login

Authenticate a user

Validates email and password. If credentials are wrong, returns 401. On success, returns a JWT access token.

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

**Response:** JSON with an access_token field.

**Errors**

- 401: Wrong email or password

### GET /api/auth/me

Get current user

Returns the authenticated user's id and email. Requires a valid JWT.

- **Login needed:** Yes
- **Source:** [`app/routers/auth.py` line 34](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/routers/auth.py#L34) (`me`)

**Example request**

```bash
curl "http://localhost:8000/api/auth/me" \
  -H "Authorization: Bearer $TOKEN"
```

**Response:** JSON with id and email fields.

## Workspaces

### POST /api/workspaces/{workspace_id}/chat

Ask a question in a workspace

Processes the question with the workspace's LLM and returns an answer, sources, cited references, model name, and latency. If the LLM is unavailable, returns 503.

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

**Response:** JSON containing answer, sources list, cited_refs, model, and latency_ms.

**Errors**

- 503: AI model unavailable: <error message>

### GET /api/workspaces/{workspace_id}/documents

List workspace documents

Returns a list of documents belonging to the authenticated user’s workspace.

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

**Response:** Array of DocumentOut objects.

### POST /api/workspaces/{workspace_id}/documents

Upload a PDF document

Accepts a PDF file, extracts pages, creates chunks, stores embeddings, and saves the file. Returns the created document. Errors: 400 for non‑PDF, 413 for oversized, 422 for extraction errors.

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

**Response:** DocumentOut JSON.

**Errors**

- 400: Only PDF files are supported
- 413: File is larger than <max> MB
- 422: <extraction error message>

### DELETE /api/workspaces/{workspace_id}/documents/{document_id}

Delete a document

Removes the document record, its embeddings, and the stored file. Returns 204 on success. If the document does not belong to the workspace, returns 404.

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

**Response:** No content.

**Errors**

- 404: Document not found

### POST /api/workspaces/{workspace_id}/evals

Create an evaluation run

Runs evaluation cases against the workspace's documents. Requires at least one document. Returns the created EvalRun. Errors: 400 if no documents.

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

**Response:** EvalRunOut JSON.

**Errors**

- 400: Upload at least one document before running an eval

### GET /api/workspaces/{workspace_id}/evals

List evaluation runs

Returns all eval runs for the workspace, newest first.

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

**Response:** Array of EvalRunOut objects.

### GET /api/workspaces/{workspace_id}/evals/{run_id}

Get a specific eval run

Returns the eval run if it belongs to the workspace. Errors: 404 if not found.

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

**Response:** EvalRunOut JSON.

**Errors**

- 404: Eval run not found

### GET /api/workspaces

List user workspaces

Returns all workspaces owned by the authenticated user.

- **Login needed:** Yes
- **Source:** [`app/routers/workspaces.py` line 22](https://github.com/gideonswer/chat-with-docs/blob/HEAD/app/routers/workspaces.py#L22) (`list_workspaces`)

**Example request**

```bash
curl "http://localhost:8000/api/workspaces" \
  -H "Authorization: Bearer $TOKEN"
```

**Response:** Array of WorkspaceOut objects.

### POST /api/workspaces

Create a workspace

Creates a new workspace with the given name. Returns the created workspace.

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

**Response:** WorkspaceOut JSON.

### DELETE /api/workspaces/{workspace_id}

Delete a workspace

Deletes the workspace, its embeddings, and all stored files. Returns 204 on success.

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

**Response:** No content.

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
