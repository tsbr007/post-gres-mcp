# PostgreSQL Manager + MCP Server — AI Cookbook

> **Audience**: AI agents continuing development on this project.

---

## 1. Project Intent

Dual-mode PostgreSQL developer tool:

| Mode | Entry Point | User |
|---|---|---|
| **Desktop GUI** | `main.py` | Human — Tkinter window |
| **MCP Server** | `mcp_server.py` | AI agent (Claude Desktop, Cursor) |

**Core problem**: SPs fail because referenced tables are empty or have wrong data.
This tool discovers what data is needed and creates it — including recursive SQL chains
where DB columns store SQL strings that must also be executed.

---

## 2. Project Structure

```
postgres-mcp/
├── main.py                    ← Tkinter UI entry point
├── mcp_server.py              ← MCP server entry point
├── config.ini                 ← Connection profiles + app settings
├── requirements.txt           ← Dependencies
├── install.bat                ← Windows setup script
├── run.bat                    ← Windows run script
├── claude_desktop_config.json ← Claude Desktop registration
├── COOKBOOK.md                 ← This file
├── README.md                  ← User-facing documentation
└── src/
    ├── __init__.py
    ├── config_manager.py       ← ConfigParser wrapper for config.ini
    ├── db_connection.py        ← psycopg2 wrapper; main + test-tx connections
    ├── sql_parser.py           ← Static regex/sqlparse SP analysis
    ├── schema_inspector.py     ← Live PG introspection (PKs, FKs, enums, CHECKs)
    ├── test_data_generator.py  ← Faker-based row generator
    ├── pg_mcp.py               ← FastMCP server: 18 tools
    └── ui/
        ├── __init__.py
        ├── connection_panel.py ← Profile list + connect form
        ├── object_explorer.py  ← Schema/table/column treeview
        ├── query_editor.py     ← SQL editor with highlighting + F5
        ├── result_grid.py      ← Results Treeview + CSV export
        ├── sp_analyzer_panel.py← Upload SQL → analyse → preview → insert
        └── status_bar.py       ← Connection indicator
```

---

## 3. Key Architecture Decisions

| Decision | Why |
|---|---|
| **Two psycopg2 connections** | Test tx stays open while main conn runs SP queries |
| **Manual rollback (not auto)** | User may run SP multiple times before deciding |
| **Static parser + MCP** | Parser is fast (no DB); MCP handles recursive dynamic SQL |
| **FastMCP stdio transport** | Standard for Claude Desktop; no port/auth needed |
| **`graphlib.TopologicalSorter`** | Stdlib FK ordering; no extra dependency |
| **`mcp>=1.27,<2` pin** | v2 is alpha with breaking changes |
| **Plain text passwords** | User's explicit choice; keyring extension documented below |

---

## 4. Module Details

### `src/db_connection.py`
Two connections:
```
self.conn    → autocommit=True   ← reads + DDL
self._tx     → autocommit=False  ← test data inserts (separate connection)
```

### `src/sql_parser.py`
Pipeline: `_extract_body()` → `_extract_selects()` → `_tables_from_sql()` → `_conditions_from_sql()`
**Limitation**: Cannot handle dynamic SQL, nested SP calls, or SQL in DB column values.

### `src/test_data_generator.py`
Per-column logic:
1. Serial PK → skip (DB auto-assigns)
2. FK → `_pick_fk_value()` from parent table
3. Enum → `get_enum_values()` → random choice
4. Generate by data_type → apply WHERE condition override → UNIQUE retry

### `src/pg_mcp.py` — 18 MCP Tools
```
CONNECTION:   connect_to_postgres, get_connection_status
SP DISCOVERY: get_sp_body, list_sps
OBJECTS:      list_tables, list_views, get_view_definition
SCHEMA:       get_table_schema, get_fk_reference_values, get_enum_values, sample_table_data
SQL EXEC:     execute_query (reads), execute_in_transaction (writes in tx)
TEST DATA:    generate_test_data, begin_test_transaction, insert_rows,
              commit_test_data, rollback_test_data, transaction_status
```

---

## 5. Recursive SQL Chain (MCP Flow)

```
Claude: get_sp_body('public', 'process_order')
  → finds: "SELECT cfg_sql FROM sp_config WHERE proc='process_order'"
Claude: execute_query("SELECT cfg_sql FROM sp_config WHERE ...")
  → returns [{cfg_sql: "DELETE FROM temp; INSERT INTO orders SELECT ..."}]
Claude: recognises SQL in cfg_sql value
Claude: execute_in_transaction("DELETE FROM temp")
Claude: execute_in_transaction("INSERT INTO orders SELECT ...")
  → recurses until no more SQL strings found
Claude: get_table_schema, get_fk_reference_values for each table
Claude: begin_test_transaction() → insert_rows() per table
Claude: "Run your SP now. Say commit or rollback."
```

---

## 6. Known Limitations

| Area | Limitation | Fix Path |
|---|---|---|
| SQL Parser | No `EXECUTE var` support | Use MCP recursive approach |
| SQL Parser | No nested SP call resolution | Add `get_sp_body` chaining |
| Generator | No inter-row constraints (end > start) | Custom generator registry |
| Generator | No array/JSONB intelligence | Detect array UDTs |
| Generator | Composite PKs generated independently | Multi-column PK handler |
| MCP Server | State lost on restart | Add state persistence |
| GUI | Long queries block UI thread | Use `threading.Thread` |

---

## 7. Extension Points

### Adding an MCP tool
```python
# In src/pg_mcp.py:
@mcp.tool()
def my_tool(param: str) -> str:
    """Docstring = tool description shown to AI."""
    conn = _require_conn()
    # ...
    return json.dumps(result)
```

### Adding a data type to generator
```python
# In src/test_data_generator.py:
_MY_TYPES = {"mytype"}
# In _value_for_type():
if dt in _MY_TYPES:
    return my_generator()
```

### Adding keyring password storage
```python
# In config_manager.py save_profile():
import keyring
keyring.set_password("postgres-mcp", section, data.pop("password"))
```

---

## 8. File Safety Matrix

| File | Safe? | Notes |
|---|---|---|
| `src/pg_mcp.py` | ✅ | Add tools; don't rename existing ones |
| `src/test_data_generator.py` | ✅ | Add types; keep return format |
| `src/schema_inspector.py` | ✅ | Add queries; keep signatures |
| `src/sql_parser.py` | ✅ | Improve regex; keep `analyse_sql_file()` |
| `src/db_connection.py` | ⚠️ | Used by both GUI and MCP |
| `config.ini` | ✅ | Keep `[app]` section |

---

## 9. Key PostgreSQL Queries

```sql
-- SP body from pg_proc
SELECT pg_get_functiondef(p.oid) FROM pg_proc p
JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = $1 AND p.proname = $2;

-- View definition
SELECT pg_get_viewdef($1, true);

-- Enum values
SELECT e.enumlabel FROM pg_type t
JOIN pg_enum e ON t.oid = e.enumtypid WHERE t.typname = $1;

-- Sequence next value
SELECT nextval(pg_get_serial_sequence($1, $2));
```
