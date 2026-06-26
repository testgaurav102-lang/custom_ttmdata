"""
Pydantic schemas for the documentation browser endpoints.
"""

from pydantic import BaseModel


class DocFileInfo(BaseModel):
    """Metadata for a single Markdown file."""

    name: str
    """Filename only, e.g. ``README.md``."""

    path: str
    """Path relative to the project root, e.g. ``prompts/agents/bi_report_writer.md``."""

    category: str
    """Logical grouping label, e.g. ``Project Docs`` or ``Prompts · Agents``."""

    size_in_bytes: int
    """File size in bytes."""

    view_url: str
    """Browser-friendly URL to open this file rendered as HTML, e.g. ``/docs/view/README.md``."""


class DocFileListing(BaseModel):
    """Response model for ``GET /docs/list``."""

    files: list[DocFileInfo]
    total: int
