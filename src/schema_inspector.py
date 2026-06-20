"""Live PostgreSQL schema introspection via information_schema and pg_catalog."""


class SchemaInspector:
    def __init__(self, conn):
        self.conn = conn

    def _fetch(self, sql, params=()):
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()

    # ── Schema / table lists ───────────────────────────────────────────────────

    def get_schemas(self):
        rows = self._fetch(
            "SELECT schema_name FROM information_schema.schemata "
            "WHERE schema_name NOT IN ('pg_catalog','information_schema','pg_toast') "
            "ORDER BY schema_name"
        )
        return [r[0] for r in rows]

    def get_tables(self, schema="public"):
        rows = self._fetch(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema=%s AND table_type='BASE TABLE' ORDER BY table_name",
            (schema,)
        )
        return [r[0] for r in rows]

    def get_views(self, schema="public"):
        rows = self._fetch(
            "SELECT table_name FROM information_schema.views "
            "WHERE table_schema=%s ORDER BY table_name", (schema,)
        )
        return [r[0] for r in rows]

    # ── Column info ────────────────────────────────────────────────────────────

    def get_columns(self, schema, table):
        rows = self._fetch(
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
        return [
            {
                "name": r[0], "data_type": r[1], "udt_name": r[2],
                "nullable": r[3] == "YES", "default": r[4],
                "max_length": r[5], "precision": r[6], "scale": r[7],
            }
            for r in rows
        ]

    # ── Constraints ────────────────────────────────────────────────────────────

    def get_primary_keys(self, schema, table):
        rows = self._fetch(
            """
            SELECT kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_schema    = kcu.table_schema
            WHERE tc.constraint_type='PRIMARY KEY'
              AND tc.table_schema=%s AND tc.table_name=%s
            ORDER BY kcu.ordinal_position
            """,
            (schema, table),
        )
        return [r[0] for r in rows]

    def get_unique_columns(self, schema, table):
        rows = self._fetch(
            """
            SELECT kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_schema    = kcu.table_schema
            WHERE tc.constraint_type='UNIQUE'
              AND tc.table_schema=%s AND tc.table_name=%s
            """,
            (schema, table),
        )
        return [r[0] for r in rows]

    def get_foreign_keys(self, schema, table):
        rows = self._fetch(
            """
            SELECT kcu.column_name,
                   ccu.table_schema, ccu.table_name, ccu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_schema    = kcu.table_schema
            JOIN information_schema.constraint_column_usage ccu
              ON ccu.constraint_name = tc.constraint_name
            WHERE tc.constraint_type='FOREIGN KEY'
              AND tc.table_schema=%s AND tc.table_name=%s
            """,
            (schema, table),
        )
        return [
            {"column": r[0], "ref_schema": r[1], "ref_table": r[2], "ref_column": r[3]}
            for r in rows
        ]

    # ── Enum values ────────────────────────────────────────────────────────────

    def get_enum_values(self, udt_name):
        rows = self._fetch(
            """
            SELECT e.enumlabel FROM pg_type t
            JOIN pg_enum e ON t.oid = e.enumtypid
            WHERE t.typname=%s ORDER BY e.enumsortorder
            """,
            (udt_name,),
        )
        return [r[0] for r in rows]

    # ── Sequences ─────────────────────────────────────────────────────────────

    def next_sequence_val(self, schema, table, column):
        with self.conn.cursor() as cur:
            cur.execute("SELECT pg_get_serial_sequence(%s, %s)", (f"{schema}.{table}", column))
            seq = cur.fetchone()[0]
            if seq:
                cur.execute("SELECT nextval(%s)", (seq,))
                return cur.fetchone()[0]
        return None

    # ── Full table metadata ────────────────────────────────────────────────────

    def table_meta(self, schema, table):
        return {
            "schema": schema, "table": table,
            "columns":      self.get_columns(schema, table),
            "primary_keys": self.get_primary_keys(schema, table),
            "unique_cols":  self.get_unique_columns(schema, table),
            "foreign_keys": self.get_foreign_keys(schema, table),
        }

    # ── Topological sort by FK dependencies ───────────────────────────────────

    def topo_sort(self, table_pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
        """Return table_pairs ordered so parents come before children."""
        from graphlib import TopologicalSorter
        deps: dict[tuple, set] = {t: set() for t in table_pairs}
        for (schema, table) in table_pairs:
            for fk in self.get_foreign_keys(schema, table):
                parent = (fk["ref_schema"], fk["ref_table"])
                if parent in deps and parent != (schema, table):
                    deps[(schema, table)].add(parent)
        ts = TopologicalSorter(deps)
        return list(ts.static_order())
