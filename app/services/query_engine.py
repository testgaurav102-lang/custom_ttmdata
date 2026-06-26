import re

from app.services.data_loader import data_loader


class QueryEngine:
    def validate_columns(self, columns: list[str]) -> list[str]:
        if not data_loader.metadata:
            return []
        existing = {c.lower(): c for c in data_loader.metadata["columns"]}
        missing = []
        for col in columns:
            if col.lower() not in existing:
                missing.append(col)
        return missing

    def generate_aggregation_sql(
        self,
        agg_func: str,
        column: str,
        group_by: str | None = None,
        where: str | None = None,
        order_by: str | None = None,
        limit: int | None = None,
    ) -> str:
        table = data_loader.metadata["table_name"]
        col_quoted = f'"{column}"'
        select_expr = f"{agg_func}({col_quoted})"

        sql = f"SELECT {select_expr} FROM {table}"
        if where:
            sql += f" WHERE {where}"
        if group_by:
            sql += f" GROUP BY \"{group_by}\""
        if order_by:
            sql += f" ORDER BY {order_by}"
        if limit:
            sql += f" LIMIT {limit}"
        return sql

    def generate_top_n_sql(
        self,
        value_column: str,
        category_column: str,
        n: int = 10,
        ascending: bool = False,
    ) -> str:
        table = data_loader.metadata["table_name"]
        direction = "ASC" if ascending else "DESC"
        return (
            f"SELECT \"{category_column}\", \"{value_column}\" "
            f"FROM {table} "
            f"ORDER BY \"{value_column}\" {direction} "
            f"LIMIT {n}"
        )

    def generate_trend_sql(
        self,
        date_column: str,
        value_column: str,
        date_format: str = "%Y-%m",
    ) -> str:
        table = data_loader.metadata["table_name"]
        return (
            f"SELECT strftime(\"{date_column}\", '{date_format}') AS period, "
            f"SUM(\"{value_column}\") AS total "
            f"FROM {table} "
            f"GROUP BY period "
            f"ORDER BY period"
        )

    def generate_correlation_sql(self, col1: str, col2: str) -> str:
        table = data_loader.metadata["table_name"]
        return (
            f"SELECT CORR(\"{col1}\", \"{col2}\") AS correlation "
            f"FROM {table}"
        )

    def generate_summary_sql(self) -> str:
        table = data_loader.metadata["table_name"]
        columns = data_loader.metadata["columns"]
        agg_parts = []
        for col in columns:
            agg_parts.append(f'COUNT("{col}") AS count_{col}')
            agg_parts.append(f'COUNT(DISTINCT "{col}") AS distinct_{col}')
        agg_str = ",\n".join(agg_parts)
        return f"SELECT {agg_str} FROM {table}"

    def execute_natural_language_query(self, user_query: str) -> dict:
        if not data_loader.metadata:
            return {
                "success": False,
                "error": "No file uploaded. Please upload a data file first.",
                "results": None,
                "sql": None,
            }
        sql = self._nl_to_sql(user_query)
        try:
            results = data_loader.execute_query(sql)
            return {"success": True, "results": results, "sql": sql, "error": None}
        except Exception as e:
            return {"success": False, "error": str(e), "results": None, "sql": sql}

    def _nl_to_sql(self, query: str) -> str:
        q = query.lower()
        table = data_loader.metadata["table_name"]
        columns = data_loader.metadata["columns"]

        if "show all" in q or "select all" in q or "all rows" in q or "all records" in q:
            limit = ""
            if "limit" in q or "top" in q:
                match = re.search(r"(?:limit|top)\s+(\d+)", q)
                if match:
                    limit = f" LIMIT {match.group(1)}"
            return f"SELECT * FROM {table}{limit}"

        if "count" in q and "row" in q:
            return f"SELECT COUNT(*) AS row_count FROM {table}"

        if "distinct" in q or "unique" in q:
            for col in columns:
                if col.lower() in q:
                    return f'SELECT DISTINCT "{col}" FROM {table}'

        if "sum" in q or "total" in q:
            for col in columns:
                if col.lower() in q:
                    return f'SELECT SUM("{col}") AS total FROM {table}'

        if "average" in q or "avg" in q or "mean" in q:
            for col in columns:
                if col.lower() in q:
                    return f'SELECT AVG("{col}") AS average FROM {table}'

        if "min" in q:
            for col in columns:
                if col.lower() in q:
                    return f'SELECT MIN("{col}") AS min_value FROM {table}'

        if "max" in q:
            for col in columns:
                if col.lower() in q:
                    return f'SELECT MAX("{col}") AS max_value FROM {table}'

        return f"SELECT * FROM {table} LIMIT 100"


query_engine = QueryEngine()
