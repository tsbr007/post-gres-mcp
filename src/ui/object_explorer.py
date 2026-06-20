"""Object explorer — hierarchical treeview for schemas, tables, and columns."""
import tkinter as tk
from tkinter import ttk, messagebox


class ObjectExplorer(ttk.Frame):
    def __init__(self, parent, db_conn, on_table_select, **kwargs):
        super().__init__(parent, **kwargs)
        self.db = db_conn
        self.on_table_select = on_table_select
        self._build()

    def _build(self):
        ttk.Label(self, text="Object Explorer", font=("TkDefaultFont", 9, "bold")).pack(
            fill="x", pady=(4, 2), padx=4
        )
        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=4, pady=(0, 2))
        ttk.Button(bar, text="↺ Refresh", command=self.refresh).pack(side="left")

        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True, padx=4)
        self._tree = ttk.Treeview(frame, show="tree", selectmode="browse")
        vsb = ttk.Scrollbar(frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self._tree.pack(fill="both", expand=True)

        self._tree.bind("<<TreeviewOpen>>",   self._on_expand)
        self._tree.bind("<Double-1>",          self._on_double_click)
        self._tree.bind("<Button-3>",          self._on_right_click)

        self._menu = tk.Menu(self._tree, tearoff=False)
        self._menu.add_command(label="📋 Select Top 100", command=self._select_top)
        self._menu.add_command(label="🔑 Show Columns",   command=self._show_columns)

    def refresh(self):
        self._tree.delete(*self._tree.get_children())
        if not self.db.is_connected():
            return
        try:
            from src.schema_inspector import SchemaInspector
            insp = SchemaInspector(self.db.conn)
            for schema in insp.get_schemas():
                s_node = self._tree.insert("", "end", text=f"📁 {schema}",
                                           values=["schema", schema])
                # Tables
                t_node = self._tree.insert(s_node, "end", text="📄 Tables",
                                           values=["tables_header", schema])
                self._tree.insert(t_node, "end", text="Loading…", values=["loading"])
                # Views
                v_node = self._tree.insert(s_node, "end", text="👁 Views",
                                           values=["views_header", schema])
                self._tree.insert(v_node, "end", text="Loading…", values=["loading"])
        except Exception as e:
            messagebox.showerror("Refresh error", str(e))

    def _on_expand(self, event):
        node = self._tree.focus()
        vals = self._tree.item(node, "values")
        if not vals:
            return
        kind, schema = vals[0], vals[1] if len(vals) > 1 else "public"

        children = self._tree.get_children(node)
        if children and self._tree.item(children[0], "text") == "Loading…":
            self._tree.delete(*children)
        else:
            return

        try:
            from src.schema_inspector import SchemaInspector
            insp = SchemaInspector(self.db.conn)
            if kind == "tables_header":
                for tbl in insp.get_tables(schema):
                    t = self._tree.insert(node, "end", text=f"🗃 {tbl}",
                                          values=["table", schema, tbl])
                    self._tree.insert(t, "end", text="…", values=["loading"])
            elif kind == "views_header":
                for vw in insp.get_views(schema):
                    self._tree.insert(node, "end", text=f"👁 {vw}",
                                      values=["view", schema, vw])
            elif kind == "table":
                tbl = vals[2]
                for col in insp.get_columns(schema, tbl):
                    pk_marker = " 🔑" if col["name"] in insp.get_primary_keys(schema, tbl) else ""
                    null_info = "" if col["nullable"] else " NOT NULL"
                    label = f"  {col['name']} ({col['data_type']}{null_info}){pk_marker}"
                    self._tree.insert(node, "end", text=label, values=["column"])
        except Exception as e:
            self._tree.insert(node, "end", text=f"Error: {e}", values=["error"])

    def _on_double_click(self, event):
        node = self._tree.focus()
        vals = self._tree.item(node, "values")
        if vals and vals[0] == "table":
            _, schema, table = vals[0], vals[1], vals[2]
            sql = f'SELECT * FROM "{schema}"."{table}" LIMIT 100;'
            self.on_table_select(sql)

    def _on_right_click(self, event):
        row = self._tree.identify_row(event.y)
        if row:
            self._tree.selection_set(row)
            self._tree.focus(row)
            vals = self._tree.item(row, "values")
            if vals and vals[0] == "table":
                self._menu.post(event.x_root, event.y_root)

    def _select_top(self):
        node = self._tree.focus()
        vals = self._tree.item(node, "values")
        if vals and vals[0] == "table":
            sql = f'SELECT * FROM "{vals[1]}"."{vals[2]}" LIMIT 100;'
            self.on_table_select(sql)

    def _show_columns(self):
        node = self._tree.focus()
        vals = self._tree.item(node, "values")
        if vals and vals[0] == "table":
            sql = (
                f"SELECT column_name, data_type, is_nullable, column_default "
                f"FROM information_schema.columns "
                f"WHERE table_schema='{vals[1]}' AND table_name='{vals[2]}' "
                f"ORDER BY ordinal_position;"
            )
            self.on_table_select(sql)
