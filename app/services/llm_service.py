"""
LLM interaction service.

Orchestrates the two-stage analysis pipeline:

Stage 1 — Analysis Planner
  Sends the dataset schema and user question to the LLM and receives a
  structured JSON analysis plan containing multiple DuckDB SQL queries.

Stage 2 — BI Report Writer
  Executes the SQL queries against DuckDB, then sends the results to the LLM
  which streams back a Markdown BI report.  Whether Mermaid charts and a
  downloadable PDF are generated depends on intent flags detected from the
  user's message:

  - ``needs_visualization`` (True when the query contains chart/graph keywords)
    → ``generate_visualization: true/false`` is forwarded to the Stage 2 LLM.
    When False the LLM produces a text-only analysis with no Mermaid blocks.

  - ``needs_pdf`` (True when the query contains download/pdf/save keywords)
    → PDF is generated and uploaded to S3 only when this flag is True.

A non-streaming variant (``generate_response``) follows the same two-stage
pattern but returns a single JSON payload instead of an SSE stream.

All system-prompt text is loaded from the ``prompts/`` directory via
``app.utils.prompt_loader`` so prompts can be iterated upon without modifying
application code.
"""

import json
import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import AsyncGenerator

from openai import OpenAI

from app.config import settings
from app.constants import (
    ACTIVITY_ANALYZING,
    ACTIVITY_GENERATING,
    ACTIVITY_PLANNING,
    ACTIVITY_QUERYING,
    CHART_KEYWORDS,
    GENERIC_ERROR_MESSAGE,
    NO_DATA_MESSAGE,
    PDF_ACTIVITY_START_MESSAGE,
    PDF_KEYWORDS,
    PDF_PROGRESS_MESSAGES,
)
from app.services.data_loader import data_loader
from app.services.pdf_service import create_pdf_report
from app.utils.prompt_loader import prompt_loader

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema context builder
# ---------------------------------------------------------------------------


def _build_schema_context_message(tables: list[dict], query: str) -> str:
    """Render a multi-table schema description for the Stage 1 planner prompt.

    Each entry in *tables* is a metadata dict produced by DataLoader with keys:
    table_name, sheet_name, file_name, columns, dtypes, row_count.
    """
    lines: list[str] = ["You have access to the following tables in DuckDB:\n"]
    for idx, t in enumerate(tables, start=1):
        lines.append(
            f"Table {idx}: {t['table_name']}"
            f" (Sheet: \"{t['sheet_name']}\", File: \"{t['file_name']}\")"
        )
        lines.append(f"  Columns : {', '.join(t['columns'])}")
        dtype_str = ", ".join(f"{c}→{d}" for c, d in t["dtypes"].items())
        lines.append(f"  Types   : {dtype_str}")
        lines.append(f"  Rows    : {t['row_count']}\n")
    lines.append(f"User Question: {query}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# OpenAI client factory
# ---------------------------------------------------------------------------


def _get_openai_client() -> OpenAI:
    return OpenAI(
        base_url=settings.chat_api_url,
        api_key=settings.datarobot_api_token,
        _strict_response_validation=False,
    )


# ---------------------------------------------------------------------------
# Stream-chunk utility
# ---------------------------------------------------------------------------


def _partial_marker_suffix(text: str, marker: str) -> str:
    """Return the longest suffix of *text* that is a prefix of *marker*.

    Used to detect markers (e.g. ``\\`\\`\\`suggestions``) split across two
    consecutive stream chunks so that the partial bytes can be held back and
    re-examined with the next chunk.
    """
    for length in range(min(len(marker) - 1, len(text)), 0, -1):
        if text.endswith(marker[:length]):
            return text[-length:]
    return ""


# ---------------------------------------------------------------------------
# LLMService
# ---------------------------------------------------------------------------


class LLMService:
    """Manages active completions and drives the LLM analysis pipeline."""

    def __init__(self) -> None:
        self._active_completions: dict[str, dict] = {}
        # Load prompts eagerly at startup so any missing file raises immediately.
        self._prompts: dict[str, str] = {
            "analysis_planner": prompt_loader.load("agents/analysis_planner.md"),
            "bi_report_writer": prompt_loader.load("agents/bi_report_writer.md"),
            "simple_analyst_planner": prompt_loader.load("agents/simple_analyst_planner.md"),
            "simple_bi_writer": prompt_loader.load("agents/simple_bi_writer.md"),
            "system": prompt_loader.load("system/data_analyst.md"),
        }
        logger.info("LLMService initialised — %d prompts loaded.", len(self._prompts))

    # ------------------------------------------------------------------
    # Completion lifecycle
    # ------------------------------------------------------------------

    def register_completion(self, completion_id: str) -> None:
        self._active_completions[completion_id] = {"status": "active"}
        logger.debug("Registered completion: %s", completion_id)

    def stop_completion(self, completion_id: str) -> dict:
        entry = self._active_completions.get(completion_id)
        if not entry:
            return {"found": False, "status": None, "message": "Completion not found"}
        entry["status"] = "stopped"
        logger.debug("Completion %s marked as stopped.", completion_id)
        return {
            "found": True,
            "status": "stopped",
            "message": "Chat completion successfully stopped",
        }

    def is_stopped(self, completion_id: str) -> bool:
        entry = self._active_completions.get(completion_id)
        return entry is not None and entry["status"] == "stopped"

    # ------------------------------------------------------------------
    # Non-streaming pipeline
    # ------------------------------------------------------------------

    async def generate_response(
        self,
        messages: list[dict],
        completion_id: str | None = None,
        file_ids: list[str] | None = None,
    ) -> dict:
        """Two-stage non-streaming analysis pipeline."""
        query, needs_visualization, _needs_pdf = self._parse_user_request(messages)
        data_context = self._build_data_context(file_ids)

        if not data_context.get("has_data"):
            final_response = NO_DATA_MESSAGE
        else:
            final_response = self._run_simple_pipeline(query, data_context, needs_visualization)

        if completion_id and self.is_stopped(completion_id):
            final_response = "[Response stopped by user]"

        return {
            "completionId": completion_id or uuid.uuid4().hex,
            "contents": [
                {
                    "contentType": "activityText",
                    "content": "Analyzing the data and generating response...",
                },
                {"contentType": "text", "content": final_response},
            ],
            "inputTokens": 0,
            "outputTokens": 0,
        }

    def _run_simple_pipeline(self, query: str, data_context: dict, needs_visualization: bool = False) -> str:
        """Execute the two-LLM-call non-streaming analysis and return text."""
        schema_user_msg = _build_schema_context_message(data_context["tables"], query)

        stage1_messages = [
            {"role": "system", "content": self._prompts["simple_analyst_planner"]},
            {"role": "user", "content": schema_user_msg},
        ]

        try:
            client = _get_openai_client()
            completion = client.chat.completions.create(
                model=settings.llm_model,
                messages=stage1_messages,
            )
            stage1_response = json.loads(completion.choices[0].message.content or "{}")
        except Exception as exc:
            logger.error("Stage 1 (simple) LLM call failed: %s", exc)
            return GENERIC_ERROR_MESSAGE

        sql_query = stage1_response.get("sql")
        query_results = None
        if sql_query:
            try:
                query_results = data_loader.execute_query(sql_query)
            except Exception as exc:
                logger.warning("SQL execution error: %s", exc)
                # Keep error detail in server logs only — send empty results to Stage 2
                query_results = []

        # Stage 1 may independently decide a chart is needed.
        stage1_wants_chart = bool(stage1_response.get("generate_chart"))
        effective_visualization = needs_visualization or stage1_wants_chart

        stage2_user_msg = (
            f"user_query :{query},\n"
            f"generate_visualization: {str(effective_visualization).lower()},\n"
            f"query_results: {query_results},\n"
            f"chart_config: \n"
            f"generate_chart: {stage1_response.get('generate_chart')},\n"
            f"chart_type: {stage1_response.get('chart_type')},\n"
            f"x_axis: {stage1_response.get('x_axis')},\n"
            f"y_axis: {stage1_response.get('y_axis')},\n"
            f"analysis_intent: {stage1_response.get('analysis_intent')}."
        )

        stage2_messages = [
            {"role": "system", "content": self._prompts["simple_bi_writer"]},
            {"role": "user", "content": stage2_user_msg},
        ]

        try:
            client = _get_openai_client()
            completion = client.chat.completions.create(
                model=settings.llm_model,
                messages=stage2_messages,
            )
            stage2_response = json.loads(completion.choices[0].message.content or "{}")
            return (
                f"{stage2_response.get('summary', '')}\n\n"
                f"{stage2_response.get('mermaid', '')}"
            )
        except Exception as exc:
            logger.error("Stage 2 (simple) LLM call failed: %s", exc)
            return GENERIC_ERROR_MESSAGE

    # ------------------------------------------------------------------
    # Streaming pipeline
    # ------------------------------------------------------------------

    async def generate_streaming(
        self,
        messages: list[dict],
        completion_id: str,
        file_ids: list[str] | None = None,
    ) -> AsyncGenerator[str, None]:
        """Two-stage streaming analysis pipeline that emits SSE events."""
        query, needs_visualization, needs_pdf = self._parse_user_request(messages)
        data_context = self._build_data_context(file_ids)

        try:
            yield _sse({"event": "start", "completionId": completion_id})

            if not data_context.get("has_data"):
                yield _sse({"event": "delta", "contentType": "textChunk", "content": NO_DATA_MESSAGE})
                yield _sse({"event": "end", "reason": "complete", "inputTokens": 0, "outputTokens": 0})
                return

            async for chunk in self._run_streaming_pipeline(
                query, data_context, completion_id, needs_visualization, needs_pdf,
            ):
                yield chunk

        except Exception as exc:
            logger.exception("Unexpected error in generate_streaming: %s", exc)
            yield _sse({"event": "delta", "contentType": "textChunk", "content": GENERIC_ERROR_MESSAGE})
            yield _sse({"event": "end", "reason": "error", "inputTokens": 0, "outputTokens": 0})

    async def _run_streaming_pipeline(
        self,
        query: str,
        data_context: dict,
        completion_id: str,
        needs_visualization: bool = False,
        needs_pdf: bool = False,
    ) -> AsyncGenerator[str, None]:
        """Stage 1: build analysis plan → Stage 2: stream BI report → optionally generate PDF.

        Mermaid charts are included only when *needs_visualization* is True.
        A PDF is generated and uploaded to S3 only when *needs_pdf* is True.
        """
        schema_user_msg = _build_schema_context_message(data_context["tables"], query)

        stage1_messages = [
            {"role": "system", "content": self._prompts["analysis_planner"]},
            {"role": "user", "content": schema_user_msg},
        ]

        # --- Stage 1: get analysis plan ---
        yield _activity(ACTIVITY_ANALYZING)
        try:
            client = _get_openai_client()
            completion = client.chat.completions.create(
                model=settings.llm_model,
                messages=stage1_messages,
            )
            stage1_response = json.loads(completion.choices[0].message.content or "{}")
        except Exception as exc:
            logger.error("Stage 1 (streaming) LLM call failed: %s", exc)
            yield _sse({"event": "delta", "contentType": "textChunk", "content": GENERIC_ERROR_MESSAGE})
            yield _sse({"event": "end", "reason": "error", "inputTokens": 0, "outputTokens": 0})
            return

        # --- Execute SQL queries from the plan ---
        query_count = len(stage1_response.get("analysis_plan", []))
        planning_msg = (
            f"{ACTIVITY_PLANNING} ({query_count} quer{'y' if query_count == 1 else 'ies'})"
            if query_count else ACTIVITY_PLANNING
        )
        yield _activity(planning_msg)
        yield _activity(ACTIVITY_QUERYING)
        try:
            final_output = self._execute_analysis_plan(query, data_context, stage1_response)
            # Enable visualization if the user's message triggered keywords OR if
            # Stage 1 determined that any query result warrants a chart.
            stage1_wants_chart = any(
                item.get("generate_chart")
                for item in stage1_response.get("analysis_plan", [])
            )
            final_output["generate_visualization"] = needs_visualization or stage1_wants_chart
        except Exception as exc:
            logger.error("Analysis plan execution failed: %s", exc)
            yield _sse({"event": "delta", "contentType": "textChunk", "content": GENERIC_ERROR_MESSAGE})
            yield _sse({"event": "end", "reason": "error", "inputTokens": 0, "outputTokens": 0})
            return

        # --- Stage 2: stream BI report ---
        yield _activity(ACTIVITY_GENERATING)
        stage2_messages = [
            {"role": "system", "content": self._prompts["bi_report_writer"]},
            {"role": "user", "content": json.dumps(final_output, indent=2)},
        ]

        try:
            client = _get_openai_client()
            stream = client.chat.completions.create(
                model=settings.llm_model,
                messages=stage2_messages,
                stream=True,
            )

            accumulated_content = ""

            for chunk in stream:
                if self.is_stopped(completion_id):
                    yield _sse({"event": "end", "reason": "stopped", "inputTokens": 0, "outputTokens": 0})
                    return

                delta_content = (
                    chunk.choices[0].delta.content
                    if chunk.choices and chunk.choices[0].delta.content
                    else None
                )
                if delta_content:
                    accumulated_content += delta_content
                    yield _sse({"event": "delta", "contentType": "textChunk", "content": delta_content})

        except Exception as exc:
            logger.error("Stage 2 (streaming) LLM call failed: %s", exc)
            yield _sse({"event": "delta", "contentType": "textChunk", "content": GENERIC_ERROR_MESSAGE})
            yield _sse({"event": "end", "reason": "error", "inputTokens": 0, "outputTokens": 0})
            return

        # --- Generate PDF after streaming completes (only when explicitly requested) ---
        file_info = None
        if needs_pdf and accumulated_content:
            logger.info("PDF generation requested — building report for completion %s.", completion_id)
            yield _activity(PDF_ACTIVITY_START_MESSAGE)
            try:
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(create_pdf_report, accumulated_content)
                    idx = 0
                    while not future.done():
                        if self.is_stopped(completion_id):
                            return
                        msg = PDF_PROGRESS_MESSAGES[min(idx, len(PDF_PROGRESS_MESSAGES) - 1)]
                        yield _activity(msg)
                        idx += 1
                        time.sleep(1)
                    file_info = future.result()
            except Exception as exc:
                logger.error("PDF generation failed: %s", exc)
        elif not needs_pdf:
            logger.debug("PDF generation skipped — not requested by user.")

        if file_info:
            yield _sse({"event": "delta", "contentType": "file", "content": json.dumps(file_info)})

        yield _sse({"event": "end", "reason": "complete", "inputTokens": 0, "outputTokens": 0})

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _execute_analysis_plan(
        self,
        query: str,
        data_context: dict,
        stage1_response: dict,
    ) -> dict:
        """Execute each SQL query in the analysis plan and collect results."""
        available_tables = [
            {
                "table_name": t["table_name"],
                "sheet_name": t["sheet_name"],
                "columns": t["columns"],
            }
            for t in data_context.get("tables", [])
        ]
        final_output: dict = {
            "user_question": query,
            "dataset_context": {
                "available_tables": available_tables,
            },
            "analysis_results": [],
        }

        for item in stage1_response.get("analysis_plan", []):
            sql_query = item.get("sql")
            query_result: list = []
            error: str | None = None

            if sql_query:
                try:
                    query_result = data_loader.execute_query(sql_query)
                    for row in query_result:
                        for key, value in row.items():
                            if hasattr(value, "isoformat"):
                                row[key] = value.isoformat()
                except Exception as exc:
                    logger.warning("SQL query failed for '%s': %s", item.get("title"), exc)
                    error = str(exc)

            final_output["analysis_results"].append({
                "title": item.get("title"),
                "analysis_intent": item.get("analysis_intent"),
                "chart_metadata": {
                    "chart_type": item.get("chart_type"),
                    "x_axis": item.get("x_axis"),
                    "y_axis": item.get("y_axis"),
                },
                "sql": sql_query,
                # On SQL error, send empty results — the error detail stays in
                # server logs only and is never exposed to the user.
                "query_result": query_result if not error else [],
            })

        return final_output

    def _parse_user_request(self, messages: list[dict]) -> tuple[str, bool, bool]:
        """Extract the latest user query text and detect visualization / PDF intent.

        Returns:
            (query, needs_visualization, needs_pdf)

            needs_visualization — True when the query contains chart/graph keywords or
                                  the message includes a file content item.
            needs_pdf           — True when the query contains download/save/pdf keywords.
        """
        last_user_msg = next(
            (m for m in reversed(messages) if m.get("role") == "user"), None
        )
        query = ""
        needs_visualization = False
        needs_pdf = False

        if last_user_msg:
            for content in last_user_msg.get("contents", []):
                if content.get("contentType") == "text":
                    query = content.get("content", "")
                if content.get("contentType") == "file":
                    needs_visualization = True

        query_lower = query.lower()
        if any(kw in query_lower for kw in CHART_KEYWORDS):
            needs_visualization = True
        if any(kw in query_lower for kw in PDF_KEYWORDS):
            needs_pdf = True

        logger.debug(
            "Intent flags — needs_visualization=%s  needs_pdf=%s  query=%r",
            needs_visualization,
            needs_pdf,
            query[:120],
        )
        return query, needs_visualization, needs_pdf

    def _build_data_context(self, file_ids: list[str] | None = None) -> dict:
        """Return schema metadata for all tables associated with *file_ids*.

        Falls back to all registered tables when *file_ids* is empty / None.
        Returns ``{"has_data": False}`` when no tables are found.
        """
        if file_ids:
            tables = data_loader.get_tables_for_files(file_ids)
        else:
            # Fall back to all loaded files so non-file-aware callers still work.
            all_ids = data_loader.list_file_ids()
            tables = data_loader.get_tables_for_files(all_ids)

        if not tables:
            return {"has_data": False}

        return {
            "has_data": True,
            "tables": tables,
            # Backward-compat keys pointing at the first table.
            "table_name": tables[0]["table_name"],
            "columns": tables[0]["columns"],
            "dtypes": tables[0]["dtypes"],
        }

    def _build_openai_messages(
        self,
        messages: list[dict],
        data_context: dict,
        query_results: list[dict] | None = None,
    ) -> list[dict]:
        """Legacy helper: build an OpenAI message list from conversation history.

        Not used by the active streaming pipeline but retained for compatibility
        with callers that use the non-streaming ``generate_response`` path.
        """
        openai_messages = [{"role": "system", "content": self._prompts["system"]}]

        if data_context.get("has_data"):
            if query_results:
                rows = [
                    " | ".join(f"{k}: {v}" for k, v in row.items())
                    for row in query_results[:50]
                ]
                results_str = "\n".join(rows)
                if len(query_results) > 50:
                    results_str += f"\n... and {len(query_results) - 50} more rows"
            else:
                results_str = "No results."

            context_block = (
                f"Table: {data_context.get('table_name')}\n"
                f"Columns: {', '.join(data_context.get('columns', []))}\n"
                f"Query results:\n{results_str}"
            )
            openai_messages.append({"role": "system", "content": context_block})

        for msg in messages:
            role = msg.get("role", "user")
            texts = [
                str(c.get("content", ""))
                for c in msg.get("contents", [])
                if c.get("contentType") == "text"
            ]
            if texts:
                openai_messages.append({"role": role, "content": " ".join(texts)})

        return openai_messages


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _sse(payload: dict) -> str:
    """Format a dict as a Server-Sent Events ``data:`` line."""
    return f"data: {json.dumps(payload)}\n\n"


def _activity(message: str) -> str:
    """Shorthand for an ``activityDelta`` SSE event shown in the frontend thinking indicator."""
    print('in Activity')
    return _sse({"event": "activityDelta", "contentType": "activityChunk", "content": message})


# Module-level singleton
llm_service = LLMService()
