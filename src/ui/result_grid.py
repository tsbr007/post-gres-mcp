"""Result grid — scrollable Treeview for query results with CSV export."""
import csv
import tkinter as tk
from tkinter import ttk, filedialog, messagebox


class ResultGrid(ttk.Frame):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self._build()

    def _build(self):
        # Toolbar
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 2))
        self._info_lbl = ttk.Label(bar, text="No results", anchor="w")
        self._info_lbl.pack(side="left", padx=4)
        ttk.Button(bar, text="⬇ Export CSV", command=self._export_csv).pack(side="right", padx=4)

        # Treeview + scrollbars
        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True)
        self._tree = ttk.Treeview(frame, show="headings", selectmode="extended")
        vsb = ttk.Scrollbar(frame, orient="vertical",   command=self._tree.yview)
        hsb = ttk.Scrollbar(frame, orient="horizontal", command=self._tree.xview)
        self._tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        vsb.pack(side="right", fill="y")
        hsb.pack(side="bottom", fill="x")
        self._tree.pack(fill="both", expand=True)
        self._columns: list[str] = []

    def display(self, result: dict):
        self._columns = result.get("columns", [])
        rows = result.get("rows", [])

        # Clear
        self._tree.delete(*self._tree.get_children())
        self._tree["columns"] = self._columns
        for col in self._columns:
            self._tree.heading(col, text=col)
            self._tree.column(col, width=120, minwidth=60, stretch=True)

        for row in rows:
            values = [str(row.get(c, "")) for c in self._columns]
            self._tree.insert("", "end", values=values)

        msg = result.get("message")
        if msg:
            self._info_lbl.config(text=msg)
        else:
            elapsed = result.get("elapsed", 0)
            self._info_lbl.config(
                text=f"{len(rows)} row(s) — {elapsed:.3f}s"
            )

    def show_error(self, err: str):
        self._tree.delete(*self._tree.get_children())
        self._tree["columns"] = ["Error"]
        self._tree.heading("Error", text="Error")
        self._tree.column("Error", width=800)
        self._tree.insert("", "end", values=[err])
        self._info_lbl.config(text="Query failed")

    def _export_csv(self):
        if not self._columns:
            messagebox.showinfo("Export", "No data to export.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            title="Save results as CSV",
        )
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(self._columns)
                for iid in self._tree.get_children():
                    writer.writerow(self._tree.item(iid, "values"))
            messagebox.showinfo("Export", f"Saved to:\n{path}")
        except Exception as e:
            messagebox.showerror("Export failed", str(e))
