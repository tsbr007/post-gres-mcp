"""Main application window — assembles all panels."""
import tkinter as tk
from tkinter import ttk

from src.config_manager import ConfigManager
from src.db_connection import DatabaseConnection
from src.ui.status_bar import StatusBar
from src.ui.connection_panel import ConnectionPanel
from src.ui.object_explorer import ObjectExplorer
from src.ui.query_editor import QueryEditor
from src.ui.result_grid import ResultGrid
from src.ui.sp_analyzer_panel import SPAnalyzerPanel
from src.ui.token_estimator_panel import TokenEstimatorPanel


class PostgresManagerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PostgreSQL Manager")
        self.geometry("1280x780")
        self.minsize(900, 600)

        self.cfg = ConfigManager()
        self.db  = DatabaseConnection()

        # Apply ttk theme
        style = ttk.Style(self)
        theme = self.cfg.get_app("theme", "clam")
        available = style.theme_names()
        style.theme_use(theme if theme in available else available[0])

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        # Menu bar
        self._build_menu()

        # Status bar (bottom, packed first so it stays at bottom)
        self.status_bar = StatusBar(self)
        self.status_bar.pack(side="bottom", fill="x")

        ttk.Separator(self).pack(side="bottom", fill="x")

        # Horizontal pane: left sidebar | right content
        self._hpane = ttk.PanedWindow(self, orient="horizontal")
        self._hpane.pack(fill="both", expand=True)

        # ── Left sidebar ──────────────────────────────────────────────────
        left_nb = ttk.Notebook(self._hpane)
        self._hpane.add(left_nb, weight=0)

        self.conn_panel = ConnectionPanel(
            left_nb, self.cfg, self.db,
            on_connect=self._on_connect,
            on_disconnect=self._on_disconnect,
        )
        left_nb.add(self.conn_panel, text="🔌 Connect")

        self.obj_explorer = ObjectExplorer(
            left_nb, self.db,
            on_table_select=self._set_query,
        )
        left_nb.add(self.obj_explorer, text="🌲 Explorer")

        # ── Right content ─────────────────────────────────────────────────
        right_nb = ttk.Notebook(self._hpane)
        self._hpane.add(right_nb, weight=1)

        # Tab 1: Query editor + results
        query_tab = ttk.Frame(right_nb)
        right_nb.add(query_tab, text="📝 Query Editor")

        vpane = ttk.PanedWindow(query_tab, orient="vertical")
        vpane.pack(fill="both", expand=True)

        self.result_grid = ResultGrid(vpane)
        self.query_editor = QueryEditor(
            vpane, self.db, self.result_grid, self.status_bar
        )
        vpane.add(self.query_editor, weight=2)
        vpane.add(self.result_grid,  weight=1)

        # Tab 2: SP Analyzer
        self.sp_panel = SPAnalyzerPanel(
            right_nb, self.db, self.cfg, self.status_bar
        )
        right_nb.add(self.sp_panel, text="🧪 SP Analyzer / Test Data")

        # Tab 3: Token Estimator
        self.token_panel = TokenEstimatorPanel(right_nb)
        right_nb.add(self.token_panel, text="📊 Token Estimator")

    def _build_menu(self):
        mb = tk.Menu(self)
        self.config(menu=mb)

        file_m = tk.Menu(mb, tearoff=False)
        file_m.add_command(label="Open SQL File…", command=self._open_sql)
        file_m.add_separator()
        file_m.add_command(label="Exit", command=self._on_close)
        mb.add_cascade(label="File", menu=file_m)

        conn_m = tk.Menu(mb, tearoff=False)
        conn_m.add_command(label="Disconnect", command=self._disconnect)
        mb.add_cascade(label="Connection", menu=conn_m)

        help_m = tk.Menu(mb, tearoff=False)
        help_m.add_command(label="About", command=self._about)
        mb.add_cascade(label="Help", menu=help_m)

    # ── Event handlers ────────────────────────────────────────────────────────

    def _on_connect(self, profile):
        ver = self.db.server_version_str()
        info = f"{profile['host']}:{profile['port']}/{profile['database']} as {profile['username']}"
        self.status_bar.set_connected(f"{info}  [{ver}]")
        self.obj_explorer.refresh()

    def _on_disconnect(self):
        self.status_bar.set_disconnected()

    def _disconnect(self):
        self.db.disconnect()
        self._on_disconnect()

    def _set_query(self, sql: str):
        self.query_editor.set_text(sql)

    def _open_sql(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            title="Open SQL File",
            filetypes=[("SQL files", "*.sql"), ("All files", "*.*")],
        )
        if path:
            with open(path, encoding="utf-8", errors="replace") as f:
                self.query_editor.set_text(f.read())

    def _about(self):
        from tkinter import messagebox
        messagebox.showinfo(
            "PostgreSQL Manager",
            "PostgreSQL Manager\n"
            "Python · Tkinter · psycopg2\n\n"
            "Features:\n"
            "• Multi-profile connection management\n"
            "• SQL editor with syntax highlighting\n"
            "• Object explorer (schemas/tables/views)\n"
            "• SP Analyzer: reverse-engineer SELECT queries\n"
            "• Test data generation with FK ordering\n"
            "• Manual commit / rollback of test data\n"
            "• CSV export"
        )

    def _on_close(self):
        self.db.disconnect()
        self.destroy()
