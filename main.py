"""
PostgreSQL Manager — Entry Point
"""
import sys
import os

# Windows DPI awareness for crisp text
if sys.platform == "win32":
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.app import PostgresManagerApp

if __name__ == "__main__":
    app = PostgresManagerApp()
    app.mainloop()
