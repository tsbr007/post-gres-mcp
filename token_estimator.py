"""
token_estimator.py — Estimate Claude token consumption for a postgres-mcp session.

Usage:
    python token_estimator.py                        # interactive mode (defaults)
    python token_estimator.py --sp my_procedure.sql  # measure an actual SP file
    python token_estimator.py --tables 3 --depth 2  # override specific defaults

Token counting method:
    Approximation: 1 token ~= 4 characters (English text/code).
    This is the standard rule-of-thumb used by Anthropic for Claude models.

Pricing (Claude Sonnet 4.x as of 2025, per 1M tokens):
    Input tokens:  $3.00
    Output tokens: $15.00
"""

import argparse
import math
import pathlib
import re
import sys

# ── Token approximation constant ─────────────────────────────────────────────
CHARS_PER_TOKEN = 4  # Standard Claude approximation


def chars_to_tokens(n: int) -> int:
    return max(1, math.ceil(n / CHARS_PER_TOKEN))


def tokens_to_cost(input_tokens: int, output_tokens: int) -> dict:
    """Claude Sonnet 4 pricing: $3/1M input, $15/1M output."""
    input_cost  = (input_tokens  / 1_000_000) * 3.00
    output_cost = (output_tokens / 1_000_000) * 15.00
    return {
        "input_tokens":  input_tokens,
        "output_tokens": output_tokens,
        "total_tokens":  input_tokens + output_tokens,
        "input_cost_usd":  round(input_cost,  6),
        "output_cost_usd": round(output_cost, 6),
        "total_cost_usd":  round(input_cost + output_cost, 6),
    }


# ── Load system prompt size ───────────────────────────────────────────────────

def get_system_prompt_tokens() -> int:
    """mcp_instructions.txt is sent as the system prompt on EVERY MCP request."""
    instructions_path = pathlib.Path(__file__).parent / "src" / "mcp_instructions.txt"
    try:
        text = instructions_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        text = "x" * 23966  # fallback: file is ~24 KB
    return chars_to_tokens(len(text))


# ── Phase-by-phase token model ────────────────────────────────────────────────

def estimate_phase_tokens(
    sp_size_chars: int,
    num_tables: int,
    recursion_depth: int,
    rows_per_table: int,
    num_columns_avg: int,
) -> dict:
    """
    Returns dict of phase_name -> (input_tokens, output_tokens).

    Each MCP round-trip:
      Input  = (tool call text) + (tool response JSON)
      Output = Claude's narration + next tool call decision
    Context growth is handled separately in estimate_context_overhead().
    """
    results = {}

    # Phase 0 – Connection Check
    results["Phase 0  Connection Check"] = (200, 150)

    # Phase 1 – SP Discovery & Loading
    sp_tokens = chars_to_tokens(sp_size_chars)
    results["Phase 1  SP Discovery & Loading"] = (sp_tokens + 300, 600)

    # Phase 2 – Recursive SQL Chain
    # Each recursion level: execute_query call + result inspection + Claude narrates
    per_level_in  = 500 + (num_tables * 200)
    per_level_out = 400
    results["Phase 2  Recursive SQL Chain"] = (
        per_level_in  * recursion_depth,
        per_level_out * recursion_depth,
    )

    # Phase 3 – Schema Analysis (per table: schema + FK values + sample data)
    per_table_out = (num_columns_avg * 30 + 200) + 200 + (rows_per_table * num_columns_avg * 10)
    per_table_in  = 300  # tool calls overhead
    results["Phase 3  Schema Analysis"] = (
        per_table_in  * num_tables + 500,
        per_table_out * num_tables + 800,
    )

    # Phase 4 – Condition Analysis
    results["Phase 4  Condition Analysis"] = (400, 500)

    # Phase 5 – Test Data Generation
    generated_tokens = num_tables * rows_per_table * num_columns_avg * 8
    results["Phase 5  Test Data Generation"] = (300, generated_tokens + 600)

    # Phase 6 – Transaction & Insert
    per_insert_in  = 150 + (rows_per_table * num_columns_avg * 5)
    per_insert_out = 100
    results["Phase 6  Transaction & Insert"] = (
        per_insert_in  * num_tables + 200,
        per_insert_out * num_tables + 300,
    )

    # Phase 7 – Operator Verification
    results["Phase 7  Operator Verification"] = (200, 400)

    # Phase 8 – Commit / Rollback
    results["Phase 8  Commit / Rollback"] = (150, 250)

    return results


def estimate_context_overhead(phase_tokens: dict, system_prompt_tokens: int) -> int:
    """
    MCP sends the FULL conversation history on every round-trip.
    Each phase pays for all prior context accumulated so far.
    We model this as a triangular sum (each phase adds to the rolling total).
    """
    cumulative   = 0
    running_hist = system_prompt_tokens  # system prompt is always included

    for inp, out in phase_tokens.values():
        cumulative   += running_hist   # this phase sends all prior context as input
        running_hist += inp + out      # grow history by this phase's tokens

    return cumulative


# ── Main estimator ────────────────────────────────────────────────────────────

def run_estimation(
    sp_size_chars: int,
    num_tables: int,
    recursion_depth: int,
    rows_per_table: int,
    num_columns_avg: int,
    sp_file: str = "",
):
    system_prompt_tokens = get_system_prompt_tokens()

    phase_tokens = estimate_phase_tokens(
        sp_size_chars=sp_size_chars,
        num_tables=num_tables,
        recursion_depth=recursion_depth,
        rows_per_table=rows_per_table,
        num_columns_avg=num_columns_avg,
    )

    context_overhead = estimate_context_overhead(phase_tokens, system_prompt_tokens)

    total_input  = sum(i for i, _ in phase_tokens.values()) + context_overhead
    total_output = sum(o for _, o in phase_tokens.values())
    cost         = tokens_to_cost(total_input, total_output)

    W = 72
    print()
    print("=" * W)
    print("  postgres-mcp  —  Claude Token Consumption Estimator")
    print("=" * W)
    print()

    # Session parameters
    print("  SESSION PARAMETERS")
    print("  " + "-" * (W - 2))
    if sp_file:
        print(f"  SP file              : {sp_file}  ({sp_size_chars:,} chars)")
    else:
        print(f"  SP size              : {sp_size_chars:,} chars  (~{chars_to_tokens(sp_size_chars):,} tokens)")
    print(f"  Tables referenced    : {num_tables}")
    print(f"  Recursion depth      : {recursion_depth}")
    print(f"  Rows per table       : {rows_per_table}")
    print(f"  Avg columns/table    : {num_columns_avg}")
    print(f"  System prompt size   : {system_prompt_tokens:,} tokens  (included in EVERY request)")
    print()

    # Phase breakdown
    print("  PHASE-BY-PHASE TOKEN BREAKDOWN")
    print("  " + "-" * (W - 2))
    print(f"  {'Phase':<42} {'Input':>7} {'Output':>7} {'Total':>7}")
    print("  " + "-" * (W - 2))
    for phase, (inp, out) in phase_tokens.items():
        print(f"  {phase:<42} {inp:>7,} {out:>7,} {inp+out:>7,}")
    print("  " + "-" * (W - 2))
    raw_in  = sum(i for i, _ in phase_tokens.values())
    raw_out = sum(o for _, o in phase_tokens.values())
    print(f"  {'Subtotal (phase content)':<42} {raw_in:>7,} {raw_out:>7,} {raw_in+raw_out:>7,}")
    print(f"  {'Context growth overhead (history resent)':<42} {context_overhead:>7,}{'':>7} {context_overhead:>7,}")
    print()

    # Totals
    print("  TOTAL ESTIMATE")
    print("  " + "-" * (W - 2))
    print(f"  Input tokens   : {cost['input_tokens']:>12,}")
    print(f"  Output tokens  : {cost['output_tokens']:>12,}")
    print(f"  TOTAL tokens   : {cost['total_tokens']:>12,}")
    print()
    print(f"  Input cost     :  ${cost['input_cost_usd']:>9.4f}  (@ $3.00 / 1M tokens)")
    print(f"  Output cost    :  ${cost['output_cost_usd']:>9.4f}  (@ $15.00 / 1M tokens)")
    print(f"  >> TOTAL COST  :  ${cost['total_cost_usd']:>9.4f}  USD")
    print()

    # Scenario comparison
    print("  SCENARIO COMPARISON  (same SP size, varying complexity)")
    print("  " + "-" * (W - 2))
    print(f"  {'Scenario':<28} {'Tables':>6} {'Depth':>6} {'Tokens':>9} {'Cost USD':>10}")
    print("  " + "-" * (W - 2))
    scenarios = [
        ("Simple SP",        1, 1, 3,  5),
        ("Moderate SP",      3, 2, 5,  8),
        ("Complex SP",       6, 3, 10, 10),
        ("Very Complex SP",  10, 5, 15, 12),
    ]
    for label, t, d, r, c in scenarios:
        pt = estimate_phase_tokens(sp_size_chars, t, d, r, c)
        co = estimate_context_overhead(pt, system_prompt_tokens)
        si = sum(i for i, _ in pt.values()) + co
        so = sum(o for _, o in pt.values())
        sc = tokens_to_cost(si, so)
        print(f"  {label:<28} {t:>6} {d:>6} {sc['total_tokens']:>9,} {sc['total_cost_usd']:>9.4f}")
    print("  " + "-" * (W - 2))
    print()

    # Notes
    print("  NOTES")
    print("  * Token counts are approximations (1 token ~= 4 chars, Anthropic standard).")
    print("  * Context overhead dominates for complex SPs with many tables/recursions.")
    print("  * Claude Desktop Pro plan ($20/mo) - flat fee, no per-token billing.")
    print("  * API pricing above applies when calling Anthropic API directly.")
    print("  * Recursive SQL chain (Phase 2) is the biggest variable cost driver.")
    print()
    print("=" * W)
    print()

    return cost


# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Estimate Claude token usage for a postgres-mcp MCP session.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python token_estimator.py
  python token_estimator.py --sp path/to/my_proc.sql
  python token_estimator.py --tables 5 --depth 3 --rows 10
        """,
    )
    parser.add_argument("--sp",      type=str, help="Path to .sql SP file to measure")
    parser.add_argument("--tables",  type=int, default=None, help="Number of tables referenced (default: 5 or auto-detected)")
    parser.add_argument("--depth",   type=int, default=2,    help="Recursion depth (default: 2)")
    parser.add_argument("--rows",    type=int, default=5,    help="Rows per table (default: 5)")
    parser.add_argument("--columns", type=int, default=8,    help="Avg columns per table (default: 8)")
    args = parser.parse_args()

    sp_size_chars = 2000   # default: ~500 line SP
    sp_file_label = ""
    num_tables    = args.tables or 5

    if args.sp:
        sp_path = pathlib.Path(args.sp)
        if not sp_path.exists():
            print(f"ERROR: SP file not found: {args.sp}")
            sys.exit(1)
        sp_text       = sp_path.read_text(encoding="utf-8", errors="replace")
        sp_size_chars = len(sp_text)
        sp_file_label = str(sp_path)
        if args.tables is None:
            # Auto-detect referenced tables from FROM/JOIN keywords
            found = re.findall(r'\b(?:FROM|JOIN)\s+\S+', sp_text, re.IGNORECASE)
            num_tables = max(1, len(found))

    run_estimation(
        sp_size_chars=sp_size_chars,
        num_tables=num_tables,
        recursion_depth=args.depth,
        rows_per_table=args.rows,
        num_columns_avg=args.columns,
        sp_file=sp_file_label,
    )


if __name__ == "__main__":
    main()
