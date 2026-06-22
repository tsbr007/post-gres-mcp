"""
Token Estimator Panel — estimate Claude token consumption for a postgres-mcp session.

Integrates token_estimator.py logic into the Tkinter app as a self-contained tab.
"""
import io
import math
import pathlib
import re
import threading
import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext


# ── Reuse core logic from token_estimator.py ─────────────────────────────────

CHARS_PER_TOKEN = 4


def _chars_to_tokens(n: int) -> int:
    return max(1, math.ceil(n / CHARS_PER_TOKEN))


def _tokens_to_cost(input_tokens: int, output_tokens: int) -> dict:
    input_cost  = (input_tokens  / 1_000_000) * 3.00
    output_cost = (output_tokens / 1_000_000) * 15.00
    return {
        "input_tokens":  input_tokens,
        "output_tokens": output_tokens,
        "total_tokens":  input_tokens + output_tokens,
        "input_cost_usd":  round(input_cost,  6),
        "output_cost_usd": round(output_cost, 6),
        "total_cost_usd":  round(input_cost + output_cost, 6),
    }


def _get_system_prompt_tokens() -> int:
    instructions_path = pathlib.Path(__file__).parent.parent / "mcp_instructions.txt"
    try:
        text = instructions_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        text = "x" * 23966
    return _chars_to_tokens(len(text))


def _estimate_phase_tokens(sp_size_chars, num_tables, recursion_depth, rows_per_table, num_columns_avg):
    results = {}
    sp_tokens = _chars_to_tokens(sp_size_chars)
    results["Phase 0  Connection Check"]        = (200, 150)
    results["Phase 1  SP Discovery & Loading"]  = (sp_tokens + 300, 600)
    per_level_in  = 500 + (num_tables * 200)
    results["Phase 2  Recursive SQL Chain"]     = (per_level_in * recursion_depth, 400 * recursion_depth)
    per_table_out = (num_columns_avg * 30 + 200) + 200 + (rows_per_table * num_columns_avg * 10)
    results["Phase 3  Schema Analysis"]         = (300 * num_tables + 500, per_table_out * num_tables + 800)
    results["Phase 4  Condition Analysis"]       = (400, 500)
    generated_tokens = num_tables * rows_per_table * num_columns_avg * 8
    results["Phase 5  Test Data Generation"]    = (300, generated_tokens + 600)
    per_insert_in = 150 + (rows_per_table * num_columns_avg * 5)
    results["Phase 6  Transaction & Insert"]    = (per_insert_in * num_tables + 200, 100 * num_tables + 300)
    results["Phase 7  Operator Verification"]   = (200, 400)
    results["Phase 8  Commit / Rollback"]       = (150, 250)
    return results


def _estimate_context_overhead(phase_tokens, system_prompt_tokens):
    cumulative   = 0
    running_hist = system_prompt_tokens
    for inp, out in phase_tokens.values():
        cumulative   += running_hist
        running_hist += inp + out
    return cumulative


def run_estimation_data(sp_size_chars, num_tables, recursion_depth, rows_per_table, num_columns_avg):
    """Return all computed data as a dict (no printing)."""
    sys_tokens    = _get_system_prompt_tokens()
    phase_tokens  = _estimate_phase_tokens(sp_size_chars, num_tables, recursion_depth, rows_per_table, num_columns_avg)
    ctx_overhead  = _estimate_context_overhead(phase_tokens, sys_tokens)
    total_input   = sum(i for i, _ in phase_tokens.values()) + ctx_overhead
    total_output  = sum(o for _, o in phase_tokens.values())
    cost          = _tokens_to_cost(total_input, total_output)

    # Scenario comparison
    scenarios = []
    for label, t, d, r, c in [
        ("Simple SP",       1, 1, 3,  5),
        ("Moderate SP",     3, 2, 5,  8),
        ("Complex SP",      6, 3, 10, 10),
        ("Very Complex SP", 10, 5, 15, 12),
    ]:
        pt = _estimate_phase_tokens(sp_size_chars, t, d, r, c)
        co = _estimate_context_overhead(pt, sys_tokens)
        si = sum(i for i, _ in pt.values()) + co
        so = sum(o for _, o in pt.values())
        sc = _tokens_to_cost(si, so)
        scenarios.append((label, t, d, sc["total_tokens"], sc["total_cost_usd"]))

    return {
        "sys_tokens":     sys_tokens,
        "phase_tokens":   phase_tokens,
        "ctx_overhead":   ctx_overhead,
        "total_input":    total_input,
        "total_output":   total_output,
        "cost":           cost,
        "scenarios":      scenarios,
    }


# ── Panel ─────────────────────────────────────────────────────────────────────

class TokenEstimatorPanel(ttk.Frame):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self._sp_text       = ""
        self._sp_path       = ""
        self._sp_size_chars = 0
        self._last_result   = None
        self._build()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build(self):
        # ── Section 1: SP Input ───────────────────────────────────────────────
        sp_frame = ttk.LabelFrame(self, text="1  Stored Procedure Input")
        sp_frame.pack(fill="x", padx=8, pady=6)

        # File row
        file_row = ttk.Frame(sp_frame)
        file_row.pack(fill="x", padx=4, pady=(4, 0))

        self._file_var = tk.StringVar(value="No file selected")
        ttk.Label(file_row, text="SQL File:").pack(side="left")
        ttk.Label(file_row, textvariable=self._file_var, width=55,
                  anchor="w", relief="sunken").pack(side="left", padx=6)
        ttk.Button(file_row, text="Browse...", command=self._browse_file).pack(side="left", padx=2)
        ttk.Button(file_row, text="Clear", command=self._clear_sp).pack(side="left", padx=2)

        # Paste SP text
        ttk.Label(sp_frame, text="  — or paste SP text directly below —",
                  foreground="#888").pack(anchor="w", padx=4, pady=(4, 0))
        self._sp_editor = scrolledtext.ScrolledText(
            sp_frame, height=8, font=("Courier New", 9),
            relief="sunken", undo=True
        )
        self._sp_editor.pack(fill="both", expand=True, padx=4, pady=(2, 4))
        self._sp_editor.bind("<KeyRelease>", self._on_sp_text_change)

        # ── Section 2: Parameters ─────────────────────────────────────────────
        param_frame = ttk.LabelFrame(self, text="2  Estimation Parameters")
        param_frame.pack(fill="x", padx=8, pady=4)

        params_row = ttk.Frame(param_frame)
        params_row.pack(fill="x", padx=6, pady=6)

        # Tables
        ttk.Label(params_row, text="Tables referenced:").grid(row=0, column=0, sticky="w", padx=(0, 4))
        self._tables_var = tk.IntVar(value=5)
        ttk.Spinbox(params_row, from_=1, to=50, width=5,
                    textvariable=self._tables_var).grid(row=0, column=1, sticky="w", padx=(0, 16))

        # Recursion depth
        ttk.Label(params_row, text="Recursion depth:").grid(row=0, column=2, sticky="w", padx=(0, 4))
        self._depth_var = tk.IntVar(value=2)
        ttk.Spinbox(params_row, from_=0, to=10, width=5,
                    textvariable=self._depth_var).grid(row=0, column=3, sticky="w", padx=(0, 16))

        # Rows per table
        ttk.Label(params_row, text="Rows per table:").grid(row=0, column=4, sticky="w", padx=(0, 4))
        self._rows_var = tk.IntVar(value=5)
        ttk.Spinbox(params_row, from_=1, to=100, width=5,
                    textvariable=self._rows_var).grid(row=0, column=5, sticky="w", padx=(0, 16))

        # Avg columns
        ttk.Label(params_row, text="Avg columns/table:").grid(row=0, column=6, sticky="w", padx=(0, 4))
        self._cols_var = tk.IntVar(value=8)
        ttk.Spinbox(params_row, from_=1, to=50, width=5,
                    textvariable=self._cols_var).grid(row=0, column=7, sticky="w")

        # Auto-detect note
        self._autodetect_var = tk.StringVar(value="")
        ttk.Label(param_frame, textvariable=self._autodetect_var,
                  foreground="#0070d2", font=("TkDefaultFont", 8)).pack(anchor="w", padx=6, pady=(0, 4))

        # Run button
        btn_row = ttk.Frame(param_frame)
        btn_row.pack(fill="x", padx=6, pady=(0, 6))
        self._run_btn = ttk.Button(btn_row, text="  Estimate Token Usage  ",
                                   command=self._run_estimation)
        self._run_btn.pack(side="left")
        ttk.Button(btn_row, text="Copy Report", command=self._copy_report).pack(side="left", padx=8)
        self._status_var = tk.StringVar(value="")
        ttk.Label(btn_row, textvariable=self._status_var,
                  foreground="#555").pack(side="left", padx=4)

        # ── Section 3: Results ────────────────────────────────────────────────
        results_frame = ttk.LabelFrame(self, text="3  Results")
        results_frame.pack(fill="both", expand=True, padx=8, pady=4)

        results_nb = ttk.Notebook(results_frame)
        results_nb.pack(fill="both", expand=True, padx=4, pady=4)

        # Tab A: Summary cards
        summary_tab = ttk.Frame(results_nb)
        results_nb.add(summary_tab, text="  Summary  ")
        self._build_summary_tab(summary_tab)

        # Tab B: Phase breakdown table
        phase_tab = ttk.Frame(results_nb)
        results_nb.add(phase_tab, text="  Phase Breakdown  ")
        self._build_phase_tab(phase_tab)

        # Tab C: Scenario comparison
        scenario_tab = ttk.Frame(results_nb)
        results_nb.add(scenario_tab, text="  Scenario Comparison  ")
        self._build_scenario_tab(scenario_tab)

        # Tab D: Raw text report
        raw_tab = ttk.Frame(results_nb)
        results_nb.add(raw_tab, text="  Full Report  ")
        self._raw_output = scrolledtext.ScrolledText(
            raw_tab, font=("Courier New", 9), state="disabled", relief="flat"
        )
        self._raw_output.pack(fill="both", expand=True, padx=4, pady=4)

    def _build_summary_tab(self, parent):
        # 3 big stat cards: Total Tokens | Input Cost | Output Cost | Total Cost
        card_row = ttk.Frame(parent)
        card_row.pack(fill="x", padx=10, pady=16)

        self._card_labels = {}
        cards = [
            ("total_tokens",  "Total Tokens",   "#0070d2"),
            ("input_tokens",  "Input Tokens",   "#5867e8"),
            ("output_tokens", "Output Tokens",  "#9b4dca"),
            ("total_cost",    "Est. Cost (USD)", "#2e844a"),
        ]
        for col, (key, label, color) in enumerate(cards):
            card = ttk.Frame(card_row, relief="solid", borderwidth=1)
            card.grid(row=0, column=col, padx=8, pady=4, ipadx=18, ipady=10, sticky="nsew")
            card_row.columnconfigure(col, weight=1)
            ttk.Label(card, text=label, font=("TkDefaultFont", 9),
                      foreground="#555").pack()
            val_lbl = ttk.Label(card, text="—", font=("TkDefaultFont", 18, "bold"),
                                foreground=color)
            val_lbl.pack(pady=4)
            self._card_labels[key] = val_lbl

        # Context warning
        self._ctx_warning = ttk.Label(
            parent, text="", foreground="#c23934",
            font=("TkDefaultFont", 9, "italic")
        )
        self._ctx_warning.pack(pady=(4, 0))

        # System prompt info
        self._sysprompt_lbl = ttk.Label(parent, text="", foreground="#555")
        self._sysprompt_lbl.pack(pady=2)

        ttk.Separator(parent, orient="horizontal").pack(fill="x", padx=10, pady=8)

        # Notes
        notes = (
            "* Token counts are approximations (1 token ~= 4 chars, Anthropic standard).\n"
            "* Context overhead dominates — MCP resends full conversation history each round-trip.\n"
            "* Claude Desktop Pro plan ($20/mo) = flat fee, no per-token billing.\n"
            "* API pricing: $3.00 / 1M input tokens,  $15.00 / 1M output tokens."
        )
        ttk.Label(parent, text=notes, justify="left",
                  foreground="#555", font=("TkDefaultFont", 8)).pack(anchor="w", padx=14)

    def _build_phase_tab(self, parent):
        cols = ("Phase", "Input Tokens", "Output Tokens", "Total Tokens")
        self._phase_tree = ttk.Treeview(parent, columns=cols, show="headings", height=12)
        for col in cols:
            self._phase_tree.heading(col, text=col)
        self._phase_tree.column("Phase",         width=280, anchor="w")
        self._phase_tree.column("Input Tokens",  width=110, anchor="e")
        self._phase_tree.column("Output Tokens", width=110, anchor="e")
        self._phase_tree.column("Total Tokens",  width=110, anchor="e")
        vsb = ttk.Scrollbar(parent, orient="vertical", command=self._phase_tree.yview)
        self._phase_tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self._phase_tree.pack(fill="both", expand=True, padx=4, pady=4)

        # Totals row info
        self._phase_totals_lbl = ttk.Label(parent, text="", foreground="#555",
                                            font=("Courier New", 9))
        self._phase_totals_lbl.pack(anchor="w", padx=8, pady=2)

    def _build_scenario_tab(self, parent):
        cols = ("Scenario", "Tables", "Recursion Depth", "Total Tokens", "Est. Cost USD")
        self._scenario_tree = ttk.Treeview(parent, columns=cols, show="headings", height=8)
        for col in cols:
            self._scenario_tree.heading(col, text=col)
        self._scenario_tree.column("Scenario",         width=180, anchor="w")
        self._scenario_tree.column("Tables",           width=70,  anchor="center")
        self._scenario_tree.column("Recursion Depth",  width=110, anchor="center")
        self._scenario_tree.column("Total Tokens",     width=110, anchor="e")
        self._scenario_tree.column("Est. Cost USD",    width=110, anchor="e")
        self._scenario_tree.pack(fill="both", expand=True, padx=4, pady=4)

        note = ttk.Label(
            parent,
            text="Scenarios use same SP size but vary table count, recursion depth, and rows.\n"
                 "Current session parameters are highlighted in blue.",
            foreground="#555", font=("TkDefaultFont", 8)
        )
        note.pack(anchor="w", padx=8, pady=4)

    # ── SP Input handling ─────────────────────────────────────────────────────

    def _browse_file(self):
        path = filedialog.askopenfilename(
            title="Select SQL File",
            filetypes=[("SQL files", "*.sql"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            text = pathlib.Path(path).read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            self._status_var.set(f"Error reading file: {e}")
            return
        self._sp_path  = path
        self._sp_text  = text
        self._sp_size_chars = len(text)
        self._file_var.set(pathlib.Path(path).name)
        # Populate editor
        self._sp_editor.delete("1.0", "end")
        self._sp_editor.insert("1.0", text)
        # Auto-detect tables
        found = re.findall(r'\b(?:FROM|JOIN)\s+\S+', text, re.IGNORECASE)
        detected = max(1, len(found))
        self._tables_var.set(detected)
        self._autodetect_var.set(
            f"Auto-detected ~{detected} table reference(s) from FROM/JOIN keywords."
        )
        self._status_var.set(f"Loaded {self._sp_size_chars:,} chars from file.")

    def _clear_sp(self):
        self._sp_text  = ""
        self._sp_path  = ""
        self._sp_size_chars = 0
        self._file_var.set("No file selected")
        self._sp_editor.delete("1.0", "end")
        self._autodetect_var.set("")
        self._status_var.set("")

    def _on_sp_text_change(self, _event=None):
        text = self._sp_editor.get("1.0", "end-1c")
        self._sp_text       = text
        self._sp_size_chars = len(text)
        if text.strip():
            self._file_var.set("(pasted text)")

    # ── Estimation ────────────────────────────────────────────────────────────

    def _run_estimation(self):
        # Read SP text from editor if not loaded from file
        sp_text = self._sp_editor.get("1.0", "end-1c").strip()
        if sp_text:
            self._sp_text       = sp_text
            self._sp_size_chars = len(sp_text)

        sp_chars = self._sp_size_chars if self._sp_size_chars > 0 else 2000

        self._run_btn.config(state="disabled")
        self._status_var.set("Estimating...")

        def _worker():
            try:
                result = run_estimation_data(
                    sp_size_chars    = sp_chars,
                    num_tables       = self._tables_var.get(),
                    recursion_depth  = self._depth_var.get(),
                    rows_per_table   = self._rows_var.get(),
                    num_columns_avg  = self._cols_var.get(),
                )
                self.after(0, lambda: self._populate_results(result, sp_chars))
            except Exception as e:
                self.after(0, lambda: self._status_var.set(f"Error: {e}"))
            finally:
                self.after(0, lambda: self._run_btn.config(state="normal"))

        threading.Thread(target=_worker, daemon=True).start()

    def _populate_results(self, result: dict, sp_chars: int):
        self._last_result = result
        cost = result["cost"]

        # ── Summary cards ─────────────────────────────────────────────────────
        self._card_labels["total_tokens"].config( text=f"{cost['total_tokens']:,}")
        self._card_labels["input_tokens"].config(  text=f"{cost['input_tokens']:,}")
        self._card_labels["output_tokens"].config( text=f"{cost['output_tokens']:,}")
        self._card_labels["total_cost"].config(    text=f"${cost['total_cost_usd']:.4f}")

        ctx_pct = int(result["ctx_overhead"] / max(cost["input_tokens"], 1) * 100)
        self._ctx_warning.config(
            text=f"Context history overhead: {result['ctx_overhead']:,} tokens  "
                 f"({ctx_pct}% of total input) — MCP resends full conversation each round-trip."
        )
        self._sysprompt_lbl.config(
            text=f"System prompt (mcp_instructions.txt): {result['sys_tokens']:,} tokens  "
                 f"— included in every request"
        )

        # ── Phase breakdown ───────────────────────────────────────────────────
        for row in self._phase_tree.get_children():
            self._phase_tree.delete(row)

        for phase, (inp, out) in result["phase_tokens"].items():
            self._phase_tree.insert("", "end", values=(
                phase, f"{inp:,}", f"{out:,}", f"{inp+out:,}"
            ))

        raw_in  = sum(i for i, _ in result["phase_tokens"].values())
        raw_out = sum(o for _, o in result["phase_tokens"].values())
        self._phase_totals_lbl.config(
            text=f"  Phase content subtotal : {raw_in:>9,} input  +  {raw_out:>9,} output  =  {raw_in+raw_out:>9,} tokens\n"
                 f"  Context overhead        : {result['ctx_overhead']:>9,} input  (history resent each round-trip)\n"
                 f"  TOTAL                   : {cost['input_tokens']:>9,} input  +  {cost['output_tokens']:>9,} output  =  {cost['total_tokens']:>9,} tokens"
        )

        # ── Scenarios ─────────────────────────────────────────────────────────
        for row in self._scenario_tree.get_children():
            self._scenario_tree.delete(row)

        for label, tables, depth, tokens, cost_usd in result["scenarios"]:
            self._scenario_tree.insert("", "end", values=(
                label, tables, depth, f"{tokens:,}", f"${cost_usd:.4f}"
            ))

        # ── Raw report ────────────────────────────────────────────────────────
        report = self._build_text_report(result, sp_chars)
        self._raw_output.config(state="normal")
        self._raw_output.delete("1.0", "end")
        self._raw_output.insert("1.0", report)
        self._raw_output.config(state="disabled")

        self._status_var.set(
            f"Done.  Total: {cost['total_tokens']:,} tokens  |  Est. cost: ${cost['total_cost_usd']:.4f} USD"
        )

    def _build_text_report(self, result: dict, sp_chars: int) -> str:
        cost = result["cost"]
        W = 72
        lines = [
            "=" * W,
            "  postgres-mcp  --  Claude Token Consumption Estimator",
            "=" * W,
            "",
            "  SESSION PARAMETERS",
            "  " + "-" * (W - 2),
            f"  SP size              : {sp_chars:,} chars  (~{_chars_to_tokens(sp_chars):,} tokens)",
            f"  Tables referenced    : {self._tables_var.get()}",
            f"  Recursion depth      : {self._depth_var.get()}",
            f"  Rows per table       : {self._rows_var.get()}",
            f"  Avg columns/table    : {self._cols_var.get()}",
            f"  System prompt size   : {result['sys_tokens']:,} tokens  (included in EVERY request)",
            "",
            "  PHASE-BY-PHASE TOKEN BREAKDOWN",
            "  " + "-" * (W - 2),
            f"  {'Phase':<42} {'Input':>7} {'Output':>7} {'Total':>7}",
            "  " + "-" * (W - 2),
        ]
        for phase, (inp, out) in result["phase_tokens"].items():
            lines.append(f"  {phase:<42} {inp:>7,} {out:>7,} {inp+out:>7,}")
        raw_in  = sum(i for i, _ in result["phase_tokens"].values())
        raw_out = sum(o for _, o in result["phase_tokens"].values())
        lines += [
            "  " + "-" * (W - 2),
            f"  {'Subtotal (phase content)':<42} {raw_in:>7,} {raw_out:>7,} {raw_in+raw_out:>7,}",
            f"  {'Context growth overhead':<42} {result['ctx_overhead']:>7,} {'':>7} {result['ctx_overhead']:>7,}",
            "",
            "  TOTAL ESTIMATE",
            "  " + "-" * (W - 2),
            f"  Input tokens   : {cost['input_tokens']:>12,}",
            f"  Output tokens  : {cost['output_tokens']:>12,}",
            f"  TOTAL tokens   : {cost['total_tokens']:>12,}",
            "",
            f"  Input cost     :  ${cost['input_cost_usd']:>9.4f}  (@ $3.00 / 1M tokens)",
            f"  Output cost    :  ${cost['output_cost_usd']:>9.4f}  (@ $15.00 / 1M tokens)",
            f"  >> TOTAL COST  :  ${cost['total_cost_usd']:>9.4f}  USD",
            "",
            "  SCENARIO COMPARISON",
            "  " + "-" * (W - 2),
            f"  {'Scenario':<28} {'Tables':>6} {'Depth':>6} {'Tokens':>9} {'Cost USD':>10}",
            "  " + "-" * (W - 2),
        ]
        for label, tables, depth, tokens, cost_usd in result["scenarios"]:
            lines.append(f"  {label:<28} {tables:>6} {depth:>6} {tokens:>9,} {cost_usd:>9.4f}")
        lines += [
            "  " + "-" * (W - 2),
            "",
            "  NOTES",
            "  * Token counts are approximations (1 token ~= 4 chars).",
            "  * Context overhead dominates for complex SPs with many tables/recursions.",
            "  * Claude Desktop Pro plan ($20/mo) - flat fee, no per-token billing.",
            "  * API pricing: $3.00/1M input, $15.00/1M output (Anthropic API).",
            "",
            "=" * W,
        ]
        return "\n".join(lines)

    # ── Copy ──────────────────────────────────────────────────────────────────

    def _copy_report(self):
        if self._last_result is None:
            self._status_var.set("Nothing to copy — run estimation first.")
            return
        report = self._raw_output.get("1.0", "end-1c")
        self.clipboard_clear()
        self.clipboard_append(report)
        self._status_var.set("Report copied to clipboard.")
