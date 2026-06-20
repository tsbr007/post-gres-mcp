"""
PostgreSQL MCP Server — built with Anthropic's FastMCP Python SDK.

This server exposes a rich set of PostgreSQL tools to any MCP-compatible
AI client (Claude Desktop, Cursor, etc.).  The AI drives all reasoning:
  - it reads SP bodies from pg_proc
  - executes SELECT queries and inspects column values for embedded SQL
  - recurses into those embedded SQL strings (SELECT / INSERT / DELETE)
  - understands schema, FK parents, enums, CHECK constraints
  - generates and inserts test data inside a safe transaction
  - waits for the user to run their SP, then commits or rolls back on demand

Run:
    python mcp_server.py                   # uses config.ini default profile
    python mcp_server.py --profile staging # uses [profile_staging] from config.ini
    python mcp_server.py --dsn "postgresql://user:pass@host/db"

Register with Claude Desktop (~/.claude/claude_desktop_config.json):
    {
      "mcpServers": {
        "postgres-mcp": {
          "command": "python",
          "args": ["C:/Balaji/MyProjects/postgres-mcp/mcp_server.py"],
          "cwd": "C:/Balaji/MyProjects/postgres-mcp"
        }
      }
    }
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.pg_mcp import run_server

if __name__ == "__main__":
    run_server(sys.argv[1:])
