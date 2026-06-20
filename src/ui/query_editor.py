"""SQL query editor with keyword highlighting, F5 run, history."""
import tkinter as tk
from tkinter import ttk, scrolledtext


_KEYWORDS = [
    "SELECT", "FROM", "WHERE", "JOIN", "LEFT", "RIGHT", "INNER", "OUTER",
    "FULL", "ON", "AS", "AND", "OR", "NOT", "IN", "IS", "NULL", "LIKE",
    "BETWEEN", "ORDER", "BY", "GROUP", "HAVING", "LIMIT", "OFFSET",
    "INSERT", "INTO", "VALUES", "UPDATE", "SET", "DELETE", "CREATE",
    "TABLE", "ALTER", "DROP", "INDEX", "VIEW", "SCHEMA", "DATABASE",
    "BEGIN", "COMMIT", "ROLLBACK", "WITH", "UNION", "ALL", "DISTINCT",
    "CASE", "WHEN", "THEN", "ELSE", "END", "EXISTS", "RETURNING",
    "CALL", "FUNCTION", "PROCEDURE", "RETURNS", "LANGUAGE", "DECLARE",
]


class QueryEditor(ttk.Frame):
    def __init__(self, parent, db_conn, result_grid, status_bar, **kwargs):
        super().__init__(parent, **kwargs)
        self.db          = db_conn
        self.result_grid = result_grid
        self.status_bar  = status_bar
        self._history: list[str] = []
        self._history_idx = -1
        self._build()

    def _build(self):
        # Toolbar
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 2))
        ttk.Button(bar, text="▶ Run (F5)",    command=self.run_query).pack(side="left", padx=2)
        ttk.Button(bar, text="⬆ History",    command=self._prev_history).pack(side="left", padx=2)
        ttk.Button(bar, text="⬇ History",    command=self._next_history).pack(side="left", padx=2)
        ttk.Button(bar, text="✕ Clear",       command=self._clear).pack(side="left", padx=2)

        # Editor
        self._text = scrolledtext.ScrolledText(
            self, wrap="none", font=("Courier New", 11),
            undo=True, relief="flat", borderwidth=1,
            background="#fafafa", foreground="#1a1a1a",
            insertbackground="#1a1a1a",
        )
        self._text.pack(fill="both", expand=True)
        self._text.bind("<F5>", lambda _: self.run_query())
        self._text.bind("<KeyRelease>", self._highlight)
        self._setup_tags()

    def _setup_tags(self):
        self._text.tag_configure("keyword",  foreground="#0033cc", font=("Courier New", 11, "bold"))
        self._text.tag_configure("string",   foreground="#008800")
        self._text.tag_configure("comment",  foreground="#888888", font=("Courier New", 11, "italic"))
        self._text.tag_configure("number",   foreground="#aa5500")

    def _highlight(self, _event=None):
        import re
        content = self._text.get("1.0", "end")
        for tag in ("keyword", "string", "comment", "number"):
            self._text.tag_remove(tag, "1.0", "end")

        for kw in _KEYWORDS:
            for m in re.finditer(rf'\b{kw}\b', content, re.IGNORECASE):
                s = f"1.0 + {m.start()} chars"
                e = f"1.0 + {m.end()} chars"
                self._text.tag_add("keyword", s, e)

        for m in re.finditer(r"'[^']*'", content):
            self._text.tag_add("string", f"1.0 + {m.start()} chars", f"1.0 + {m.end()} chars")

        for m in re.finditer(r'--[^\n]*', content):
            self._text.tag_add("comment", f"1.0 + {m.start()} chars", f"1.0 + {m.end()} chars")

        for m in re.finditer(r'\b\d+(\.\d+)?\b', content):
            self._text.tag_add("number", f"1.0 + {m.start()} chars", f"1.0 + {m.end()} chars")

    def set_text(self, sql: str):
        self._text.delete("1.0", "end")
        self._text.insert("1.0", sql)
        self._highlight()

    def get_text(self) -> str:
        # If text is selected, run only selection
        try:
            return self._text.get("sel.first", "sel.last").strip()
        except tk.TclError:
            return self._text.get("1.0", "end").strip()

    def run_query(self):
        sql = self.get_text()
        if not sql:
            return
        if not self.db.is_connected():
            self.status_bar.set_message("Not connected — please connect first.")
            return
        self._history.append(sql)
        self._history_idx = len(self._history)
        try:
            result = self.db.execute(sql)
            self.result_grid.display(result)
            elapsed = result.get("elapsed", 0)
            rows    = result.get("rowcount", 0)
            self.status_bar.set_message(f"Query OK — {rows} row(s) — {elapsed:.3f}s")
        except Exception as e:
            self.result_grid.show_error(str(e))
            self.status_bar.set_message(f"Error: {e}")

    def _prev_history(self):
        if self._history and self._history_idx > 0:
            self._history_idx -= 1
            self.set_text(self._history[self._history_idx])

    def _next_history(self):
        if self._history and self._history_idx < len(self._history) - 1:
            self._history_idx += 1
            self.set_text(self._history[self._history_idx])

    def _clear(self):
        self._text.delete("1.0", "end")
