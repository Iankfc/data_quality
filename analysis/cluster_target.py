"""Hierarchical clustering of the policy_claims_summary target table.

Two analyses:
  1. Columns: which numeric columns move together.
     Distance = 1 - |Spearman correlation|, average linkage.
  2. Rows: which owner + policy_type rows look alike.
     Money columns log-transformed, all columns standardised, Ward linkage.

Outputs:
  - printed summary (merge steps, cophenetic correlation, cluster profiles)
  - test_plan/images/target_column_dendrogram.png
  - test_plan/images/target_row_dendrogram.png

Run from anywhere:
    .venv/bin/python analysis/cluster_target.py
    .venv/bin/python analysis/cluster_target.py --clusters 4
Or press F5 / run without arguments (settings in the __main__ block).
"""

import argparse
import os
import sys
from pathlib import Path

import duckdb
import matplotlib

matplotlib.use("Agg")  # no display needed
import matplotlib.pyplot as plt
import numpy as np
from scipy.cluster.hierarchy import cophenet, dendrogram, fcluster, linkage
from scipy.spatial.distance import pdist, squareform
from scipy.stats import spearmanr

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Numeric columns used for clustering. latest_incident_date is converted to
# days_before_latest (days between the row's incident and the latest incident
# in the table), which keeps results the same whatever day the script runs.
NUMERIC_COLUMNS = [
    "policy_count",
    "total_annual_premium",
    "claim_count",
    "total_claimed",
    "total_approved",
    "approval_rate_pct",
    "days_before_latest",
]
# Skewed money columns: log-transform before clustering rows.
LOG_COLUMNS = {"total_annual_premium", "total_claimed", "total_approved"}


def load_target(model_sql: Path):
    """Run the model and return (labels, column names, numeric matrix)."""
    sql = model_sql.read_text().strip().rstrip(";")
    rel = duckdb.sql(f"""
        WITH t AS ({sql})
        SELECT owner_id || ' ' || split_part(policy_type, ' ', 1) AS label,
               policy_count,
               total_annual_premium,
               CAST(claim_count AS BIGINT) AS claim_count,
               total_claimed,
               total_approved,
               approval_rate_pct,
               date_diff('day', latest_incident_date,
                         MAX(latest_incident_date) OVER ()) AS days_before_latest
        FROM t
        ORDER BY label
    """)
    rows = rel.fetchall()
    labels = [r[0] for r in rows]
    X = np.array([[np.nan if v is None else float(v) for v in r[1:]] for r in rows])
    return labels, list(NUMERIC_COLUMNS), X


def drop_unusable(names, X):
    """Remove columns with nulls or no variation (they cannot be clustered)."""
    keep, dropped = [], []
    for i, name in enumerate(names):
        col = X[:, i]
        if np.isnan(col).any():
            dropped.append((name, "contains nulls"))
        elif np.nanstd(col) == 0:
            dropped.append((name, f"constant (always {col[0]:g})"))
        else:
            keep.append(i)
    return [names[i] for i in keep], X[:, keep], dropped


def cluster_columns(names, X, out_png: Path):
    rho, _ = spearmanr(X)
    dist = 1 - np.abs(rho)
    np.fill_diagonal(dist, 0)
    condensed = squareform(dist, checks=False)
    Z = linkage(condensed, method="average")
    coph, _ = cophenet(Z, condensed)

    print("\n=== Column clustering (distance = 1 - |Spearman|, average linkage) ===")
    print(f"Cophenetic correlation: {coph:.2f}")
    print("Spearman correlation matrix:")
    width = max(len(n) for n in names)
    print(" " * (width + 1) + " ".join(f"{n[:8]:>8}" for n in names))
    for i, n in enumerate(names):
        print(f"{n:<{width}} " + " ".join(f"{rho[i, j]:8.2f}" for j in range(len(names))))
    print("Merge steps (distance; |rho| = 1 - distance):")
    groups = {i: [names[i]] for i in range(len(names))}
    for step, (a, b, d, _) in enumerate(Z, start=1):
        a, b = int(a), int(b)
        groups[len(names) + step - 1] = groups[a] + groups[b]
        print(f"  {step}. {groups[a]} + {groups[b]}  at {d:.2f}")

    fig, ax = plt.subplots(figsize=(9, 4.5))
    dendrogram(Z, labels=names, orientation="right", ax=ax, color_threshold=0.5)
    ax.set_xlabel("Distance (1 - |Spearman correlation|)")
    ax.set_title("policy_claims_summary: column clustering")
    ax.axvline(0.5, ls="--", c="grey", lw=0.8)
    fig.tight_layout()
    fig.savefig(out_png, dpi=150)
    plt.close(fig)
    print(f"Saved {out_png.relative_to(PROJECT_ROOT)}")


def cluster_rows(labels, names, X, k, out_png: Path):
    R = X.copy()
    for i, n in enumerate(names):
        if n in LOG_COLUMNS:
            R[:, i] = np.log1p(R[:, i])
    R = (R - R.mean(axis=0)) / R.std(axis=0)
    Z = linkage(R, method="ward")
    coph, _ = cophenet(Z, pdist(R))
    groups = fcluster(Z, k, criterion="maxclust")

    print(f"\n=== Row clustering (log money, standardised, Ward linkage), {k} groups ===")
    print(f"Cophenetic correlation: {coph:.2f}")
    header = ["group", "rows"] + [f"avg {n}" for n in names]
    print(" | ".join(header))
    for g in sorted(set(groups)):
        idx = np.where(groups == g)[0]
        avgs = [f"{X[idx, i].mean():,.1f}" for i in range(len(names))]
        print(" | ".join([str(g), ", ".join(labels[i] for i in idx)] + avgs))

    fig, ax = plt.subplots(figsize=(9, 5))
    cut = (Z[-k, 2] + Z[-k + 1, 2]) / 2 if k > 1 else None
    dendrogram(Z, labels=labels, orientation="right", ax=ax,
               color_threshold=cut if cut else 0)
    if cut:
        ax.axvline(cut, ls="--", c="grey", lw=0.8)
    ax.set_xlabel("Ward distance (standardised columns)")
    ax.set_title(f"policy_claims_summary: row clustering ({k} groups)")
    fig.tight_layout()
    fig.savefig(out_png, dpi=150)
    plt.close(fig)
    print(f"Saved {out_png.relative_to(PROJECT_ROOT)}")


def main(model_sql, image_dir, clusters=3) -> int:
    model_sql = Path(model_sql).resolve()
    image_dir = Path(image_dir).resolve()
    os.chdir(PROJECT_ROOT)  # model SQL reads source/ with relative paths
    image_dir.mkdir(parents=True, exist_ok=True)

    labels, names, X = load_target(model_sql)
    print(f"Target rows: {len(labels)}")
    names, X, dropped = drop_unusable(names, X)
    for name, reason in dropped:
        print(f"Excluded column {name}: {reason}")
    if len(labels) < 3 or len(names) < 2:
        print("Not enough rows or columns to cluster.", file=sys.stderr)
        return 1

    cluster_columns(names, X, image_dir / "target_column_dendrogram.png")
    cluster_rows(labels, names, X, clusters, image_dir / "target_row_dendrogram.png")
    return 0


def parse_args():
    parser = argparse.ArgumentParser(description="Hierarchical clustering of the target table.")
    parser.add_argument("--model", type=Path,
                        default=PROJECT_ROOT / "model" / "policy_claims_summary.sql")
    parser.add_argument("--image-dir", type=Path, default=PROJECT_ROOT / "test_plan" / "images")
    parser.add_argument("--clusters", type=int, default=3, help="number of row groups (default 3)")
    return parser.parse_args()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        args = parse_args()
        sys.exit(main(args.model, args.image_dir, args.clusters))

    # No arguments (e.g. F5 in the VS Code debugger): edit the values below.
    MODEL_SQL = PROJECT_ROOT / "model" / "policy_claims_summary.sql"
    IMAGE_DIR = PROJECT_ROOT / "test_plan" / "images"
    CLUSTERS = 3

    sys.exit(main(MODEL_SQL, IMAGE_DIR, CLUSTERS))
