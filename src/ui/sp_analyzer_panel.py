"""
SP Analyzer Panel — load an SP via file browse OR paste it directly,
reverse-engineer SELECT queries, generate test data, allow preview/edit,
insert with manual commit/rollback.
"""
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext


class SPAnalyzerPanel(ttk.Frame):
    def __init__(self, parent, db_conn, config_mgr, status_bar, **kwargs):
        super().__init__(parent, **kwargs)
        self.db         = db_conn
        self.cfg        = config_mgr
        self.status_bar = status_bar
        self._sql_text  = ""
        self._analysis  = None          # dict from sql_parser.analyse_sql_file
        self._generated: dict[tuple, list[dict]] = {}  # (schema,table) -> rows
        self._ordered_tables: list[tuple] = []
        self._build()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build(self):
        # ── Row 0: SP Input (file OR paste) ───────────────────────────────
        top = ttk.LabelFrame(self, text="1  Stored Procedure Input")
        top.pack(fill="x", padx=8, pady=6)

        self._input_nb = ttk.Notebook(top)
        self._input_nb.pack(fill="both", expand=True, padx=4, pady=4)

        # ── Tab A: Browse file ─────────────────────────────────────────────
        file_tab = ttk.Frame(self._input_nb)
        self._input_nb.add(file_tab, text="  📂 Browse File  ")

        self._file_var = tk.StringVar(value="No file selected")
        ttk.Label(file_tab, textvariable=self._file_var, width=58,
                  anchor="w", relief="sunken").pack(side="left", padx=4, pady=6)
        ttk.Button(file_tab, text="Browse…", command=self._browse).pack(side="left", padx=2)

        # ── Tab B: Paste SQL ───────────────────────────────────────────────
        paste_tab = ttk.Frame(self._input_nb)
        self._input_nb.add(paste_tab, text="  📋 Paste SQL  ")

        paste_btn_row = ttk.Frame(paste_tab)
        paste_btn_row.pack(fill="x", padx=4, pady=(4, 2))
        ttk.Label(paste_btn_row, text="Paste or type your stored procedure here:",
                  foreground="#555").pack(side="left")
        ttk.Button(paste_btn_row, text="Clear",
                   command=self._clear_paste).pack(side="right", padx=2)

        self._paste_editor = scrolledtext.ScrolledText(
            paste_tab, height=6, font=("Courier New", 9),
            relief="sunken", undo=True,
        )
        self._paste_editor.pack(fill="both", expand=True, padx=4, pady=(0, 4))

        # ── Analyse button (shared, below the notebook) ────────────────────
        btn_row = ttk.Frame(top)
        btn_row.pack(fill="x", padx=4, pady=(0, 4))
        ttk.Button(btn_row, text="🔍 Analyse", command=self._analyse).pack(side="left", padx=2)

        # ── Row 1: Analysis results (tables + conditions) ──────────────────
        mid = ttk.LabelFrame(self, text="2  Analysis — Detected Tables & Conditions")
        mid.pack(fill="x", padx=8, pady=2)
        mid.columnconfigure(0, weight=1)
        mid.columnconfigure(1, weight=1)

        ttk.Label(mid, text="Tables Found:").grid(row=0, column=0, sticky="w", padx=4)
        self._tables_lbox = tk.Listbox(mid, height=5, selectmode="extended",
                                        exportselection=False)
        self._tables_lbox.grid(row=1, column=0, sticky="nsew", padx=4, pady=2)

        ttk.Label(mid, text="WHERE Conditions Inferred:").grid(row=0, column=1, sticky="w", padx=4)
        self._cond_text = tk.Text(mid, height=5, state="disabled",
                                   font=("Courier New", 9), relief="sunken")
        self._cond_text.grid(row=1, column=1, sticky="nsew", padx=4, pady=2)

        # ── Row 2: Options ─────────────────────────────────────────────────
        opt = ttk.Frame(self)
        opt.pack(fill="x", padx=8, pady=4)
        ttk.Label(opt, text="Rows per table:").pack(side="left")
        self._rows_var = tk.IntVar(value=int(self.cfg.get_app("default_test_rows", "10")))
        ttk.Spinbox(opt, from_=1, to=100, width=5,
                    textvariable=self._rows_var).pack(side="left", padx=4)
        ttk.Label(opt, text="Schema:").pack(side="left", padx=(10, 0))
        self._schema_var = tk.StringVar(value="public")
        ttk.Entry(opt, textvariable=self._schema_var, width=14).pack(side="left", padx=4)
        ttk.Button(opt, text="⚙ Generate Preview",
                   command=self._generate_preview).pack(side="left", padx=8)

        # ── Row 3: Preview grid ────────────────────────────────────────────
        prev = ttk.LabelFrame(self, text="3  Data Preview  (double-click cell to edit)")
        prev.pack(fill="both", expand=True, padx=8, pady=2)

        self._nb_preview = ttk.Notebook(prev)
        self._nb_preview.pack(fill="both", expand=True)

        # ── Row 4: Action buttons ──────────────────────────────────────────
        act = ttk.LabelFrame(self, text="4  Actions")
        act.pack(fill="x", padx=8, pady=6)

        self._tx_status = tk.StringVar(value="No open transaction")
        ttk.Label(act, textvariable=self._tx_status,
                  foreground="#555").pack(side="left", padx=8)

        ttk.Button(act, text="⬇ Insert Test Data",
                   command=self._insert_data).pack(side="right", padx=4)
        ttk.Button(act, text="✔ Commit",
                   command=self._commit).pack(side="right", padx=4)
        ttk.Button(act, text="↺ Rollback",
                   command=self._rollback).pack(side="right", padx=4)

        # ── Row 5: Log ─────────────────────────────────────────────────────
        log_f = ttk.LabelFrame(self, text="Log")
        log_f.pack(fill="x", padx=8, pady=(0, 6))
        self._log = scrolledtext.ScrolledText(log_f, height=5,
                                               font=("Courier New", 9),
                                               state="disabled", relief="flat")
        self._log.pack(fill="both", expand=True)

    # ── File & analysis ───────────────────────────────────────────────────────

    def _browse(self):
        path = filedialog.askopenfilename(
            title="Select SQL file",
            filetypes=[("SQL files", "*.sql"), ("All files", "*.*")],
        )
        if path:
            self._file_var.set(path)
            with open(path, encoding="utf-8", errors="replace") as f:
                self._sql_text = f.read()
            self._log_write(f"Loaded: {path} ({len(self._sql_text)} chars)")

    def _clear_paste(self):
        self._paste_editor.delete("1.0", "end")

    def _get_active_sql(self) -> str:
        """Return SQL from whichever input tab is currently selected."""
        active = self._input_nb.index(self._input_nb.select())
        if active == 1:          # Paste SQL tab
            return self._paste_editor.get("1.0", "end-1c").strip()
        return self._sql_text    # Browse File tab

    def _analyse(self):
        sql = self._get_active_sql()
        if not sql:
            messagebox.showwarning(
                "No SQL",
                "Please browse and select a SQL file, or paste your SP text into the 'Paste SQL' tab.",
            )
            return
        self._sql_text = sql          # keep in sync regardless of source
        self._log_write(f"Analysing SQL ({len(sql)} chars)…")
        try:
            from src.sql_parser import analyse_sql_file
            self._analysis = analyse_sql_file(self._sql_text)
            self._populate_analysis()
            self._log_write(
                f"Found {len(self._analysis['tables'])} table(s), "
                f"{len(self._analysis['selects'])} SELECT(s), "
                f"{sum(len(v) for v in self._analysis['conditions'].values())} condition(s)."
            )
        except Exception as e:
            messagebox.showerror("Analysis error", str(e))
            self._log_write(f"ERROR: {e}")

    def _populate_analysis(self):
        self._tables_lbox.delete(0, "end")
        for schema, table in self._analysis["tables"]:
            self._tables_lbox.insert("end", f"{schema}.{table}")
        # Select all by default
        self._tables_lbox.selection_set(0, "end")

        self._cond_text.config(state="normal")
        self._cond_text.delete("1.0", "end")
        for col, conds in self._analysis["conditions"].items():
            for c in conds:
                line = f"{col} {c['operator']} {c['value']}\n"
                self._cond_text.insert("end", line)
        self._cond_text.config(state="disabled")

    # ── Preview generation ────────────────────────────────────────────────────

    def _get_selected_tables(self) -> list[tuple[str, str]]:
        if not self._analysis:
            return []
        all_tables = self._analysis["tables"]
        sel_indices = self._tables_lbox.curselection()
        if not sel_indices:
            return all_tables
        return [all_tables[i] for i in sel_indices]

    def _generate_preview(self):
        if not self.db.is_connected():
            messagebox.showwarning("Not connected", "Please connect to a database first.")
            return
        if not self._analysis:
            messagebox.showwarning("No analysis", "Please run Analyse first.")
            return

        tables = self._get_selected_tables()
        if not tables:
            messagebox.showwarning("No tables", "No tables selected.")
            return

        self._log_write("Generating preview data…")
        try:
            from src.schema_inspector import SchemaInspector
            from src.test_data_generator import TestDataGenerator
            insp = SchemaInspector(self.db.conn)
            gen  = TestDataGenerator(insp, default_rows=self._rows_var.get())
            self._generated = gen.generate_for_tables(
                tables, self._analysis["conditions"],
                num_rows=self._rows_var.get(),
            )
            self._ordered_tables = list(self._generated.keys())
            self._render_preview_tabs()
            self._log_write("Preview generated — review and click 'Insert Test Data'.")
        except Exception as e:
            messagebox.showerror("Generation error", str(e))
            self._log_write(f"ERROR: {e}")

    def _render_preview_tabs(self):
        # Clear existing tabs
        for tab in self._nb_preview.tabs():
            self._nb_preview.forget(tab)

        self._preview_trees: dict[tuple, ttk.Treeview] = {}

        for key, rows in self._generated.items():
            schema, table = key
            if not rows:
                continue
            frame = ttk.Frame(self._nb_preview)
            self._nb_preview.add(frame, text=f"{schema}.{table}")

            cols = list(rows[0].keys())
            tree = ttk.Treeview(frame, columns=cols, show="headings", height=8)
            for col in cols:
                tree.heading(col, text=col)
                tree.column(col, width=110, minwidth=60)

            for i, row in enumerate(rows):
                vals = [str(row.get(c, "")) for c in cols]
                tree.insert("", "end", iid=str(i), values=vals)

            vsb = ttk.Scrollbar(frame, orient="vertical",   command=tree.yview)
            hsb = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
            tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
            vsb.pack(side="right", fill="y")
            hsb.pack(side="bottom", fill="x")
            tree.pack(fill="both", expand=True)
            tree.bind("<Double-1>", lambda e, t=tree, k=key, c=cols: self._edit_cell(e, t, k, c))
            self._preview_trees[key] = tree

    def _edit_cell(self, event, tree, key, cols):
        """Inline cell editor on double-click."""
        region = tree.identify_region(event.x, event.y)
        if region != "cell":
            return
        row_iid = tree.identify_row(event.y)
        col_id  = tree.identify_column(event.x)
        col_idx = int(col_id.replace("#", "")) - 1
        if col_idx < 0 or col_idx >= len(cols):
            return
        col_name = cols[col_idx]
        x, y, w, h = tree.bbox(row_iid, col_id)
        val = tree.set(row_iid, col_id)
        entry_var = tk.StringVar(value=val)
        entry = ttk.Entry(tree, textvariable=entry_var)
        entry.place(x=x, y=y, width=w, height=h)
        entry.focus()

        def _commit_edit(_e=None):
            new_val = entry_var.get()
            tree.set(row_iid, col_id, new_val)
            # Update internal data
            row_idx = int(row_iid)
            self._generated[key][row_idx][col_name] = new_val
            entry.destroy()

        entry.bind("<Return>", _commit_edit)
        entry.bind("<FocusOut>", _commit_edit)

    # ── Insert / commit / rollback ────────────────────────────────────────────

    def _insert_data(self):
        if not self.db.is_connected():
            messagebox.showwarning("Not connected", "Please connect first.")
            return
        if not self._generated:
            messagebox.showwarning("No data", "Generate a preview first.")
            return
        if self.db.has_open_test_tx():
            if not messagebox.askyesno(
                "Transaction open",
                "A test transaction is already open.\n"
                "Rollback existing data and start fresh?"
            ):
                return
            self.db.rollback_test_tx()

        try:
            self.db.begin_test_tx()
            total = 0
            for key in self._ordered_tables:
                schema, table = key
                rows = self._generated.get(key, [])
                for row in rows:
                    if not row:
                        continue
                    self.db.tx_insert(schema, table, list(row.keys()), list(row.values()))
                    total += 1
            self._tx_status.set(f"🟡  Transaction open — {total} row(s) inserted (not committed)")
            self.status_bar.set_message(f"Test data inserted ({total} rows) — NOT committed yet.")
            self._log_write(f"Inserted {total} row(s) into open transaction. Commit or Rollback when ready.")
        except Exception as e:
            self.db.rollback_test_tx()
            self._tx_status.set("No open transaction")
            messagebox.showerror("Insert error", str(e))
            self._log_write(f"INSERT ERROR: {e}")

    def _commit(self):
        if not self.db.has_open_test_tx():
            messagebox.showinfo("Nothing to commit", "No open test transaction.")
            return
        if messagebox.askyesno("Commit", "Commit all inserted test data permanently?"):
            try:
                self.db.commit_test_tx()
                self._tx_status.set("✅  Committed")
                self.status_bar.set_message("Test data committed.")
                self._log_write("Transaction committed.")
            except Exception as e:
                messagebox.showerror("Commit error", str(e))

    def _rollback(self):
        if not self.db.has_open_test_tx():
            messagebox.showinfo("Nothing to rollback", "No open test transaction.")
            return
        if messagebox.askyesno("Rollback", "Rollback all inserted test data?"):
            self.db.rollback_test_tx()
            self._tx_status.set("↺  Rolled back")
            self.status_bar.set_message("Test data rolled back.")
            self._log_write("Transaction rolled back.")

    # ── Log helper ────────────────────────────────────────────────────────────

    def _log_write(self, msg: str):
        self._log.config(state="normal")
        self._log.insert("end", msg + "\n")
        self._log.see("end")
        self._log.config(state="disabled")
