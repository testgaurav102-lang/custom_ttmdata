"""
Data loading and query execution service.

Responsibilities:
- Validate uploaded file type and size.
- Parse CSV / XLS / XLSX into a pandas DataFrame.
- Auto-detect date columns and normalise them to ISO-8601 strings.
- Register the DataFrame as a DuckDB in-memory table.
- Expose ``execute_query`` for running arbitrary SQL against the loaded table.

The global ``data_loader`` singleton holds a single dataset at a time.
Uploading a new file replaces the previous one.
"""

import logging
import os
import uuid
from pathlib import Path

import duckdb
import pandas as pd

from app.config import settings
from app.constants import DATE_DETECTION_THRESHOLD

logger = logging.getLogger(__name__)


class DataLoader:
    """Singleton responsible for ingesting and querying the active dataset."""

    def __init__(self) -> None:
        self._db_path: str | None = None
        self._conn: duckdb.DuckDBPyConnection | None = None
        self._metadata: dict = {}

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def conn(self) -> duckdb.DuckDBPyConnection:
        if self._conn is None:
            self._conn = duckdb.connect(self._db_path or ":memory:")
        return self._conn

    @property
    def metadata(self) -> dict:
        return self._metadata

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

    def load_file(self, file_path: str, file_name: str) -> dict:
        """Parse *file_path*, register it in DuckDB, and update metadata.

        Args:
            file_path: Absolute path to the uploaded file.
            file_name: Display name used in metadata.

        Returns:
            The updated metadata dict.

        Raises:
            ValueError: For unsupported file types, oversized files, or empty data.
        """
        ext = self._validate_file(file_path)
        table_name = f"data_{uuid.uuid4().hex[:8]}"

        df: pd.DataFrame | None = None
        if ext == ".csv":
            df = pd.read_csv(file_path)
        elif ext in (".xls", ".xlsx"):
            df = pd.read_excel(
                file_path,
                engine="openpyxl" if ext == ".xlsx" else "xlrd",
            )

        if df is None or df.empty:
            raise ValueError("No data found in file.")

        df = self._normalise_date_columns(df)

        self.conn.execute(f"DROP TABLE IF EXISTS {table_name}")
        self.conn.register("temp_df", df)
        self.conn.execute(f"CREATE TABLE {table_name} AS SELECT * FROM temp_df")

        row_count: int = self.conn.execute(
            f"SELECT COUNT(*) FROM {table_name}"
        ).fetchone()[0]

        self._metadata = {
            "table_name": table_name,
            "file_name": file_name,
            "file_path": str(file_path),
            "columns": list(df.columns),
            "dtypes": {col: str(df[col].dtype) for col in df.columns},
            "row_count": row_count,
        }

        logger.info(
            "Loaded '%s' → table '%s' (%d rows, %d columns).",
            file_name,
            table_name,
            row_count,
            len(df.columns),
        )
        return self._metadata

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
    # Query execution
    # ------------------------------------------------------------------

    def execute_query(self, sql: str) -> list[dict]:
        """Run *sql* against the active DuckDB table and return rows as dicts."""
        result = self.conn.execute(sql)
        columns = [desc[0] for desc in result.description]
        rows = result.fetchall()
        return [dict(zip(columns, row)) for row in rows]

    def get_column_info(self) -> list[dict]:
        """Return detailed column type information from DuckDB DESCRIBE."""
        if not self._metadata:
            return []
        table = self._metadata["table_name"]
        info = self.conn.execute(f"DESCRIBE {table}").fetchall()
        return [{"column_name": row[0], "column_type": row[1]} for row in info]

    def reset(self) -> None:
        """Close the DuckDB connection and clear all metadata."""
        if self._conn:
            self._conn.close()
        self._conn = None
        self._metadata = {}
        logger.info("DataLoader reset — connection and metadata cleared.")


# Module-level singleton
data_loader = DataLoader()
