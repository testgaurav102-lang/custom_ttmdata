# Architecture Overview

## Design Goals

| Goal | How it is achieved |
|------|--------------------|
| Separation of concerns | Layers: Routers → Services → Utils; PDF generation isolated from file storage |
| Externalized prompts | All LLM prompts in `prompts/` as Markdown; zero code changes to update a prompt |
| Centralised config | Single `app/config.py` via Pydantic-Settings; no scattered `os.getenv` calls |
| Observable errors | Python `logging` throughout; `print()` replaced by structured log calls |
| Scalability | Modular services, clear interfaces, easy to add new agents/routes/tools |
| Intent-driven output | Visualization and PDF generation are gated behind per-request intent flags; no unnecessary work |

---

## Layer Map

```
HTTP Request
     │
     ▼
┌────────────────────────────────────────────────────┐
│  Routers  (app/routers/)                           │
│  chat.py · files.py · metadata.py                  │
│  Thin controllers — validate, delegate, respond     │
└──────────────────────────┬─────────────────────────┘
                           │
          ┌────────────────┼──────────────────┐
          ▼                ▼                  ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│ LLMService   │  │ DataLoader   │  │ FileStorage  │
│ (llm_service)│  │ (data_loader)│  │ (file_storage│
│              │  │              │  │  + pdf_svc)  │
│ Two-stage    │  │ DuckDB       │  │ Local index  │
│ LLM pipeline │  │ ingestion &  │  │ + S3 upload  │
│ + SSE stream │  │ SQL execution│  │ + PDF gen    │
│ + intent     │  │              │  │ (on-demand)  │
│   detection  │  │              │  │              │
└──────┬───────┘  └──────────────┘  └──────────────┘
       │
       ▼
┌──────────────────────────────────────────────────┐
│  External Services                               │
│  DataRobot LLM (OpenAI SDK) · AWS S3 · mmdc CLI │
└──────────────────────────────────────────────────┘
```

---

## Intent Detection System

Every `POST /chat/completions` request passes through `_parse_user_request()` which derives
two boolean intent flags from the user's natural language query before anything else runs:

```
User Query text
      │
      ├─ contains CHART_KEYWORDS?  →  needs_visualization = True
      │  (chart, graph, plot, visualize, bar chart, …)
      │
      └─ contains PDF_KEYWORDS?    →  needs_pdf = True
         (download, pdf, save, export, generate report, …)
```

These flags control two downstream decisions independently:

| Flag | Effect on Stage 2 LLM | Effect on post-stream work |
|------|----------------------|---------------------------|
| `needs_visualization = True` | `generate_visualization: true` injected into Stage 2 JSON payload → LLM produces Mermaid chart blocks | — |
| `needs_visualization = False` | `generate_visualization: false` injected → LLM produces text-only analysis, no Mermaid blocks | — |
| `needs_pdf = True` | — | PDF is built (`ThreadPoolExecutor`), uploaded to S3, file SSE event emitted |
| `needs_pdf = False` | — | PDF step is **skipped entirely** — faster response, no S3 write |

---

## Streaming Pipeline Detail

```
generate_streaming(messages, completion_id)
  │
  ├─ _parse_user_request()   →  (query, needs_visualization, needs_pdf)
  ├─ _build_data_context()   →  {table_name, columns, dtypes}
  │
  └─ _run_streaming_pipeline(query, data_context, completion_id,
                              needs_visualization, needs_pdf)
       │
       ├─ Stage 1: LLM call (analysis_planner.md)
       │    Returns JSON { "analysis_plan": [ { sql, chart_type, … } ] }
       │
       ├─ _execute_analysis_plan()
       │    Runs each SQL against DuckDB
       │    Injects "generate_visualization": true/false into final_output
       │
       ├─ Stage 2: LLM streaming (bi_report_writer.md)
       │    Reads generate_visualization flag from input JSON
       │    true  → streams Markdown + Mermaid chart blocks
       │    false → streams text-only Markdown analysis
       │
       └─ (only when needs_pdf = True)
            create_pdf_report()
              ├─ render_mermaid_to_png() via mmdc CLI
              ├─ _build_pdf_elements() → ReportLab flowables
              ├─ S3 upload
              └─ emit file SSE event
```

---

## Key Components

### `app/config.py` — Settings
Single source of truth for every configurable value. All settings are declared
as Pydantic fields with types, defaults, and descriptions. New settings are
added here; application code reads from `settings.*`.

### `app/constants.py` — Constants
Hardcoded strings, lookup maps, and enumerations that are not secrets and do not
change between environments:

| Constant | Purpose |
|----------|---------|
| `SUPPORTED_EXTENSIONS` | Valid upload file types |
| `MIME_TO_EXT` | MIME type → extension mapping for upload detection |
| `CHART_KEYWORDS` | Trigger words that set `needs_visualization = True` |
| `PDF_KEYWORDS` | Trigger words that set `needs_pdf = True` |
| `DATE_DETECTION_THRESHOLD` | 80% threshold for auto date-column conversion |
| `PDF_PROGRESS_MESSAGES` | Activity messages streamed during PDF build |
| `NO_DATA_MESSAGE` | Fallback when no dataset is loaded |

### `app/utils/prompt_loader.py` — PromptLoader
Loads prompt Markdown files from `prompts/` relative to the project root.
Files are cached in memory after the first read. Call `clear_cache()` to force
a reload (useful in development).

### `app/services/llm_service.py` — LLMService
Owns the complete analysis pipeline including intent detection:

```
generate_streaming()
  └─ _run_streaming_pipeline(needs_visualization, needs_pdf)
       ├─ Stage 1: LLM generates analysis plan (JSON with SQL queries)
       ├─ _execute_analysis_plan() → runs SQL + injects generate_visualization flag
       ├─ Stage 2: LLM streams Markdown BI report (with or without Mermaid, per flag)
       └─ create_pdf_report() → only when needs_pdf = True
```

### `app/services/pdf_service.py` — PDF Service
Encapsulates all PDF generation concerns. Called **only when `needs_pdf` is True**:
- `render_mermaid_to_png()` — calls `mmdc` CLI to render Mermaid diagrams.
- `create_pdf_report()` — parses LLM Markdown into a ReportLab document,
  uploads to S3, and returns file metadata.

### `app/services/data_loader.py` — DataLoader
Singleton that holds the currently active dataset:
- Validates file type and size.
- Reads CSV/XLS/XLSX into a pandas DataFrame.
- Auto-detects and normalises date columns.
- Registers the DataFrame as a DuckDB in-memory table.
- `execute_query(sql)` — runs arbitrary SQL and returns rows as dicts.

### `app/services/file_storage.py` — FileStorageService
Maintains a JSON file index (`uploads/.file_index.json`) mapping `file_id` →
`FileRecord`. Records with missing on-disk paths are discarded at startup.
Used for local development scenarios where S3 is not required.

### `app/services/aws_service.py` — AWS
Creates and exports the boto3 S3 client singleton. The bucket name and
credentials are read from `settings` to avoid hardcoding.

---

## Prompt Directory Layout

```
prompts/
├── system/
│   └── data_analyst.md            # Base LLM identity/instruction
├── agents/
│   ├── analysis_planner.md        # Stage 1 streaming: returns JSON analysis plan
│   ├── bi_report_writer.md        # Stage 2 streaming: reads generate_visualization flag;
│   │                              #   true  → Markdown + Mermaid charts
│   │                              #   false → text-only Markdown analysis
│   ├── simple_analyst_planner.md  # Stage 1 non-streaming variant
│   └── simple_bi_writer.md        # Stage 2 non-streaming variant
└── templates/
    └── schema_context.md          # User-message template ({table_name}, {columns}, …)
```

**Loading convention:** `prompt_loader.load("agents/analysis_planner.md")`

---

## Adding a New Agent or Pipeline

1. Create a prompt file under `prompts/agents/your_agent.md`.
2. Load it in `LLMService.__init__`:
   ```python
   self._prompts["your_agent"] = prompt_loader.load("agents/your_agent.md")
   ```
3. Add a method in `LLMService` (or a new service) that calls `_get_openai_client()`.
4. Wire it to a new router endpoint in `app/routers/`.

No changes are needed to `config.py`, `constants.py`, or any unrelated service.

---

## Adding a New Intent Flag

1. Add the trigger keywords to `app/constants.py` as a new `tuple[str, ...]`.
2. In `_parse_user_request()` in `llm_service.py`, detect the new keywords and set a new boolean.
3. Return the new flag from `_parse_user_request` (extend the return tuple).
4. Consume it in `_run_streaming_pipeline()` or wherever appropriate.

---

## Adding a New API Endpoint

1. Add request/response Pydantic models to the appropriate file in `app/models/`.
2. Create the route in the relevant `app/routers/` file.
3. If new business logic is required, add it to an existing service or create
   a new `app/services/my_service.py`.
4. Register the router in `app/main.py` if a new router file was created.

---

## Observability

| Level | What is logged |
|-------|----------------|
| INFO | App start/stop, file uploads, S3 operations, prompt load count, PDF generation triggered |
| WARNING | SQL execution failures, S3 presigned URL failures, DuckDB load errors |
| ERROR | LLM call failures, PDF generation failures, unhandled exceptions |
| DEBUG | Intent flags (needs_visualization, needs_pdf), completion lifecycle, prompt loads, S3 counts |

Log format: `TIMESTAMP  LEVEL    module  message`

Enable DEBUG logs by setting `DEBUG=true` in your `.env`.

---

## Scalability Considerations

| Constraint | Current state | Recommended path |
|------------|---------------|------------------|
| Single in-memory dataset | One `DataLoader` singleton | Per-session dataset with Redis/DB mapping |
| Synchronous PDF generation | `ThreadPoolExecutor(1)` | Celery / background task queue |
| LLM completion stop state | In-process dict | Redis for multi-process/worker setups |
| `time.sleep` blocking event loop | Present in PDF progress loop | Replace with `asyncio.sleep` |
| Intent detection is keyword-based | Simple string matching | NLU/classifier model for richer intent detection |
| No test suite | Absent | Add pytest fixtures + httpx async client |
