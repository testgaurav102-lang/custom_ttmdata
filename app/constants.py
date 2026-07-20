"""
Application-wide constants.

All hardcoded strings, lookup maps, and fixed enumerations live here so that
they are easy to find, audit, and change without touching business logic.
"""

# ---------------------------------------------------------------------------
# File upload
# ---------------------------------------------------------------------------

SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({"csv", "xls", "xlsx"})

MIME_TO_EXT: dict[str, str] = {
    "text/csv": "csv",
    "application/csv": "csv",
    "application/vnd.ms-excel": "xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
}

# Default label applied to uploaded files
DEFAULT_FILE_LABEL: str = "Confidential"

# ---------------------------------------------------------------------------
# PDF report
# ---------------------------------------------------------------------------

PDF_REPORT_FILENAME: str = "Analysis Report.pdf"

# Activity messages streamed while PDF is being built
PDF_PROGRESS_MESSAGES: list[str] = [
    "Formatting report...",
    "Rendering charts and tables...",
    "Preparing PDF document...",
    "Uploading report...",
]

PDF_ACTIVITY_START_MESSAGE: str = "Generating analysis report..."

# Activity messages streamed at each stage of the LLM analysis pipeline
ACTIVITY_ANALYZING: str = "\n Analyzing your question..."
ACTIVITY_PLANNING: str = "\n Planning data queries..."
ACTIVITY_QUERYING: str = "\n Querying the data..."
ACTIVITY_GENERATING: str = "\n Generating insights..."

# ---------------------------------------------------------------------------
# LLM / analysis pipeline
# ---------------------------------------------------------------------------

# Fallback message when no dataset has been loaded
NO_DATA_MESSAGE: str = (
    "I cannot find sufficient information in the uploaded document "
    "to answer this question."
)

# Generic message shown to the user when any internal error occurs
GENERIC_ERROR_MESSAGE: str = (
    "Something went wrong while processing your request. Please try again."
)

# Keywords that signal the user wants a chart/visualisation
CHART_KEYWORDS: tuple[str, ...] = (
    # Explicit chart requests
    "chart",
    "graph",
    "plot",
    "visual",
    "show",
    "show me",
    "visualization",
    "visualisation",
    "visualize",
    "visualise",
    "dashboard",
    "pie chart",
    "bar chart",
    "line chart",
    "trend line",
    "flow diagram",
    "show me a chart",
    "show me a graph",
    # Trend / time-series intent
    "trend",
    "over time",
    "over the year",
    "over the month",
    "over the quarter",
    "over the week",
    "monthly",
    "weekly",
    "daily",
    "quarterly",
    "annually",
    "yearly",
    "by month",
    "by year",
    "by quarter",
    "by week",
    "by day",
    "per month",
    "per year",
    "per quarter",
    # Comparison / ranking intent
    "compare",
    "comparison",
    "versus",
    " vs ",
    "ranking",
    "rank",
    "top 5",
    "top 10",
    "bottom 5",
    "bottom 10",
    "highest",
    "lowest",
    # Distribution / breakdown intent
    "distribution",
    "breakdown",
    "breakdown by",
    "split by",
    "proportion",
    "share",
)

# Keywords that signal the user wants a downloadable PDF report
PDF_KEYWORDS: tuple[str, ...] = (
    "download",
    "pdf",
    "save",
    "export",
    "downloadable",
    # bare "report" catches: "provide the report", "show me the report",
    # "give me a report", "share the report", "attach the report", etc.
    "report",
    "generate report",
    "save report",
    "download report",
    "export report",
    "generate pdf",
    "save as pdf",
    "create report",
    "provide report",
    "give me a report",
    "share the report",
    "attach report",
    "send report",
)

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

# Fraction of non-null values that must parse as dates for auto-conversion
DATE_DETECTION_THRESHOLD: float = 0.8
