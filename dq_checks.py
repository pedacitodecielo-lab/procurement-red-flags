"""Data-quality checks on the model. Writes model/dq_checks.csv and exits with an
error if a critical check fails, so the weekly GitHub Actions run stops before
committing bad data."""

import sys
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).parent

# (name, SQL returning a count of problem rows, critical?)
CHECKS = [
    ("duplicate tender IDs",
     "SELECT count(*) - count(DISTINCT tender_id) FROM tender_risk", True),
    ("completed tenders without an owner's estimate (pages not yet scraped)",
     "SELECT count(*) FROM tender_risk WHERE completed AND hps IS NULL", False),
    ("completed tenders with details but no winner star in the bids",
     """SELECT count(*) FROM tender_risk t WHERE completed AND hps IS NOT NULL
        AND NOT EXISTS (SELECT 1 FROM bids b WHERE b.tender_id = t.tender_id AND b.is_winner)""", False),
    ("tenders with more than one winner star",
     """SELECT count(*) FROM (SELECT tender_id FROM bids WHERE is_winner
        GROUP BY tender_id HAVING count(*) > 1)""", True),
    ("non-positive owner's estimate or budget ceiling",
     "SELECT count(*) FROM tender_risk WHERE hps <= 0 OR pagu <= 0", True),
    ("owner's estimate above the budget ceiling",
     "SELECT count(*) FROM tender_risk WHERE hps > pagu * 1.0001", False),
    ("winning bid above the owner's estimate",
     "SELECT count(*) FROM tender_risk WHERE winner_bid > hps * 1.0001", False),
    ("negative bids",
     "SELECT count(*) FROM bids WHERE bid < 0", True),
]


def main():
    con = duckdb.connect(str(ROOT / "procurement.duckdb"), read_only=True)
    rows = []
    for name, sql, critical in CHECKS:
        n = con.sql(sql).fetchone()[0]
        rows.append({"check": name, "problem_rows": n, "critical": critical,
                     "status": "ok" if n == 0 else ("FAIL" if critical else "review")})
    result = pd.DataFrame(rows)
    (ROOT / "model").mkdir(exist_ok=True)
    result.to_csv(ROOT / "model" / "dq_checks.csv", index=False)
    print(result.to_string(index=False))
    if (result["status"] == "FAIL").any():
        sys.exit("critical data-quality check failed")


if __name__ == "__main__":
    main()
