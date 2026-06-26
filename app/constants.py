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

# ---------------------------------------------------------------------------
# LLM / analysis pipeline
# ---------------------------------------------------------------------------

# Fallback message when no dataset has been loaded
NO_DATA_MESSAGE: str = (
    "I cannot find sufficient information in the uploaded document "
    "to answer this question."
)

# Keywords that signal the user wants a chart/visualisation
CHART_KEYWORDS: tuple[str, ...] = (
    "chart",
    "graph",
    "visualization",
    "dashboard",
    "trend line",
    "pie chart",
    "bar chart",
    "line chart",
    "flow diagram",
    "plot",
    "visualize",
    "visualise",
    "show me a chart",
    "show me a graph",
)

# Keywords that signal the user wants a downloadable PDF report
PDF_KEYWORDS: tuple[str, ...] = (
    "download",
    "pdf",
    "save",
    "export",
    "downloadable",
    "generate report",
    "save report",
    "download report",
    "export report",
    "generate pdf",
    "save as pdf",
    "create report",
)

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

# Fraction of non-null values that must parse as dates for auto-conversion
DATE_DETECTION_THRESHOLD: float = 0.8
