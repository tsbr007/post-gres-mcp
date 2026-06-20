"""
Test data generator — produces Faker-based rows that satisfy WHERE conditions,
respects column types, PKs, FKs, and UNIQUE constraints.
"""
import random
import datetime
import uuid

try:
    from faker import Faker
    _fk = Faker()
except ImportError:
    _fk = None


# ── Type-aware value generation ───────────────────────────────────────────────

_INT_TYPES    = {"integer", "int", "int2", "int4", "int8", "bigint", "smallint", "serial", "bigserial"}
_FLOAT_TYPES  = {"numeric", "decimal", "real", "double precision", "float4", "float8", "money"}
_STR_TYPES    = {"character varying", "varchar", "char", "character", "text", "name", "citext"}
_DATE_TYPES   = {"date"}
_TIME_TYPES   = {"time without time zone", "time with time zone", "time"}
_TS_TYPES     = {"timestamp without time zone", "timestamp with time zone", "timestamp", "timestamptz"}
_BOOL_TYPES   = {"boolean", "bool"}
_UUID_TYPES   = {"uuid"}
_JSON_TYPES   = {"json", "jsonb"}


def _rand_str(max_len=None):
    if _fk:
        base = _fk.word()
    else:
        base = "test_value"
    if max_len and len(base) > max_len:
        base = base[:max_len]
    return base


def _rand_int(lo=1, hi=9999):
    return random.randint(lo, hi)


def _rand_float():
    return round(random.uniform(1.0, 9999.99), 2)


def _rand_date():
    if _fk:
        return _fk.date_between(start_date="-1y", end_date="today")
    return datetime.date.today()


def _rand_ts():
    if _fk:
        return _fk.date_time_between(start_date="-1y", end_date="now")
    return datetime.datetime.now()


def _value_for_type(col: dict, enum_values: list | None = None) -> object:
    dt  = col["data_type"].lower()
    udt = col["udt_name"].lower()

    if enum_values:
        return random.choice(enum_values)
    if dt in _BOOL_TYPES or udt in _BOOL_TYPES:
        return random.choice([True, False])
    if dt in _UUID_TYPES or udt in _UUID_TYPES:
        return str(uuid.uuid4())
    if dt in _INT_TYPES or udt in _INT_TYPES:
        return _rand_int()
    if dt in _FLOAT_TYPES or udt in _FLOAT_TYPES:
        return _rand_float()
    if dt in _DATE_TYPES or udt in _DATE_TYPES:
        return _rand_date()
    if dt in _TS_TYPES or udt in _TS_TYPES:
        return _rand_ts()
    if dt in _TIME_TYPES or udt in _TIME_TYPES:
        return datetime.time(random.randint(0, 23), random.randint(0, 59))
    if dt in _JSON_TYPES or udt in _JSON_TYPES:
        return '{"generated": true}'
    # Default: string
    return _rand_str(col.get("max_length"))


# ── Condition-aware override ──────────────────────────────────────────────────

def _apply_condition(base_val, col_name: str, conditions: dict) -> object:
    """If a WHERE condition exists for this column, honour it."""
    col_conds = conditions.get(col_name.lower(), [])
    for c in col_conds:
        op  = c["operator"]
        val = c["value"]
        if op == "=" and val is not None:
            # Try to coerce the string literal to the base type
            try:
                return type(base_val)(val)
            except Exception:
                return val
        if op in (">", ">=") and val is not None:
            try:
                threshold = type(base_val)(val)
                if isinstance(threshold, (int, float)):
                    return threshold + _rand_int(1, 100)
            except Exception:
                pass
        if op in ("<", "<=") and val is not None:
            try:
                threshold = type(base_val)(val)
                if isinstance(threshold, (int, float)):
                    return threshold - _rand_int(1, 10)
            except Exception:
                pass
        if op == "IN" and isinstance(val, list) and val:
            return random.choice(val)
        if op == "BETWEEN" and isinstance(val, list) and len(val) == 2:
            try:
                lo, hi = type(base_val)(val[0]), type(base_val)(val[1])
                if isinstance(lo, (int, float)):
                    return random.uniform(lo, hi) if isinstance(lo, float) else random.randint(lo, hi)
            except Exception:
                pass
        if op == "IS NOT NULL":
            return base_val  # already non-null
        if op == "IS NULL":
            return None
    return base_val


# ── FK value lookup ───────────────────────────────────────────────────────────

def _pick_fk_value(inspector, ref_schema, ref_table, ref_col, tx_conn=None):
    """Pick an existing value from the referenced (parent) table."""
    conn = tx_conn or inspector.conn
    try:
        with conn.cursor() as cur:
            cur.execute(
                f'SELECT "{ref_col}" FROM "{ref_schema}"."{ref_table}" '
                f'ORDER BY RANDOM() LIMIT 1'
            )
            row = cur.fetchone()
            return row[0] if row else None
    except Exception:
        return None


# ── Main generator ────────────────────────────────────────────────────────────

class TestDataGenerator:
    def __init__(self, inspector, default_rows: int = 10):
        self.inspector    = inspector
        self.default_rows = default_rows

    def generate_for_tables(
        self,
        table_pairs: list[tuple[str, str]],
        conditions: dict,
        num_rows: int | None = None,
        tx_conn=None,
    ) -> dict[tuple, list[dict]]:
        """
        Generate `num_rows` row dicts per table.
        Returns { (schema, table): [{"col": val, ...}, ...] }
        The caller decides whether to insert them.
        """
        rows_per = num_rows or self.default_rows
        ordered  = self.inspector.topo_sort(table_pairs)
        result   = {}

        for (schema, table) in ordered:
            if (schema, table) not in table_pairs:
                continue
            meta       = self.inspector.table_meta(schema, table)
            pk_cols    = set(meta["primary_keys"])
            fk_map     = {fk["column"]: fk for fk in meta["foreign_keys"]}
            unique_cols = set(meta["unique_cols"])
            used_unique: dict[str, set] = {}

            table_rows = []
            for _ in range(rows_per):
                row = {}
                for col in meta["columns"]:
                    cname   = col["name"]
                    default = col.get("default") or ""

                    # Skip serial / sequence PKs — let DB handle them
                    if cname in pk_cols and "nextval" in str(default).lower():
                        continue

                    # FK column → pick from parent
                    if cname in fk_map:
                        fk    = fk_map[cname]
                        val   = _pick_fk_value(
                            self.inspector,
                            fk["ref_schema"], fk["ref_table"], fk["ref_column"],
                            tx_conn=tx_conn,
                        )
                        if val is not None:
                            row[cname] = val
                            continue

                    # Enum type?
                    enum_vals = None
                    if col["data_type"] == "USER-DEFINED":
                        enum_vals = self.inspector.get_enum_values(col["udt_name"])

                    base_val = _value_for_type(col, enum_vals)
                    val      = _apply_condition(base_val, cname, conditions)

                    # UNIQUE retry
                    if cname in unique_cols:
                        used_unique.setdefault(cname, set())
                        attempts = 0
                        while val in used_unique[cname] and attempts < 20:
                            base_val = _value_for_type(col, enum_vals)
                            val      = _apply_condition(base_val, cname, conditions)
                            attempts += 1
                        used_unique[cname].add(val)

                    # Skip NULL on NOT NULL columns with a second attempt
                    if val is None and not col["nullable"]:
                        val = _value_for_type(col, enum_vals)

                    row[cname] = val

                table_rows.append(row)
            result[(schema, table)] = table_rows

        return result
