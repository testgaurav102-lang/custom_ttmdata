# Migration Notes

This document records every change made during the refactoring and enhancement
of the Sales Intel Agent codebase.  All existing functionality is preserved
unless explicitly noted.

---

## Summary

| Category                 | Change type  | Impact                                            |
|--------------------------|--------------|---------------------------------------------------|
| Prompt externalization   | New files    | Prompts editable without code changes             |
| PDF service extraction   | New file     | Clear separation of PDF vs. file-storage concerns |
| Constants module         | New file     | Hardcoded values centralised                      |
| Config enhancements      | Modified     | `aws_bucket`, `llm_model`, `puppeteer_config_path`|
| Bug fixes (files.py)     | Modified     | Missing imports, undefined vars corrected         |
| Logging                  | Modified     | `print()` replaced with structured logging        |
| Package `__init__.py`    | New files    | Explicit package declarations                     |
| pyproject.toml           | Modified     | Synced with requirements.txt                      |
| Dockerfile               | Modified     | Adds `COPY prompts ./prompts`                     |
| `.env.example`           | New file     | Template for all required env vars                |
| README.md                | Modified     | Reflects actual API routes and behavior           |
| ARCHITECTURE.md          | New file     | Design overview, layer map, scalability notes     |

---

## New Files

| File                                      | Purpose                                                          |
|-------------------------------------------|------------------------------------------------------------------|
| `app/__init__.py`                         | Explicit package declaration                                     |
| `app/models/__init__.py`                  | Explicit package declaration                                     |
| `app/routers/__init__.py`                 | Explicit package declaration                                     |
| `app/services/__init__.py`               | Explicit package declaration                                     |
| `app/utils/__init__.py`                   | Explicit package declaration                                     |
| `app/constants.py`                        | MIME maps, file extension set, chart keywords, progress messages |
| `app/utils/prompt_loader.py`              | File-based prompt loading with in-memory cache                   |
| `app/services/pdf_service.py`             | Mermaid → PNG rendering, Markdown → PDF, S3 upload              |
| `prompts/system/data_analyst.md`          | Extracted `SYSTEM_PROMPT` from `llm_service.py`                  |
| `prompts/agents/analysis_planner.md`      | Extracted Stage 1 streaming system prompt                        |
| `prompts/agents/bi_report_writer.md`      | Extracted Stage 2 streaming system prompt                        |
| `prompts/agents/simple_analyst_planner.md`| Extracted Stage 1 non-streaming system prompt                    |
| `prompts/agents/simple_bi_writer.md`      | Extracted Stage 2 non-streaming system prompt                    |
| `prompts/templates/schema_context.md`     | Schema + question user-message template                          |
| `.env.example`                            | Template covering all required environment variables             |
| `ARCHITECTURE.md`                         | Design overview, layer map, extensibility guide                  |
| `MIGRATION_NOTES.md`                      | This file                                                        |

---

## Modified Files

### `app/config.py`
- Added `llm_model: str = "datarobot-deployed-llm"` — previously hardcoded in `llm_service.py`.
- Added `aws_bucket: str = "s3-ai-demo-bucket"` — previously hardcoded in `aws_service.py`.
- Added `puppeteer_config_path: str = ""` — allows overriding the bundled Puppeteer config.
- Added module-level docstring.

### `app/services/aws_service.py`
- `BUCKET` now reads from `settings.aws_bucket` instead of being a hardcoded string literal.
- Added logging.

### `app/services/data_loader.py`
- Replaced `print()` calls with `logger.debug()` / `logger.info()` / `logger.warning()`.
- Extracted date-normalisation logic into `_normalise_date_columns()` static method.
- Imported `DATE_DETECTION_THRESHOLD` from `app.constants` (was a local magic number `0.8`).
- Improved docstrings.

### `app/services/file_storage.py`
- **Removed** all PDF/Mermaid/ReportLab code (moved to `pdf_service.py`).
- Added `logging` throughout.
- Module-level style definitions removed (now in `pdf_service.py`).

### `app/services/llm_service.py`
- **Removed** five inline string literal system prompts (~400 lines of prompt text).
- **Added** `PromptLoader` usage — prompts loaded from `prompts/` files at startup.
- **Removed** unused imports: `generate_sql_from_query`, `ChartGenerator`, `file_storage`.
- Added `from app.services.pdf_service import create_pdf_report` (was `from app.services.file_storage import ...`).
- `BUCKET` and hardcoded `"datarobot-deployed-llm"` model string replaced with `settings.llm_model`.
- Extracted `_execute_analysis_plan()` helper method for cleaner `_run_streaming_pipeline()`.
- Added `_sse()` module-level helper to DRY up SSE event formatting.
- Added `logging` throughout; removed all `print()` calls.
- Minor: `_parse_user_request` uses `next(... for ... in reversed())` instead of a manual loop.

### `app/routers/files.py`
**Bug fixes:**
- Added `from botocore.exceptions import ClientError` (was missing, caused `NameError` at runtime).
- Replaced `fileId` undefined variable references with `file_id` in exception handlers.
- Replaced undefined `logger` with a proper `logging.getLogger(__name__)` instance.

**Improvements:**
- `MIME_TO_EXT` and `SUPPORTED_EXTENSIONS` constants moved to `app/constants.py`.
- `DEFAULT_FILE_LABEL = "Confidential"` moved to `app/constants.py`.
- Unused `verify_auth` definition kept but made no-op.
- Unused imports removed (`Path as FPath`, `FPath`, `FileResponse`, `Query`, `Depends`).
- `expires_in` now reads from `settings.file_url_expiry_seconds` instead of hardcoded `3600`.
- Cleanup of temporary files on upload error.
- Added `logging` throughout.

### `app/routers/chat.py`
- Removed `ChatCompletionResponse` import (never used in routing).
- Removed `ContentItem` import (never used in routing).
- Added `logging`.
- Added module-level docstring.

### `app/main.py`
- Added `logging.basicConfig()` call — log level controlled by `settings.debug`.
- Added module-level docstring.
- Added description to `FastAPI(...)` constructor.

### `pyproject.toml`
- Added missing dependencies to align with `requirements.txt`:
  `openai`, `python-dotenv`, `boto3`, `reportlab`, `svglib`.

### `Dockerfile`
- Added `COPY prompts ./prompts` after `COPY app ./app` so the `prompts/`
  directory is available inside the container.

### `README.md`
- Corrected route from `POST /upload` → `POST /files`.
- Corrected model name references.
- Added SSE event schema table.
- Added Prompt Management section.
- Added Docker instructions.
- Documented all environment variables including new ones.
- Removed description of rule-based SQL/chart path (legacy — not the active flow).

---

## Phase 2 — Intent-Based Conditional Visualization & PDF

This phase introduced on-demand chart and PDF generation controlled by intent
flags derived from the user's natural language query.

### Motivation

Previously, the pipeline **always** generated Mermaid charts in the BI report
and **always** built a PDF after every streaming response — regardless of whether
the user asked for either.  This caused:

- Unnecessary LLM token usage for chart syntax the user did not want.
- Unnecessary `mmdc` / ReportLab / S3 work on every request.
- Slower responses for simple analytical questions.

### Changes

#### `app/constants.py`
- Added `PDF_KEYWORDS: tuple[str, ...]` — terms like `"download"`, `"pdf"`,
  `"save"`, `"export"`, `"generate report"` that signal the user wants a
  downloadable file.
- Extended `CHART_KEYWORDS` with `"visualise"`, `"show me a chart"`,
  `"show me a graph"` for broader visualization detection.

#### `app/services/llm_service.py`

| Location | Before | After |
|----------|--------|-------|
| `_parse_user_request` | Returns `(query, needs_chart: bool)` | Returns `(query, needs_visualization: bool, needs_pdf: bool)` |
| `generate_streaming` | `query, _ = _parse_user_request(...)` | `query, needs_visualization, needs_pdf = _parse_user_request(...)` |
| `_run_streaming_pipeline` | No visualization/pdf params; PDF always generated | Accepts `needs_visualization`, `needs_pdf`; injects `generate_visualization` into Stage 2 payload; PDF gated by `needs_pdf` |
| `_execute_analysis_plan` | Returns plain `final_output` dict | Caller injects `"generate_visualization": bool` into `final_output` before Stage 2 call |
| `generate_response` | `query, _ = _parse_user_request(...)` | `query, needs_visualization, _needs_pdf = _parse_user_request(...)` |
| `_run_simple_pipeline` | No visualization param | Accepts `needs_visualization`; passes it into Stage 2 user message |

**New log line (DEBUG):**
```
Intent flags — needs_visualization=True  needs_pdf=False  query='show me a bar chart of...'
```

**New log line (INFO) when PDF is triggered:**
```
PDF generation requested — building report for completion <id>.
```

**New log line (DEBUG) when PDF is skipped:**
```
PDF generation skipped — not requested by user.
```

#### `prompts/agents/bi_report_writer.md`
- Added `# VISUALIZATION CONTROL` section at the top of the prompt (highest
  priority, read before all other rules):
  - `generate_visualization: false` → produce **text-only analysis**; zero
    Mermaid blocks; no mention of charts.
  - `generate_visualization: true` → follow existing chart generation rules.
- Updated `# SECTION OUTPUT FORMAT` to explicitly state when the Mermaid block
  should and should not appear.

#### `mermaid.md`
- Replaced the placeholder test diagram with full documentation of the Mermaid
  chart system: supported chart types, the conditional rendering pipeline, null
  handling rules, CLI configuration, and extension guide.

#### `ARCHITECTURE.md`
- Added `# Intent Detection System` section with flag derivation diagram and
  effect table.
- Updated `# Streaming Pipeline Detail` to show `needs_visualization` and
  `needs_pdf` parameters through the call stack.
- Updated `LLMService` component description.
- Updated `PDF Service` description to note on-demand invocation.
- Added `PDF_KEYWORDS` to the Constants table.
- Added `# Adding a New Intent Flag` extension guide.
- Added intent-detection scalability note to the Scalability table.
- Updated Observability table with new DEBUG/INFO log entries.

### Behaviour Matrix

| User asks… | `needs_visualization` | `needs_pdf` | LLM output | Post-stream work |
|---|---|---|---|---|
| Plain data question | `false` | `false` | Text-only analysis | Nothing |
| Chart request | `true` | `false` | Analysis + Mermaid charts | Nothing |
| Download request | `false` | `true` | Text-only analysis | PDF built & uploaded |
| Chart + download | `true` | `true` | Analysis + Mermaid charts | PDF built & uploaded |

### Backward Compatibility

- All existing API contracts are unchanged.
- Clients that previously relied on always receiving a PDF file SSE event will
  no longer receive one unless the user's query contains a download/save keyword.
  Update client prompts or UI copy accordingly.

---

## Functionality Preservation Checklist

| Feature | Status | Notes |
|---------|--------|-------|
| `POST /files` — upload CSV/XLS/XLSX | ✅ Preserved | |
| `GET /files/{id}/url` — presigned S3 URL | ✅ Preserved | |
| `DELETE /files` — bulk S3 delete | ✅ Preserved | |
| `GET /metadata` — models + file types | ✅ Preserved | |
| `POST /chat/completions` — SSE streaming pipeline | ✅ Preserved | |
| `POST /chat/completions/{id}/stop` | ✅ Preserved | |
| `GET /health` + `GET /` | ✅ Preserved | |
| Two-stage LLM analysis (plan → SQL → BI report) | ✅ Preserved | |
| Mermaid chart rendering → PNG via `mmdc` | ✅ Conditional | Only when `needs_visualization = True` |
| ReportLab PDF generation | ✅ Conditional | Only when `needs_pdf = True` |
| PDF upload to S3 + presigned file SSE event | ✅ Conditional | Only when `needs_pdf = True` |
| Date column auto-detection in data loader | ✅ Preserved | |
| Non-streaming `generate_response()` path | ✅ Preserved | |
| `QueryEngine` SQL builders (available for future use) | ✅ Preserved | |
| `ChartGenerator` Mermaid builders (available) | ✅ Preserved | |
| `sql_generator` NL-to-SQL heuristics (available) | ✅ Preserved | |

---

## Known Pre-Existing Issues (Not in Scope)

The following issues existed before this refactoring and were **not** introduced
by it.  They are documented here for visibility:

1. **Single-user dataset:** `data_loader` holds one dataset globally.  Concurrent
   users overwrite each other's data.  Requires per-session isolation.
2. **Blocking event loop:** `time.sleep(1)` in the PDF progress loop blocks the
   asyncio event loop.  Replace with `asyncio.sleep(1)` in a future release.
3. **No authentication enforcement:** `verify_auth` is defined but never applied
   as a route dependency.
4. **Temp file accumulation:** PDF temp files in `/tmp/` are cleaned up; upstream
   uploaded files in `/tmp/{file_id}/` are not removed after S3 upload.
5. **No test suite:** `pyproject.toml` configures pytest but no tests exist.
