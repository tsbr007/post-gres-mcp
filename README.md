# PostgreSQL Manager + MCP Server

A complete Python application for PostgreSQL database management with two modes:
- **Desktop GUI** (Tkinter) — for direct human use
- **MCP Server** — for AI-assisted database analysis via Claude Desktop

## What It Does

### 🔌 Connection Management
- Save multiple named PostgreSQL connection profiles in `config.ini`
- Test connections before saving
- Fields: host, port, database, username, password, SSL mode

### 🌲 Object Explorer
- Browse: Schemas → Tables → Columns (with types, nullability, PK markers)
- Browse: Schemas → Views
- Double-click a table → auto-generates `SELECT * FROM ... LIMIT 100`
- Right-click → Select Top 100, Show Columns

### 📝 SQL Query Editor
- Syntax highlighting for SQL keywords
- Press **F5** to execute (or click Run)
- Query history (session-based, navigate with ↑/↓ buttons)
- Select specific text to run only that portion

### 📊 Results Grid
- Scrollable table with column headers
- Row count + elapsed time display
- **Export to CSV** with one click

### 🧪 SP Analyzer + Test Data Generator
Upload a `.sql` file containing a stored procedure or function:
1. **Analyse** — extracts SELECT queries, detects referenced tables, infers WHERE conditions
2. **Generate Preview** — creates Faker-based test data respecting types, FKs, enums, UNIQUE
3. **Insert Test Data** — inserts into an open transaction (NOT committed)
4. **Run your SP** manually in the query editor to verify
5. **Commit** or **Rollback** — on-demand, manual control

### 🤖 MCP Server (AI-Powered Mode)
When connected to Claude Desktop, Claude can:
- Fetch SP bodies directly from `pg_proc`
- Execute SELECT queries found in the SP
- **Recursively follow SQL strings stored inside DB column values** (the killer feature)
- Understand schema, FKs, enums, CHECK constraints
- Generate and insert test data in FK-dependency order
- Wait for you to verify, then commit or rollback

---

## Prerequisites

### Mandatory
| Requirement | Version | Check Command |
|---|---|---|
| **Python** | 3.10+ | `python --version` |
| **pip** | any | `pip --version` |
| **PostgreSQL** | 10+ (any server) | `psql --version` |

### Optional (for MCP mode)
| Requirement | Purpose |
|---|---|
| **Claude Desktop** | AI client that connects to our MCP server |

> ⚠️ Python must be in your system PATH. Run `python --version` in a terminal to verify.

---

## Installation

### Option 1: Run the installer script (Windows)
```cmd
install.bat
```
This checks for Python, creates a virtual environment, and installs all dependencies.

### Option 2: Manual
```powershell
pip install -r requirements.txt
```

Dependencies installed:
- `psycopg2-binary` — PostgreSQL driver
- `sqlparse` — SQL statement parser
- `Faker` — realistic test data generation
- `mcp[cli]` — Anthropic's MCP SDK for the AI server

---

## Running the Application

### Desktop GUI
```cmd
run.bat
```
Or manually:
```powershell
python main.py
```

### MCP Server (for Claude Desktop)
```powershell
python mcp_server.py
```

With auto-connect:
```powershell
python mcp_server.py --host localhost --port 5432 --db mydb --user postgres --password secret
python mcp_server.py --profile local
python mcp_server.py --dsn "postgresql://user:pass@host:5432/db"
```

---

## Configuring Claude Desktop

1. Copy `claude_desktop_config.json` to `%APPDATA%\Claude\claude_desktop_config.json`
   (or merge into your existing config)
2. Restart Claude Desktop
3. The `postgres-mcp` tools will appear automatically

Example config:
```json
{
  "mcpServers": {
    "postgres-mcp": {
      "command": "python",
      "args": ["C:/Balaji/MyProjects/postgres-mcp/mcp_server.py"],
      "cwd": "C:/Balaji/MyProjects/postgres-mcp"
    }
  }
}
```

---

## Configuration — `config.ini`

```ini
[app]
theme = clam
font_size = 11
row_limit = 1000
default_test_rows = 10

[profile_local]
name = Local PostgreSQL
host = localhost
port = 5432
database = postgres
username = postgres
password =
ssl_mode = prefer
```

Add more profiles by duplicating the `[profile_xxx]` section with a unique name.

---

## MCP Tools Reference

| Tool | Description |
|---|---|
| `connect_to_postgres` | Connect with host/port/db/user/password |
| `get_connection_status` | Check if connected |
| `get_sp_body` | Fetch SP/function source from pg_proc |
| `list_sps` | List all SPs/functions in a schema |
| `list_tables` | List base tables |
| `list_views` | List views |
| `get_view_definition` | Get view SQL (discover real tables behind views) |
| `get_table_schema` | Full metadata: columns, PKs, FKs, UNIQUEs, CHECKs |
| `get_fk_reference_values` | Read valid values from FK parent tables |
| `get_enum_values` | List valid enum labels |
| `sample_table_data` | Sample existing rows |
| `execute_query` | Run any SELECT/read SQL |
| `execute_in_transaction` | Run INSERT/UPDATE/DELETE inside safe test tx |
| `generate_test_data` | Faker-based row generation |
| `begin_test_transaction` | Open a write transaction |
| `insert_rows` | Insert row dicts into the open transaction |
| `commit_test_data` | Commit permanently |
| `rollback_test_data` | Roll back all test inserts |
| `transaction_status` | Check if a test transaction is open |

---

## Troubleshooting

| Issue | Solution |
|---|---|
| `python` not found | Add Python to system PATH |
| `psycopg2` install fails | Install Visual C++ Build Tools, or use `psycopg2-binary` (already in requirements) |
| MCP server not showing in Claude | Check `%APPDATA%\Claude\claude_desktop_config.json` path is correct |
| Connection refused | Verify PostgreSQL is running and accepting connections on the configured host:port |
| `ModuleNotFoundError: mcp` | Run `pip install "mcp[cli]>=1.27,<2"` |

---

## License

MIT
