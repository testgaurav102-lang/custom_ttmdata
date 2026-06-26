class ChartGenerator:
    def generate(self, data: list[dict], query: str) -> str:
        if not data:
            return "No data available for chart generation."
        q = query.lower()
        if any(w in q for w in ["pie"]):
            return self._pie_chart(data)
        if any(w in q for w in ["flow", "flowchart", "diagram"]):
            return self._flow_diagram(data)
        if any(w in q for w in ["line", "trend"]):
            return self._line_chart(data)
        return self._bar_chart(data)

    def _bar_chart(self, data: list[dict]) -> str:
        if not data:
            return ""
        keys = list(data[0].keys())
        label_key = keys[0]
        value_key = keys[1] if len(keys) > 1 else keys[0]
        labels = [str(row[label_key]) for row in data[:10]]
        values = [_to_num(row[value_key]) for row in data[:10]]
        max_val = max(values) if values else 100
        title = f"{value_key} by {label_key}"
        mermaid = f"xychart-beta\ntitle \"{title}\"\nx-axis {labels}\ny-axis \"{value_key}\" 0 --> {max_val}\nbar {values}"
        return f"```mermaid\n{mermaid}\n```"

    def _line_chart(self, data: list[dict]) -> str:
        if not data:
            return ""
        keys = list(data[0].keys())
        label_key = keys[0]
        value_key = keys[1] if len(keys) > 1 else keys[0]
        labels = [str(row[label_key]) for row in data[:10]]
        values = [_to_num(row[value_key]) for row in data[:10]]
        max_val = max(values) if values else 100
        title = f"{value_key} Trend"
        mermaid = f"xychart-beta\ntitle \"{title}\"\nx-axis {labels}\ny-axis \"{value_key}\" 0 --> {max_val}\nline {values}"
        return f"```mermaid\n{mermaid}\n```"

    def _pie_chart(self, data: list[dict]) -> str:
        if not data:
            return ""
        keys = list(data[0].keys())
        label_key = keys[0]
        value_key = keys[1] if len(keys) > 1 else keys[0]
        total = sum(_to_num(row[value_key]) for row in data[:10])
        entries = "\n".join(
            f'"{str(row[label_key])}" : {_to_num(row[value_key])}'
            for row in data[:10]
        )
        title = f"Revenue Distribution"
        mermaid = f"pie showData\ntitle {title}\n{entries}"
        return f"```mermaid\n{mermaid}\n```"

    def _flow_diagram(self, data: list[dict]) -> str:
        mermaid = """flowchart TD
    A[Upload File] --> B[Load into DuckDB]
    B --> C[Validate Schema]
    C --> D[Execute Query]
    D --> E[Generate Response]
    D --> F{Chart Requested?}
    F -->|Yes| G[Generate Mermaid Chart]
    F -->|No| E
    G --> E"""
        return f"```mermaid\n{mermaid}\n```"


def _to_num(val) -> float:
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0
