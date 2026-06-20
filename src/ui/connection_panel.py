"""Connection panel — manage and activate named connection profiles."""
import tkinter as tk
from tkinter import ttk, messagebox


class ConnectionPanel(ttk.Frame):
    def __init__(self, parent, config_mgr, db_conn, on_connect, on_disconnect, **kwargs):
        super().__init__(parent, **kwargs)
        self.cfg   = config_mgr
        self.db    = db_conn
        self.on_connect    = on_connect
        self.on_disconnect = on_disconnect
        self._current_section = None
        self._build()
        self._refresh_list()

    def _build(self):
        ttk.Label(self, text="Connection Profiles", font=("TkDefaultFont", 10, "bold")).pack(
            fill="x", pady=(6, 2), padx=6
        )

        # Profile list
        lf = ttk.Frame(self)
        lf.pack(fill="x", padx=6)
        self._listbox = tk.Listbox(lf, height=6, exportselection=False,
                                   selectbackground="#4a90d9", selectforeground="white")
        self._listbox.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(lf, command=self._listbox.yview)
        sb.pack(side="right", fill="y")
        self._listbox.config(yscrollcommand=sb.set)
        self._listbox.bind("<<ListboxSelect>>", self._on_profile_select)

        # Profile buttons
        pbf = ttk.Frame(self)
        pbf.pack(fill="x", padx=6, pady=2)
        ttk.Button(pbf, text="＋ New",    command=self._new_profile).pack(side="left")
        ttk.Button(pbf, text="✕ Delete", command=self._delete_profile).pack(side="left", padx=2)

        ttk.Separator(self).pack(fill="x", padx=6, pady=4)

        # Form fields
        fields = [
            ("Profile Name", "name"), ("Host",     "host"),
            ("Port",         "port"), ("Database", "database"),
            ("Username",     "username"), ("Password", "password"),
            ("SSL Mode",     "ssl_mode"),
        ]
        self._vars: dict[str, tk.StringVar] = {}
        form = ttk.Frame(self)
        form.pack(fill="x", padx=6)
        for row_i, (label, key) in enumerate(fields):
            ttk.Label(form, text=label + ":").grid(row=row_i, column=0, sticky="w", pady=2)
            var = tk.StringVar()
            self._vars[key] = var
            show = "*" if key == "password" else ""
            ttk.Entry(form, textvariable=var, show=show, width=22).grid(
                row=row_i, column=1, sticky="ew", padx=(4, 0), pady=2
            )
        form.columnconfigure(1, weight=1)

        # Action buttons
        abf = ttk.Frame(self)
        abf.pack(fill="x", padx=6, pady=6)
        ttk.Button(abf, text="💾 Save",        command=self._save_profile).pack(fill="x", pady=1)
        ttk.Button(abf, text="🔍 Test",        command=self._test_conn).pack(fill="x", pady=1)
        ttk.Button(abf, text="⚡ Connect",     command=self._connect).pack(fill="x", pady=1)
        ttk.Button(abf, text="⏹ Disconnect",  command=self._disconnect).pack(fill="x", pady=1)

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _refresh_list(self):
        self._profiles = self.cfg.get_profiles()
        self._listbox.delete(0, "end")
        self._sections = list(self._profiles.keys())
        for sec in self._sections:
            self._listbox.insert("end", self._profiles[sec]["name"])

    def _load_profile_to_form(self, section):
        p = self._profiles[section]
        for key, var in self._vars.items():
            var.set(p.get(key, ""))
        self._current_section = section

    def _form_to_dict(self):
        return {k: v.get() for k, v in self._vars.items()}

    def _on_profile_select(self, _event=None):
        sel = self._listbox.curselection()
        if sel:
            self._load_profile_to_form(self._sections[sel[0]])

    # ── Button handlers ────────────────────────────────────────────────────────

    def _new_profile(self):
        section = self.cfg.new_section_key()
        for key, var in self._vars.items():
            var.set("" if key not in ("host", "port", "ssl_mode") else
                    {"host": "localhost", "port": "5432", "ssl_mode": "prefer"}[key])
        self._current_section = section

    def _save_profile(self):
        if not self._current_section:
            self._current_section = self.cfg.new_section_key()
        self.cfg.save_profile(self._current_section, self._form_to_dict())
        self._refresh_list()
        messagebox.showinfo("Saved", "Profile saved.")

    def _delete_profile(self):
        if not self._current_section:
            return
        if messagebox.askyesno("Delete", "Delete this profile?"):
            self.cfg.delete_profile(self._current_section)
            self._current_section = None
            self._refresh_list()
            for v in self._vars.values():
                v.set("")

    def _test_conn(self):
        ok, msg = self.db.test_connection(self._form_to_dict())
        (messagebox.showinfo if ok else messagebox.showerror)("Test Connection", msg)

    def _connect(self):
        profile = self._form_to_dict()
        try:
            self.db.connect(profile)
            self.on_connect(profile)
        except Exception as e:
            messagebox.showerror("Connection Error", str(e))

    def _disconnect(self):
        self.db.disconnect()
        self.on_disconnect()
