# Sales Intel Agent

Enterprise-grade AI Data Analysis Agent with REST APIs, DuckDB-powered data
ingestion, streaming BI report generation, and Mermaid chart creation. Built
with FastAPI and backed by a DataRobot OpenAI-compatible LLM deployment.

---

## Table of Contents

1. [Architecture](#architecture)
2. [Project Structure](#project-structure)
3. [Core Functionality](#core-functionality)
4. [Module Reference](#module-reference)
   - [Entry Point: `app/main.py`](#entry-point-appmainpy)
   - [Configuration: `app/config.py`](#configuration-appconfigpy)
   - [Constants: `app/constants.py`](#constants-appconstantspy)
   - [Routers](#routers)
   - [Services](#services)
   - [Utils](#utils)
   - [Prompts](#prompts)
5. [API Reference](#api-reference)
6. [Data Flow](#data-flow)
7. [Prompt Management](#prompt-management)
8. [Setup and Installation](#setup-and-installation)
9. [Environment Variables](#environment-variables)
10. [Running with Docker](#running-with-docker)
11. [Tech Stack](#tech-stack)
12. [Extending the System](#extending-the-system)
13. [Observability](#observability)
14. [Security Notes](#security-notes)

---

## Architecture

### High-Level System Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                          Client Application                         │
│                    (REST / SSE consumer)                            │
└────────────────────────────┬────────────────────────────────────────┘
                             │  HTTP / SSE
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        FastAPI Application                          │
│  ┌────────────────┐  ┌────────────────┐  ┌───────────────────────┐  │
│  │  /metadata     │  │  /files        │  │  /chat/completions    │  │
│  │  (metadata.py) │  │  (files.py)    │  │  (chat.py)            │  │
│  └────────────────┘  └───────┬────────┘  └──────────┬────────────┘  │
└──────────────────────────────┼──────────────────────┼───────────────┘
                               │                      │
              ┌────────────────┘                      │
              ▼                                       ▼
┌─────────────────────────┐             ┌─────────────────────────────┐
│      Data Pipeline      │             │       LLM Pipeline          │
│  ┌───────────────────┐  │             │  ┌─────────────────────┐    │
│  │   DataLoader      │  │◀────────────│  │   LLMService        │    │
│  │  (DuckDB/pandas)  │  │  SQL query  │  │  (Two-stage AI)     │    │
│  └───────────────────┘  │             │  └──────────┬──────────┘    │
│  ┌───────────────────┐  │             │             │               │
│  │  FileStorageService│ │             │  ┌──────────▼──────────┐    │
│  │  (JSON index)     │  │             │  │  PDFService         │    │
│  └───────────────────┘  │             │  │  (Mermaid + PDF)    │    │
└─────────┬───────────────┘             │  └─────────────────────┘    │
          │                             └──────────────┬──────────────┘
          │                                            │
          ▼                                            ▼
┌─────────────────┐                       ┌────────────────────────────┐
│    AWS S3       │◀──────────────────────│  DataRobot LLM Endpoint    │
│  (File storage  │   PDF upload          │  (OpenAI-compatible API)   │
│   + PDF reports)│                       └────────────────────────────┘
└─────────────────┘
          ▲
          │  Mermaid diagram render
┌─────────────────┐
│  Mermaid CLI    │
│  (mmdc + Node)  │
└─────────────────┘
```

### Architectural Layers

The application is organized into four distinct layers:

| Layer | Directory | Responsibility |
|-------|-----------|----------------|
| **Routers** | `app/routers/` | HTTP request handling, input validation, response formatting. Thin controllers that delegate all business logic to services. |
| **Services** | `app/services/` | Core business logic — LLM orchestration, data ingestion, file storage, PDF generation, AWS integration. |
| **Utils** | `app/utils/` | Cross-cutting utilities — prompt loading and caching, SQL helpers, chart generation helpers. |
| **Prompts** | `prompts/` | All LLM system prompt text stored as Markdown files, versioned and editable without code changes. |

### Design Principles

- **Separation of concerns** — Each service owns exactly one domain: data loading, LLM calls, file storage, or PDF generation.
- **Externalized prompts** — LLM instructions live in `prompts/` Markdown files. No Python code changes are needed to modify AI behavior.
- **Centralized configuration** — Every environment variable is declared once in `app/config.py` via Pydantic-Settings.
- **Singleton services** — `data_loader`, `llm_service`, `file_storage`, and `s3_client` are module-level singletons to avoid connection churn.
- **Observable by default** — Structured `logging` calls at DEBUG / INFO / WARNING / ERROR levels throughout, never `print()`.

---

## Project Structure

```
sales_intel_agent/
│
├── app/                            # Main application package
│   ├── __init__.py
│   ├── main.py                     # FastAPI app: CORS, lifespan hooks, router registration
│   ├── config.py                   # Pydantic-Settings: all env vars typed and defaulted
│   ├── constants.py                # MIME maps, chart keywords, progress messages, thresholds
│   │
│   ├── models/                     # Pydantic request / response schemas
│   │   ├── __init__.py
│   │   ├── chat.py                 # ChatCompletionRequest, StopResponse, ErrorResponse
│   │   ├── file.py                 # FileUploadResponse, FileErrorResponse
│   │   └── metadata.py             # MetadataResponse with model/filetype/capability fields
│   │
│   ├── routers/                    # FastAPI route handlers (thin controllers)
│   │   ├── __init__.py
│   │   ├── chat.py                 # POST /chat/completions, POST /chat/completions/{id}/stop
│   │   ├── docs.py                 # GET /docs, GET /docs/list, GET /docs/view/{path}
│   │   ├── files.py                # POST /files, GET /files/{id}/url, DELETE /files
│   │   └── metadata.py             # GET /metadata
│   │
│   ├── services/                   # Business logic layer
│   │   ├── __init__.py
│   │   ├── aws_service.py          # boto3 S3 client singleton — credentials from config
│   │   ├── data_loader.py          # File validation → pandas → DuckDB ingestion + query exec
│   │   ├── file_storage.py         # JSON-backed local file index (FileRecord / FileStorageService)
│   │   ├── llm_service.py          # Two-stage LLM pipeline, SSE streaming, stop control
│   │   ├── pdf_service.py          # Mermaid → PNG (via mmdc), Markdown → ReportLab PDF, S3 upload
│   │   ├── puppeteer-config.json   # Headless Chrome config used by Mermaid CLI
│   │   └── query_engine.py         # SQL builder helpers (available for future use)
│   │
│   └── utils/                      # Stateless helper utilities
│       ├── __init__.py
│       ├── chart_generator.py      # Mermaid chart builder helpers (available for future use)
│       ├── prompt_loader.py        # Loads and in-memory caches prompt Markdown files
│       └── sql_generator.py        # NL-to-SQL heuristics (available for future use)
│
├── prompts/                        # Externalized LLM prompt files — no code changes to edit
│   ├── system/
│   │   └── data_analyst.md         # Base system identity: "You are a senior data analyst…"
│   ├── agents/
│   │   ├── analysis_planner.md     # Stage 1 streaming: instructs LLM to return JSON plan + SQL
│   │   ├── bi_report_writer.md     # Stage 2 streaming: instructs LLM to stream Markdown + Mermaid
│   │   ├── simple_analyst_planner.md  # Stage 1 non-streaming variant
│   │   └── simple_bi_writer.md        # Stage 2 non-streaming variant
│   └── templates/
│       └── schema_context.md       # User-message template with {table_name}, {columns}, {query}
│
├── uploads/                        # Local directory for the file-index JSON
│   └── .gitkeep
│
├── docs/                           # All browsable documentation (.md files)
│   ├── ARCHITECTURE.md             # Detailed architectural reference for contributors
│   ├── MIGRATION_NOTES.md          # Notes on schema/structural migrations
│   └── mermaid.md                  # Mermaid chart system reference
├── .env.example                    # Environment variable template — copy to .env
├── .dockerignore
├── .gitignore
├── Dockerfile
├── pyproject.toml
├── requirements.txt
└── start-app.sh                    # Convenience shell script to start the server
```

---

## Core Functionality

### 1. Two-Stage LLM Analysis Pipeline

The heart of the agent is a two-stage LLM pipeline that converts a natural language question about tabular data into a structured BI report. What is produced depends on two **intent flags** detected from the user's message:

| Flag | Detected when the query contains… | Effect |
|------|------------------------------------|--------|
| `needs_visualization` | chart / graph / plot / visualize keywords | `generate_visualization: true` is sent to Stage 2 LLM → Mermaid charts are included |
| `needs_pdf` | download / pdf / save / export keywords | PDF is built and uploaded to S3 after streaming; a file SSE event is sent |

If **neither** flag is set the agent produces a clean **text-only analysis** with no charts and no PDF — maximizing speed for simple data questions.

```
User Question
      │
      ▼
Intent Detection
  ├── contains chart/graph keywords?  →  needs_visualization = true
  └── contains download/pdf keywords? →  needs_pdf = true
      │
      ▼
[Stage 1: Analysis Planner]  →  SQL Queries  →  DuckDB
                                                     │
                                             Query Results
                                                     │
Stage 2 input includes: { generate_visualization: true/false, analysis_results: [...] }
      │
      ▼
[Stage 2: BI Report Writer]
  ├── needs_visualization = true  → Streaming Markdown + Mermaid charts
  └── needs_visualization = false → Streaming Markdown, text-only (no charts)
      │
      ▼ (only when needs_pdf = true)
PDF Generation → S3 Upload → file SSE event
```

**Stage 1 — Analysis Planner** (`prompts/agents/analysis_planner.md`)

The LLM receives the dataset schema (table name, column names, data types) and the user's question. It responds with a structured JSON `analysis_plan` — an array of analysis items, each containing:

- `title` — human-readable name for the sub-analysis
- `analysis_intent` — what insight this query aims to reveal
- `sql` — a DuckDB-compatible SQL query to retrieve the data
- `chart_type`, `x_axis`, `y_axis` — chart configuration for the BI writer

```json
{
  "analysis_plan": [
    {
      "title": "Revenue by Region",
      "analysis_intent": "Compare total revenue across sales regions",
      "sql": "SELECT region, SUM(revenue) AS total_revenue FROM data_abc123 GROUP BY region ORDER BY total_revenue DESC",
      "chart_type": "bar",
      "x_axis": "region",
      "y_axis": "total_revenue"
    }
  ]
}
```

**Stage 2 — BI Report Writer** (`prompts/agents/bi_report_writer.md`)

The LLM receives the original question, the analysis plan, and all SQL query results. It streams back a rich Markdown BI report containing:
- Executive summary
- Section-by-section analysis with insights
- Mermaid chart code blocks for every visualization
- A `\`\`\`suggestions` block with follow-up questions

The response is streamed token-by-token as Server-Sent Events, giving the client a real-time streaming experience.

---

### 2. DuckDB In-Memory Query Engine

Every uploaded file is parsed by `pandas` and loaded into a private DuckDB in-memory table. DuckDB provides full SQL-92 support (window functions, GROUP BY, ORDER BY, JOINs) with zero setup, making it ideal for ad-hoc analytical queries generated by the LLM.

Key behaviors:
- **Auto date detection** — Columns where ≥80% of non-null values parse as dates are automatically converted to ISO-8601 strings to prevent LLM confusion with epoch integers.
- **Unique table names** — Each upload creates a table named `data_<8-char UUID>` so there are no collisions between sessions.
- **Single active dataset** — The global `DataLoader` singleton holds one dataset at a time. Uploading a new file replaces the previous one.

---

### 3. Real-Time SSE Streaming

The `/chat/completions` endpoint returns a `text/event-stream` (`StreamingResponse`). Each line is a `data: <JSON>` SSE event. The event types are:

| Event | When emitted | Key fields |
|-------|-------------|------------|
| `start` | Immediately when pipeline begins | `completionId` |
| `activityDelta` | Background status updates (PDF build progress) | `contentType: "activityChunk"`, `content` |
| `delta` | Each LLM token streamed | `contentType: "textChunk"`, `content` |
| `delta` | After PDF is uploaded | `contentType: "file"`, `content: "{fileId, fileName, sizeInBytes}"` |
| `end` | When the full pipeline completes | `reason: "complete\|stopped\|error"`, `inputTokens`, `outputTokens` |

Clients can stop any in-flight completion by calling `POST /chat/completions/{completionId}/stop`. The `LLMService` checks a per-completion stop flag before yielding each token chunk.

---

### 4. PDF Report Generation (On-Demand Only)

PDF generation is **only triggered when the user explicitly asks for a downloadable file** — i.e., when the query contains keywords like `download`, `pdf`, `save`, `export`, or `generate report`. For regular analytical questions no PDF is created, making responses faster and avoiding unnecessary S3 operations.

When the `needs_pdf` flag is True, a background thread (`ThreadPoolExecutor`) builds a PDF from the accumulated Markdown content after the Stage 2 stream finishes:

1. **Mermaid → PNG** — Each ` ```mermaid ` fence is extracted and rendered to a PNG by invoking the `mmdc` CLI (Mermaid CLI) with a bundled Puppeteer headless Chrome config.
2. **Markdown → ReportLab** — The rest of the Markdown is parsed line-by-line:
   - `#` → Cover page title (centered, large font)
   - `##` → Section heading (triggers a page break before it)
   - `###` → Sub-section heading
   - `- item` → Bullet point
   - Plain text → Body paragraph
   - ` ```suggestions ` blocks are stripped — they are not included in the PDF
3. **S3 Upload** — The completed PDF is uploaded to S3 under `{fileId}/original/Analysis Report.pdf`.
4. **SSE file event** — A `delta` event with `contentType: "file"` is emitted so the client can offer the report for download.

While the PDF is being built, progress messages (`"Formatting report..."`, `"Rendering charts and tables..."`, etc.) are emitted as `activityDelta` SSE events.

---

### 5. File Upload Pipeline

```
multipart/form-data (POST /files)
         │
         ├── Extension / MIME validation
         ├── Size check (max 5 MB by default)
         ├── Save to /tmp/{fileId}/original/
         ├── Upload to S3: {fileId}/original/{filename}
         └── Load into DuckDB via DataLoader.load_file()
                  │
                  ├── pandas.read_csv / read_excel
                  ├── Auto-detect and normalize date columns
                  └── DuckDB: CREATE TABLE data_{uuid} AS SELECT * FROM temp_df
```

File metadata (extension, MIME type, size, local path) is persisted in `uploads/.file_index.json` by `FileStorageService`. Presigned S3 download URLs are generated on demand via `GET /files/{fileId}/url`.

---

## Module Reference

### Entry Point: `app/main.py`

Creates the `FastAPI` application instance. Responsibilities:
- Configures structured logging (level is INFO by default, DEBUG when `DEBUG=true`).
- Registers an `asynccontextmanager` lifespan that logs startup/shutdown.
- Attaches `CORSMiddleware` with `allow_origins=["*"]` for broad compatibility.
- Mounts the three routers: `metadata`, `chat`, `files`.
- Exposes `GET /health` (liveness probe) and `GET /` (root health check).

---

### Configuration: `app/config.py`

A single `Settings` class (Pydantic `BaseSettings`) declares every environment variable with a Python type annotation and a safe default. The `.env` file is loaded automatically.

All application code imports the module-level `settings` singleton:
```python
from app.config import settings
settings.aws_bucket       # "s3-ai-demo-bucket"
settings.max_file_size_mb # 5
```

This guarantees:
- Secrets never appear as hardcoded strings.
- Configuration is validated at import time, not buried in `try/except os.getenv(...)` calls.
- Adding a new variable is a single line in `config.py`.

---

### Constants: `app/constants.py`

Stores all hardcoded values that are not secrets and do not vary by environment:

| Constant | Type | Purpose |
|----------|------|---------|
| `SUPPORTED_EXTENSIONS` | `frozenset` | `{"csv", "xls", "xlsx"}` — valid upload formats |
| `MIME_TO_EXT` | `dict` | Maps MIME types to file extensions for upload detection |
| `DEFAULT_FILE_LABEL` | `str` | `"Confidential"` — applied to every uploaded file |
| `PDF_REPORT_FILENAME` | `str` | Fixed output filename `"Analysis Report.pdf"` |
| `PDF_PROGRESS_MESSAGES` | `list[str]` | Background activity messages streamed during PDF build |
| `PDF_ACTIVITY_START_MESSAGE` | `str` | First activity message when PDF generation begins |
| `NO_DATA_MESSAGE` | `str` | Returned when the user queries with no file uploaded |
| `CHART_KEYWORDS` | `tuple[str, ...]` | Terms like `"chart"`, `"graph"`, `"plot"` — sets `needs_visualization = True` |
| `PDF_KEYWORDS` | `tuple[str, ...]` | Terms like `"download"`, `"pdf"`, `"save"`, `"export"` — sets `needs_pdf = True` |
| `DATE_DETECTION_THRESHOLD` | `float` | `0.8` — 80% of non-null values must parse as dates for auto-conversion |

---

### Routers

#### `app/routers/chat.py`

Handles conversational AI interactions.

| Route | Method | Description |
|-------|--------|-------------|
| `/chat/completions` | POST | Starts a new streaming SSE analysis. Generates a `completionId`, registers it with `LLMService`, and returns a `StreamingResponse`. |
| `/chat/completions/{completion_id}/stop` | POST | Marks the specified completion as stopped. The streaming generator checks this flag before emitting each chunk and exits gracefully. Returns `404 COMPLETION_NOT_FOUND` if the ID is unknown. |

A `verify_auth` dependency is defined but not enforced by default — attach it as `Depends(verify_auth)` to protect individual routes.

#### `app/routers/files.py`

Handles all file lifecycle operations.

| Route | Method | Description |
|-------|--------|-------------|
| `/files` | POST | Validates MIME type and size, saves to `/tmp`, uploads to S3, loads into DuckDB. |
| `/files/{file_id}/url` | GET | Lists S3 objects under `{fileId}/original/`, generates a presigned GET URL valid for `FILE_URL_EXPIRY_SECONDS`. |
| `/files` | DELETE | Accepts `?fileIds=id1,id2,...`, bulk-deletes all S3 objects under each `{fileId}/` prefix. |

Extension resolution priority: `extension` form field → filename suffix → `mimeType` field → `Content-Type` header.

#### `app/routers/metadata.py`

Single route `GET /metadata` that returns capability flags read directly from `settings`:
- Supported model list with mode information
- Default model name
- File type definitions (extension, MIME type, max size)
- `supportsFileUpload: true`
- `supportsStreaming: true`

---

### Services

#### `app/services/llm_service.py` — `LLMService`

The most complex service; owns the entire analysis pipeline.

**Singleton:** `llm_service = LLMService()`

**Initialization:**
- Loads all five prompt files from `prompts/` into `self._prompts` dict at startup. A missing prompt file raises `FileNotFoundError` immediately.
- Initializes `self._active_completions: dict[str, dict]` for stop-control state.

**Key methods:**

| Method | Description |
|--------|-------------|
| `register_completion(id)` | Adds a completion entry with status `"active"`. Called before streaming begins. |
| `stop_completion(id)` | Sets the status to `"stopped"`. Returns `{"found": bool, "status": ..., "message": ...}`. |
| `is_stopped(id)` | Checked before each SSE chunk is yielded. Returns `True` if the completion was stopped. |
| `generate_streaming(messages, completion_id)` | **Main public API.** Async generator. Parses intent flags, checks for data, runs `_run_streaming_pipeline`, emits all SSE events. |
| `generate_response(messages, completion_id)` | Non-streaming variant. Returns a single JSON dict with the full report. |
| `_run_streaming_pipeline(query, data_context, completion_id, needs_visualization, needs_pdf)` | Orchestrates Stage 1 → SQL execution → Stage 2 stream. Injects `generate_visualization` into the Stage 2 payload. Triggers PDF only when `needs_pdf=True`. |
| `_execute_analysis_plan(query, data_context, plan)` | Iterates over each item in the Stage 1 JSON plan, runs its SQL against DuckDB, serializes date objects to ISO strings, and returns a combined results dict for Stage 2. |
| `_parse_user_request(messages)` | Extracts the latest user text. Returns a 3-tuple `(query, needs_visualization, needs_pdf)`. `needs_visualization` is True when `CHART_KEYWORDS` match. `needs_pdf` is True when `PDF_KEYWORDS` match. |
| `_build_data_context()` | Returns `{"has_data": True/False, "table_name": ..., "columns": [...], "dtypes": {...}}` from the `DataLoader` metadata. |

**`_sse(payload)` helper:** Formats any dict as `data: <JSON>\n\n` — the Server-Sent Events wire format.

---

#### `app/services/data_loader.py` — `DataLoader`

**Singleton:** `data_loader = DataLoader()`

Manages the single active dataset across the application lifetime.

**Key methods:**

| Method | Description |
|--------|-------------|
| `load_file(file_path, file_name)` | Validates extension and size → reads with `pandas` → normalizes dates → creates DuckDB table → updates `self._metadata`. Returns the metadata dict. |
| `execute_query(sql)` | Runs arbitrary SQL against the active DuckDB connection. Returns `list[dict]` (one dict per row). |
| `get_column_info()` | Runs `DESCRIBE <table>` and returns column names and DuckDB types. |
| `reset()` | Closes the DuckDB connection and clears all metadata. Useful in tests. |
| `_normalise_date_columns(df)` (static) | For each non-numeric column, attempts `pd.to_datetime`. If ≥80% of non-null values parse successfully, the column is converted to `"%Y-%m-%d"` strings. |

**DuckDB table lifecycle:**
1. `data_loader.conn` is a lazy property that creates a `:memory:` DuckDB connection on first access.
2. Each `load_file` call generates a fresh table name (`data_{uuid8}`), drops any existing table with that name, registers the DataFrame via `conn.register("temp_df", df)`, then materializes it: `CREATE TABLE {name} AS SELECT * FROM temp_df`.

---

#### `app/services/pdf_service.py` — PDF Service

Separates all PDF generation concerns from file-storage bookkeeping.

**Key functions:**

| Function | Description |
|----------|-------------|
| `create_pdf_report(content)` | **Main public API.** Takes the full LLM Markdown string, builds the PDF, uploads to S3, returns `{"fileId", "fileName", "sizeInBytes"}` or `None` on failure. |
| `render_mermaid_to_png(mermaid_code)` | Writes `.mmd` to a temp file, calls `mmdc -p puppeteer-config.json -i <mmd> -o <png> -b white`. Returns `(png_path, mmd_path)`. The caller must clean up both files. |
| `fit_image(path, max_width, max_height)` | Scales a PNG to fit within the given dimensions while preserving aspect ratio. Returns a `reportlab.platypus.Image`. |
| `_markdown_to_reportlab(text)` | Converts `**bold**` to `<b>bold</b>` and escapes `&` for ReportLab XML. |
| `_build_pdf_elements(content, doc)` | Splits content on ` ```mermaid ` fences. Even-indexed parts → `_append_text_block`. Odd-indexed parts (Mermaid code) → `_append_mermaid_block`. Returns the full flowable list. |
| `_append_text_block(text, elements, flag)` | Parses each line: `##` triggers a page break + Heading2; `###` → Heading3; `- ` → bullet; else → body paragraph. |
| `_append_mermaid_block(code, elements, doc)` | Renders to PNG via `render_mermaid_to_png`, fits image to page width, appends. Logs a warning and appends an error paragraph on failure. Always cleans up temp files. |

**PDF layout:**
- Cover page: Centered title extracted from the first `# Heading` in the Markdown.
- Each `##` section starts on a new page.
- Margins: 40 pt on all sides.
- The ` ```suggestions` block is stripped before rendering.

---

#### `app/services/file_storage.py` — `FileStorageService`

**Singleton:** `file_storage = FileStorageService()`

Maintains a local JSON registry at `uploads/.file_index.json`. Each entry is a `FileRecord` with: `file_id`, `file_name`, `size_in_bytes`, `mime_type`, `extension`, `file_path`, `label`, `uploaded_at`.

On startup, the index is loaded and stale records (whose `file_path` no longer exists on disk) are silently dropped.

**Key methods:**

| Method | Description |
|--------|-------------|
| `store(...)` | Creates a `FileRecord` with a new UUID, persists index to disk. |
| `get(file_id)` | Returns the `FileRecord` or `None`. |
| `delete(file_id)` | Removes the record, deletes the on-disk file, persists index. |
| `delete_many(file_ids)` | Bulk delete, returns `{file_id: was_found}` mapping. |
| `generate_url(file_id)` | Builds a local download URL dict. Used when S3 is unavailable. |

---

#### `app/services/aws_service.py`

Creates and exports the module-level `s3_client` (a `boto3.client("s3", ...)`) and the `BUCKET` name, both sourced from `settings`. No credentials are hardcoded.

---

### Utils

#### `app/utils/prompt_loader.py` — `PromptLoader`

**Singleton:** `prompt_loader = PromptLoader()`

Resolves all paths relative to `prompts/` at the project root (two directories above `app/utils/`).

| Method | Description |
|--------|-------------|
| `load(relative_path)` | Returns prompt text. Reads from disk on first call, returns cached value on subsequent calls. Raises `FileNotFoundError` for missing files. |
| `format(relative_path, **kwargs)` | Loads the prompt and calls `.format(**kwargs)` for template variable substitution. |
| `clear_cache()` | Evicts all cached prompts. Useful in tests or hot-reload development scenarios. |

---

### Prompts

All LLM instructions live in the `prompts/` directory as Markdown files. No Python code changes are required to modify AI behavior — edit the files directly.

| File | Purpose |
|------|---------|
| `prompts/system/data_analyst.md` | Base system identity injected into every LLM call. |
| `prompts/agents/analysis_planner.md` | Stage 1 streaming prompt — instructs the LLM to return a JSON plan and SQL queries. |
| `prompts/agents/bi_report_writer.md` | Stage 2 streaming prompt — instructs the LLM to stream Markdown and Mermaid charts. |
| `prompts/agents/simple_analyst_planner.md` | Stage 1 non-streaming variant. |
| `prompts/agents/simple_bi_writer.md` | Stage 2 non-streaming variant. |
| `prompts/templates/schema_context.md` | User-message template with `{table_name}`, `{columns}`, and `{query}` placeholders. |

Prompts are loaded and cached by `PromptLoader` (see [Utils](#utils) above). See [Prompt Management](#prompt-management) for the full authoring guide.

---

## API Reference

### GET /metadata

Returns supported models, file types, and capability flags.

**Response:**
```json
{
  "modelsSupported": [
    { "modelName": "gpt-5 mini", "modes": ["quick_search"], "defaultMode": "quick_search" }
  ],
  "defaultModel": "gpt-5 mini",
  "supportsFileUpload": true,
  "fileTypes": [
    { "extension": "csv",  "mimeType": "text/csv",                                                    "maxSizeInBytes": 5242880 },
    { "extension": "xls",  "mimeType": "application/vnd.ms-excel",                                   "maxSizeInBytes": 5242880 },
    { "extension": "xlsx", "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "maxSizeInBytes": 5242880 }
  ],
  "maxFileUploadCount": 1,
  "supportsStreaming": true
}
```

---

### POST /files

Upload a CSV, XLS, or XLSX file for analysis.

**Request:** `multipart/form-data`

| Field       | Type   | Required | Description                           |
|-------------|--------|----------|---------------------------------------|
| `file`      | File   | Yes      | The data file to upload               |
| `fileName`  | string | No       | Override the display name             |
| `mimeType`  | string | No       | Override MIME-type detection          |
| `extension` | string | No       | Override extension detection          |

**Response (200):**
```json
{
  "fileId": "550e8400-e29b-41d4-a716-446655440000",
  "fileName": "sales_2024.csv",
  "sizeInBytes": 204800,
  "label": "Confidential"
}
```

**Error codes:** `EMPTY_FILE`, `UNSUPPORTED_FILE`, `FILE_SIZE_EXCEEDED`, `COULD_NOT_PROCESS`

---

### GET /files/{fileId}/url

Returns a presigned S3 download URL for an uploaded file.

**Response (200):**
```json
{
  "url": "https://s3.amazonaws.com/...",
  "expiresIn": 3600,
  "mimeType": "text/csv",
  "fileName": "sales_2024.csv",
  "sizeInBytes": 204800
}
```

---

### DELETE /files

Bulk-delete files from S3.

**Query parameter:** `fileIds` — comma-separated file IDs.

**Response (200):**
```json
{ "message": "File deleted successfully." }
```

---

### POST /chat/completions

Send a conversational query. Returns a **Server-Sent Events** stream.

**Request:**
```json
{
  "chatId": "64d5f9e8b3a2c4d1e8f7a123",
  "messageId": "ff3effb6-a8cf-4361-9e80-d3e85db8232f",
  "model": "gpt-5 mini",
  "mode": "quick_search",
  "messages": [
    {
      "role": "user",
      "contents": [
        { "contentType": "text", "content": "What was the total revenue by region?" }
      ]
    }
  ],
  "files": []
}
```

**SSE event types:**

| Event          | Fields                                                     | Description                       |
|----------------|------------------------------------------------------------|-----------------------------------|
| `start`        | `completionId`                                             | Pipeline has started              |
| `delta`        | `contentType: "textChunk"`, `content: "<text>"`            | Streaming Markdown chunk          |
| `activityDelta`| `contentType: "activityChunk"`, `content: "<status text>"` | Background activity message       |
| `delta`        | `contentType: "file"`, `content: "{fileId, fileName, ...}"` | PDF report reference             |
| `end`          | `reason: "complete|stopped|error"`, `inputTokens`, `outputTokens` | Stream finished            |

---

### POST /chat/completions/{completionId}/stop

Stop an in-progress streaming completion.

**Response (200):**
```json
{
  "completionId": "abc123",
  "status": "stopped",
  "message": "Chat completion successfully stopped"
}
```

**Error (404):** `COMPLETION_NOT_FOUND`

---

### GET /health

Liveness probe.

**Response:** `{ "status": "ok", "app": "Sales Intel Agent" }`

---

## Data Flow

```
User Question
      │
      ▼
_parse_user_request()
      ├── Extract query text from last user message
      ├── needs_visualization = any(CHART_KEYWORDS in query)   e.g. "show me a chart", "graph", "plot"
      └── needs_pdf           = any(PDF_KEYWORDS   in query)   e.g. "download", "save", "export pdf"
      │
      ▼
_build_data_context()      Fetch table name, column names, dtype map from DataLoader.metadata
      │
      ▼
Stage 1 LLM call           System: prompts/agents/analysis_planner.md
      │                    User:   "Schema: tablename: data_abc, columns: [...], User Question: ..."
      │                    Response: JSON { "analysis_plan": [ { "sql": "...", "chart_type": ... } ] }
      ▼
_execute_analysis_plan()   For each plan item: run SQL via data_loader.execute_query()
      │                    Serialize date objects to ISO-8601 strings
      │                    Inject "generate_visualization": true/false into final_output
      ▼
Stage 2 LLM streaming      System: prompts/agents/bi_report_writer.md
      │                    User:   JSON {
      │                              generate_visualization: true | false,   ← controls chart output
      │                              user_question, dataset_context,
      │                              analysis_results: [...]
      │                            }
      │
      ├── needs_visualization = true  → LLM streams Markdown + Mermaid chart blocks
      └── needs_visualization = false → LLM streams text-only Markdown (no charts)
      │
      ▼
SSE delta events           Each token chunk → "data: {event: delta, contentType: textChunk, content: ...}"
      │
      ▼ (only when needs_pdf = true)
PDF generation             After stream ends:
(ThreadPoolExecutor)       1. Extract Mermaid blocks → render each via mmdc → PNG
                           2. Parse remaining Markdown → ReportLab flowables
                           3. Build PDF with cover page + section pages
                           4. Upload PDF to S3 at {fileId}/original/Analysis Report.pdf
                           5. Generate presigned URL
      │
      ▼ (only when needs_pdf = true)
SSE file event             "data: {event: delta, contentType: file, content: {fileId, fileName, sizeInBytes}}"
      │
      ▼
SSE end event              "data: {event: end, reason: complete, inputTokens: 0, outputTokens: 0}"
```

### Intent Detection Summary

| User asks… | `needs_visualization` | `needs_pdf` | Result |
|---|---|---|---|
| "What was total revenue by region?" | `false` | `false` | Text-only analysis, no charts, no PDF |
| "Show me a bar chart of revenue by region" | `true` | `false` | Analysis with Mermaid charts, no PDF |
| "Download a report of revenue by region" | `false` | `true` | Text-only analysis saved as PDF |
| "Show a chart and download the report" | `true` | `true` | Analysis with charts, saved as PDF |

---

## Prompt Management

All LLM system prompts live under the `prompts/` directory as Markdown files.
They are loaded once at startup by `PromptLoader` and cached in memory.

**To update a prompt:**

1. Edit the relevant file in `prompts/agents/` or `prompts/system/`.
2. Restart the application (or call `prompt_loader.clear_cache()` in dev mode).
3. No Python code changes required.

| File                                | Purpose                                     |
|-------------------------------------|---------------------------------------------|
| `system/data_analyst.md`            | Base system instruction — LLM identity, tone, output format rules |
| `agents/analysis_planner.md`        | Stage 1 streaming: instructs LLM to produce a JSON analysis plan with SQL queries |
| `agents/bi_report_writer.md`        | Stage 2 streaming: reads `generate_visualization` flag from input — generates Mermaid charts only when `true`, text-only analysis when `false` |
| `agents/simple_analyst_planner.md`  | Stage 1 non-streaming: simpler JSON output schema |
| `agents/simple_bi_writer.md`        | Stage 2 non-streaming: returns `{"summary": "...", "mermaid": "..."}` |
| `templates/schema_context.md`       | User-message template with `{table_name}`, `{columns}`, `{dtypes}`, `{query}` |

---

## Setup and Installation

### Prerequisites

- Python ≥ 3.11
- Node.js 22 + `@mermaid-js/mermaid-cli` installed globally (`npm install -g @mermaid-js/mermaid-cli`)
- A DataRobot-deployed LLM with an OpenAI-compatible chat endpoint
- An AWS S3 bucket

### Installation

```bash
git clone <repo-url> sales_intel_agent
cd sales_intel_agent

# Copy and configure environment variables
cp .env.example .env
# Edit .env: set DATAROBOT_API_TOKEN, CHAT_API_URL, AWS_*, etc.

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Running locally

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8080
```

OpenAPI docs: [http://localhost:8080/docs](http://localhost:8080/docs)

---

## Environment Variables

| Variable               | Default                    | Description                                                  |
|------------------------|----------------------------|--------------------------------------------------------------|
| `APP_NAME`             | `Sales Intel Agent`        | Application display name                                     |
| `DEBUG`                | `false`                    | Enable DEBUG-level logging                                   |
| `BASE_URL`             | `http://localhost:8080`    | Public base URL for local file download links                |
| `UPLOAD_DIR`           | `uploads`                  | Local directory for the file-index JSON                      |
| `MAX_FILE_SIZE_MB`     | `5`                        | Maximum upload size in MB                                    |
| `MAX_FILE_UPLOAD_COUNT`| `1`                        | Maximum files per upload request                             |
| `FILE_URL_EXPIRY_SECONDS` | `3600`                  | Presigned S3 URL TTL in seconds                              |
| `DEFAULT_MODEL`        | `gpt-5 mini`               | Model name returned in GET /metadata                         |
| `DATAROBOT_API_TOKEN`  | —                          | API token for the DataRobot LLM endpoint                     |
| `CHAT_API_URL`         | —                          | DataRobot OpenAI-compatible endpoint URL                     |
| `LLM_MODEL`            | `datarobot-deployed-llm`   | Model identifier sent to the LLM API                         |
| `AWS_ACCESS_KEY_ID`    | —                          | AWS credentials                                              |
| `AWS_SECRET_ACCESS_KEY`| —                          | AWS credentials                                              |
| `REGION_NAME`          | `ap-southeast-2`           | AWS region                                                   |
| `AWS_BUCKET`           | `s3-ai-demo-bucket`        | S3 bucket for files and PDF reports                          |
| `PUPPETEER_CONFIG_PATH`| *(bundled default)*        | Path to a custom Puppeteer config for the Mermaid CLI        |

---

## Running with Docker

```bash
# Build
docker build -t sales-intel-agent .

# Run (pass .env at runtime — never bake secrets into the image)
docker run -p 8080:8080 --env-file .env sales-intel-agent
```

---

## Tech Stack

| Component        | Technology                                   |
|------------------|----------------------------------------------|
| Web Framework    | FastAPI                                      |
| Database         | DuckDB (in-memory)                           |
| Data Processing  | pandas, openpyxl, xlrd                       |
| LLM Client       | OpenAI SDK (DataRobot-compatible)            |
| Schema Validation| Pydantic v2 + pydantic-settings              |
| File Storage     | AWS S3 (boto3)                               |
| PDF Generation   | ReportLab                                    |
| Chart Rendering  | Mermaid CLI (`mmdc`) → PNG                   |
| Streaming        | Server-Sent Events (SSE) via FastAPI         |

---

## Extending the System

### Adding a New AI Agent / Pipeline Stage

1. Create a prompt file: `prompts/agents/your_agent.md`
2. Load it in `LLMService.__init__`:
   ```python
   self._prompts["your_agent"] = prompt_loader.load("agents/your_agent.md")
   ```
3. Add a method in `LLMService` (or a new service) that calls `_get_openai_client()`.
4. Wire it to a new route in `app/routers/`.

No changes needed to `config.py`, `constants.py`, or any unrelated service.

### Adding a New API Endpoint

1. Add Pydantic request/response models to the appropriate file in `app/models/`.
2. Create the route handler in the relevant `app/routers/` file.
3. If new business logic is required, add a method to an existing service or create `app/services/my_service.py`.
4. Register the router in `app/main.py` only if a new router file was created.

### Scalability Considerations

| Constraint | Current state | Recommended path |
|------------|---------------|------------------|
| Single in-memory dataset | One `DataLoader` singleton | Per-session dataset with Redis/DB mapping |
| Synchronous PDF generation | `ThreadPoolExecutor(1)` | Celery / background task queue |
| LLM completion stop state | In-process dict | Redis for multi-process/worker setups |
| `time.sleep` blocking event loop | Present in PDF progress loop | Replace with `asyncio.sleep` |
| No test suite | Absent | Add pytest fixtures + httpx async client |

---

## Observability

| Level   | What is logged                                                          |
|---------|-------------------------------------------------------------------------|
| INFO    | App start/stop, file uploads, S3 operations, prompt load count          |
| WARNING | SQL execution failures, S3 presigned URL failures, DuckDB load errors   |
| ERROR   | LLM call failures, PDF generation failures, unhandled exceptions         |
| DEBUG   | Completion lifecycle events, individual prompt loads, S3 object counts  |

Log format: `TIMESTAMP  LEVEL    module  message`

Enable DEBUG logs by setting `DEBUG=true` in your `.env`.

---

## Security Notes

- Secrets are never hardcoded — all credentials are read from environment variables.
- File uploads are validated by extension and size before any processing.
- The agent does not execute arbitrary code or make external HTTP requests beyond
  the configured LLM endpoint and AWS S3.
- The `Authorization` header is parsed on all routes but enforcement is opt-in
  per route (add `Depends(verify_auth)` to enforce).
- Presigned S3 URLs expire after `FILE_URL_EXPIRY_SECONDS` (default 1 hour).
- Temporary files written to `/tmp` during PDF generation are cleaned up after each render.
