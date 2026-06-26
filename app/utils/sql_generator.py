import re


def generate_sql_from_query(query: str, metadata: dict) -> str:
    if not metadata:
        return ""

    table = metadata["table_name"]
    columns = metadata["columns"]
    q = query.lower()

    if "show all" in q or "select all" in q or "all rows" in q or "all records" in q:
        limit = ""
        m = re.search(r"(?:limit|top)\s+(\d+)", q)
        if m:
            limit = f" LIMIT {m.group(1)}"
        return f"SELECT * FROM {table}{limit}"

    if "count" in q and "row" in q:
        return f"SELECT COUNT(*) AS row_count FROM {table}"

    if "distinct" in q or "unique" in q:
        for col in columns:
            if col.lower() in q:
                return f'SELECT DISTINCT "{col}" FROM {table} ORDER BY "{col}"'

    agg_map = {
        "sum": "SUM",
        "total": "SUM",
        "average": "AVG",
        "avg": "AVG",
        "mean": "AVG",
        "minimum": "MIN",
        "min": "MIN",
        "maximum": "MAX",
        "max": "MAX",
    }
    for word, func in agg_map.items():
        if word in q:
            for col in columns:
                if col.lower() in q:
                    group_col = _find_group_column(q, columns)
                    if group_col:
                        return (
                            f'SELECT "{group_col}", {func}("{col}") AS {func.lower()}_{col} '
                            f"FROM {table} GROUP BY \"{group_col}\""
                        )
                    return f'SELECT {func}("{col}") AS {func.lower()}_{col} FROM {table}'

    if "top" in q or "limit" in q:
        m = re.search(r"(?:top|limit)\s+(\d+)", q)
        n = int(m.group(1)) if m else 10
        val_col, cat_col = _find_value_category_columns(q, columns)
        if val_col and cat_col:
            direction = "DESC" if any(w in q for w in ["top", "highest", "largest", "most"]) else "ASC"
            return (
                f'SELECT "{cat_col}", "{val_col}" FROM {table} '
                f"ORDER BY \"{val_col}\" {direction} LIMIT {n}"
            )

    if "group by" in q or "grouped by" in q:
        for col in columns:
            if col.lower() in q:
                agg_col, agg_func = _find_agg_column(q, columns)
                if agg_col:
                    return f'SELECT "{col}", {agg_func}("{agg_col}") FROM {table} GROUP BY "{col}"'
                return f'SELECT "{col}", COUNT(*) FROM {table} GROUP BY "{col}"'

    if "trend" in q or "over time" in q or "monthly" in q or "yearly" in q:
        date_col, val_col = _find_date_value_columns(columns)
        if date_col and val_col:
            return (
                f"SELECT strftime(\"{date_col}\", '%Y-%m') AS period, "
                f"SUM(\"{val_col}\") AS total "
                f"FROM {table} GROUP BY period ORDER BY period"
            )

    if "correlation" in q or "corr" in q:
        found = [c for c in columns if c.lower() in q]
        if len(found) >= 2:
            return f'SELECT CORR("{found[0]}", "{found[1]}") AS correlation FROM {table}'

    for col in columns:
        if col.lower() in q and "sort" in q or "order" in q:
            direction = "DESC" if "desc" in q else "ASC"
            return f'SELECT * FROM {table} ORDER BY "{col}" {direction} LIMIT 100'

    return f"SELECT * FROM {table} LIMIT 100"


def _find_group_column(query: str, columns: list[str]) -> str | None:
    q = query.lower()
    for col in columns:
        if f"by {col.lower()}" in q or f"per {col.lower()}" in q:
            return col
    for col in columns:
        if col.lower() in q:
            return col
    return None


def _find_value_category_columns(
    query: str, columns: list[str]
) -> tuple[str | None, str | None]:
    q = query.lower()
    numeric_cols = [c for c in columns if any(t in q for t in [c.lower()])]
    val_col = None
    cat_col = None
    for col in columns:
        if any(w in q for w in ["amount", "revenue", "sales", "price", "count", col.lower()]):
            val_col = col
        elif any(w in q for w in [col.lower()]):
            cat_col = col
    if val_col and not cat_col:
        for col in columns:
            if col != val_col:
                cat_col = col
                break
    return val_col, cat_col


def _find_agg_column(query: str, columns: list[str]) -> tuple[str | None, str]:
    q = query.lower()
    for col in columns:
        if col.lower() in q:
            for func in ["SUM", "AVG", "COUNT", "MIN", "MAX"]:
                if func.lower() in q:
                    return col, func
            return col, "COUNT"
    return None, "COUNT"


def _find_date_value_columns(columns: list[str]) -> tuple[str | None, str | None]:
    date_col = None
    val_col = None
    date_keywords = ["date", "time", "month", "year", "day", "period"]
    val_keywords = ["amount", "revenue", "sales", "price", "value", "cost", "profit"]
    for col in columns:
        cl = col.lower()
        if any(k in cl for k in date_keywords):
            date_col = col
        if any(k in cl for k in val_keywords):
            val_col = col
    if not val_col:
        for col in columns:
            if col != date_col:
                val_col = col
                break
    return date_col, val_col
