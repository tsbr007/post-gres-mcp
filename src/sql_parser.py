"""
SQL Parser — reverse-engineers SELECT statements from a stored procedure / function body.
Extracts: table references (FROM / JOIN) and WHERE-clause conditions.
"""
import re
import sqlparse


# ── Helpers ────────────────────────────────────────────────────────────────────

def _extract_body(sql_text: str) -> str:
    """Return just the procedure body, stripping the CREATE wrapper if present."""
    # PostgreSQL $$ ... $$ style
    m = re.search(r'\$\w*\$(.*?)\$\w*\$', sql_text, re.DOTALL)
    if m:
        return m.group(1)
    # BEGIN ... END block
    m = re.search(r'\bBEGIN\b(.*?)\bEND\b', sql_text, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1)
    return sql_text


def _extract_selects(body: str) -> list[str]:
    """Return individual SELECT statement strings found in body."""
    stmts = sqlparse.parse(body)
    selects = [str(s).strip() for s in stmts if s.get_type() == "SELECT"]
    if not selects:
        # Fallback regex — grab everything from SELECT … to ; or end-of-string
        selects = re.findall(
            r'(SELECT\b.*?)(?=\bSELECT\b|;|$)',
            body, re.DOTALL | re.IGNORECASE
        )
    return [s.strip() for s in selects if s.strip()]


# ── Table extraction ───────────────────────────────────────────────────────────

_TABLE_RE = re.compile(
    r'\b(?:FROM|JOIN)\s+(?:"?(\w+)"?\.)?"?(\w+)"?'
    r'(?:\s+(?:AS\s+)?(?!\bON\b|\bWHERE\b|\bINNER\b|\bLEFT\b|\bRIGHT\b)\w+)?',
    re.IGNORECASE,
)
_SKIP = {"select", "where", "on", "set", "values", "with", "lateral", "only",
         "natural", "cross", "full", "outer"}


def _tables_from_sql(sql: str) -> list[tuple[str, str]]:
    results = []
    for m in _TABLE_RE.finditer(sql):
        schema = (m.group(1) or "public").lower()
        table  = m.group(2).lower()
        if table not in _SKIP and (schema, table) not in results:
            results.append((schema, table))
    return results


# ── WHERE-condition extraction ─────────────────────────────────────────────────

def _conditions_from_sql(sql: str) -> list[dict]:
    conds = []
    m = re.search(
        r'\bWHERE\b(.*?)(?:\bGROUP\s+BY\b|\bHAVING\b|\bORDER\s+BY\b|\bLIMIT\b|;|$)',
        sql, re.DOTALL | re.IGNORECASE,
    )
    if not m:
        return conds
    where = m.group(1)

    # col = / != / > / < / >= / <= value
    for x in re.finditer(
        r'(?:[\w"]+\.)*"?(\w+)"?\s*(=|!=|<>|>=|<=|>|<)\s*'
        r"(?:'([^']*)'|\"([^\"]*)\"|([\w.]+))",
        where, re.IGNORECASE
    ):
        col = x.group(1).lower()
        op  = x.group(2)
        val = x.group(3) or x.group(4) or x.group(5)
        conds.append({"column": col, "operator": op, "value": val})

    # col LIKE 'pattern'
    for x in re.finditer(
        r'(?:[\w"]+\.)*"?(\w+)"?\s+LIKE\s+\'([^\']*)\'' , where, re.IGNORECASE
    ):
        conds.append({"column": x.group(1).lower(), "operator": "LIKE", "value": x.group(2)})

    # col IS [NOT] NULL
    for x in re.finditer(
        r'(?:[\w"]+\.)*"?(\w+)"?\s+IS\s+(NOT\s+)?NULL', where, re.IGNORECASE
    ):
        op = "IS NOT NULL" if x.group(2) else "IS NULL"
        conds.append({"column": x.group(1).lower(), "operator": op, "value": None})

    # col IN (v1, v2, ...)
    for x in re.finditer(
        r'(?:[\w"]+\.)*"?(\w+)"?\s+IN\s*\(([^)]+)\)', where, re.IGNORECASE
    ):
        vals = [v.strip().strip("'\"") for v in x.group(2).split(",")]
        conds.append({"column": x.group(1).lower(), "operator": "IN", "value": vals})

    # col BETWEEN v1 AND v2
    for x in re.finditer(
        r'(?:[\w"]+\.)*"?(\w+)"?\s+BETWEEN\s+(\S+)\s+AND\s+(\S+)', where, re.IGNORECASE
    ):
        conds.append({
            "column": x.group(1).lower(), "operator": "BETWEEN",
            "value": [x.group(2).strip("'\""), x.group(3).strip("'\"")],
        })

    return conds


# ── Public API ────────────────────────────────────────────────────────────────

def analyse_sql_file(sql_text: str) -> dict:
    """
    Returns:
    {
        "selects":    [str, ...],
        "tables":     [(schema, table), ...],
        "conditions": {column: [{"operator": ..., "value": ...}, ...], ...}
    }
    """
    body    = _extract_body(sql_text)
    selects = _extract_selects(body)

    all_tables: list[tuple[str, str]] = []
    all_conds:  dict[str, list]       = {}

    for sel in selects:
        for t in _tables_from_sql(sel):
            if t not in all_tables:
                all_tables.append(t)
        for c in _conditions_from_sql(sel):
            col = c["column"]
            all_conds.setdefault(col, []).append(
                {"operator": c["operator"], "value": c["value"]}
            )

    return {"selects": selects, "tables": all_tables, "conditions": all_conds}
