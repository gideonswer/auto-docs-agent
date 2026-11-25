# chat-with-docs

A lightweight RAG web service that lets you upload PDFs, ask questions, and get answers with page‑level citations. It is for developers who want a quick way to build a document‑centric chatbot.

## Features
- Upload and manage PDF documents per workspace
- Chat interface that returns answers with citations
- JWT‑based authentication and per‑user workspaces
- Automatic chunking of PDFs with overlap for better retrieval
- Vector store backed by ChromaDB, filtered by workspace
- LLM abstraction that supports Gemini, Groq, Claude, or any OpenAI‑compatible provider
- Evaluation pipeline that compares LLM answers to reference answers and reports metrics
- Health endpoint exposing LLM configuration

## How it works
1. A user registers or logs in and receives a JWT token.
2. The user creates a workspace and uploads PDFs.
3. PDFs are parsed into pages, cleaned, split into overlapping chunks, and each chunk is embedded via sentence‑transformers.
4. Chunks are stored in ChromaDB tagged with the workspace ID.
5. When a question is posted, the system embeds the query, retrieves top‑k relevant chunks, builds a prompt with citations, and calls the configured LLM.
6. The LLM response is returned with citation markers and the source passages can be viewed.  
See [ARCHITECTURE.md](ARCHITECTURE.md) for diagrams.

## Tech stack
- Python
- FastAPI
- Uvicorn
- SQLAlchemy
- Pydantic‑settings
- PyJWT
- Bcrypt
- PyPDF
- ChromaDB
- Sentence‑transformers
- OpenAI
- Anthropic
- Pytest
- HTTPX

## Quick start
```bash
git clone https://github.com/gideonswer/chat-with-docs
cd chat-with-docs
python -m venv .venv
source .venv/bin/activate   # On Windows use .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env to set required keys (JWT_SECRET, LLM keys, etc.)
uvicorn app.main:app --reload
```

## Configuration
| Variable | Default | What it does |
|---|---|---|
| `JWT_SECRET` | `paste-a-long-random-string-here` | Generate one with:  python -c "import secrets; print(secrets.token_urlsafe(48))" |
| `LLM_PROVIDER` | `gemini` | Main model: Gemini free tier (key from https://aistudio.google.com/apikey) |
| `LLM_MODEL` | `gemini-3.8-flash` | Primary LLM model name for generating responses |
| `GEMINI_API_KEY` | *(none)* | API key for accessing Gemini LLM service |
| `LLM_FALLBACK_PROVIDER` | `groq` | Backup model: Groq free tier (key from https://console.groq.com/keys) Used automatically if Gemini fails or you hit its daily limit. Leave t |
| `LLM_FALLBACK_MODEL` | `llama-3.3-70b-versatile` | Backup LLM model used if primary fails |
| `GROQ_API_KEY` | *(none)* | API key for accessing Groq LLM service |
| `CHUNK_SIZE` | `900` | RAG tuning (try changes, then re-run your eval to compare) |
| `CHUNK_OVERLAP` | `150` | Number of overlapping tokens between RAG chunks |
| `TOP_K` | `5` | Number of top similar chunks to retrieve for RAG |
| `APP_NAME` | `Chat with Docs` | Displayed name of the chat application |
| `DATABASE_URL` | `sqlite:///./data/app.db` | Connection string for the application's database |
| `CHROMA_DIR` | `./data/chroma` | Directory path for storing Chroma vector store |
| `UPLOAD_DIR` | `./data/uploads` | Directory path for storing uploaded files |
| `MAX_UPLOAD_MB` | `20` | Maximum upload size in megabytes |
| `JWT_ALGORITHM` | `HS256` | Algorithm used to sign JWT tokens |
| `JWT_EXPIRE_MINUTES` | `60 * 24` | Token expiration time in minutes |
| `ANTHROPIC_API_KEY` | *(none)* | API key for accessing Anthropic LLM service |
| `OPENAI_COMPATIBLE_BASE_URL` | `http://localhost:11434/v1` | Base URL for OpenAI-compatible LLM server |
| `OPENAI_COMPATIBLE_API_KEY` | `ollama` | API key for OpenAI-compatible LLM server |
| `EMBEDDING_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | Model used to generate document embeddings |

Copy `.env.example` to `.env` and fill in your values.

## Usage
- **Register**: `POST /api/auth/register` with JSON `{"email":"user@example.com","password":"secret"}`
- **Login**: `POST /api/auth/login` with form data `username=user@example.com&password=secret` → returns JWT token
- **Create workspace**: `POST /api/workspaces` with JSON `{"name":"My Docs"}`
- **Upload PDF**: `POST /api/workspaces/{id}/documents` with multipart file
- **Chat**: `POST /api/workspaces/{id}/chat` with JSON `{"question":"What is X?"}`
- **Evaluation**: `POST /api/workspaces/{id}/evals` with JSON `{"cases":[{...}]}`

## API
The service exposes 15 HTTP routes.  
| Method | Path | Login needed |
|---|---|---|
| `GET` | `/api/health` | No |
| `GET` | `/` | No |
| `POST` | `/api/auth/register` | No |
| `POST` | `/api/auth/login` | No |
| `GET` | `/api/auth/me` | Yes |
| `POST` | `/api/workspaces/{workspace_id}/chat` | Yes |
| `GET` | `/api/workspaces/{workspace_id}/documents` | Yes |
| `POST` | `/api/workspaces/{workspace_id}/documents` | Yes |
| `DELETE` | `/api/workspaces/{workspace_id}/documents/{document_id}` | Yes |
| `POST` | `/api/workspaces/{workspace_id}/evals` | Yes |
| `GET` | `/api/workspaces/{workspace_id}/evals` | Yes |
| `GET` | `/api/workspaces/{workspace_id}/evals/{run_id}` | Yes |
| `GET` | `/api/workspaces` | Yes |
| `POST` | `/api/workspaces` | Yes |
| `DELETE` | `/api/workspaces/{workspace_id}` | Yes |

Full details and examples are in [API.md](API.md).

## Project structure
The repository contains the FastAPI application, routers, models, and utilities.  
```text
chat-with-docs/
├── app/
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── auth.py
│   │   ├── chat.py
│   │   ├── documents.py
│   │   ├── evals.py
│   │   └── workspaces.py
│   ├── static/
│   │   └── index.html
│   ├── __init__.py
│   ├── auth.py
│   ├── config.py
│   ├── db.py
│   ├── embeddings.py
│   ├── evals.py
│   ├── ingest.py
│   ├── llm.py
│   ├── main.py
│   ├── models.py
│   ├── rag.py
│   ├── schemas.py
│   └── vectorstore.py
├── docs/
│   ├── chat-answer.png
│   └── eval-results.png
├── sample_docs/
│   ├── acme_evals.json
│   └── acme_policy.pdf
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_api.py
│   └── test_units.py
├── .env.example
├── .gitignore
├── LICENSE
├── README.md
└── requirements.txt
```

## Running tests
```bash
pytest
```

## License
MIT License

## Configuration

| Variable | Default | What it does |
|---|---|---|
| `JWT_SECRET` | `paste-a-long-random-string-here` | Generate one with:  python -c "import secrets; print(secrets.token_urlsafe(48))" |
| `LLM_PROVIDER` | `gemini` | Main model: Gemini free tier (key from https://aistudio.google.com/apikey) |
| `LLM_MODEL` | `gemini-3.8-flash` | Primary LLM model name for generating responses |
| `GEMINI_API_KEY` | *(none)* | API key for accessing Gemini LLM service |
| `LLM_FALLBACK_PROVIDER` | `groq` | Backup model: Groq free tier (key from https://console.groq.com/keys) Used automatically if Gemini fails or you hit its daily limit. Leave t |
| `LLM_FALLBACK_MODEL` | `llama-3.3-70b-versatile` | Backup LLM model used if primary fails |
| `GROQ_API_KEY` | *(none)* | API key for accessing Groq LLM service |
| `CHUNK_SIZE` | `900` | RAG tuning (try changes, then re-run your eval to compare) |
| `CHUNK_OVERLAP` | `150` | Number of overlapping tokens between RAG chunks |
| `TOP_K` | `5` | Number of top similar chunks to retrieve for RAG |
| `APP_NAME` | `Chat with Docs` | Displayed name of the chat application |
| `DATABASE_URL` | `sqlite:///./data/app.db` | Connection string for the application's database |
| `CHROMA_DIR` | `./data/chroma` | Directory path for storing Chroma vector store |
| `UPLOAD_DIR` | `./data/uploads` | Directory path for storing uploaded files |
| `MAX_UPLOAD_MB` | `20` | Maximum upload size in megabytes |
| `JWT_ALGORITHM` | `HS256` | Algorithm used to sign JWT tokens |
| `JWT_EXPIRE_MINUTES` | `60 * 24` | Token expiration time in minutes |
| `ANTHROPIC_API_KEY` | *(none)* | API key for accessing Anthropic LLM service |
| `OPENAI_COMPATIBLE_BASE_URL` | `http://localhost:11434/v1` | Base URL for OpenAI-compatible LLM server |
| `OPENAI_COMPATIBLE_API_KEY` | `ollama` | API key for OpenAI-compatible LLM server |
| `EMBEDDING_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | Model used to generate document embeddings |

Copy `.env.example` to `.env` and fill in your values.

## API

| Method | Path | Login needed |
|---|---|---|
| `GET` | `/api/health` | No |
| `GET` | `/` | No |
| `POST` | `/api/auth/register` | No |
| `POST` | `/api/auth/login` | No |
| `GET` | `/api/auth/me` | Yes |
| `POST` | `/api/workspaces/{workspace_id}/chat` | Yes |
| `GET` | `/api/workspaces/{workspace_id}/documents` | Yes |
| `POST` | `/api/workspaces/{workspace_id}/documents` | Yes |
| `DELETE` | `/api/workspaces/{workspace_id}/documents/{document_id}` | Yes |
| `POST` | `/api/workspaces/{workspace_id}/evals` | Yes |
| `GET` | `/api/workspaces/{workspace_id}/evals` | Yes |
| `GET` | `/api/workspaces/{workspace_id}/evals/{run_id}` | Yes |
| `GET` | `/api/workspaces` | Yes |
| `POST` | `/api/workspaces` | Yes |
| `DELETE` | `/api/workspaces/{workspace_id}` | Yes |

Full details and examples are in [API.md](API.md).

## Project structure

```text
chat-with-docs/
├── app/
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── auth.py
│   │   ├── chat.py
│   │   ├── documents.py
│   │   ├── evals.py
│   │   └── workspaces.py
│   ├── static/
│   │   └── index.html
│   ├── __init__.py
│   ├── auth.py
│   ├── config.py
│   ├── db.py
│   ├── embeddings.py
│   ├── evals.py
│   ├── ingest.py
│   ├── llm.py
│   ├── main.py
│   ├── models.py
│   ├── rag.py
│   ├── schemas.py
│   └── vectorstore.py
├── docs/
│   ├── chat-answer.png
│   └── eval-results.png
├── sample_docs/
│   ├── acme_evals.json
│   └── acme_policy.pdf
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_api.py
│   └── test_units.py
├── .env.example
├── .gitignore
├── LICENSE
├── README.md
└── requirements.txt
```
