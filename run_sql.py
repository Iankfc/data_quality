"""Run one or more .sql files with DuckDB and print the results.

Debug / run without arguments:
    Edit SQL_FILES (and DB / OUT) in the `if __name__ == "__main__":` block at the
    bottom, then press F5 in VS Code (or run `.venv/bin/python run_sql.py`).

Usage (from anywhere):
    .venv/bin/python run_sql.py model/policy_claims_summary.sql
    .venv/bin/python run_sql.py model/a.sql model/b.sql
    .venv/bin/python run_sql.py model/x.sql --db warehouse.duckdb    # persistent database
    .venv/bin/python run_sql.py model/x.sql --out output/result.csv  # save last result to CSV/Parquet

Relative paths inside the SQL (e.g. 'source/policy_owner.csv') are resolved
from the project root, where this script lives.
"""

import argparse
import os
import sys
import time
from pathlib import Path

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parent


def run_file(con: duckdb.DuckDBPyConnection, sql_path: Path, max_rows: int):
    """Execute every statement in a file; print each result set. Returns the last result."""
    sql = sql_path.read_text()
    statements = duckdb.extract_statements(sql)
    print(f"\n=== {sql_path} ({len(statements)} statement(s)) ===")

    last = None
    for i, stmt in enumerate(statements, start=1):
        start = time.perf_counter()
        rel = con.sql(stmt.query)
        elapsed = time.perf_counter() - start
        if rel is not None:  # statement returned rows (SELECT, WITH, ...)
            rel.show(max_width=250, max_rows=max_rows)
            last = rel
        print(f"-- statement {i}: {stmt.type.name} OK ({elapsed:.3f}s)")
    return last


def main(files, db=":memory:", out=None, max_rows=1000) -> int:
    """Run the given .sql files. Paths may be str or Path."""
    # Resolve file paths before changing directory, so paths relative to the caller still work.
    files = [Path(f).resolve() for f in files]
    out = Path(out).resolve() if out else None
    db = db if db == ":memory:" else str(Path(db).resolve())
    os.chdir(PROJECT_ROOT)

    missing = [f for f in files if not f.is_file()]
    if missing:
        print(f"File(s) not found: {', '.join(map(str, missing))}", file=sys.stderr)
        return 1

    con = duckdb.connect(db)
    last = None
    try:
        for f in files:
            last = run_file(con, f, max_rows) or last
        if out:
            if last is None:
                print("out given but no statement returned rows.", file=sys.stderr)
                return 1
            out.parent.mkdir(parents=True, exist_ok=True)
            if out.suffix.lower() == ".parquet":
                last.write_parquet(str(out))
            else:
                last.write_csv(str(out))
            print(f"\nSaved last result to {out}")
    except duckdb.Error as e:
        print(f"\nDuckDB error: {e}", file=sys.stderr)
        return 1
    finally:
        con.close()
    return 0


def parse_args():
    parser = argparse.ArgumentParser(description="Run .sql files with DuckDB.")
    parser.add_argument("files", nargs="+", type=Path, help=".sql file(s) to run")
    parser.add_argument("--db", default=":memory:",
                        help="DuckDB database file (default: in-memory)")
    parser.add_argument("--out", type=Path,
                        help="write the last result set to .csv or .parquet")
    parser.add_argument("--max-rows", type=int, default=1000,
                        help="max rows to print per result (default: 1000)")
    return parser.parse_args()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        # Command line: .venv/bin/python run_sql.py model/x.sql [--db ...] [--out ...]
        args = parse_args()
        sys.exit(main(args.files, args.db, args.out, args.max_rows))

    # No arguments (e.g. F5 in the VS Code debugger): edit the values below.
    SQL_FILES = [PROJECT_ROOT / "model" / "policy_claims_summary.sql"]
    DB = ":memory:"   # or PROJECT_ROOT / "warehouse.duckdb"
    OUT = None        # or PROJECT_ROOT / "output" / "result.csv"
    MAX_ROWS = 1000

    main(SQL_FILES, DB, OUT, MAX_ROWS)
