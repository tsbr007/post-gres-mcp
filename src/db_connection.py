"""psycopg2 connection wrapper with test-data transaction support."""
import time
import psycopg2
import psycopg2.extras


def _connect(profile, timeout=10):
    return psycopg2.connect(
        host=profile["host"], port=int(profile["port"]),
        database=profile["database"], user=profile["username"],
        password=profile["password"],
        sslmode=profile.get("ssl_mode", "prefer"),
        connect_timeout=timeout,
    )


class DatabaseConnection:
    def __init__(self):
        self.conn = None
        self.profile = None
        self.default_schema: str = "public"   # set from profile on connect
        self._tx_conn = None          # Open transaction for test data

    # ── Main connection ────────────────────────────────────────────────
    def connect(self, profile):
        self.disconnect()
        self.conn = _connect(profile)
        self.conn.autocommit = True
        self.profile = profile
        self.default_schema = profile.get("schema", "public")

    def test_connection(self, profile):
        try:
            c = _connect(profile, timeout=5)
            v = c.server_version
            c.close()
            major, minor = v // 10000, (v % 10000) // 100
            return True, f"PostgreSQL {major}.{minor} — connection OK"
        except Exception as e:
            return False, str(e)

    def disconnect(self):
        self.rollback_test_tx()
        if self.conn:
            try:
                self.conn.close()
            except Exception:
                pass
            self.conn = None
            self.profile = None
            self.default_schema = "public"

    def is_connected(self):
        return self.conn is not None and not self.conn.closed

    def server_version_str(self):
        if not self.is_connected():
            return ""
        try:
            with self.conn.cursor() as cur:
                cur.execute("SELECT version();")
                return cur.fetchone()[0].split(",")[0]
        except Exception:
            return ""

    # ── Query execution ────────────────────────────────────────────────
    def execute(self, sql, params=None):
        if not self.is_connected():
            raise RuntimeError("Not connected to any database.")
        t0 = time.time()
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            elapsed = round(time.time() - t0, 3)
            if cur.description:
                cols = [d[0] for d in cur.description]
                rows = [dict(r) for r in cur.fetchall()]
                return {"columns": cols, "rows": rows,
                        "rowcount": len(rows), "elapsed": elapsed}
            return {"columns": [], "rows": [], "rowcount": cur.rowcount,
                    "elapsed": elapsed,
                    "message": f"{cur.rowcount} row(s) affected"}

    # ── Test-data transaction ──────────────────────────────────────────
    def begin_test_tx(self):
        if self._tx_conn:
            raise RuntimeError("A test transaction is already open.")
        self._tx_conn = _connect(self.profile)
        self._tx_conn.autocommit = False

    def tx_insert(self, schema, table, columns, values):
        if not self._tx_conn:
            raise RuntimeError("No test transaction. Call begin_test_tx() first.")
        cols = ", ".join(f'"{c}"' for c in columns)
        ph   = ", ".join(["%s"] * len(values))
        sql  = f'INSERT INTO "{schema}"."{table}" ({cols}) VALUES ({ph})'
        with self._tx_conn.cursor() as cur:
            cur.execute(sql, values)

    def commit_test_tx(self):
        if self._tx_conn:
            self._tx_conn.commit()
            self._tx_conn.close()
            self._tx_conn = None

    def rollback_test_tx(self):
        if self._tx_conn:
            try:
                self._tx_conn.rollback()
                self._tx_conn.close()
            except Exception:
                pass
            self._tx_conn = None

    def has_open_test_tx(self):
        return self._tx_conn is not None
