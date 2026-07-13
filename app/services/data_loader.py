"""
Data loading and query execution service.

Responsibilities:
- Validate uploaded file type and size.
- Parse CSV / XLS / XLSX into one or more pandas DataFrames.
  * XLSX / XLS files: each sheet is loaded as a separate DuckDB table.
  * CSV files: loaded as a single DuckDB table.
- Auto-detect date columns and normalise them to ISO-8601 strings.
- Register each DataFrame as a named DuckDB in-memory table.
- Maintain a per-file registry so callers can retrieve all tables for a given
  file_id (or a set of file_ids).
- Expose ``execute_query`` for running arbitrary SQL against any loaded table.

Multiple files can be loaded concurrently; tables persist until
``drop_file_tables`` or ``reset`` is called.
"""

import logging
import os
import re
import uuid
from pathlib import Path

import duckdb
import pandas as pd

from app.config import settings
from app.constants import DATE_DETECTION_THRESHOLD

logger = logging.getLogger(__name__)

# Maximum characters allowed in a sanitised sheet / table-name segment.
_MAX_SEGMENT_LEN = 40


def _sanitize_name(name: str, max_len: int = _MAX_SEGMENT_LEN) -> str:
    """Convert *name* to a DuckDB-safe identifier segment.

    Steps:
    1. Lowercase.
    2. Replace any run of non-alphanumeric characters with a single underscore.
    3. Strip leading/trailing underscores.
    4. Truncate to *max_len* characters.
    5. Ensure the result starts with a letter; prefix ``t_`` if it does not.
    """
    name = name.lower()
    name = re.sub(r"[^a-z0-9]+", "_", name).strip("_")
    name = name[:max_len].rstrip("_")
    if not name:
        name = "sheet"
    if not name[0].isalpha():
        name = f"t_{name}"
    return name


class DataLoader:
    """Manages DuckDB tables for one or more uploaded files."""

    def __init__(self) -> None:
        self._conn: duckdb.DuckDBPyConnection | None = None
        # file_id → list of table-metadata dicts
        self._file_registry: dict[str, list[dict]] = {}

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def conn(self) -> duckdb.DuckDBPyConnection:
        if self._conn is None:
            self._conn = duckdb.connect(":memory:")
        return self._conn

    @property
    def metadata(self) -> dict:
        """Backward-compatible: return the first table of the last loaded file."""
        if not self._file_registry:
            return {}
        last_file_tables = list(self._file_registry.values())[-1]
        return last_file_tables[0] if last_file_tables else {}

    # ------------------------------------------------------------------
    # File loading
    # ------------------------------------------------------------------

    def _validate_file(self, file_path: str) -> str:
        """Return the lowercase extension or raise ``ValueError``."""
        ext = Path(file_path).suffix.lower()
        if ext not in {".csv", ".xls", ".xlsx"}:
            raise ValueError(f"Unsupported file type: {ext}")
        size = os.path.getsize(file_path)
        max_bytes = settings.max_file_size_mb * 1024 * 1024
        if size > max_bytes:
            raise ValueError(
                f"File size {size} bytes exceeds maximum allowed {max_bytes} bytes "
                f"({settings.max_file_size_mb} MB)."
            )
        return ext

    def load_file(self, file_path: str, file_name: str, file_id: str) -> list[dict]:
        """Parse *file_path*, register all sheets in DuckDB, and return metadata.

        For XLSX / XLS files every sheet is loaded into its own DuckDB table.
        For CSV files a single table is created.

        Args:
            file_path: Absolute path to the uploaded file.
            file_name: Display name used in metadata.
            file_id:   UUID string from the upload router (used as registry key
                       and as part of the table-name prefix).

        Returns:
            List of metadata dicts, one per loaded table/sheet.

        Raises:
            ValueError: For unsupported file types, oversized files, or empty data.
        """
        ext = self._validate_file(file_path)
        id_prefix = file_id.replace("-", "")[:8]

        tables: list[dict] = []

        if ext == ".csv":
            df = pd.read_csv(file_path)
            if df is None or df.empty:
                raise ValueError("No data found in CSV file.")
            df = self._normalise_date_columns(df)
            table_name = f"f_{id_prefix}"
            meta = self._register_table(df, table_name, file_name, "Sheet1", file_name)
            tables.append(meta)

        else:
            engine = "openpyxl" if ext == ".xlsx" else "xlrd"
            xl = pd.ExcelFile(file_path, engine=engine)
            sheet_names = xl.sheet_names

            if not sheet_names:
                raise ValueError("No sheets found in Excel file.")

            for sheet_name in sheet_names:
                df = xl.parse(sheet_name)
                if df is None or df.empty:
                    logger.warning("Sheet '%s' is empty — skipping.", sheet_name)
                    continue

                df = self._normalise_date_columns(df)
                safe_sheet = _sanitize_name(str(sheet_name))
                table_name = f"s_{id_prefix}_{safe_sheet}"
                meta = self._register_table(df, table_name, file_name, sheet_name, file_name)
                tables.append(meta)

            if not tables:
                raise ValueError("All sheets in the Excel file are empty.")

        self._file_registry[file_id] = tables

        logger.info(
            "Loaded '%s' (file_id=%s) → %d table(s): %s",
            file_name,
            file_id,
            len(tables),
            [t["table_name"] for t in tables],
        )
        return tables

    def _register_table(
        self,
        df: pd.DataFrame,
        table_name: str,
        file_name: str,
        sheet_name: str,
        display_name: str,
    ) -> dict:
        """Create a DuckDB table from *df* and return its metadata dict."""
        self.conn.execute(f'DROP TABLE IF EXISTS "{table_name}"')
        self.conn.register("_temp_df", df)
        self.conn.execute(f'CREATE TABLE "{table_name}" AS SELECT * FROM _temp_df')

        row_count: int = self.conn.execute(
            f'SELECT COUNT(*) FROM "{table_name}"'
        ).fetchone()[0]

        meta = {
            "table_name": table_name,
            "sheet_name": sheet_name,
            "file_name": file_name,
            "display_name": display_name,
            "columns": list(df.columns),
            "dtypes": {col: str(df[col].dtype) for col in df.columns},
            "row_count": row_count,
        }

        logger.info(
            "  Registered table '%s' (sheet='%s', %d rows, %d columns).",
            table_name,
            sheet_name,
            row_count,
            len(df.columns),
        )
        return meta

    @staticmethod
    def _normalise_date_columns(df: pd.DataFrame) -> pd.DataFrame:
        """Convert columns that look like dates to ISO-8601 string format."""
        for col in df.columns:
            if pd.api.types.is_datetime64_any_dtype(df[col]):
                df[col] = df[col].dt.strftime("%Y-%m-%d")
                continue

            if pd.api.types.is_numeric_dtype(df[col]):
                continue

            try:
                parsed = pd.to_datetime(df[col], errors="coerce", format="mixed")
                non_null = df[col].notna().sum()
                valid_dates = parsed.notna().sum()

                if non_null > 0 and (valid_dates / non_null) >= DATE_DETECTION_THRESHOLD:
                    df[col] = parsed.dt.strftime("%Y-%m-%d")
            except Exception as exc:
                logger.debug("Date detection skipped for column '%s': %s", col, exc)

        return df

    # ------------------------------------------------------------------
    # Registry queries
    # ------------------------------------------------------------------

    def get_tables_for_file(self, file_id: str) -> list[dict]:
        """Return all table metadata dicts registered under *file_id*."""
        return self._file_registry.get(file_id, [])

    def get_tables_for_files(self, file_ids: list[str]) -> list[dict]:
        """Return flattened table metadata for all given *file_ids*."""
        tables: list[dict] = []
        for fid in file_ids:
            tables.extend(self._file_registry.get(fid, []))
        return tables

    def list_file_ids(self) -> list[str]:
        """Return all currently registered file IDs."""
        return list(self._file_registry.keys())

    # ------------------------------------------------------------------
    # Query execution
    # ------------------------------------------------------------------

    def execute_query(self, sql: str) -> list[dict]:
        """Run *sql* against the DuckDB instance and return rows as dicts."""
        result = self.conn.execute(sql)
        columns = [desc[0] for desc in result.description]
        rows = result.fetchall()
        return [dict(zip(columns, row)) for row in rows]

    def get_column_info(self, table_name: str | None = None) -> list[dict]:
        """Return detailed column type information from DuckDB DESCRIBE.

        If *table_name* is omitted, uses the last-loaded table for
        backward compatibility.
        """
        if table_name is None:
            if not self.metadata:
                return []
            table_name = self.metadata["table_name"]
        info = self.conn.execute(f'DESCRIBE "{table_name}"').fetchall()
        return [{"column_name": row[0], "column_type": row[1]} for row in info]

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def drop_file_tables(self, file_id: str) -> None:
        """Drop all DuckDB tables associated with *file_id* and remove from registry."""
        tables = self._file_registry.pop(file_id, [])
        for meta in tables:
            table_name = meta["table_name"]
            try:
                self.conn.execute(f'DROP TABLE IF EXISTS "{table_name}"')
                logger.info("Dropped table '%s' for file_id=%s.", table_name, file_id)
            except Exception as exc:
                logger.warning("Could not drop table '%s': %s", table_name, exc)

    def reset(self) -> None:
        """Close the DuckDB connection and clear all registry data."""
        if self._conn:
            self._conn.close()
        self._conn = None
        self._file_registry = {}
        logger.info("DataLoader reset — connection and registry cleared.")


# Module-level singleton
data_loader = DataLoader()
