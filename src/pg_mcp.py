"""
PostgreSQL MCP Server — FastMCP tool definitions.

Tools exposed to the AI agent:
  DB connection
    connect_to_postgres        Connect using DSN or profile from config.ini
    get_connection_status      Check if connected

  Exploration (AI uses these to understand the SP and its dependencies)
    get_sp_body                Fetch SP / function source from pg_proc by name
    list_sps                   List all SPs / functions in a schema
    list_tables                List base tables in a schema
    list_views                 List views in a schema
    get_view_definition        Get the SQL definition of a view (expands view deps)
    get_table_schema           Columns, types, PKs, FKs, unique, CHECK constraints
    get_fk_reference_values    Read actual valid values from a FK parent table
    get_enum_values            List valid enum labels for a type
    sample_table_data          Sample existing rows from any table

  SQL execution (AI calls these recursively when it finds SQL inside column values)
    execute_query              Run any SELECT / read query — returns rows as JSON
    execute_in_transaction     Run INSERT / UPDATE / DELETE inside the test transaction
                               (safe — always rolled back unless commit is called)

  Test data management
    generate_test_data         Faker-based row generation for given tables + conditions
    begin_test_transaction     Open a write transaction for all test inserts
    insert_rows                Insert a list of row dicts into the open transaction
    commit_test_data           Commit the transaction permanently
    rollback_test_data         Roll back all inserts — manual, on-demand
    transaction_status         Check whether a test transaction is currently open
"""

import json
import argparse
import asyncio
import sys
import os
import time
import re
import pathlib
from typing import Any


# ── Load system instructions from external text file ──────────────────────────

def _load_instructions() -> str:
    """
    Load the MCP system instructions from mcp_instructions.txt located in the
    same directory as this file.  Falls back to a short inline string when the
    file cannot be found, so the server always starts.
    """
    instructions_path = pathlib.Path(__file__).parent / "mcp_instructions.txt"
    try:
        return instructions_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return (
            "You are a PostgreSQL expert assistant. Use the provided MCP tools "
            "to analyse stored procedures, trace recursive SQL chains, generate "
            "constraint-safe test data with Faker, and manage a test transaction "
            "lifecycle (begin / insert / commit or rollback). "
            "Never commit without explicit operator approval. "
            f"[WARNING: {instructions_path} not found — using fallback instructions.]"
        )

import psycopg2
import psycopg2.extras

from mcp.server.fastmcp import FastMCP

# ── shared state (this process is single-client stdio) ────────────────────────
_conn: psycopg2.extensions.connection | None = None   # main read connection
_tx:   psycopg2.extensions.connection | None = None   # open test transaction
_tx_rows_inserted: int = 0
_default_schema: str = "public"   # set from profile/args on connect


# ── FastMCP server instance ────────────────────────────────────────────────────
mcp = FastMCP(
    "postgres-mcp",
    instructions=_load_instructions(),
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _require_conn() -> psycopg2.extensions.connection:
    if _conn is None or _conn.closed:
        raise RuntimeError(
            "Not connected to any PostgreSQL database. "
            "Call connect_to_postgres first."
        )
    return _conn


def _require_tx() -> psycopg2.extensions.connection:
    if _tx is None or _tx.closed:
        raise RuntimeError(
            "No test transaction is open. Call begin_test_transaction() first."
        )
    return _tx


def _rows_to_json(cur) -> str:
    """Serialize cursor results to a compact JSON string."""
    if cur.description is None:
        return json.dumps({"affected": cur.rowcount})
    cols = [d[0] for d in cur.description]
    rows = []
    for row in cur.fetchall():
        record = {}
        for col, val in zip(cols, row):
            # Make non-serialisable types (dates, Decimals, etc.) into strings
            if hasattr(val, "isoformat"):
                val = val.isoformat()
            elif not isinstance(val, (str, int, float, bool, type(None))):
                val = str(val)
            record[col] = val
        rows.append(record)
    return json.dumps({"columns": cols, "rows": rows, "count": len(rows)}, indent=2)


def _connect_dsn(dsn: str) -> None:
    global _conn
    if _conn and not _conn.closed:
        _conn.close()
    _conn = psycopg2.connect(dsn, connect_timeout=10)
    _conn.autocommit = True


def _connect_profile(profile: dict) -> None:
    global _conn, _default_schema
    if _conn and not _conn.closed:
        _conn.close()
    _conn = psycopg2.connect(
        host=profile["host"], port=int(profile["port"]),
        database=profile["database"], user=profile["username"],
        password=profile["password"],
        sslmode=profile.get("ssl_mode", "prefer"),
        connect_timeout=10,
    )
    _conn.autocommit = True
    _default_schema = profile.get("schema", "public")


# ── Connection tools ──────────────────────────────────────────────────────────

@mcp.tool()
def connect_to_postgres(
    host: str = "localhost",
    port: int = 5432,
    database: str = "postgres",
    username: str = "postgres",
    password: str = "",
    ssl_mode: str = "prefer",
    schema: str = "public",
) -> str:
    """
    Connect to a PostgreSQL database.
    'schema' sets the default schema used by list_sps, list_tables, list_views, etc.
    Returns server version on success.
    """
    global _conn
    try:
        _connect_profile({
            "host": host, "port": str(port), "database": database,
            "username": username, "password": password,
            "ssl_mode": ssl_mode, "schema": schema,
        })
        with _conn.cursor() as cur:
            cur.execute("SELECT version();")
            ver = cur.fetchone()[0]
        return f"Connected. Default schema: '{_default_schema}'. {ver}"
    except Exception as e:
        return f"ERROR: {e}"


@mcp.tool()
def get_connection_status() -> str:
    """Return whether a database connection is currently open, including the default schema."""
    if _conn and not _conn.closed:
        try:
            with _conn.cursor() as cur:
                cur.execute("SELECT current_database(), current_user, inet_server_addr(), inet_server_port();")
                db, user, addr, port = cur.fetchone()
            return f"Connected — db={db}, user={user}, server={addr}:{port}, schema={_default_schema}"
        except Exception:
            pass
    return "Not connected."


# ── SP / Function exploration ─────────────────────────────────────────────────

@mcp.tool()
def get_sp_body(schema: str, name: str) -> str:
    """
    Fetch the full source code of a stored procedure or function from pg_proc.
    Returns the CREATE OR REPLACE FUNCTION/PROCEDURE statement including the body.
    Use this as the starting point for SP analysis.
    """
    conn = _require_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT pg_get_functiondef(p.oid)
                FROM pg_proc p
                JOIN pg_namespace n ON n.oid = p.pronamespace
                WHERE n.nspname = %s AND p.proname = %s
                ORDER BY p.oid
                """,
                (schema, name),
            )
            rows = cur.fetchall()
            if not rows:
                return f"No SP/function named '{name}' found in schema '{schema}'."
            # Return all overloads if there are multiple
            return "\n\n-- OVERLOAD --\n\n".join(r[0] for r in rows)
    except Exception as e:
        return f"ERROR: {e}"


@mcp.tool()
def list_sps(schema: str = "public") -> str:
    """
    List all stored procedures and functions in the given schema.
    Returns JSON with name, kind (function/procedure), return type, language.
    """
    conn = _require_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT p.proname AS name,
                       CASE p.prokind WHEN 'f' THEN 'function'
                                      WHEN 'p' THEN 'procedure'
                                      ELSE 'other' END AS kind,
                       pg_get_function_result(p.oid) AS return_type,
                       l.lanname AS language
                FROM pg_proc p
                JOIN pg_namespace n ON n.oid = p.pronamespace
                JOIN pg_language l  ON l.oid = p.prolang
                WHERE n.nspname = %s
                ORDER BY p.proname
                """,
                (schema,),
            )
            return _rows_to_json(cur)
    except Exception as e:
        return f"ERROR: {e}"


@mcp.tool()
def list_tables(schema: str = "public") -> str:
    """List all base tables in a schema."""
    conn = _require_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema=%s AND table_type='BASE TABLE' ORDER BY table_name",
                (schema,),
            )
            return _rows_to_json(cur)
    except Exception as e:
        return f"ERROR: {e}"


@mcp.tool()
def list_views(schema: str = "public") -> str:
    """List all views in a schema."""
    conn = _require_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT table_name FROM information_schema.views "
                "WHERE table_schema=%s ORDER BY table_name",
                (schema,),
            )
            return _rows_to_json(cur)
    except Exception as e:
        return f"ERROR: {e}"


@mcp.tool()
def get_view_definition(schema: str, view_name: str) -> str:
    """
    Return the SQL definition of a view.
    Use this when the SP references a view — inspect the view definition to
    discover the underlying real tables that need test data.
    """
    conn = _require_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT pg_get_viewdef(%s, true)",
                (f"{schema}.{view_name}",),
            )
            row = cur.fetchone()
            if row:
                return row[0]
            return f"View '{schema}.{view_name}' not found."
    except Exception as e:
        return f"ERROR: {e}"


@mcp.tool()
def get_table_schema(schema: str, table: str) -> str:
    """
    Return full schema metadata for a table:
    - Columns (name, data_type, nullable, default)
    - Primary keys
    - Foreign keys (with referenced table/column)
    - Unique constraints
    - CHECK constraints
    Use this before generating test data for the table.
    """
    conn = _require_conn()
    try:
        result: dict[str, Any] = {"schema": schema, "table": table}

        with conn.cursor() as cur:
            # Columns
            cur.execute(
                """
                SELECT column_name, data_type, udt_name, is_nullable,
                       column_default, character_maximum_length,
                       numeric_precision, numeric_scale
                FROM information_schema.columns
                WHERE table_schema=%s AND table_name=%s
                ORDER BY ordinal_position
                """,
                (schema, table),
            )
            result["columns"] = [
                {
                    "name": r[0], "data_type": r[1], "udt_name": r[2],
                    "nullable": r[3] == "YES", "default": r[4],
                    "max_length": r[5], "precision": r[6], "scale": r[7],
                }
                for r in cur.fetchall()
            ]

            # Primary keys
            cur.execute(
                """
                SELECT kcu.column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                  ON tc.constraint_name=kcu.constraint_name AND tc.table_schema=kcu.table_schema
                WHERE tc.constraint_type='PRIMARY KEY' AND tc.table_schema=%s AND tc.table_name=%s
                ORDER BY kcu.ordinal_position
                """,
                (schema, table),
            )
            result["primary_keys"] = [r[0] for r in cur.fetchall()]

            # Foreign keys
            cur.execute(
                """
                SELECT kcu.column_name,
                       ccu.table_schema, ccu.table_name, ccu.column_name AS ref_col
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                  ON tc.constraint_name=kcu.constraint_name AND tc.table_schema=kcu.table_schema
                JOIN information_schema.constraint_column_usage ccu
                  ON ccu.constraint_name=tc.constraint_name
                WHERE tc.constraint_type='FOREIGN KEY' AND tc.table_schema=%s AND tc.table_name=%s
                """,
                (schema, table),
            )
            result["foreign_keys"] = [
                {"column": r[0], "ref_schema": r[1], "ref_table": r[2], "ref_column": r[3]}
                for r in cur.fetchall()
            ]

            # Unique constraints
            cur.execute(
                """
                SELECT kcu.column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                  ON tc.constraint_name=kcu.constraint_name AND tc.table_schema=kcu.table_schema
                WHERE tc.constraint_type='UNIQUE' AND tc.table_schema=%s AND tc.table_name=%s
                """,
                (schema, table),
            )
            result["unique_columns"] = [r[0] for r in cur.fetchall()]

            # CHECK constraints
            cur.execute(
                """
                SELECT cc.constraint_name, cc.check_clause
                FROM information_schema.check_constraints cc
                JOIN information_schema.constraint_table_usage ctu
                  ON cc.constraint_name=ctu.constraint_name
                WHERE ctu.table_schema=%s AND ctu.table_name=%s
                  AND cc.check_clause NOT LIKE '%%IS NOT NULL%%'
                """,
                (schema, table),
            )
            result["check_constraints"] = [
                {"name": r[0], "clause": r[1]} for r in cur.fetchall()
            ]

        return json.dumps(result, indent=2)
    except Exception as e:
        return f"ERROR: {e}"


@mcp.tool()
def get_fk_reference_values(
    ref_schema: str,
    ref_table: str,
    ref_column: str,
    limit: int = 20,
) -> str:
    """
    Read actual existing values from a parent/lookup table for a FK column.
    Use this to pick valid FK values when generating test data for child tables.
    Returns distinct values from the referenced column.
    """
    conn = _require_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f'SELECT DISTINCT "{ref_column}" FROM "{ref_schema}"."{ref_table}" '
                f'ORDER BY "{ref_column}" LIMIT %s',
                (limit,),
            )
            return _rows_to_json(cur)
    except Exception as e:
        return f"ERROR: {e}"


@mcp.tool()
def get_enum_values(type_name: str) -> str:
    """
    Return all valid labels for a PostgreSQL ENUM type.
    Use this when a column data_type is 'USER-DEFINED' — check udt_name against this.
    """
    conn = _require_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT e.enumlabel
                FROM pg_type t
                JOIN pg_enum e ON t.oid = e.enumtypid
                WHERE t.typname = %s
                ORDER BY e.enumsortorder
                """,
                (type_name,),
            )
            return _rows_to_json(cur)
    except Exception as e:
        return f"ERROR: {e}"


@mcp.tool()
def sample_table_data(schema: str, table: str, limit: int = 10) -> str:
    """
    Sample existing rows from a table.
    Use this to:
    1. Check if satisfying test data already exists (skip generation if so).
    2. Understand the shape and realistic values in the table.
    """
    conn = _require_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f'SELECT * FROM "{schema}"."{table}" LIMIT %s', (limit,)
            )
            return _rows_to_json(cur)
    except Exception as e:
        return f"ERROR: {e}"


# ── SQL execution tools (recursive chain) ─────────────────────────────────────

@mcp.tool()
def execute_query(sql: str) -> str:
    """
    Execute any SQL query (SELECT, WITH, EXPLAIN, etc.) and return results as JSON.

    This is the primary tool for the recursive SQL chain:
    - Run SELECT queries found in the SP body
    - Run SQL strings found INSIDE column values of query results
    - Continue recursively until no more SQL-like strings are found

    A string is likely SQL if it starts with SELECT, WITH, INSERT, UPDATE,
    DELETE, EXECUTE, CALL, or PERFORM (case-insensitive, after stripping whitespace).

    All queries run on the main connection (auto-committed reads).
    For write operations found in column values, use execute_in_transaction instead.
    """
    conn = _require_conn()
    try:
        t0 = time.time()
        with conn.cursor() as cur:
            cur.execute(sql)
            result = _rows_to_json(cur)
        elapsed = round(time.time() - t0, 3)
        # Inject timing
        parsed = json.loads(result)
        parsed["elapsed_seconds"] = elapsed
        return json.dumps(parsed, indent=2)
    except Exception as e:
        return f"ERROR: {e}"


@mcp.tool()
def execute_in_transaction(sql: str) -> str:
    """
    Execute an INSERT / UPDATE / DELETE (or any DML) inside the open test transaction.
    Use this when you find write SQL strings stored inside column values of a table.
    Everything is rolled back unless commit_test_data() is called.
    Requires begin_test_transaction() to have been called first.
    """
    tx = _require_tx()
    try:
        with tx.cursor() as cur:
            cur.execute(sql)
            affected = cur.rowcount
        return json.dumps({"status": "ok", "rows_affected": affected})
    except Exception as e:
        return f"ERROR: {e}"


# ── Test data management ──────────────────────────────────────────────────────

@mcp.tool()
def generate_test_data(
    tables: list[dict],
    conditions: dict | None = None,
    rows_per_table: int = 10,
) -> str:
    """
    Generate Faker-based test rows for a list of tables.

    'tables' format:
        [{"schema": "public", "table": "orders"}, ...]
        Tables must be listed in FK dependency order (parents first).

    'conditions' format (from WHERE clause analysis):
        {"status": [{"operator": "=", "value": "ACTIVE"}], ...}

    Returns generated rows as JSON — call insert_rows() to actually insert them.
    You can review and adjust the values before inserting.
    """
    try:
        from src.schema_inspector import SchemaInspector
        from src.test_data_generator import TestDataGenerator
        conn = _require_conn()
        insp = SchemaInspector(conn)
        gen  = TestDataGenerator(insp, default_rows=rows_per_table)
        pairs = [(t["schema"], t["table"]) for t in tables]
        generated = gen.generate_for_tables(
            pairs, conditions or {}, num_rows=rows_per_table,
            tx_conn=_tx,
        )
        # Serialise — convert non-JSON types
        output = {}
        for (schema, table), rows in generated.items():
            serialised = []
            for row in rows:
                sr = {}
                for k, v in row.items():
                    if hasattr(v, "isoformat"):
                        v = v.isoformat()
                    elif not isinstance(v, (str, int, float, bool, type(None))):
                        v = str(v)
                    sr[k] = v
                serialised.append(sr)
            output[f"{schema}.{table}"] = serialised
        return json.dumps(output, indent=2)
    except Exception as e:
        return f"ERROR: {e}"


@mcp.tool()
def begin_test_transaction() -> str:
    """
    Open a new PostgreSQL transaction for inserting test data.
    All subsequent insert_rows() and execute_in_transaction() calls will use this.
    Nothing is visible to other connections or committed until commit_test_data().
    Call rollback_test_data() to undo everything at any time.
    """
    global _tx, _tx_rows_inserted
    if _tx and not _tx.closed:
        return "A test transaction is already open. Call rollback_test_data() first if you want to restart."
    conn = _require_conn()
    from src.config_manager import ConfigManager  # get connection params
    # Clone the connection params from the existing live connection
    dsn = conn.dsn
    _tx = psycopg2.connect(dsn, connect_timeout=10)
    _tx.autocommit = False
    _tx_rows_inserted = 0
    return "Test transaction opened. Use insert_rows() to add data. Call commit_test_data() or rollback_test_data() when done."


@mcp.tool()
def insert_rows(schema: str, table: str, rows: list[dict]) -> str:
    """
    Insert a list of row dictionaries into a table inside the open test transaction.
    Each dict maps column name → value.
    Serial/sequence columns can be omitted — the database will assign them.
    Requires begin_test_transaction() to have been called first.
    Returns count of inserted rows.
    """
    global _tx_rows_inserted
    tx = _require_tx()
    if not rows:
        return "No rows provided."
    try:
        inserted = 0
        for row in rows:
            cols = list(row.keys())
            vals = list(row.values())
            col_str = ", ".join(f'"{c}"' for c in cols)
            placeholders = ", ".join(["%s"] * len(vals))
            sql = f'INSERT INTO "{schema}"."{table}" ({col_str}) VALUES ({placeholders})'
            with tx.cursor() as cur:
                cur.execute(sql, vals)
            inserted += 1
        _tx_rows_inserted += inserted
        return f"Inserted {inserted} row(s) into {schema}.{table}. Total in this transaction: {_tx_rows_inserted}."
    except Exception as e:
        return f"ERROR inserting into {schema}.{table}: {e}"


@mcp.tool()
def commit_test_data() -> str:
    """
    Commit the open test transaction — makes all inserted data permanent.
    Only call this after the user has run their SP and confirmed the data is correct.
    """
    global _tx, _tx_rows_inserted
    if not _tx or _tx.closed:
        return "No open test transaction to commit."
    try:
        _tx.commit()
        _tx.close()
        total = _tx_rows_inserted
        _tx = None
        _tx_rows_inserted = 0
        return f"Transaction committed. {total} row(s) are now permanent in the database."
    except Exception as e:
        return f"ERROR during commit: {e}"


@mcp.tool()
def rollback_test_data() -> str:
    """
    Roll back the open test transaction — removes ALL inserted test data.
    This is a manual, on-demand operation. Call it whenever you want to undo.
    """
    global _tx, _tx_rows_inserted
    if not _tx or _tx.closed:
        return "No open test transaction to roll back."
    try:
        _tx.rollback()
        _tx.close()
        total = _tx_rows_inserted
        _tx = None
        _tx_rows_inserted = 0
        return f"Transaction rolled back. {total} inserted row(s) have been removed."
    except Exception as e:
        return f"ERROR during rollback: {e}"


@mcp.tool()
def transaction_status() -> str:
    """Return status of the current test transaction."""
    global _tx, _tx_rows_inserted
    if _tx and not _tx.closed:
        return f"Test transaction OPEN — {_tx_rows_inserted} row(s) inserted (not yet committed)."
    return "No open test transaction."


# ── Server startup ────────────────────────────────────────────────────────────

def run_server(argv: list[str]) -> None:
    """Parse CLI args, optionally auto-connect, then start stdio MCP server."""
    parser = argparse.ArgumentParser(description="PostgreSQL MCP Server")
    parser.add_argument("--dsn",     help="Full DSN: postgresql://user:pass@host/db")
    parser.add_argument("--profile", help="Profile name from config.ini (e.g. 'local')")
    parser.add_argument("--host",    default="localhost")
    parser.add_argument("--port",    default="5432")
    parser.add_argument("--db",      default="postgres")
    parser.add_argument("--user",    default="postgres")
    parser.add_argument("--password",default="")
    parser.add_argument("--schema",  default="public", help="Default schema (default: public)")
    args = parser.parse_args(argv)

    # Auto-connect if params given
    global _conn
    try:
        if args.dsn:
            _connect_dsn(args.dsn)
        elif args.profile:
            from src.config_manager import ConfigManager
            cfg = ConfigManager()
            profiles = cfg.get_profiles()
            key = f"profile_{args.profile}"
            if key in profiles:
                _connect_profile(profiles[key])
            else:
                print(f"[postgres-mcp] Profile '{args.profile}' not found in config.ini", file=sys.stderr)
        elif any([args.host != "localhost", args.port != "5432",
                  args.db != "postgres", args.user != "postgres", args.password]):
            _connect_profile({
                "host": args.host, "port": args.port,
                "database": args.db, "username": args.user,
                "password": args.password, "ssl_mode": "prefer",
                "schema": args.schema,
            })
        else:
            # Try default profile from config.ini
            try:
                from src.config_manager import ConfigManager
                cfg = ConfigManager()
                profiles = cfg.get_profiles()
                if profiles:
                    first = next(iter(profiles.values()))
                    _connect_profile(first)
            except Exception:
                pass
    except Exception as e:
        print(f"[postgres-mcp] Auto-connect failed: {e}", file=sys.stderr)

    # Run as stdio MCP server (default transport for Claude Desktop)
    mcp.run(transport="stdio")
