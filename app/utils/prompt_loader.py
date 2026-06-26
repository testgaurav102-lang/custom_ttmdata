"""
Prompt loading utility.

Prompts are stored as plain-text Markdown files under the top-level
``prompts/`` directory so that prompt engineers can iterate on them
independently of application code.

Directory layout::

    prompts/
    ├── system/          # Base system-level instructions
    ├── agents/          # Per-agent system prompts
    └── templates/       # User-message templates with {placeholder} vars

Usage::

    from app.utils.prompt_loader import prompt_loader

    system_prompt = prompt_loader.load("system/data_analyst.md")
    user_msg = prompt_loader.format(
        "templates/schema_context.md",
        table_name="sales_data",
        columns=["region", "revenue"],
        dtypes={"region": "object", "revenue": "float64"},
        query="What is total revenue by region?",
    )
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Resolve the ``prompts/`` directory relative to this file's location:
#   app/utils/prompt_loader.py  →  ../../prompts/
_PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / "prompts"


class PromptLoader:
    """Loads prompt files from disk and caches them in memory.

    All paths are relative to the ``prompts/`` directory at the project root.
    """

    def __init__(self, base_dir: Path | None = None) -> None:
        self._base_dir: Path = base_dir or _PROMPTS_DIR
        self._cache: dict[str, str] = {}

    def load(self, relative_path: str) -> str:
        """Return the prompt text for *relative_path*, using an in-memory cache.

        Args:
            relative_path: Path relative to ``prompts/``, e.g.
                ``"agents/analysis_planner.md"``.

        Returns:
            The raw prompt text.

        Raises:
            FileNotFoundError: When the prompt file does not exist.
        """
        if relative_path not in self._cache:
            full_path = self._base_dir / relative_path
            if not full_path.exists():
                raise FileNotFoundError(
                    f"Prompt file not found: {full_path}. "
                    f"Expected under prompts/{relative_path}"
                )
            self._cache[relative_path] = full_path.read_text(encoding="utf-8")
            logger.debug("Loaded prompt: %s", relative_path)
        return self._cache[relative_path]

    def format(self, relative_path: str, **kwargs) -> str:
        """Load a prompt template and substitute ``{placeholder}`` variables.

        Args:
            relative_path: Path relative to ``prompts/``.
            **kwargs: Variable names and their values for substitution.

        Returns:
            The prompt text with all placeholders replaced.
        """
        template = self.load(relative_path)
        return template.format(**kwargs)

    def clear_cache(self) -> None:
        """Evict all cached prompts (useful in tests or hot-reload scenarios)."""
        self._cache.clear()


# Module-level singleton — import and use directly.
prompt_loader = PromptLoader()
