"""
Documentation browser endpoints.

All Markdown (.md) files intended for the docs browser live under the
``docs/`` directory at the project root.  Drop a new ``.md`` file there and
it will appear automatically — no code changes required.

Three endpoints are exposed:

  GET /docs              — HTML index page listing every .md file, grouped by
                           category, with clickable links to the view page.

  GET /docs/list         — JSON listing of all .md files (for programmatic use).

  GET /docs/view/{path}  — HTML page that renders the requested .md file with
                           full syntax highlighting and a navigation sidebar.

Base-URL safety: every internal link is built from the incoming ``Request``
URL so the router works correctly behind any reverse proxy or sub-path mount
(e.g. ``/custom_applications/<id>/docs/...``).  No base URL is hardcoded.

Path-traversal protection: every requested file path is resolved and validated
to be within ``_DOCS_DIR`` before any content is read.
"""

import logging
from itertools import groupby
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from app.models.docs import DocFileInfo, DocFileListing

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/docs", tags=["Docs"])

# ---------------------------------------------------------------------------
# Docs directory — the single folder scanned for .md files.
# Place any Markdown file here to make it appear in the browser.
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DOCS_DIR = _PROJECT_ROOT / "docs"


# ---------------------------------------------------------------------------
# Base-URL helper  (the only place that touches the request URL)
# ---------------------------------------------------------------------------

def _docs_base(request: Request) -> str:
    """Return the /docs prefix as it actually appears in the current request URL.

    Works regardless of what sub-path the application is mounted under.

    Examples
    --------
    Request path                                    → returned value
    /docs                                           → /docs
    /docs/view/README.md                            → /docs
    /custom_applications/abc123/docs                → /custom_applications/abc123/docs
    /custom_applications/abc123/docs/view/README.md → /custom_applications/abc123/docs
    """
    path = str(request.url.path)
    marker = "/docs"
    idx = path.find(marker)
    if idx == -1:
        return "/docs"
    return path[: idx + len(marker)]


# ---------------------------------------------------------------------------
# Category helper
# ---------------------------------------------------------------------------

def _category(rel_path: str) -> str:
    """Return a human-readable category label for a path relative to ``docs/``.

    Files directly inside ``docs/`` get the label ``"Documentation"``.
    Files inside a sub-directory (e.g. ``docs/guides/foo.md``) are grouped
    under the capitalised sub-directory name.
    """
    parts = Path(rel_path).parts
    if len(parts) == 1:
        return "Documentation"
    return " · ".join(p.capitalize() for p in parts[:-1])


# ---------------------------------------------------------------------------
# File scanner
# ---------------------------------------------------------------------------

def _scan_markdown_files(docs_base: str) -> list[DocFileInfo]:
    """Recursively collect every .md file under ``_DOCS_DIR``.

    Only ``_DOCS_DIR`` (``docs/``) is scanned — the rest of the project tree
    is never touched.  Drop a new ``.md`` file into ``docs/`` (or a
    sub-directory of it) and it will appear automatically.

    ``docs_base`` is the resolved URL prefix for this request (e.g.
    ``/custom_applications/abc/docs``).  It is used to build ``view_url``
    so links work on any host or sub-path mount.
    """
    if not _DOCS_DIR.exists():
        logger.warning("Docs directory not found: %s", _DOCS_DIR)
        return []

    files: list[DocFileInfo] = []
    for md_file in sorted(_DOCS_DIR.rglob("*.md")):
        rel_path = md_file.relative_to(_DOCS_DIR).as_posix()
        try:
            size = md_file.stat().st_size
        except OSError:
            continue
        files.append(
            DocFileInfo(
                name=md_file.name,
                path=rel_path,
                category=_category(rel_path),
                size_in_bytes=size,
                view_url=f"{docs_base}/view/{rel_path}",
            )
        )
    files.sort(key=lambda f: (f.category, f.name.lower()))
    return files


# ---------------------------------------------------------------------------
# Shared HTML chrome
# ---------------------------------------------------------------------------

_HTML_STYLES = """
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
                 "Helvetica Neue", Arial, sans-serif;
    background: #0f1117;
    color: #e2e8f0;
    min-height: 100vh;
  }

  /* ---- top bar ---- */
  .topbar {
    position: sticky; top: 0; z-index: 100;
    display: flex; align-items: center; gap: 14px;
    padding: 12px 28px;
    background: #1a1d27;
    border-bottom: 1px solid #2d3147;
    box-shadow: 0 2px 8px rgba(0,0,0,.4);
  }
  .topbar .brand { font-size: 1.05rem; font-weight: 700; color: #7c8cff; letter-spacing: .3px; }
  .topbar .breadcrumb { font-size: .82rem; color: #64748b; }
  .topbar .breadcrumb a { color: #7c8cff; text-decoration: none; }
  .topbar .breadcrumb a:hover { text-decoration: underline; }

  /* ---- two-column layout ---- */
  .layout { display: flex; height: calc(100vh - 53px); }

  /* ---- sidebar ---- */
  .sidebar {
    width: 270px; min-width: 220px;
    background: #141720;
    border-right: 1px solid #2d3147;
    overflow-y: auto;
    padding: 16px 0 24px;
    flex-shrink: 0;
  }
  .sidebar-title {
    font-size: .7rem; font-weight: 700; letter-spacing: 1.2px;
    text-transform: uppercase; color: #4a5568;
    padding: 0 18px 8px;
  }
  .sidebar-group { margin-bottom: 4px; }
  .sidebar-group-label {
    font-size: .72rem; font-weight: 700; letter-spacing: .8px;
    text-transform: uppercase; color: #475569;
    padding: 10px 18px 4px;
  }
  .sidebar-link {
    display: block; padding: 6px 18px;
    font-size: .82rem; color: #94a3b8;
    text-decoration: none; white-space: nowrap;
    overflow: hidden; text-overflow: ellipsis;
    border-left: 2px solid transparent;
    transition: background .15s, color .15s, border-color .15s;
  }
  .sidebar-link:hover { background: #1e2235; color: #c7d2fe; border-color: #7c8cff; }
  .sidebar-link.active { background: #1e2235; color: #a5b4fc; border-color: #7c8cff; font-weight: 600; }

  /* ---- main content ---- */
  .main { flex: 1; overflow-y: auto; padding: 36px 48px; }

  /* ---- index cards ---- */
  .index-section { margin-bottom: 40px; }
  .index-section h2 {
    font-size: .78rem; font-weight: 700; letter-spacing: 1.1px;
    text-transform: uppercase; color: #4a5568;
    margin-bottom: 12px; padding-bottom: 8px;
    border-bottom: 1px solid #2d3147;
  }
  .card-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
    gap: 12px;
  }
  .card {
    background: #1a1d27; border: 1px solid #2d3147;
    border-radius: 8px; padding: 16px 18px;
    text-decoration: none; color: inherit;
    transition: border-color .15s, box-shadow .15s;
  }
  .card:hover { border-color: #7c8cff; box-shadow: 0 0 0 1px #7c8cff33; }
  .card-name { font-size: .92rem; font-weight: 600; color: #a5b4fc; margin-bottom: 4px; }
  .card-path { font-size: .75rem; color: #4a5568; margin-bottom: 8px; font-family: monospace; }
  .card-size { font-size: .72rem; color: #374151; }

  /* ---- markdown body ---- */
  .md-body { max-width: 860px; line-height: 1.75; }
  .md-body h1 { font-size: 2rem; font-weight: 800; color: #e2e8f0; margin: 0 0 24px; }
  .md-body h2 { font-size: 1.35rem; font-weight: 700; color: #c7d2fe; margin: 40px 0 12px; padding-bottom: 6px; border-bottom: 1px solid #2d3147; }
  .md-body h3 { font-size: 1.1rem; font-weight: 600; color: #a5b4fc; margin: 28px 0 8px; }
  .md-body h4 { font-size: .97rem; font-weight: 600; color: #94a3b8; margin: 20px 0 6px; }
  .md-body p { margin: 0 0 14px; color: #cbd5e1; }
  .md-body a { color: #7c8cff; text-decoration: none; }
  .md-body a:hover { text-decoration: underline; }
  .md-body ul, .md-body ol { margin: 0 0 14px 22px; color: #cbd5e1; }
  .md-body li { margin-bottom: 4px; }
  .md-body strong { color: #e2e8f0; font-weight: 700; }
  .md-body em { color: #a5b4fc; }
  .md-body blockquote {
    border-left: 3px solid #7c8cff; margin: 16px 0;
    padding: 8px 18px; background: #1a1d27; border-radius: 0 6px 6px 0;
    color: #94a3b8;
  }
  .md-body code {
    font-family: "Fira Code", "Cascadia Code", Consolas, monospace;
    font-size: .85em; background: #1e2235; color: #a5f3fc;
    padding: 2px 6px; border-radius: 4px;
  }
  .md-body pre {
    background: #1a1d27; border: 1px solid #2d3147;
    border-radius: 8px; padding: 18px 20px; margin: 16px 0;
    overflow-x: auto;
  }
  .md-body pre code { background: none; padding: 0; font-size: .88rem; color: #e2e8f0; }
  .md-body table { width: 100%; border-collapse: collapse; margin: 16px 0; font-size: .88rem; }
  .md-body th {
    background: #1e2235; color: #a5b4fc; font-weight: 700;
    padding: 9px 14px; text-align: left; border-bottom: 2px solid #2d3147;
  }
  .md-body td { padding: 8px 14px; border-bottom: 1px solid #1e2235; color: #cbd5e1; vertical-align: top; }
  .md-body tr:hover td { background: #1a1d27; }
  .md-body hr { border: none; border-top: 1px solid #2d3147; margin: 28px 0; }

  /* ---- scrollbars ---- */
  ::-webkit-scrollbar { width: 6px; height: 6px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb { background: #2d3147; border-radius: 4px; }
  ::-webkit-scrollbar-thumb:hover { background: #475569; }
</style>
"""


def _sidebar_html(files: list[DocFileInfo], active_path: str = "") -> str:
    """Build the sidebar navigation grouped by category.

    ``file.view_url`` is already correct for the current request because
    ``_scan_markdown_files`` received the request-derived ``docs_base``.
    """
    html = '<nav class="sidebar">'
    for category, group in groupby(files, key=lambda f: f.category):
        html += (
            f'<div class="sidebar-group">'
            f'<div class="sidebar-group-label">{category}</div>'
        )
        for f in group:
            active_class = " active" if f.path == active_path else ""
            html += (
                f'<a class="sidebar-link{active_class}" '
                f'href="{f.view_url}" title="{f.path}">{f.name}</a>'
            )
        html += "</div>"
    html += "</nav>"
    return html


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_class=HTMLResponse, include_in_schema=False)
@router.get("/", response_class=HTMLResponse)
async def docs_index(request: Request):
    """HTML index page — lists every Markdown file grouped by category."""
    base = _docs_base(request)
    files = _scan_markdown_files(base)

    cards_html = ""
    for category, group in groupby(files, key=lambda f: f.category):
        cards_html += (
            f'<div class="index-section">'
            f'<h2>{category}</h2>'
            f'<div class="card-grid">'
        )
        for f in group:
            size_kb = f"{f.size_in_bytes / 1024:.1f} KB"
            cards_html += (
                f'<a class="card" href="{f.view_url}">'
                f'<div class="card-name">📄 {f.name}</div>'
                f'<div class="card-path">{f.path}</div>'
                f'<div class="card-size">{size_kb}</div>'
                f"</a>"
            )
        cards_html += "</div></div>"

    sidebar = _sidebar_html(files)

    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>Docs — Sales Intel Agent</title>
  {_HTML_STYLES}
</head>
<body>
  <header class="topbar">
    <span class="brand">Sales Intel Agent</span>
    <span class="breadcrumb">/ <a href="{base}">Docs</a></span>
    <span style="margin-left:auto;font-size:.78rem;color:#4a5568">{len(files)} files</span>
  </header>
  <div class="layout">
    {sidebar}
    <main class="main">
      {cards_html}
    </main>
  </div>
</body>
</html>
""")


@router.get("/list", response_model=DocFileListing)
async def list_docs(request: Request):
    """JSON listing of all Markdown files (for programmatic access)."""
    base = _docs_base(request)
    files = _scan_markdown_files(base)
    return DocFileListing(files=files, total=len(files))


@router.get("/view/{file_path:path}", response_class=HTMLResponse)
async def view_doc(file_path: str, request: Request):
    """Render a Markdown file as an HTML page.

    ``file_path`` is relative to the project root, e.g. ``README.md`` or
    ``prompts/agents/bi_report_writer.md``.
    """
    base = _docs_base(request)

    # Security: resolve and confirm the path stays within _DOCS_DIR
    requested = (_DOCS_DIR / file_path).resolve()
    try:
        requested.relative_to(_DOCS_DIR)
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied.")

    if requested.suffix.lower() != ".md":
        raise HTTPException(status_code=400, detail="Only .md files can be viewed.")

    if not requested.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {file_path}")

    raw_content = requested.read_text(encoding="utf-8")
    # Escape characters that would break a JS template literal
    escaped = (
        raw_content
        .replace("\\", "\\\\")
        .replace("`", "\\`")
        .replace("$", "\\$")
    )

    files = _scan_markdown_files(base)
    sidebar = _sidebar_html(files, active_path=Path(file_path).as_posix())

    # Breadcrumb: each path segment links to its own view URL
    parts = Path(file_path).parts
    crumb_parts = []
    for i, segment in enumerate(parts):
        partial = "/".join(parts[: i + 1])
        if i < len(parts) - 1:
            crumb_parts.append(
                f'<a href="{base}/view/{partial}">{segment}</a>'
            )
        else:
            crumb_parts.append(f'<span style="color:#e2e8f0">{segment}</span>')
    crumb_html = ' <span style="color:#4a5568">/</span> '.join(crumb_parts)

    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>{parts[-1]} — Sales Intel Agent Docs</title>
  {_HTML_STYLES}
</head>
<body>
  <header class="topbar">
    <span class="brand">Sales Intel Agent</span>
    <span class="breadcrumb">
      / <a href="{base}">Docs</a> / {crumb_html}
    </span>
  </header>
  <div class="layout">
    {sidebar}
    <main class="main">
      <div id="md-content" class="md-body"></div>
    </main>
  </div>

  <!-- marked.js for Markdown → HTML -->
  <script src="https://cdn.jsdelivr.net/npm/marked@12/marked.min.js"></script>
  <!-- highlight.js for code-block syntax highlighting -->
  <link rel="stylesheet"
        href="https://cdn.jsdelivr.net/npm/highlight.js@11/styles/github-dark.min.css"/>
  <script src="https://cdn.jsdelivr.net/npm/highlight.js@11/highlight.min.js"></script>

  <script>
    marked.setOptions({{
      highlight: function(code, lang) {{
        if (lang && hljs.getLanguage(lang)) {{
          return hljs.highlight(code, {{ language: lang }}).value;
        }}
        return hljs.highlightAuto(code).value;
      }},
      breaks: true,
      gfm: true,
    }});

    const raw = `{escaped}`;
    document.getElementById("md-content").innerHTML = marked.parse(raw);
    document.querySelectorAll("pre code").forEach(hljs.highlightElement);
  </script>
</body>
</html>
""")
