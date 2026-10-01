"""Find unusual completed tenders with an Isolation Forest, and explain each one.

The rule-based flags in build_model.py catch known patterns. This model looks
for tenders whose combination of features is rare, which can surface cases the
rules miss. It is unsupervised: there are no confirmed fraud labels, so the
output is a review list, not a verdict.

Design choices:
- Separate models for price-based tenders ("Tender") and quality-based
  consultant selections ("Seleksi"), because their normal ranges differ.
- Risk-directed features. A first version flagged tenders that were unusual in
  any direction, including healthy ones (many bids, winner far below the
  estimate). Each feature is now measured as a robust z-score (median / MAD),
  signed so that positive means riskier, and clipped at 0: being unusually
  competitive no longer counts as anomalous.
- Tender size and the estimate-to-budget ratio are not risk signals on their
  own, so they are left out of the model (size is used later to rank by value).
- Each anomaly gets a plain-language reason: the three risk features furthest
  from the typical value for its group.
- Stability check: the model is refit with 5 random seeds and we report how
  much the top-5% list overlaps between runs.

Inputs:  procurement.duckdb (from build_model.py)
Outputs: model/anomalies.csv, model/anomaly_validation.csv
"""

from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

ROOT = Path(__file__).parent
MODEL = ROOT / "model"
TOP_SHARE = 0.05  # review the most unusual 5% of each group
SEEDS = [11, 22, 33, 44, 55]

# feature -> (label, risk direction): -1 means a LOW value is the risky side.
FEATURES = {
    "n_bids": ("Bids submitted", -1),
    "bid_rate": ("Share of registered bidders who bid", -1),
    "winner_to_hps": ("Winning bid / owner's estimate", +1),
    "bid_cv": ("Spread of bids (coefficient of variation)", -1),
    "winner_gap_to_lowest": ("Winning bid above the lowest bid", +1),
    "disqualified_share": ("Share of bidders disqualified", +1),
    "vendor_unit_wins": ("Wins by the same vendor in the same work unit", +1),
}
# In quality-based selection a higher price can win on merit, so this is not a risk there.
NOT_FOR_SELEKSI = {"winner_gap_to_lowest"}

QUERY = """
WITH wins AS (
    SELECT portal, work_unit, winner_name, count(*) AS vendor_unit_wins
    FROM tender_risk WHERE completed AND winner_name IS NOT NULL
    GROUP BY ALL
)
SELECT r.tender_id, r.province, r.work_unit, r.tender_name, r.category, r.procurement_method,
       r.winner_name, r.contract_value, r.n_flags,
       r.n_bids,
       r.n_bids / NULLIF(r.n_registered, 0) AS bid_rate,
       r.winner_to_hps,
       -- Spread is only meaningful with 3+ bids; otherwise left empty (filled with the median).
       CASE WHEN r.n_bids >= 3 THEN r.bid_cv END AS bid_cv,
       coalesce(r.winner_bid / NULLIF(r.lowest_bid, 0) - 1, 0) AS winner_gap_to_lowest,
       r.n_disqualified / NULLIF(r.n_participants, 0) AS disqualified_share,
       w.vendor_unit_wins
FROM tender_risk r
LEFT JOIN wins w USING (portal, work_unit, winner_name)
WHERE r.completed AND r.hps IS NOT NULL AND r.n_bids >= 1
"""


def robust_z(frame):
    median = frame.median()
    mad = (frame - median).abs().median() * 1.4826
    # Features with no spread (MAD = 0) fall back to the standard deviation.
    scale = mad.where(mad > 0, frame.std()).replace(0, np.nan)
    return (frame - median) / scale


# Plain-language wording for the audit shortlist: (sentence, value format).
PLAIN = {
    "n_bids": ("Few bids", "{:.0f}"),
    "bid_rate": ("Few registered firms actually bid", "{:.0%}"),
    "winner_to_hps": ("Winning bid close to the owner's estimate", "{:.1%} of estimate"),
    "bid_cv": ("Bids unusually close together", "{:.2%} spread"),
    "winner_gap_to_lowest": ("Winner priced above the cheapest bid", "+{:.1%}"),
    "disqualified_share": ("Many bidders disqualified", "{:.0%}"),
    "vendor_unit_wins": ("Same firm keeps winning in this work unit", "{:.0f} wins"),
}


def explain(risk_row, raw_row, medians):
    parts = []
    for feat in risk_row.sort_values(ascending=False).index[:3]:
        if not risk_row[feat] > 0:
            continue
        sentence, fmt = PLAIN[feat]
        typical = fmt.split(" ")[0].format(medians[feat])  # unit is said once
        parts.append(f"{sentence} ({fmt.format(raw_row[feat])} vs typical {typical})")
    return "; ".join(parts)


def fit_group(group, features):
    X = group[features].fillna(group[features].median())
    signs = pd.Series({f: FEATURES[f][1] for f in features})
    risk = (robust_z(X) * signs).clip(lower=0).fillna(0)  # positive = riskier than typical

    n_top = max(1, int(round(len(group) * TOP_SHARE)))
    tops, scores = [], []
    for seed in SEEDS:
        forest = IsolationForest(n_estimators=300, contamination="auto", random_state=seed)
        forest.fit(risk)
        score = -forest.score_samples(risk)  # higher = more unusual
        scores.append(score)
        tops.append(set(group.index[np.argsort(score)[-n_top:]]))
    group = group.copy()
    group["anomaly_score"] = np.mean(scores, axis=0)
    group["anomaly_rank_pct"] = group["anomaly_score"].rank(pct=True)
    group["is_anomaly"] = group["anomaly_rank_pct"] > 1 - TOP_SHARE

    medians = X.median()
    group["reason"] = [explain(risk.loc[i], X.loc[i], medians) if group.at[i, "is_anomaly"] else ""
                       for i in group.index]

    overlaps = [len(a & b) / len(a | b) for i, a in enumerate(tops) for b in tops[i + 1:]]
    return group, float(np.mean(overlaps))


def main():
    con = duckdb.connect(str(ROOT / "procurement.duckdb"), read_only=True)
    data = con.sql(QUERY).df()
    data["family"] = np.where(data["procurement_method"] == "Seleksi", "Seleksi (consultant)",
                              "Tender (works and goods)")

    results, validation = [], []
    for family, group in data.groupby("family"):
        features = [f for f in FEATURES if not (family.startswith("Seleksi") and f in NOT_FOR_SELEKSI)]
        scored, stability = fit_group(group, features)
        results.append(scored)
        flagged = scored["n_flags"] >= 2
        validation.append({
            "family": family,
            "tenders": len(scored),
            "anomalies": int(scored["is_anomaly"].sum()),
            "seed_stability_jaccard": round(stability, 3),
            # How often anomalies also carry 2+ rule flags, vs the base rate.
            "anomaly_with_2plus_flags": round(scored.loc[scored["is_anomaly"], "n_flags"].ge(2).mean(), 3),
            "all_with_2plus_flags": round(flagged.mean(), 3),
        })

    out = pd.concat(results)
    MODEL.mkdir(exist_ok=True)
    cols = ["tender_id", "family", "province", "work_unit", "tender_name", "winner_name",
            "contract_value", "n_flags", "anomaly_score", "anomaly_rank_pct", "is_anomaly", "reason",
            *FEATURES]
    out[cols].sort_values("anomaly_score", ascending=False).to_csv(MODEL / "anomalies.csv", index=False)
    pd.DataFrame(validation).to_csv(MODEL / "anomaly_validation.csv", index=False)
    print(pd.DataFrame(validation).to_string(index=False))


if __name__ == "__main__":
    main()
