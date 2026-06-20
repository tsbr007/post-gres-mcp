"""Status bar — bottom strip showing connection state."""
import tkinter as tk
from tkinter import ttk


class StatusBar(ttk.Frame):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, relief="sunken", **kwargs)
        self._lbl = ttk.Label(self, text="Not connected", anchor="w", padding=(6, 2))
        self._lbl.pack(side="left", fill="x", expand=True)
        self._indicator = ttk.Label(self, text="●", foreground="#cc3333", padding=(4, 2))
        self._indicator.pack(side="right")

    def set_connected(self, info: str):
        self._lbl.config(text=f"  Connected — {info}")
        self._indicator.config(foreground="#27ae60")

    def set_disconnected(self):
        self._lbl.config(text="  Not connected")
        self._indicator.config(foreground="#cc3333")

    def set_message(self, msg: str):
        self._lbl.config(text=f"  {msg}")
